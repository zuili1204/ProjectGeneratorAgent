"""dev-debug 自动升级与 pga debug 的引擎行为。"""
from __future__ import annotations

import pytest

from agent.agent_loop import AgentRunResult
from agent.config import LLMConfig, WorkflowConfig
from agent.workflow_engine import StepDef, StepState, WorkflowEngine, WorkflowState, _now_iso
from agent.workspace import Workspace


def _engine(**overrides) -> WorkflowEngine:
    cfg = WorkflowConfig(
        enable_git=False,
        enable_checkpoints=False,
        auto_proceed=False,
        health_retry=0,
        verification_gate="off",
        auto_debug=True,
        debug_max_rounds=1,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return WorkflowEngine(llm_config=LLMConfig(api_key="sk-test"), workflow_config=cfg)


def _step_def(skill="dev-selfcheck") -> StepDef:
    return StepDef(
        skill_name=skill, display_name="自测验证",
        primary_output="SELF_CHECK.md", min_size=100,
    )


def _state(wid: str, status="running") -> WorkflowState:
    return WorkflowState(
        workflow_id=wid, template="grad_project", title="调试测试", params={},
        status=status, created_at=_now_iso(), updated_at=_now_iso(),
        steps=[StepState("dev-selfcheck", "自测验证", status="failed",
                         error_message="缺失 SELF_CHECK.md")],
    )


def _fake_agent(files: dict[str, str]):
    async def fake(**kwargs):
        ws = kwargs["workspace"]
        for path, content in files.items():
            ws.write_file(path, content)
        return AgentRunResult(
            iterations=2, files_written=list(files), llm_calls=2, tool_calls=2,
            total_tokens=120, prompt_tokens=80, completion_tokens=40,
            duration_sec=1.0,
        )
    return fake


@pytest.mark.asyncio
async def test_auto_debug_fixes_failed_step(ws_dir, monkeypatch):
    wid = "wf_dbg_ok"
    ws = Workspace(wid)
    ws.write_file("code/main.py", "print('hi')\n")
    engine = _engine()
    state = _state(wid)
    step_state = state.steps[0]
    engine._save_state(ws, state)

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", _fake_agent({
        "SELF_CHECK.md": "# 自检报告\n\n所有检查项通过，测试 exit_code: 0。\n" * 8,
        "DEBUG_REPORT.md": "# 调试报告\n\n根因：SELF_CHECK.md 未写。\n",
    }))

    fixed, err = await engine._maybe_escalate_debug(
        ws, state, wid, _step_def(), step_state, engine.workflow_config,
        "主产物检查失败: 缺失 SELF_CHECK.md",
    )

    assert fixed is True, err
    assert step_state.debug_rounds == 1
    assert step_state.debug_reports == ["DEBUG_REPORT.md"]
    assert ws.file_exists("SELF_CHECK.md")


@pytest.mark.asyncio
async def test_auto_debug_respects_round_limit(ws_dir, monkeypatch):
    wid = "wf_dbg_limit"
    ws = Workspace(wid)
    ws.write_file("code/main.py", "print('hi')\n")
    engine = _engine()
    state = _state(wid)
    step_state = state.steps[0]
    step_state.debug_rounds = 1

    async def should_not_run(**kwargs):
        raise AssertionError("达到轮次上限后不应再调用 dev-debug")

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", should_not_run)

    fixed, err = await engine._maybe_escalate_debug(
        ws, state, wid, _step_def(), step_state, engine.workflow_config, "still broken",
    )

    assert fixed is False
    assert "轮次上限" in err


@pytest.mark.asyncio
async def test_auto_debug_disabled(ws_dir, monkeypatch):
    wid = "wf_dbg_off"
    ws = Workspace(wid)
    ws.write_file("code/main.py", "print('hi')\n")
    engine = _engine(auto_debug=False)
    state = _state(wid)

    async def should_not_run(**kwargs):
        raise AssertionError("auto_debug=False 时不应调用 dev-debug")

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", should_not_run)

    fixed, _ = await engine._maybe_escalate_debug(
        ws, state, wid, _step_def(), state.steps[0], engine.workflow_config, "broken",
    )

    assert fixed is False


@pytest.mark.asyncio
async def test_single_step_escalates_after_retries(ws_dir, monkeypatch):
    """健康检查重试耗尽后，_run_single_step 应调用自动调试而不是直接失败。"""
    from agent.workflow_engine import load_template

    wid = "wf_dbg_wire"
    ws = Workspace(wid)
    ws.write_file("code/main.py", "print('hi')\n")
    engine = _engine()
    state = _state(wid, status="running")
    calls: list[str] = []

    async def fake_run(**kwargs):
        return AgentRunResult(iterations=1, files_written=[], llm_calls=1, tool_calls=0)

    async def fake_escalate(*args, **kwargs):
        calls.append("debug")
        return True, ""

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", fake_run)
    monkeypatch.setattr(engine, "_maybe_escalate_debug", fake_escalate)

    await engine._run_single_step(
        ws, state, load_template("grad_project"), engine.workflow_config,
        wid, 0, _step_def(),
    )

    assert calls == ["debug"]
    assert state.steps[0].status == "completed"


@pytest.mark.asyncio
async def test_debug_step_completes_step(ws_dir, monkeypatch):
    """pga debug：修好后步骤应 completed，工作流置 paused 等用户 resume。"""
    wid = "wf_dbg_manual"
    ws = Workspace(wid)
    ws.write_file("code/main.py", "print('hi')\n")
    engine = _engine()
    state = _state(wid, status="failed")

    # dev-selfcheck 是 grad_project 的最后一步
    engine._save_state(ws, state)

    monkeypatch.setattr("agent.workflow_engine.run_agent_loop", _fake_agent({
        "SELF_CHECK.md": "# 自检报告\n\n修复完成，测试 exit_code: 0。\n" * 8,
        "DEBUG_REPORT.md": "# 调试报告\n\n已修复。\n",
    }))

    out = await engine.debug_step(wid, "dev-selfcheck", recheck=True, resume=False)

    assert out.steps[0].status == "completed"
    assert out.steps[0].debug_rounds == 1
    assert out.status == "paused"
