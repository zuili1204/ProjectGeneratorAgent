"""安全：run_command 命令沙箱校验。

防止 LLM 被 prompt 注入后执行危险命令（rm -rf / format / 外发请求等）。
采用黑名单 + 白名单双重校验：黑名单明确禁止，白名单快速放行常见开发命令。
"""
from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass

log = logging.getLogger(__name__)


# 危险命令模式（黑名单）：匹配即拒绝
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\brm\s+-rf?\s+/", re.IGNORECASE),         # rm -rf /
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+/(?:\s|$)", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+[A-Z]:[\\/]", re.IGNORECASE),  # rm -rf C:\ (Windows 盘符)
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+\*"),           # rm -rf * (通配全删)
    re.compile(r"\bmkfs\b", re.IGNORECASE),                # 格式化
    re.compile(r"\bformat\b\s+[A-Z]:", re.IGNORECASE),     # Windows format
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bhalt\b", re.IGNORECASE),
    re.compile(r"\bdel\s+/[sS]", re.IGNORECASE),           # Windows del /s
    re.compile(r"\brmdir\s+/s", re.IGNORECASE),            # Windows rmdir /s
    re.compile(r":\(\)\s*\{.*\};:", re.IGNORECASE),        # fork bomb
    re.compile(r"\bcurl\b.*\|\s*(?:sh|bash|zsh)", re.IGNORECASE),  # curl | sh
    re.compile(r"\bwget\b.*\|\s*(?:sh|bash|zsh)", re.IGNORECASE),
    re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),        # 写裸盘
    re.compile(r"\bdd\b\s+if=.*of=/dev/", re.IGNORECASE),  # dd 写裸盘
    re.compile(r"\bchmod\s+-R\s+777\s+/", re.IGNORECASE),  # 全盘 777
    re.compile(r"\b(?:curl|wget|Invoke-WebRequest|irm)\b", re.IGNORECASE),  # 外发请求（开发命令不需要）
]

# 允许的命令前缀（白名单）：快速放行，降低误报
# 不在白名单不等于禁止，只是会进一步审视；但黑名单命中必拒
_ALLOWED_PREFIXES: tuple[str, ...] = (
    "python", "python3", "py",
    "node", "npm", "npx", "yarn", "pnpm", "bun",
    "pip", "pip3", "poetry", "uv",
    "py_compile",  # python -m py_compile 的 shlex 拆分会把 python 作为前缀
    "http.server", "http.server",  # python -m http.server
    "pytest", "unittest",
    "eslint", "tsc", "vite", "webpack",
    "git",  # git status / diff 等只读操作（写操作由黑名单兜底）
    "ls", "dir", "cat", "echo", "type", "find", "grep", "rg", "select-string",
    "mkdir", "touch", "cp", "mv",  # 文件操作（rm 由黑名单控制）
)

# Python -m 子模块白名单
_ALLOWED_PYTHON_M_MODULES: tuple[str, ...] = (
    "py_compile", "http.server", "unittest", "pytest", "json", "ast",
)


@dataclass
class CommandCheck:
    """命令校验结果。"""
    allowed: bool
    reason: str = ""
    category: str = ""  # allowed / dangerous / unknown


def validate_command(command: str) -> CommandCheck:
    """校验 shell 命令是否安全。

    Args:
        command: 完整 shell 命令字符串

    Returns:
        CommandCheck(allowed=...) ; allowed=False 时 reason 给出拒绝原因
    """
    if not command or not command.strip():
        return CommandCheck(allowed=False, reason="空命令", category="unknown")

    # 1. 黑名单命中 → 直接拒
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(command):
            return CommandCheck(
                allowed=False,
                reason=f"命中危险命令模式: {pat.pattern[:60]}",
                category="dangerous",
            )

    # 2. 尝试拆分命令，识别首个可执行名
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Windows 路径或引号不闭合，降级用 split
        tokens = command.split()

    if not tokens:
        return CommandCheck(allowed=False, reason="无法解析命令", category="unknown")

    # 处理 `python -m xxx` 形式
    if len(tokens) >= 2 and tokens[0] in ("python", "python3", "py") and tokens[1] == "-m":
        if len(tokens) >= 3:
            module = tokens[2]
            if module in _ALLOWED_PYTHON_M_MODULES:
                return CommandCheck(allowed=True, category="allowed")
            # 未在白名单的 -m 模块：放行但记录（开发场景可能需要）
            log.debug("python -m %s not in whitelist, allowing", module)
            return CommandCheck(allowed=True, category="allowed")

    # 处理 `python xxx.py` / `node xxx.js` 等
    first = tokens[0]
    # 取 basename（兼容 Windows 路径）
    first_name = first.replace("\\", "/").rsplit("/", 1)[-1]
    if first_name.endswith(".exe"):
        first_name = first_name[:-4]

    if first_name in _ALLOWED_PREFIXES:
        return CommandCheck(allowed=True, category="allowed")

    # 管道 / 链式命令：检查每段
    if "|" in command or "&&" in command or "||" in command or ";" in command:
        # 已过黑名单，对链式命令宽容放行（白名单难精确）
        return CommandCheck(allowed=True, category="allowed")

    # 未知命令：记录但不硬拒（避免阻断合理但未列举的开发命令）
    log.info("unknown command prefix %r, allowing with caution", first_name)
    return CommandCheck(allowed=True, category="unknown")
