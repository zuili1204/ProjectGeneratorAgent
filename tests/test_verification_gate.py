"""验证门禁：报告分级 + 接入 dev-selfcheck 健康检查。"""
from __future__ import annotations

import pytest

from agent.config import WorkflowConfig
from agent.health_check import CheckResult, VerificationReport
from agent.workflow_engine import (
    StepDef, StepState, WorkflowEngine, WorkflowState, _gate_findings,
)
from agent.workspace import Workspace


def _ok(warnings=None) -> CheckResult:
    return CheckResult(ok=True, missing=[], errors=[], warnings=warnings or [])


def _fail(errors) -> CheckResult:
    return CheckResult(ok=False, missing=[], errors=list(errors), warnings=[])


def _report(*, dir_ok=True, files_ok=True, tests_ok=True, runtime_ok=True) -> VerificationReport:
    return VerificationReport(
        test_dir_exists=_ok() if dir_ok else _fail(["未找到测试目录"]),
        test_files_exist=_ok() if files_ok else _fail(["未发现测试文件"]),
        tests_pass=_ok() if tests_ok else _fail(["pytest 失败（exit=1）"]),
        runtime_ok=_ok() if runtime_ok else _fail(["/health 调用失败"]),
        overall_ok=all((dir_ok, files_ok, tests_ok, runtime_ok)),
        summary="test",
    )


def test_gate_findings_tests_failure_is_blocking():
    errors, warnings = _gate_findings(_report(tests_ok=False), strict=False)
    assert any("测试执行" in e for e in errors)
    assert warnings == []


def test_gate_findings_runtime_only_warns_by_default():
    errors, warnings = _gate_findings(_report(runtime_ok=False), strict=False)
    assert errors == []
    assert any("运行时验证" in w for w in warnings)


def test_gate_findings_runtime_blocks_in_strict_mode():
    errors, _ = _gate_findings(_report(runtime_ok=False), strict=True)
    assert any("运行时验证" in e for e in errors)


@pytest.mark.asyncio
async def test_selfcheck_health_check_enforces_gate(ws_dir, monkeypatch):
    """dev-selfcheck 的健康检查必须真正执行门禁，失败时驱动重试。"""
    wid = "wf_gate"
    ws = Workspace(wid)
    ws.write_file("SELF_CHECK.md", "# 自检报告\n\n所有检查项均已完成，测试通过。\n" * 10)

    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="门禁测试", params={},
        steps=[StepState("dev-selfcheck", "自测验证")],
    )
    wf_config = WorkflowConfig(enable_git=False, verification_gate="tests")
    engine = WorkflowEngine(workflow_config=wf_config)
    step_def = StepDef(
        skill_name="dev-selfcheck", display_name="自测验证",
        primary_output="SELF_CHECK.md", min_size=10,
    )

    async def fake_gate(workspace, project_type, skip_runtime=False):
        return _report(tests_ok=False)

    monkeypatch.setattr("agent.workflow_engine.run_verification_gate", fake_gate)

    ok, err, hint = await engine._run_health_checks(ws, state, wid, step_def, wf_config)

    assert ok is False
    assert "验证门禁失败" in err
    assert "pytest 失败" in err
    assert hint["type"] == "verification_failed"


@pytest.mark.asyncio
async def test_selfcheck_gate_can_be_disabled(ws_dir, monkeypatch):
    wid = "wf_gate_off"
    ws = Workspace(wid)
    ws.write_file("SELF_CHECK.md", "# 自检报告\n\n所有检查项均已完成，测试通过。\n" * 10)

    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="门禁关闭", params={},
        steps=[StepState("dev-selfcheck", "自测验证")],
    )
    wf_config = WorkflowConfig(enable_git=False, verification_gate="off")
    engine = WorkflowEngine(workflow_config=wf_config)
    step_def = StepDef(
        skill_name="dev-selfcheck", display_name="自测验证",
        primary_output="SELF_CHECK.md", min_size=10,
    )

    async def should_not_call(*_a, **_k):
        raise AssertionError("verification_gate=off 时不应执行门禁")

    monkeypatch.setattr("agent.workflow_engine.run_verification_gate", should_not_call)

    ok, err, _ = await engine._run_health_checks(ws, state, wid, step_def, wf_config)

    assert ok is True, err
