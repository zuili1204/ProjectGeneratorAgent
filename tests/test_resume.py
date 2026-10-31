"""恢复语义：failed 步骤必须重跑，不能被误判为 completed。"""
from __future__ import annotations

import pytest

from agent import checkpoint_store
from agent.agent_loop import AgentRunResult
from agent.config import WorkflowConfig
from agent.workflow_engine import StepState, WorkflowEngine, WorkflowState, _now_iso
from agent.workspace import Workspace


def _state(wid: str) -> WorkflowState:
    return WorkflowState(
        workflow_id=wid,
        template="grad_project",
        title="恢复语义测试",
        params={},
        status="paused",
        created_at=_now_iso(),
        updated_at=_now_iso(),
        steps=[
            StepState("dev-requirement", "需求分析", status="completed"),
            StepState("dev-design", "系统设计", status="failed", error_message="用户 reject"),
            StepState("dev-code", "编码实现", status="pending"),
            StepState("dev-review", "代码评审", status="pending"),
            StepState("dev-selfcheck", "自测验证", status="pending"),
        ],
    )


def _config() -> WorkflowConfig:
    return WorkflowConfig(
        enable_git=False,
        enable_checkpoints=False,
        auto_proceed=False,
        health_retry=0,
        verification_gate="off",
    )


@pytest.mark.asyncio
async def test_resume_reruns_failed_step_and_does_not_complete(ws_dir, monkeypatch):
    """failed 步骤恢复后应被重跑；重跑仍失败时工作流必须 failed，而不是 completed。"""
    wid = "wf_resume"
    ws = Workspace(wid)
    engine = WorkflowEngine(workflow_config=_config())
    engine._save_state(ws, _state(wid))

    async def fake_run(**_kwargs):
        return AgentRunResult(error="simulated LLM failure")

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", fake_run)

    out = await engine.run_workflow(wid)

    assert out.status == "failed"
    assert out.steps[1].status == "failed"
    # started_at 被刷新，证明该步确实重新执行过，而不是被跳过
    assert out.steps[1].started_at is not None
    assert out.steps[2].status == "pending"


@pytest.mark.asyncio
async def test_resume_waiting_checkpoint_approve_finalizes_without_rerun(ws_dir, monkeypatch):
    """进程在等待检查点退出后：已有的 approve 决策应直接收尾，不重跑该步。"""
    wid = "wf_cp_approve"
    ws = Workspace(wid)
    engine = WorkflowEngine(workflow_config=_config())

    state = _state(wid)
    state.status = "running"
    state.steps[1].status = "completed"
    state.steps[2].status = "completed"
    state.steps[3].status = "skipped"
    state.steps[4].status = "waiting_checkpoint"
    engine._save_state(ws, state)

    checkpoint_store.write_request(ws.root, "dev-selfcheck")
    checkpoint_store.write_response(ws.root, "dev-selfcheck", {"action": "approve", "feedback": "OK"})

    async def should_not_run(**_kwargs):
        raise AssertionError("已消费检查点决策时不应重跑步骤")

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", should_not_run)

    out = await engine.run_workflow(wid)

    assert out.status == "completed"
    assert out.steps[4].status == "completed"


@pytest.mark.asyncio
async def test_resume_waiting_checkpoint_reject_reruns_with_feedback(ws_dir, monkeypatch):
    """进程退出前用户已 reject：resume 应注入反馈并重跑该步（不是再等一轮）。"""
    wid = "wf_cp_reject"
    ws = Workspace(wid)
    engine = WorkflowEngine(workflow_config=_config())

    state = _state(wid)
    state.steps[1].status = "completed"
    state.steps[2].status = "completed"
    state.steps[3].status = "skipped"
    state.steps[4].status = "waiting_checkpoint"
    engine._save_state(ws, state)

    checkpoint_store.write_request(ws.root, "dev-selfcheck")
    checkpoint_store.write_response(
        ws.root, "dev-selfcheck",
        {"action": "reject", "feedback": "测试没跑", "severity": "major"},
    )

    calls: list[dict] = []

    async def fake_run(**kwargs):
        calls.append(kwargs)
        return AgentRunResult(error="simulated LLM failure")

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", fake_run)

    out = await engine.run_workflow(wid)

    # 步骤确实被重跑（而非原地暂停等待下一次 resume）
    assert calls, "reject 后 resume 应重跑该步骤"
    assert out.steps[4].status == "failed"
    assert out.steps[4].checkpoint_response is not None
    assert out.steps[4].checkpoint_response["feedback"] == "测试没跑"
