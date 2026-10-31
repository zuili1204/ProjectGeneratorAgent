"""检查点落盘信号：跨进程写读、超时、竞态保护。"""
from __future__ import annotations

import asyncio

import pytest

from agent import checkpoint_store
from agent.workflow_engine import submit_checkpoint, wait_checkpoint
from agent.workspace import Workspace


def test_write_request_and_response_roundtrip(ws_dir):
    ws = Workspace("wf_store")
    checkpoint_store.write_request(ws.root, "dev-code", "auto_reject")
    data = checkpoint_store.read(ws.root, "dev-code")
    assert data is not None
    assert data["status"] == "waiting"
    assert data["step"] == "dev-code"

    checkpoint_store.write_response(ws.root, "dev-code", {"action": "revise", "feedback": "改接口"})
    data = checkpoint_store.read(ws.root, "dev-code")
    assert data["status"] == "responded"
    assert data["action"] == "revise"
    assert data["feedback"] == "改接口"


def test_write_request_keeps_existing_response(ws_dir):
    """状态落盘与开始轮询之间存在窗口：已有 responded 不能被 waiting 覆盖。"""
    ws = Workspace("wf_race")
    checkpoint_store.write_request(ws.root, "dev-code")
    checkpoint_store.write_response(ws.root, "dev-code", {"action": "approve"})

    checkpoint_store.write_request(ws.root, "dev-code")

    data = checkpoint_store.read(ws.root, "dev-code")
    assert data is not None
    assert data["status"] == "responded"
    assert data["action"] == "approve"


@pytest.mark.asyncio
async def test_wait_checkpoint_reads_cross_process_file(ws_dir):
    """另一个「进程」只写文件（不经过进程内 Event），等待方应能读到并继续。"""
    wid = "wf_wait"
    ws = Workspace(wid)

    async def approve_soon():
        await asyncio.sleep(0.2)
        # 直接写文件，模拟另一个进程的 CLI approve
        checkpoint_store.write_response(
            ws.root, "dev-code", {"action": "approve", "feedback": "ok"}
        )

    task = asyncio.create_task(approve_soon())
    resp = await wait_checkpoint(wid, "dev-code", timeout=3)
    await task

    assert resp["action"] == "approve"
    assert resp["approved"] is True
    # 消费后状态落为 consumed，不会再次触发
    assert checkpoint_store.read(ws.root, "dev-code")["status"] == "consumed"


def test_submit_checkpoint_writes_signal_file(ws_dir):
    """submit_checkpoint 除了进程内 Event，也必须把决策落盘。"""
    import json

    wid = "wf_submit"
    ws = Workspace(wid)
    (ws.root / "state.json").write_text(json.dumps({
        "steps": [{"skill_name": "dev-code", "status": "waiting_checkpoint"}]
    }), encoding="utf-8")

    submit_checkpoint(wid, {"action": "revise", "feedback": "改接口"}, step="dev-code")

    data = checkpoint_store.read(ws.root, "dev-code")
    assert data is not None
    assert data["status"] == "responded"
    assert data["action"] == "revise"


@pytest.mark.asyncio
async def test_wait_checkpoint_timeout_auto_reject(ws_dir):
    wid = "wf_timeout"
    ws = Workspace(wid)

    resp = await wait_checkpoint(wid, "dev-code", timeout=0, timeout_action="auto_reject")

    assert resp["action"] == "reject"
    assert resp["auto"] is True
    assert checkpoint_store.read(ws.root, "dev-code")["status"] == "timeout"


def test_resolve_waiting_step_from_state(ws_dir):
    import json

    ws = Workspace("wf_state")
    (ws.root / "state.json").write_text(json.dumps({
        "steps": [
            {"skill_name": "dev-requirement", "status": "completed"},
            {"skill_name": "dev-code", "status": "waiting_checkpoint"},
        ]
    }, ensure_ascii=False), encoding="utf-8")

    assert checkpoint_store.resolve_waiting_step(ws.root) == "dev-code"
