"""agent_loop 的两处守卫：上下文预算统计口径、循环检测指纹。"""
from __future__ import annotations

import json

import pytest

from agent.agent_loop import (
    LOOP_TERMINATE_THRESHOLD,
    _args_hash,
    _message_tokens,
    run_agent_loop,
)
from agent.llm_client import LLMResponse, ToolCall
from agent.workspace import Workspace


def _write_call(idx: int, content: str) -> LLMResponse:
    args = {"path": "code/a.py", "content": content}
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(
            id=f"call_{idx}", name="write_file", arguments=args,
            args_raw=json.dumps(args, ensure_ascii=False),
        )],
    )


class FakeLLM:
    """按脚本返回响应，并记录每次看到的 messages 角色序列。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.seen_roles: list[list[str]] = []

    async def chat_stream(self, messages, tools=None, on_delta=None):
        self.seen_roles.append([m.get("role") for m in messages])
        return self._responses.pop(0)


def test_args_hash_includes_content():
    h1 = _args_hash("write_file", {"path": "code/a.py", "content": "v1"})
    h2 = _args_hash("write_file", {"path": "code/a.py", "content": "v2"})
    h3 = _args_hash("write_file", {"path": "code/a.py", "content": "v1"})

    assert h1 != h2, "同一文件不同内容不应被当成重复调用"
    assert h1 == h3


def test_message_tokens_counts_tool_call_arguments():
    plain = _message_tokens({"role": "assistant", "content": "hi"})
    big_args = "x" * 4000
    with_tool = _message_tokens({
        "role": "assistant",
        "content": None,
        "tool_calls": [{"function": {"name": "write_file", "arguments": big_args}}],
    })

    assert with_tool > plain + 1000, "write_file 的大段 arguments 必须计入预算"


@pytest.mark.asyncio
async def test_rewriting_same_file_with_new_content_is_not_a_loop(ws_dir):
    """同一文件连续改写 4 次（内容不同）不应触发死循环终止。"""
    llm = FakeLLM([
        _write_call(1, "v1"),
        _write_call(2, "v2"),
        _write_call(3, "v3"),
        _write_call(4, "v4"),
        LLMResponse(text="done"),
    ])

    result = await run_agent_loop(
        llm=llm,
        workspace=Workspace("wf_loop_ok"),
        prompt="写文件",
        max_iter=10,
    )

    assert result.error is None
    assert len(result.files_written) == 4
    # 每次工具调用都有对应的 tool 响应（不破坏协议）
    last_roles = llm.seen_roles[-1]
    assert last_roles.count("tool") == 4
    assert (Workspace("wf_loop_ok").root / "code/a.py").read_text(encoding="utf-8") == "v4"


@pytest.mark.asyncio
async def test_identical_calls_terminate_as_dead_loop(ws_dir):
    """完全相同的调用重复到阈值才应终止。"""
    same = _write_call(1, "same")
    llm = FakeLLM([same] * LOOP_TERMINATE_THRESHOLD)

    result = await run_agent_loop(
        llm=llm,
        workspace=Workspace("wf_loop_dead"),
        prompt="写文件",
        max_iter=10,
    )

    assert result.error is not None
    assert "死循环" in result.error
