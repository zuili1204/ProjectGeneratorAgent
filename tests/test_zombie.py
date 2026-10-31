"""僵尸工作流检测：心跳新鲜时不能误判另一个进程在跑的任务。"""
from __future__ import annotations

import json

import agent.server as server
from agent.workflow_engine import StepState, WorkflowEngine, WorkflowState, _now_iso
from agent.workspace import Workspace


def _make_running(ws: Workspace, wid: str) -> None:
    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="t", params={},
        status="running", created_at=_now_iso(), updated_at=_now_iso(),
        steps=[StepState("dev-requirement", "需求分析", status="running")],
    )
    WorkflowEngine()._save_state(ws, state)


def test_stale_running_workflow_marked_interrupted(ws_dir, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", ws_dir)
    monkeypatch.setattr(server, "_running_tasks", {})

    wid = "wf_zombie"
    ws = Workspace(wid)
    _make_running(ws, wid)

    zombies = server._detect_zombie_workflows()

    assert zombies == [wid]
    assert json.loads((ws.root / "state.json").read_text(encoding="utf-8"))["status"] == "interrupted"


def test_fresh_heartbeat_is_not_treated_as_zombie(ws_dir, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES_DIR", ws_dir)
    monkeypatch.setattr(server, "_running_tasks", {})

    wid = "wf_alive"
    ws = Workspace(wid)
    _make_running(ws, wid)
    # 模拟另一个进程（CLI）仍在运行
    (ws.root / "_runtime").mkdir(parents=True, exist_ok=True)
    (ws.root / "_runtime" / "heartbeat").write_text(_now_iso(), encoding="utf-8")

    zombies = server._detect_zombie_workflows()

    assert zombies == []
    assert json.loads((ws.root / "state.json").read_text(encoding="utf-8"))["status"] == "running"
