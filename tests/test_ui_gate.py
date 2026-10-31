"""静态 UI 质量门：token 纪律 / 对比度 / 可访问性 / 响应式。"""
from __future__ import annotations

import pytest

from agent.config import WorkflowConfig
from agent.ui_gate import contrast_ratio, run_ui_gate
from agent.workflow_engine import StepDef, StepState, WorkflowEngine, WorkflowState, _now_iso
from agent.workspace import Workspace


GOOD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="css/tokens.css">
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <img src="logo.png" alt="站点 logo">
  <label for="q">搜索</label><input id="q" type="search">
  <button class="btn" type="button">提交</button>
</body>
</html>
"""

GOOD_TOKENS = """:root {
  --bg: #ffffff;
  --fg: #111111;
  --primary: #1d4ed8;
  --on-primary: #ffffff;
  --space-2: 8px;
}
"""

GOOD_CSS = """.btn {
  min-height: 44px;
  color: var(--fg);
  background: var(--primary);
}
@media (max-width: 768px) {
  .btn { width: 100%; }
}
"""


def _good(ws: Workspace) -> None:
    ws.write_file("project.json", '{"title":"t","template":"grad_project","project_type":"frontend_only"}')
    ws.write_file("DESIGN_SYSTEM.md", "# Design System\n")
    ws.write_file("code/css/tokens.css", GOOD_TOKENS)
    ws.write_file("code/css/style.css", GOOD_CSS)
    ws.write_file("code/index.html", GOOD_HTML)


def test_good_frontend_passes(ws_dir):
    ws = Workspace("wf_ui_good")
    _good(ws)

    report = run_ui_gate(ws, "frontend_only")

    assert report.ok, [f"{f.code}:{f.file}:{f.message}" for f in report.blockers]
    assert report.checked_files >= 3


def test_bad_frontend_reports_blockers(ws_dir):
    ws = Workspace("wf_ui_bad")
    ws.write_file("project.json", '{"title":"t","template":"grad_project","project_type":"frontend_only"}')
    ws.write_file("DESIGN_SYSTEM.md", "# Design System\n")
    ws.write_file("code/css/style.css", ".btn { background: #ff0000; min-height: 20px; }\n")
    ws.write_file("code/index.html", """<!DOCTYPE html>
<html><body>
  <img src="logo.png">
  <button></button>
  <a href="#">🔍</a>
</body></html>
""")

    report = run_ui_gate(ws, "frontend_only")
    codes = {f.code for f in report.findings}

    assert report.ok is False
    assert {"TOKENS_MISSING", "RAW_HEX", "MISSING_ALT", "BUTTON_NO_NAME", "NO_VIEWPORT"} <= codes
    assert "TOUCH_TARGET" in codes
    assert "EMOJI_ICON" in codes


def test_contrast_pairs_are_checked(ws_dir):
    ws = Workspace("wf_ui_contrast")
    ws.write_file("project.json", '{"title":"t","project_type":"frontend_only"}')
    ws.write_file("code/css/tokens.css", """:root {
  --bg: #ffffff;
  --fg: #000000;
  --primary: #777777;
  --on-primary: #888888;
}
""")
    ws.write_file("code/css/style.css", ".btn { color: var(--primary); }\n")

    report = run_ui_gate(ws, "frontend_only")

    assert contrast_ratio("#777777", "#888888") < 3
    assert any(f.code == "CONTRAST_LOW" for f in report.blockers)


def test_non_frontend_is_skipped(ws_dir):
    ws = Workspace("wf_ui_script")
    ws.write_file("code/main.py", "print('hi')\n")

    report = run_ui_gate(ws, "script")

    assert report.ok
    assert any("非前端" in n for n in report.notes)


def test_focus_removed_and_motion_warnings(ws_dir):
    ws = Workspace("wf_ui_focus")
    ws.write_file("code/css/tokens.css", ":root { --bg: #ffffff; --fg: #000000; }\n")
    ws.write_file(
        "code/css/style.css",
        ".btn:focus { outline: none; }\n.card { transition: color .2s; }\n",
    )
    ws.write_file("code/index.html", GOOD_HTML)

    report = run_ui_gate(ws, "frontend_only")
    codes = {f.code for f in report.findings}

    assert "FOCUS_REMOVED" in codes
    assert "NO_REDUCED_MOTION" in codes


def test_reduced_motion_in_another_file_suppresses_warning(ws_dir):
    ws = Workspace("wf_ui_motion_ok")
    ws.write_file("code/css/tokens.css", ":root { --bg: #ffffff; --fg: #000000; }\n")
    ws.write_file("code/css/motion.css", ".card { transition: color .2s; }\n")
    ws.write_file(
        "code/css/responsive.css",
        "@media (prefers-reduced-motion: reduce) { .card { transition: none; } }\n",
    )
    ws.write_file("code/index.html", GOOD_HTML)

    report = run_ui_gate(ws, "frontend_only")
    codes = {f.code for f in report.findings}

    assert "NO_REDUCED_MOTION" not in codes


def _wire_workspace(wid: str) -> Workspace:
    ws = Workspace(wid)
    ws.write_file("project.json", '{"title":"t","project_type":"frontend_only"}')
    ws.write_file("DESIGN_SYSTEM.md", "# Design System\n")
    ws.write_file("SELF_CHECK.md", "# 自检报告\n\n所有检查项已完成。\n" * 10)
    ws.write_file("code/css/style.css", ".btn { background: #ff0000; min-height: 20px; }\n")
    ws.write_file("code/index.html", """<!DOCTYPE html>
<html><body>
  <img src="logo.png">
  <button></button>
</body></html>
""")
    return ws


def _selfcheck_step() -> StepDef:
    return StepDef(
        skill_name="dev-selfcheck", display_name="自测验证",
        primary_output="SELF_CHECK.md", min_size=10,
    )


@pytest.mark.asyncio
async def test_selfcheck_health_check_enforces_ui_gate(ws_dir):
    wid = "wf_ui_wire"
    ws = _wire_workspace(wid)
    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="UI 门禁", params={},
        steps=[StepState("dev-selfcheck", "自测验证")],
    )
    cfg = WorkflowConfig(enable_git=False, verification_gate="off", ui_gate="block")
    engine = WorkflowEngine(workflow_config=cfg)

    ok, err, hint = await engine._run_health_checks(
        ws, state, wid, _selfcheck_step(), cfg
    )

    assert ok is False
    assert "UI 质量门失败" in err
    assert hint["type"] == "ui_gate_failed"
    assert ws.file_exists("UI_GATE.md")


@pytest.mark.asyncio
async def test_ui_gate_can_be_disabled(ws_dir):
    wid = "wf_ui_off"
    ws = _wire_workspace(wid)
    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="UI 门禁关闭", params={},
        steps=[StepState("dev-selfcheck", "自测验证")],
    )
    cfg = WorkflowConfig(enable_git=False, verification_gate="off", ui_gate="off")
    engine = WorkflowEngine(workflow_config=cfg)

    ok, err, _ = await engine._run_health_checks(
        ws, state, wid, _selfcheck_step(), cfg
    )

    assert ok is True, err
    assert not ws.file_exists("UI_GATE.md")
