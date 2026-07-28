"""子代理派发：独立上下文执行隔离任务。

借鉴 superpowers subagent-driven-development：
- Fresh subagent per task，永不继承 controller 会话历史
- task_brief 是需求单一来源
- 子代理产出走文件（report），不进 controller context
- controller 永不在自己会话里改子代理产出的代码（会跳过审查）

设计：
- 子代理是一个独立的 run_agent_loop 调用，messages 重置
- 只注入 task_brief + context_files 内容作为 user 消息
- 子代理用相同的工具集（但不能再 dispatch_subagent，避免无限递归）
- 返回 SubagentResult（status / report / files_written / tokens）

状态契约：
- DONE: 任务完成，产物已写入工作区
- DONE_WITH_CONCERNS: 完成但有遗留问题（记录在 report）
- BLOCKED: 无法完成，需 controller 裁决
- FAILED: 执行异常
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from .agent_loop import (
    run_agent_loop, AgentRunResult, ALL_TOOLS_NON_RECURSIVE,
    WRITE_FILE_TOOL, READ_FILE_TOOL, LIST_FILES_TOOL, RUN_COMMAND_TOOL,
)
from .llm_client import LLMClient
from .workspace import Workspace

log = logging.getLogger(__name__)


@dataclass
class SubagentResult:
    """子代理执行结果。"""
    status: str = "FAILED"  # DONE / DONE_WITH_CONCERNS / BLOCKED / FAILED
    report: str = ""        # 子代理自述报告（含产出、遗留问题、阻塞原因）
    files_written: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_sec: float = 0.0
    error: str = ""


def _build_subagent_prompt(
    task_brief: str,
    context_files: list[str],
    workspace: Workspace,
    skill_hint: str = "",
) -> str:
    """构造子代理的 user prompt。

    子代理只看到：任务简报 + 指定上下文文件内容 + 工作区文件清单。
    永不看到 controller 的会话历史。
    """
    parts: list[str] = []

    parts.append("# 任务简报（你的需求单一来源）\n")
    parts.append(task_brief.strip())
    parts.append("")

    if skill_hint:
        parts.append(f"参考 skill：{skill_hint}（你可自主决定是否采用其方法论）\n")

    if context_files:
        parts.append("# 上下文文件（你被允许读取的文件）\n")
        for rel in context_files:
            try:
                content = workspace.read_file(rel)
                # 截断过长文件
                if len(content) > 6000:
                    content = content[:6000] + f"\n... (truncated, {len(content) - 6000} chars omitted)"
                parts.append(f"## {rel}\n```\n{content}\n```\n")
            except Exception as e:
                parts.append(f"## {rel}\n[读取失败: {e}]\n")

    # 工作区文件清单（让子代理知道有什么可读）
    files = workspace.scan()
    if files:
        parts.append("# 工作区文件清单（你可读取这些文件）\n")
        for f in files[:50]:  # 限制 50 个避免 prompt 过长
            size = workspace.file_size(f)
            parts.append(f"- {f} ({size}B)")
        if len(files) > 50:
            parts.append(f"... 共 {len(files)} 个文件（仅展示前 50）")
        parts.append("")

    parts.append(
        "# 执行约束\n"
        "1. 你是独立子代理，只看上述简报与上下文文件，看不到调用方的会话历史\n"
        "2. 用 write_file 写产物，用 run_command 跑验证（测试/语法检查）\n"
        "3. 完成后用一段文字总结：产出文件、验证证据（exit_code）、遗留问题\n"
        "4. 状态契约：DONE（完成）/ DONE_WITH_CONCERNS（完成但有遗留）/ BLOCKED（无法完成需裁决）\n"
        "5. 验证后完成：声明 DONE 前必须贴出 run_command 的实际输出，不允许「应该可以」\n"
    )

    return "\n".join(parts)


def _parse_subagent_status(final_text: str) -> str:
    """从子代理最终输出解析状态。"""
    text = final_text.upper()
    if "BLOCKED" in text:
        return "BLOCKED"
    if "DONE_WITH_CONCERNS" in text or "CONCERNS" in text:
        return "DONE_WITH_CONCERNS"
    if "DONE" in text or "完成" in final_text:
        return "DONE"
    return "DONE_WITH_CONCERNS"  # 默认带 concerns，让 controller 审查


async def dispatch_subagent(
    llm: LLMClient,
    workspace: Workspace,
    task_brief: str,
    context_files: list[str] | None = None,
    skill_hint: str = "",
    max_iter: int = 20,
    inactivity_timeout: int = 120,
    context_window: int = 32000,
) -> SubagentResult:
    """派发独立子代理执行隔离任务。

    Args:
        llm: LLM 客户端（与 controller 共用，但 messages 独立）
        workspace: 工作区（子代理可读写）
        task_brief: 任务简报，作为需求单一来源
        context_files: 子代理可读的上下文文件路径列表
        skill_hint: 建议 skill（子代理可自主决定是否采用）
        max_iter: 子代理最大迭代（默认 20，小于 controller 的 30）
        inactivity_timeout: 无输出超时
        context_window: 子代理上下文窗口（默认 32k，小于 controller）

    Returns:
        SubagentResult
    """
    import time
    start = time.time()
    result = SubagentResult()

    if not task_brief.strip():
        result.status = "FAILED"
        result.error = "task_brief 为空"
        return result

    prompt = _build_subagent_prompt(task_brief, context_files or [], workspace, skill_hint)

    log.info("dispatch_subagent: brief=%d chars, context_files=%d, prompt=%d chars",
             len(task_brief), len(context_files or []), len(prompt))

    # 子代理用非递归工具集（不能再 dispatch_subagent，避免无限嵌套）
    # ALL_TOOLS_NON_RECURSIVE 在 agent_loop.py 末尾定义
    try:
        run_result: AgentRunResult = await run_agent_loop(
            llm=llm,
            workspace=workspace,
            prompt=prompt,
            max_iter=max_iter,
            on_output=None,
            on_tool_call=None,
            on_tool_result=None,
            inactivity_timeout=inactivity_timeout,
            context_window=context_window,
            tools_override=ALL_TOOLS_NON_RECURSIVE,
        )
    except Exception as e:
        result.status = "FAILED"
        result.error = f"子代理执行异常: {e}"
        result.duration_sec = time.time() - start
        log.exception("subagent failed")
        return result

    # 汇总
    result.iterations = run_result.iterations
    result.total_tokens = run_result.total_tokens
    result.prompt_tokens = run_result.prompt_tokens
    result.completion_tokens = run_result.completion_tokens
    result.files_written = run_result.files_written
    result.commands_run = run_result.commands_run
    result.duration_sec = time.time() - start
    result.report = run_result.final_text or ""

    if run_result.error and not run_result.files_written:
        result.status = "FAILED"
        result.error = run_result.error
    elif run_result.error and run_result.files_written:
        # 软截断：有产出但有 error，标 DONE_WITH_CONCERNS
        result.status = "DONE_WITH_CONCERNS"
        result.report += f"\n\n[子代理软截断]: {run_result.error}"
    else:
        result.status = _parse_subagent_status(run_result.final_text or "")

    log.info("subagent done: status=%s files=%d tokens=%d iter=%d dur=%.1fs",
             result.status, len(result.files_written), result.total_tokens,
             result.iterations, result.duration_sec)
    return result
