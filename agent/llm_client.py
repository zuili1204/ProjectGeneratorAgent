"""LLM 客户端：OpenAI 兼容 API 调用 + tool calling。

不依赖 Claude Code CLI，直接通过 OpenAI SDK 调用任意 OpenAI 兼容后端
（DeepSeek / Qwen / Moonshot / OpenAI / 本地 vLLM 等）。

改进（相对初版）：
- AsyncOpenAI 显式配置 max_retries（HTTP 层）
- chat / chat_stream 外包业务层重试（指数退避 + 抖动），覆盖连接重置/超时
- 流式 tool_call arguments JSON 解析失败时不再静默降级为空 dict，
  而是标记 args_parse_error，由 agent_loop 回填给 LLM 自纠正
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable

from openai import AsyncOpenAI

from .config import LLMConfig
from .resilience import RetryPolicy, retry_async

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """一次工具调用的结构化表示。"""
    id: str
    name: str
    arguments: dict
    # arguments JSON 解析失败时，记录原始字符串与错误，供 agent_loop 回填 LLM 自纠正
    args_parse_error: str | None = None
    args_raw: str = ""

    @property
    def is_broken(self) -> bool:
        return self.args_parse_error is not None


@dataclass
class LLMResponse:
    """LLM 响应的标准化表示。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """异步 LLM 客户端，封装 OpenAI 兼容 API 调用。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.config.validate()
        # HTTP 层重试交给 SDK：覆盖 408/409/429/5xx
        self._client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            max_retries=self.config.max_retries,
        )
        # 业务层重试策略：覆盖连接重置 / 超时等 SDK 不重试的网络异常
        self._retry_policy = RetryPolicy(
            max_retries=self.config.max_retries,
            base_delay=self.config.retry_base_delay,
            max_delay=self.config.retry_max_delay,
            retry_exceptions=tuple(),  # 空表示重试所有非 CancelledError
        )
        log.info(
            "LLMClient initialized: base_url=%s model=%s max_retries=%d",
            self.config.base_url, self.config.model, self.config.max_retries,
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """非流式调用。

        Args:
            messages: OpenAI 消息列表
            tools: 工具定义列表（OpenAI function 格式）
            tool_choice: 工具选择策略
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 tokens
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        log.debug("LLM chat: messages=%d tools=%d", len(messages), len(tools or []))

        async def _call():
            resp = await self._client.chat.completions.create(**kwargs)
            return self._parse_response(resp)

        return await retry_async(_call, policy=self._retry_policy)

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """流式调用，文本 delta 通过 on_delta 回调实时输出。

        工具调用会缓冲累积，调用结束后一次性返回（避免流式 tool_call 的分片问题）。

        外包业务层重试：流式调用一旦中途断流（连接重置 / 协议错误），
        整个 chat_stream 重试（注意：重试时 on_delta 可能重复输出部分文本，
        调用方应容忍）。
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        async def _stream_once() -> LLMResponse:
            return await self._consume_stream(kwargs, on_delta)

        return await retry_async(_stream_once, policy=self._retry_policy)

    async def _consume_stream(
        self,
        kwargs: dict[str, Any],
        on_delta: Callable[[str], Awaitable[None]] | None,
    ) -> LLMResponse:
        """消费一次流式响应。"""
        full_text = ""
        accumulated_tools: dict[int, dict] = {}
        finish_reason = "stop"
        usage = {}

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                # 部分后端在最后一个 chunk 给 usage
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                    }
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                full_text += delta.content
                if on_delta:
                    await on_delta(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    if idx not in accumulated_tools:
                        accumulated_tools[idx] = {
                            "id": tc.id or f"call_{idx}",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        accumulated_tools[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        accumulated_tools[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        accumulated_tools[idx]["arguments"] += tc.function.arguments

            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        tool_calls: list[ToolCall] = []
        for idx in sorted(accumulated_tools.keys()):
            tc = accumulated_tools[idx]
            raw = tc["arguments"]
            try:
                args = json.loads(raw) if raw else {}
                tool_calls.append(ToolCall(
                    id=tc["id"], name=tc["name"], arguments=args,
                    args_raw=raw,
                ))
            except json.JSONDecodeError as e:
                # 解析失败：保留原始字符串与错误，交给 agent_loop 回填 LLM 自纠正
                # 不再静默降级为空 dict（会导致空参数工具调用产生不可预期写入）
                log.warning("Tool call arguments JSON parse failed: %s", raw[:200])
                tool_calls.append(ToolCall(
                    id=tc["id"], name=tc["name"], arguments={},
                    args_parse_error=f"JSON 解析失败: {e}; 原始内容: {raw[:500]}",
                    args_raw=raw,
                ))

        return LLMResponse(
            text=full_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _parse_response(resp) -> LLMResponse:
        """解析非流式响应。"""
        choice = resp.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for tc in (message.tool_calls or []):
            raw = tc.function.arguments or ""
            try:
                args = json.loads(raw) if raw else {}
                tool_calls.append(ToolCall(
                    id=tc.id, name=tc.function.name, arguments=args,
                    args_raw=raw,
                ))
            except json.JSONDecodeError as e:
                log.warning("Tool call arguments JSON parse failed: %s", raw[:200])
                tool_calls.append(ToolCall(
                    id=tc.id, name=tc.function.name, arguments={},
                    args_parse_error=f"JSON 解析失败: {e}; 原始内容: {raw[:500]}",
                    args_raw=raw,
                ))
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return LLMResponse(
            text=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )


def make_tool(
    name: str,
    description: str,
    parameters: dict,
) -> dict:
    """构造 OpenAI function 格式的工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
