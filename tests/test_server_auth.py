"""服务端鉴权：工作流读取 / 导出 / 配置 / WebSocket 必须带 token。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agent.server as server
from agent.workflow_engine import StepState, WorkflowEngine, WorkflowState, _now_iso
from agent.workspace import Workspace

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(ws_dir, monkeypatch):
    monkeypatch.setattr(server, "_detect_zombie_workflows", lambda: [])
    monkeypatch.setattr(server, "WORKSPACES_DIR", ws_dir)
    app = server.create_app()
    server._SERVER_TOKEN = TOKEN
    try:
        with TestClient(app) as c:
            yield c
    finally:
        server._SERVER_TOKEN = ""


def _seed_workflow(wid: str) -> None:
    ws = Workspace(wid)
    state = WorkflowState(
        workflow_id=wid, template="grad_project", title="鉴权探针", params={},
        status="completed", created_at=_now_iso(), updated_at=_now_iso(),
        steps=[StepState("dev-requirement", "需求分析", status="completed")],
    )
    WorkflowEngine()._save_state(ws, state)
    ws.write_file("REQUIREMENT.md", "# 需求\n" * 20)


def test_workflow_reads_require_token(client):
    _seed_workflow("wf_auth")

    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/workflows/wf_auth").status_code == 401
    assert client.get("/api/workflows/wf_auth/files").status_code == 401
    assert client.get("/api/workflows/wf_auth/export").status_code == 401
    assert client.get("/api/config").status_code == 401

    assert client.get("/api/workflows", headers=AUTH).status_code == 200
    assert client.get("/api/workflows/wf_auth", headers=AUTH).status_code == 200
    assert client.get("/api/workflows/wf_auth/files", headers=AUTH).status_code == 200
    assert client.get("/api/workflows/wf_auth/export", headers=AUTH).status_code == 200
    assert client.get("/api/config", headers=AUTH).status_code == 200


def test_public_endpoints_stay_open(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/templates").status_code == 200
    assert client.get("/api/skills").status_code == 200


def test_websocket_requires_token(client):
    _seed_workflow("wf_ws")

    with pytest.raises(Exception):
        with client.websocket_connect("/ws/workflows/wf_ws?token=wrong"):
            pass

    with client.websocket_connect(f"/ws/workflows/wf_ws?token={TOKEN}") as ws:
        first = ws.receive_json()
        assert first["event"] == "snapshot"
        assert first["workflow_id"] == "wf_ws"
