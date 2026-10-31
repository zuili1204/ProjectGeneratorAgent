"""流式调用的 usage 统计：确保 token / 成本不再恒为 0。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.config import LLMConfig
from agent.llm_client import LLMClient


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c
        return gen()


class FakeCompletions:
    def __init__(self, chunks, captured, reject_stream_options=False):
        self._chunks = chunks
        self._captured = captured
        self._reject = reject_stream_options

    async def create(self, **kwargs):
        self._captured.append(dict(kwargs))
        if self._reject and "stream_options" in kwargs:
            raise RuntimeError("Unsupported parameter: stream_options")
        return FakeStream(self._chunks)


def _client(chunks, captured, reject=False):
    cfg = LLMConfig(api_key="sk-test", base_url="https://api.deepseek.com/v1", model="deepseek-chat")
    client = LLMClient(cfg)
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(chunks, captured, reject))
    )
    return client


def _chunks():
    content = SimpleNamespace(content="hello", tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)
    return [
        SimpleNamespace(choices=[SimpleNamespace(delta=content, finish_reason=None)], usage=None),
        # 末尾 usage-only chunk（OpenAI / DeepSeek 在 include_usage 时的形态）
        SimpleNamespace(choices=[], usage=usage),
    ]


@pytest.mark.asyncio
async def test_stream_requests_usage_and_captures_tokens():
    captured: list[dict] = []
    client = _client(_chunks(), captured)

    resp = await client.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert captured[0]["stream_options"] == {"include_usage": True}
    assert resp.usage["prompt_tokens"] == 11
    assert resp.usage["completion_tokens"] == 7
    assert resp.usage["total_tokens"] == 18


@pytest.mark.asyncio
async def test_stream_falls_back_when_backend_rejects_stream_options():
    """旧版 vLLM / Qwen 兼容层不认 stream_options 时应自动降级，而不是整步失败。"""
    captured: list[dict] = []
    client = _client(_chunks(), captured, reject=True)

    resp = await client.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert len(captured) == 2
    assert "stream_options" in captured[0]
    assert "stream_options" not in captured[1]
    assert resp.usage["prompt_tokens"] == 11
