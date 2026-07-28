"""LLM Agent 循环：tool calling 驱动的智能体执行核心。

对应 Modex-MH-Agent 的 ClaudeRunner.run_skill，但用纯 Python + OpenAI SDK 实现，
不依赖 Claude Code CLI 子进程。

工作原理：
1. 接收 SKILL prompt 作为 user 消息
2. 调用 LLM，LLM 决定调用哪些工具（write_file / read_file / list_files / run_command / dispatch_subagent）
3. 执行工具，把结果作为 tool 消息加入历史
4. 循环直到 LLM 不再调用工具（finish_reason=stop）或达到 max_iter

改进（相对初版）：
- 无输出超时看门狗：LLM 卡住不返回时取消并标记失败
- 循环检测：反复调用同一工具时注入提醒，再犯则终止
- token 预算守卫：messages 超过上下文 70% 时压缩历史 tool 结果
- 结构化工具错误：返回错误码（DISK_FULL/PERMISSION_DENIED/PATH_INVALID/TIMEOUT）
- 命令沙箱：run_command 经 security.validate_command 校验，命中危险模式拒绝
- read_file 支持 offset/limit，截断时显式提示
- tool_call arguments JSON 解析失败时回填 LLM 自纠正（不再静默空参数执行）
- max_iter 软截断：有产出但需通过验证门禁（不再自动放行）
- verification-before-completion：system prompt 强制要求跑验证命令贴输出
- dispatch_subagent：派发独立子代理执行隔离任务（P1，子代理不继承会话历史）
- 指标统计：llm_calls / tool_calls / retries / duration
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from .config import DEFAULT_AGENT_MAX_ITER, DEFAULT_INACTIVITY_TIMEOUT, DEFAULT_MODEL_CONTEXT_WINDOW
from .llm_client import LLMClient, LLMResponse, make_tool
from .resilience import estimate_tokens
from .security import validate_command
from .workspace import Workspace

log = logging.getLogger(__name__)


# === 工具定义 ===

WRITE_FILE_TOOL = make_tool(
    name="write_file",
    description=(
        "把内容写入工作区文件。如果文件已存在则覆盖。自动创建父目录。"
        "大文件可分片写入：首次 write_file 写前半部分，后续用 append=true 追加。"
        "单次写入建议不超过 8000 字符以避免 JSON 参数被截断。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于工作区根目录的路径，如 'code/backend/main.py' 或 'REQUIREMENT.md'",
            },
            "content": {
                "type": "string",
                "description": "文件内容（UTF-8 文本）。大文件请分片：首次写前半部分，后续用 append=true 追加剩余部分。",
            },
            "append": {
                "type": "boolean",
                "description": "可选，为 true 时内容追加到文件末尾而非覆盖（用于分片写入大文件）。默认 false（覆盖）。",
            },
        },
        "required": ["path", "content"],
    },
)

READ_FILE_TOOL = make_tool(
    name="read_file",
    description=(
        "读取工作区中已存在的文件内容。支持 offset/limit 分段读取大文件。"
        "截断时会显式提示剩余字符数。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于工作区根目录的路径",
            },
            "offset": {
                "type": "integer",
                "description": "可选，从第几个字符开始读（0 基），默认 0",
            },
            "limit": {
                "type": "integer",
                "description": "可选，最多读取多少字符，默认 8000",
            },
        },
        "required": ["path"],
    },
)

LIST_FILES_TOOL = make_tool(
    name="list_files",
    description="列出工作区中所有文件（可选指定子目录），返回路径+大小+分类。",
    parameters={
        "type": "object",
        "properties": {
            "subdir": {
                "type": "string",
                "description": "可选，只列出该子目录下的文件。省略则列出全部。",
            },
        },
        "required": [],
    },
)

RUN_COMMAND_TOOL = make_tool(
    name="run_command",
    description=(
        "在工作区目录下执行 shell 命令（用于语法检查、依赖安装、运行测试等）。"
        "超时默认 60 秒，pip/npm install 类命令可传 timeout 最高 180 秒。"
        "危险命令（rm -rf /、format、外发请求等）会被沙箱拒绝。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "完整的 shell 命令，如 'python -m py_compile code/backend/main.py'",
            },
            "timeout": {
                "type": "integer",
                "description": "可选，超时秒数，上限 180，默认 60",
            },
        },
        "required": ["command"],
    },
)

DISPATCH_SUBAGENT_TOOL = make_tool(
    name="dispatch_subagent",
    description=(
        "派发独立子代理执行隔离任务。子代理不继承当前会话历史，"
        "只接收 task_brief 作为需求单一来源。适用于：独立代码评审、"
        "独立模块实现、独立测试编写等需要隔离上下文的任务。"
        "子代理完成后返回状态 + 报告摘要。"
        "Use when: 需要独立视角（评审）、需要隔离上下文（避免污染）、"
        "需要并行执行多个独立子任务。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_brief": {
                "type": "string",
                "description": (
                    "任务简报：作为子代理需求的单一来源。"
                    "包含目标、可读上下文文件、产物路径、验收条件。"
                    "子代理只会看到这份简报 + 指定的 context_files，看不到当前会话历史。"
                ),
            },
            "context_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "子代理可读取的上下文文件相对路径列表（如 ['REQUIREMENT.md', 'DESIGN.md', 'code/backend/main.py']）",
            },
            "skill_hint": {
                "type": "string",
                "description": "可选，建议子代理使用的 skill（如 'dev-review'），子代理可自主决定是否采用",
            },
        },
        "required": ["task_brief"],
    },
)

ALL_TOOLS = [WRITE_FILE_TOOL, READ_FILE_TOOL, LIST_FILES_TOOL, RUN_COMMAND_TOOL, DISPATCH_SUBAGENT_TOOL]

# 非递归工具集：子代理用，不含 dispatch_subagent（避免无限嵌套）
ALL_TOOLS_NON_RECURSIVE = [WRITE_FILE_TOOL, READ_FILE_TOOL, LIST_FILES_TOOL, RUN_COMMAND_TOOL]


# === 结构化工具错误 ===

class ToolError:
    """工具错误码常量。"""
    PATH_INVALID = "PATH_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISK_FULL = "DISK_FULL"
    TIMEOUT = "TIMEOUT"
    COMMAND_BLOCKED = "COMMAND_BLOCKED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


def _format_error(code: str, detail: str) -> str:
    return f"ERROR[{code}]: {detail}"


# === 工具执行器 ===

async def _exec_write_file(workspace: Workspace, args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    append = args.get("append", False)
    if not path:
        return _format_error(ToolError.PATH_INVALID, "path is required")
    if not isinstance(content, str):
        return _format_error(ToolError.PATH_INVALID, "content must be string")
    try:
        if append and workspace.file_exists(path):
            existing = workspace.read_file(path)
            workspace.write_file(path, existing + content)
            total = len(existing) + len(content)
            return f"OK: appended {len(content)} bytes to {path} (total {total} bytes)"
        workspace.write_file(path, content)
        return f"OK: wrote {len(content)} bytes to {path}"
    except ValueError as e:
        # 路径非法（穿越等）
        return _format_error(ToolError.PATH_INVALID, str(e))
    except PermissionError as e:
        return _format_error(ToolError.PERMISSION_DENIED, str(e))
    except OSError as e:
        # 磁盘满通常报 No space left on device
        if "space" in str(e).lower() or e.errno in (28,):
            return _format_error(ToolError.DISK_FULL, str(e))
        return _format_error(ToolError.UNKNOWN, str(e))
    except Exception as e:
        return _format_error(ToolError.UNKNOWN, str(e))


async def _exec_read_file(workspace: Workspace, args: dict) -> str:
    path = args.get("path", "")
    if not path:
        return _format_error(ToolError.PATH_INVALID, "path is required")
    offset = int(args.get("offset", 0) or 0)
    limit = int(args.get("limit", 8000) or 8000)
    if limit > 20000:
        limit = 20000
    try:
        content = workspace.read_file(path)
    except FileNotFoundError:
        return _format_error(ToolError.NOT_FOUND, f"file not found: {path}")
    except ValueError as e:
        return _format_error(ToolError.PATH_INVALID, str(e))
    except Exception as e:
        return _format_error(ToolError.UNKNOWN, str(e))

    total = len(content)
    if offset >= total:
        return f"OK: offset {offset} 超出文件长度 {total}（文件已读完）"
    chunk = content[offset:offset + limit]
    if offset + limit < total:
        remaining = total - offset - limit
        chunk += f"\n... (已截断：本段 offset={offset}, limit={limit}; 剩余 {remaining} 字符未读，请用 offset={offset + limit} 继续)"
    else:
        chunk += f"\n[文件已读完，共 {total} 字符]"
    if offset > 0:
        chunk = f"[从 offset={offset} 开始读取]\n" + chunk
    return chunk


async def _exec_list_files(workspace: Workspace, args: dict) -> str:
    subdir = args.get("subdir", "")
    all_files = workspace.scan()
    if subdir:
        prefix = subdir.replace("\\", "/").rstrip("/") + "/"
        files = [f for f in all_files if f.startswith(prefix)]
    else:
        files = all_files
    if not files:
        return "(no files)"
    lines = []
    for f in files:
        size = workspace.file_size(f)
        cls = workspace.classify_file(f)
        lines.append(f"{f} ({size}B, {cls})")
    return "\n".join(lines)


async def _exec_run_command(workspace: Workspace, args: dict) -> str:
    command = args.get("command", "")
    if not command:
        return _format_error(ToolError.PATH_INVALID, "command is required")
    timeout = int(args.get("timeout", 60) or 60)
    timeout = max(5, min(180, timeout))

    # 命令沙箱校验
    chk = validate_command(command)
    if not chk.allowed:
        return _format_error(
            ToolError.COMMAND_BLOCKED,
            f"命令被沙箱拒绝：{chk.reason}。请改用安全的开发命令（python/node/pip/npm 等）。",
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            return _format_error(ToolError.TIMEOUT, f"command timed out after {timeout}s\ncommand: {command}")
        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        result = f"exit_code: {proc.returncode}\n"
        if out:
            result += f"stdout:\n{out}\n"
        if err:
            result += f"stderr:\n{err}\n"
        if len(result) > 8000:
            result = result[:8000] + f"\n... (truncated, {len(result) - 8000} chars omitted)"
        return result
    except Exception as e:
        return _format_error(ToolError.UNKNOWN, str(e))


# === dispatch_subagent 执行器（P1） ===
#
# 借鉴 superpowers SDD：子代理不继承会话历史，task_brief 是需求单一来源。
# controller 永不直接改子代理产出的代码（会跳过审查）。
# 子代理用 ALL_TOOLS_NON_RECURSIVE（无 dispatch_subagent，避免无限嵌套）。

# 持有 LLMClient 与 LLMConfig 引用（由 run_agent_loop 注入）
# 避免循环 import：在函数内 import subagent 模块


async def _exec_dispatch_subagent(workspace: Workspace, args: dict, llm: Any = None, llm_config: Any = None) -> str:
    """派发独立子代理执行隔离任务。"""
    task_brief = args.get("task_brief", "")
    context_files = args.get("context_files", []) or []
    skill_hint = args.get("skill_hint", "")

    if not task_brief.strip():
        return _format_error(ToolError.PATH_INVALID, "task_brief is required")

    if llm is None:
        return _format_error(
            ToolError.UNKNOWN,
            "dispatch_subagent 不可用：未注入 LLMClient（请通过 run_agent_loop 的 llm 参数传递）"
        )

    # 延迟 import 避免循环
    from .subagent import dispatch_subagent

    try:
        result = await dispatch_subagent(
            llm=llm,
            workspace=workspace,
            task_brief=task_brief,
            context_files=context_files,
            skill_hint=skill_hint,
            max_iter=20,
            inactivity_timeout=120,
            context_window=32000,
        )
    except Exception as e:
        return _format_error(ToolError.UNKNOWN, f"子代理执行异常: {e}")

    # 格式化报告返回给 controller
    lines = [
        f"子代理状态: {result.status}",
        f"迭代: {result.iterations}, Tokens: {result.total_tokens}, 耗时: {result.duration_sec:.1f}s",
    ]
    if result.files_written:
        lines.append(f"产出文件: {result.files_written}")
    if result.commands_run:
        lines.append(f"执行命令: {len(result.commands_run)} 条")
    if result.error:
        lines.append(f"错误: {result.error}")
    if result.report:
        lines.append("--- 报告 ---")
        # 截断过长报告
        report = result.report
        if len(report) > 4000:
            report = report[:4000] + f"\n... (truncated, {len(report) - 4000} chars omitted)"
        lines.append(report)
    return "\n".join(lines)


# 带 llm 注入的工具执行器分派
async def _execute_tool_call(
    name: str, args: dict, workspace: Workspace, llm: Any = None, llm_config: Any = None,
) -> str:
    """统一工具执行分派（支持 dispatch_subagent 的 llm 注入）。"""
    if name == "dispatch_subagent":
        return await _exec_dispatch_subagent(workspace, args, llm=llm, llm_config=llm_config)
    executor = _TOOL_EXECUTORS.get(name)
    if not executor:
        return _format_error(ToolError.UNKNOWN, f"unknown tool '{name}'")
    try:
        return await executor(workspace, args)
    except Exception as e:
        return _format_error(ToolError.UNKNOWN, str(e))


_TOOL_EXECUTORS: dict[str, Callable[[Workspace, dict], Awaitable[str]]] = {
    "write_file": _exec_write_file,
    "read_file": _exec_read_file,
    "list_files": _exec_list_files,
    "run_command": _exec_run_command,
}


# === Agent 循环 ===

@dataclass
class AgentRunResult:
    """单次 agent 循环的执行结果。"""
    iterations: int = 0
    files_written: list[str] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    final_text: str = ""
    total_tokens: int = 0
    truncated: bool = False
    error: str | None = None
    # 新增指标
    llm_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    duration_sec: float = 0.0
    soft_truncated: bool = False   # 达到 max_iter 但有产出，允许软截断完成
    # 成本拆分（P3-2）：prompt/completion tokens 分别累计，便于按价目折算 USD
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _args_hash(name: str, args: dict) -> str:
    """对工具调用做指纹，用于循环检测。write_file 的 content 不计入指纹
    （避免合法的多次写不同内容被误判），只看 path + 其他参数。"""
    if name == "write_file":
        key = {"path": args.get("path", "")}
    else:
        key = dict(args)
    try:
        return name + ":" + json.dumps(key, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return name + ":" + str(sorted(key.items()))


def _compress_messages(messages: list[dict], keep_recent: int = 10) -> list[dict]:
    """压缩消息历史：保留 system + user 首条 + 最近 keep_recent 条，
    中间的 tool/assistant 消息压缩为摘要。

    用于上下文超限时回收 token 预算。

    注意：切分点必须不破坏 tool_calls ↔ tool 的配对关系。
    如果 tail 以 tool 消息开头，该 tool 消息的 assistant(tool_calls)
    会被压缩到 middle → API 返回 400:
    "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
    修复：向前扩展 tail 直到越过 tool 消息组，将对应的 assistant(tool_calls) 一并保留。
    """
    if len(messages) <= keep_recent + 2:
        return messages
    head = messages[:2]  # system + first user

    # 找到安全的切分点：tail 不能以 tool 消息开头
    cut = len(messages) - keep_recent
    if cut < 2:
        cut = 2
    while cut > 2 and messages[cut].get("role") == "tool":
        cut -= 1

    tail = messages[cut:]
    middle = messages[2:cut]
    summary_lines: list[str] = []
    for m in middle:
        role = m.get("role", "")
        if role == "assistant":
            tc = m.get("tool_calls")
            if tc:
                names = [t.get("function", {}).get("name", "?") for t in tc]
                summary_lines.append(f"(assistant 调用工具: {', '.join(names)})")
            elif m.get("content"):
                summary_lines.append(f"(assistant 输出: {str(m['content'])[:80]}...)")
        elif role == "tool":
            content = str(m.get("content", ""))[:80]
            summary_lines.append(f"(tool 结果: {content}...)")
    if summary_lines:
        head.append({
            "role": "system",
            "content": "[历史压缩摘要] " + " | ".join(summary_lines[-20:]),
        })
    return head + tail


async def run_agent_loop(
    llm: LLMClient,
    workspace: Workspace,
    prompt: str,
    max_iter: int = DEFAULT_AGENT_MAX_ITER,
    on_output: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
    on_tool_result: Callable[[str, str], Awaitable[None]] | None = None,
    inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT,
    context_window: int = DEFAULT_MODEL_CONTEXT_WINDOW,
    tools_override: list | None = None,
    llm_config: Any = None,
) -> AgentRunResult:
    """执行 LLM agent 循环。

    Args:
        llm: LLM 客户端
        workspace: 工作区
        prompt: 渲染后的 SKILL prompt
        max_iter: 最大迭代次数
        on_output: 文本输出回调（实时）
        on_tool_call: 工具调用回调（name, args）
        on_tool_result: 工具结果回调（name, result）
        inactivity_timeout: 无输出超时秒数（LLM 卡住不返回则取消）
        context_window: 模型上下文窗口 token 数，用于预算守卫
        tools_override: 可选，覆盖默认工具集（子代理用非递归集）
        llm_config: 可选，LLMConfig（用于 dispatch_subagent 执行器构造子代理）

    Returns:
        AgentRunResult
    """
    active_tools = tools_override if tools_override is not None else ALL_TOOLS
    result = AgentRunResult()
    start_time = time.time()

    # 系统消息：定义 agent 行为
    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "你是一个项目生成智能体。你通过调用工具（write_file/read_file/list_files/run_command/dispatch_subagent）"
                "完成任务。每次只调用必要的工具，完成后用一段简短文字总结你做了什么。\n\n"
                "## 重要规则\n"
                "1. **必须实际调用 write_file 工具来创建文件**，不要只说「我会写出 xxx」就结束\n"
                "2. 任务中要求的产物文件（如 SELF_CHECK.md、RUN.md、REQUIREMENT.md、DESIGN.md）"
                "必须通过 write_file 工具实际写入，否则任务视为失败\n"
                "3. 不要重复读取已经读过的文件。文件路径用相对于工作区根目录的相对路径\n"
                "4. 工作目录是当前工作区，所有命令都在该目录下执行\n"
                "5. 如果任务说「必须产出 xxx 文件」，你在结束前一定要调用 write_file 写出它\n"
                "6. 工具返回 ERROR[CODE] 时按 CODE 换策略：PATH_INVALID 用 list_files 确认路径；"
                "NOT_FOUND 检查文件名；TIMEOUT 缩小命令范围；COMMAND_BLOCKED 改用允许的命令\n"
                "7. read_file 截断时会提示剩余字符数，用 offset 参数继续读取，不要重复从头读\n"
                "8. **验证后完成（verification-before-completion）**：声明「完成」前必须用 run_command "
                "跑实际验证命令（测试、语法检查、启动命令）并把输出贴出来。不允许「应该没问题」、"
                "「大概可以」、「之前跑过」等假设性表述。没有 fresh 验证证据的完成声明视为未完成。\n"
                "9. **测试执行**：如果产物包含 code/tests/ 目录，结束前必须执行 pytest 或 npm test "
                "并贴出通过证据（exit_code: 0）。测试不通过必须修复至通过才能结束。\n"
                "10. **dispatch_subagent 隔离**：需要独立视角（如代码评审）时用 dispatch_subagent 派发"
                "子代理，子代理只看 task_brief + context_files，不继承当前会话。controller 永不在自己会话里"
                "改子代理产出的代码（会跳过审查）。"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    # 循环检测：滑动窗口记录最近工具调用指纹
    recent_calls: deque[str] = deque(maxlen=8)
    loop_warned = False

    for iteration in range(1, max_iter + 1):
        result.iterations = iteration
        log.debug("agent iter %d, messages=%d", iteration, len(messages))

        # token 预算守卫：超 70% 上下文窗口则压缩历史
        if context_window > 0:
            est_tokens = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
            if est_tokens > context_window * 0.7:
                log.warning("context budget exceeded: est=%d > 70%% of %d, compressing",
                            est_tokens, context_window)
                messages = _compress_messages(messages)

        # 无输出超时看门狗：用 shield + wait_for 循环，delta 到达则续命
        last_delta = {"time": time.monotonic()}

        async def on_output_watch(text: str) -> None:
            last_delta["time"] = time.monotonic()
            if on_output:
                await on_output(text)

        call_task = asyncio.create_task(
            llm.chat_stream(messages=messages, tools=active_tools, on_delta=on_output_watch)
        )

        resp: LLMResponse | None = None
        try:
            while True:
                try:
                    resp = await asyncio.wait_for(
                        asyncio.shield(call_task), timeout=inactivity_timeout
                    )
                    break
                except asyncio.TimeoutError:
                    # 检查是否近期有 delta；有则继续等（LLM 在慢慢流式输出）
                    if time.monotonic() - last_delta["time"] < inactivity_timeout:
                        continue
                    # 真正无输出超时
                    call_task.cancel()
                    try:
                        await call_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    result.error = (
                        f"无输出超时：LLM 在 {inactivity_timeout}s 内无任何返回"
                    )
                    result.duration_sec = time.time() - start_time
                    log.error("agent loop inactivity timeout at iter %d", iteration)
                    return result
        except asyncio.CancelledError:
            call_task.cancel()
            raise
        except Exception as e:
            result.error = f"LLM 调用失败 (iter {iteration}): {e}"
            result.duration_sec = time.time() - start_time
            log.exception("LLM call failed at iteration %d", iteration)
            return result

        result.llm_calls += 1
        if resp.usage:
            p_tok = resp.usage.get("prompt_tokens", 0) or 0
            c_tok = resp.usage.get("completion_tokens", 0) or 0
            result.prompt_tokens += p_tok
            result.completion_tokens += c_tok
            result.total_tokens += resp.usage.get("total_tokens", 0) or (p_tok + c_tok)

        # 把 assistant 消息加入历史
        assistant_msg: dict = {"role": "assistant", "content": resp.text or None}
        if resp.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.args_raw if tc.args_raw else json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in resp.tool_calls
            ]
        messages.append(assistant_msg)

        # 如果没有工具调用，循环结束
        if not resp.has_tool_calls:
            result.final_text = resp.text
            log.info("agent loop done: iter=%d tokens=%d", iteration, result.total_tokens)
            result.duration_sec = time.time() - start_time
            return result

        # 执行所有工具调用
        for tc in resp.tool_calls:
            result.tool_calls += 1

            # 处理 arguments JSON 解析失败：回填 LLM 自纠正
            if tc.is_broken:
                parse_hint = ""
                if tc.name == "write_file":
                    parse_hint = (
                        " 提示：文件内容可能过长导致 JSON 参数被截断。"
                        "请将文件拆分为多次 write_file 调用——首次写入前半部分（不超过 8000 字符），"
                        "后续用 append=true 追加剩余部分。"
                    )
                tool_result = (
                    f"ERROR[PARSE]: 工具 {tc.name} 的 arguments 解析失败，无法执行。"
                    f"请重新调用该工具并提供合法的 JSON 参数。{parse_hint}\n{tc.args_parse_error}"
                )
                if on_tool_result:
                    await on_tool_result(tc.name, tool_result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })
                continue

            if on_tool_call:
                await on_tool_call(tc.name, tc.arguments)

            # 循环检测
            fingerprint = _args_hash(tc.name, tc.arguments)
            recent_calls.append(fingerprint)
            repeat_count = sum(1 for x in recent_calls if x == fingerprint)
            if repeat_count >= 3:
                if not loop_warned:
                    loop_warned = True
                    # 注入提醒，再犯则终止
                    messages.append({
                        "role": "system",
                        "content": (
                            f"检测到你已重复调用 {tc.name}({tc.arguments.get('path', '')}) "
                            f"{repeat_count} 次。请换思路或宣布任务结束，不要继续重复同样的调用。"
                        ),
                    })
                    log.warning("loop detected: %s repeated %d times", tc.name, repeat_count)
                    continue
                else:
                    result.error = f"检测到工具调用死循环：{tc.name} 重复 {repeat_count} 次，已终止"
                    result.duration_sec = time.time() - start_time
                    log.error("agent loop dead-loop terminated at iter %d", iteration)
                    return result

            executor = _TOOL_EXECUTORS.get(tc.name)
            if tc.name == "dispatch_subagent":
                # 子代理派发：需要 llm 注入
                try:
                    tool_result = await _execute_tool_call(
                        tc.name, tc.arguments, workspace, llm=llm, llm_config=llm_config,
                    )
                except Exception as e:
                    tool_result = _format_error(ToolError.UNKNOWN, str(e))
                    log.exception("tool %s execution failed", tc.name)
            elif not executor:
                tool_result = _format_error(ToolError.UNKNOWN, f"unknown tool '{tc.name}'")
            else:
                try:
                    tool_result = await executor(workspace, tc.arguments)
                except Exception as e:
                    tool_result = _format_error(ToolError.UNKNOWN, str(e))
                    log.exception("tool %s execution failed", tc.name)

            # 记录到结果
            if tc.name == "write_file":
                path = tc.arguments.get("path", "")
                if path:
                    result.files_written.append(path)
            elif tc.name == "read_file":
                path = tc.arguments.get("path", "")
                if path:
                    result.files_read.append(path)
            elif tc.name == "run_command":
                cmd = tc.arguments.get("command", "")
                if cmd:
                    result.commands_run.append(cmd)

            if on_tool_result:
                await on_tool_result(tc.name, tool_result)

            # 把工具结果加入消息历史
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

    # 达到最大迭代次数
    result.truncated = True
    # 软截断：有产出文件但不自动放行，标记 needs_verification 让上层健康检查决定
    # （不再自动 soft_truncated=True 放行；上层必须跑验证门禁通过才允许 completed）
    if result.files_written:
        result.soft_truncated = True  # 保留字段用于上层判断"有产出"
        result.error = (
            f"达到最大迭代次数 {max_iter}（有 {len(result.files_written)} 个文件产出）。"
            f"需通过 verification gate 才能标记完成：测试目录存在 + 测试通过 + 运行时验证。"
        )
    else:
        result.error = f"达到最大迭代次数 {max_iter}（无文件产出，硬失败）"
        result.soft_truncated = False
    result.duration_sec = time.time() - start_time
    log.warning("agent loop truncated at max_iter=%d, soft=%s, files=%d",
                max_iter, result.soft_truncated, len(result.files_written))
    return result
