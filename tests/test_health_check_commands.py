"""测试执行命令构造：项目在 code/ 下时必须先 cd，否则导入失败。"""
from __future__ import annotations

import pytest

from agent.health_check import check_tests_pass
from agent.workspace import Workspace


@pytest.mark.asyncio
async def test_python_tests_run_from_code_dir(ws_dir, monkeypatch):
    ws = Workspace("wf_py_tests")
    ws.write_file("code/tests/test_ok.py", "def test_ok():\n    assert True\n")

    calls: list[str] = []

    async def fake_run(workspace, command, timeout=60):
        calls.append(command)
        return 0, "1 passed", ""

    monkeypatch.setattr("agent.health_check._run_command_capture", fake_run)

    res = await check_tests_pass(ws)

    assert res.ok, res.errors
    assert calls and 'cd "code"' in calls[0]
    assert "pytest tests" in calls[0]


@pytest.mark.asyncio
async def test_node_tests_run_in_package_dir(ws_dir, monkeypatch):
    ws = Workspace("wf_node_tests")
    ws.write_file("code/tests/run-tests.js", "console.log('ok')\n")
    ws.write_file(
        "code/package.json",
        '{"name":"x","scripts":{"test":"node tests/run-tests.js"}}',
    )

    calls: list[str] = []

    async def fake_run(workspace, command, timeout=60):
        calls.append(command)
        return 0, "ok", ""

    monkeypatch.setattr("agent.health_check._run_command_capture", fake_run)

    res = await check_tests_pass(ws)

    assert res.ok, res.errors
    assert calls and 'cd "code"' in calls[0]
    assert "npm test" in calls[0]
