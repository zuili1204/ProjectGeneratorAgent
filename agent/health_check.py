"""健康检查：文件大小、二级文件齐全、语法检查。

对应 Modex-MH-Agent 的：
- _min_size_for (主产物大小检查)
- _check_step_companions (二级文件齐全)
- _required_companions_for (必需文件列表)

改进：
- Python 用 compile() 做真语法检查（不只看大小）
- JS/TS 用括号匹配
- HTML 用标签闭合检查
- 按 project_type 动态决定 dev-code 的必需文件
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .workspace import Workspace

log = logging.getLogger(__name__)


# === dev-code 按 project_type 的必需文件 ===
_CODE_REQUIRED_BY_TYPE: dict[str, list[str]] = {
    "fullstack": [
        "code/backend/main.py",
        "code/frontend/package.json",
        "code/RUN.md",
    ],
    "backend_only": [
        "code/backend/main.py",
        "code/backend/requirements.txt",
        "code/RUN.md",
    ],
    "frontend_only": [
        "code/package.json",
        "code/RUN.md",
    ],
    "cli": [
        "code/RUN.md",
    ],
    "script": [
        "code/RUN.md",
    ],
}


def required_companions(skill_name: str, workspace: Workspace) -> list[str]:
    """获取 skill 必须存在的二级文件列表。

    dev-code 按 project_type 动态决定，其他 skill 用模板里的 required_companions。
    """
    if skill_name == "dev-code":
        project_type = workspace.detect_project_type()
        return _CODE_REQUIRED_BY_TYPE.get(project_type, ["code/RUN.md"])
    # 其他 skill 的 required_companions 由模板定义，这里返回空（由调用方传入）
    return []


@dataclass
class CheckResult:
    """单次检查结果。"""
    ok: bool
    missing: list[str]
    errors: list[str]
    warnings: list[str]


def check_step_companions(
    workspace: Workspace,
    skill_name: str,
    extra_required: list[str] | None = None,
    min_size: int = 50,
) -> CheckResult:
    """检查二级文件是否齐全。

    每个文件要求：存在 + 大小 > min_size 字节（防空文件占位）。
    """
    required = list(extra_required or [])
    required.extend(required_companions(skill_name, workspace))

    missing: list[str] = []
    errors: list[str] = []
    for rel in required:
        if not workspace.file_exists(rel):
            missing.append(rel)
            continue
        size = workspace.file_size(rel)
        if size < min_size:
            errors.append(f"{rel} 太小（{size} 字节 < {min_size}）")
    ok = not missing and not errors
    return CheckResult(ok=ok, missing=missing, errors=errors, warnings=[])


def check_primary_output(
    workspace: Workspace,
    rel_path: str,
    min_size: int = 100,
) -> CheckResult:
    """检查主产物是否存在且大小达标。"""
    if not workspace.file_exists(rel_path):
        return CheckResult(ok=False, missing=[rel_path], errors=[], warnings=[])
    size = workspace.file_size(rel_path)
    if size < min_size:
        return CheckResult(
            ok=False,
            missing=[],
            errors=[f"{rel_path} 太小（{size} 字节 < {min_size}）"],
            warnings=[],
        )
    return CheckResult(ok=True, missing=[], errors=[], warnings=[])


# === 语法检查 ===

def check_python_syntax(workspace: Workspace, rel_path: str) -> tuple[bool, str]:
    """对单个 .py 文件做 compile() 语法检查。

    Returns:
        (ok, error_message)
    """
    try:
        content = workspace.read_file(rel_path)
    except Exception as e:
        return False, f"读取失败: {e}"
    try:
        compile(content, rel_path, "exec")
    except SyntaxError as e:
        return False, f"语法错误 (line {e.lineno}): {e.msg}"
    return True, ""


def check_js_brackets(workspace: Workspace, rel_path: str) -> tuple[bool, str]:
    """对 JS/TS 文件做括号匹配检查。

    检查 () [] {} 是否配对。不解析语法，只做粗粒度检查。
    """
    try:
        content = workspace.read_file(rel_path)
    except Exception as e:
        return False, f"读取失败: {e}"

    # 简单括号计数（不处理字符串/注释中的括号，但够用）
    pairs = {"(": ")", "[": "]", "{": "}"}
    closers = set(pairs.values())
    stack: list[str] = []
    in_string: str | None = None  # 当前所在的字符串引号
    in_line_comment = False
    in_block_comment = False

    i = 0
    while i < len(content):
        c = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        # 注释处理
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if c == "\\":
                i += 2  # 跳过转义字符
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue

        # 进入注释/字符串/正则表达式
        if c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if c in ('"', "'", "`"):
            in_string = c
            i += 1
            continue
        # 正则表达式字面量检测：/ 不是注释开头，需要判断是除法还是正则
        if c == "/" and nxt != "/" and nxt != "*":
            # 找前一个非空白字符
            prev_idx = i - 1
            while prev_idx >= 0 and content[prev_idx] in " \t\n\r":
                prev_idx -= 1
            prev_char = content[prev_idx] if prev_idx >= 0 else ""
            # 如果前一个字符是 ) ] } 标识符 数字 引号 → 除法，不跳过
            # 如果前一个字符是 ( [ { , ; = ! & | : + - * < > ? 或空 → 正则
            if prev_char and (prev_char.isalnum() or prev_char in ")]}\"'"):
                pass  # 除法，正常处理
            else:
                # 正则表达式，跳过到下一个未转义的 /
                i += 1
                while i < len(content):
                    if content[i] == "\\":
                        i += 2
                        continue
                    if content[i] == "[":
                        # 字符类 [...]，跳过到 ]
                        i += 1
                        while i < len(content) and content[i] != "]":
                            if content[i] == "\\":
                                i += 2
                                continue
                            i += 1
                        i += 1
                        continue
                    if content[i] == "/":
                        i += 1
                        # 跳过正则标志 (g, i, m, s, u, y)
                        while i < len(content) and content[i] in "gimsuy":
                            i += 1
                        break
                    i += 1
                continue

        # 括号匹配
        if c in pairs:
            stack.append(c)
        elif c in closers:
            if not stack:
                return False, f"多余的闭合括号 '{c}'"
            opener = stack.pop()
            if pairs[opener] != c:
                return False, f"括号不匹配: '{opener}' 与 '{c}'"
        i += 1

    if stack:
        return False, f"未闭合的括号: {''.join(stack)}"
    return True, ""


def check_html_tags(workspace: Workspace, rel_path: str) -> tuple[bool, str]:
    """对 HTML 文件做标签闭合检查（粗粒度）。"""
    try:
        content = workspace.read_file(rel_path)
    except Exception as e:
        return False, f"读取失败: {e}"

    # 自闭合标签不需要闭合
    void_tags = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    tag_re = re.compile(r"</?([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*/?>")
    stack: list[str] = []
    for m in tag_re.finditer(content):
        tag = m.group(0)
        name = m.group(1).lower()
        is_close = tag.startswith("</")
        is_self_close = tag.endswith("/>")
        if is_self_close or name in void_tags:
            continue
        if is_close:
            if not stack or stack[-1] != name:
                return False, f"标签不匹配: </{name}> (栈顶: {stack[-1] if stack else '空'})"
            stack.pop()
        else:
            stack.append(name)
    if stack:
        return False, f"未闭合的标签: {stack}"
    return True, ""


def check_css_braces(workspace: Workspace, rel_path: str) -> tuple[bool, str]:
    """对 CSS/SCSS/LESS 文件做花括号匹配检查（粗粒度）。

    忽略注释与字符串内的括号。
    """
    try:
        content = workspace.read_file(rel_path)
    except Exception as e:
        return False, f"读取失败: {e}"

    stack: list[str] = []
    i = 0
    in_block_comment = False
    in_string: str | None = None
    while i < len(content):
        c = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if c in ('"', "'"):
            in_string = c
            i += 1
            continue
        if c == "{":
            stack.append("{")
        elif c == "}":
            if not stack:
                return False, "多余的 '}'"
            stack.pop()
        i += 1
    if stack:
        return False, f"未闭合的 '{''.join(stack)}'"
    return True, ""


def check_all_code_files(workspace: Workspace) -> CheckResult:
    """扫描工作区 code/ 目录下所有代码文件，做语法检查。

    返回聚合结果。
    """
    errors: list[str] = []
    warnings: list[str] = []
    code_dir = workspace.root / "code"
    if not code_dir.exists():
        return CheckResult(ok=True, missing=[], errors=[], warnings=["code/ 目录不存在"])

    for p in sorted(code_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(workspace.root).as_posix()
        ext = p.suffix.lower()

        if ext == ".py":
            ok, msg = check_python_syntax(workspace, rel)
            if not ok:
                errors.append(f"{rel}: {msg}")
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            ok, msg = check_js_brackets(workspace, rel)
            if not ok:
                errors.append(f"{rel}: {msg}")
        elif ext in (".html", ".htm"):
            ok, msg = check_html_tags(workspace, rel)
            if not ok:
                errors.append(f"{rel}: {msg}")
        elif ext in (".css", ".scss", ".less"):
            ok, msg = check_css_braces(workspace, rel)
            if not ok:
                errors.append(f"{rel}: {msg}")

    return CheckResult(ok=not errors, missing=[], errors=errors, warnings=warnings)


# === 产物契约 / 依赖检查 ===

# Python 标准库模块（粗略集合，用于判断 import 是否需要第三方包）
_PY_STDLIB_MODULES: set[str] = set()
try:
    import sys
    _PY_STDLIB_MODULES = {
        m.split(".")[0] for m in set(sys.stdlib_module_names)  # py3.10+
    }  # type: ignore[attr-defined]
except AttributeError:
    # 兜底：常见标准库
    _PY_STDLIB_MODULES = {
        "os", "sys", "json", "re", "time", "datetime", "pathlib", "typing",
        "asyncio", "logging", "collections", "functools", "itertools",
        "math", "random", "hashlib", "io", "csv", "sqlite3", "urllib",
        "http", "socket", "threading", "subprocess", "shutil", "tempfile",
        "argparse", "configparser", "dataclasses", "enum", "abc",
    }


def check_md_sections(
    workspace: Workspace, rel_path: str, required_sections: list[str],
) -> CheckResult:
    """检查 markdown 文件是否包含必需章节（## 标题）。

    Args:
        required_sections: 必需的章节标题文本（不含 ## 前缀），不区分大小写。
                           用于产物契约校验，如 ['技术栈', '功能需求']。
    """
    if not workspace.file_exists(rel_path):
        return CheckResult(ok=False, missing=[rel_path], errors=[], warnings=[])
    try:
        content = workspace.read_file(rel_path)
    except Exception as e:
        return CheckResult(ok=False, missing=[], errors=[f"读取失败: {e}"], warnings=[])
    # 提取所有 ## 与 ### 标题
    headings = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
    headings_lower = [h.strip().lower() for h in headings]
    missing_sections: list[str] = []
    for req in required_sections:
        req_lower = req.strip().lower()
        if not any(req_lower in h or h in req_lower for h in headings_lower):
            missing_sections.append(req)
    if missing_sections:
        return CheckResult(
            ok=False, missing=[],
            errors=[f"{rel_path} 缺少章节: {missing_sections}（现有章节: {headings[:10]}）"],
            warnings=[],
        )
    return CheckResult(ok=True, missing=[], errors=[], warnings=[])


def check_imports_exist(workspace: Workspace) -> CheckResult:
    """扫描 code/ 下 .py 文件的 import 语句，对照 requirements.txt 与标准库判断依赖是否存在。

    返回 warning（不阻断，因为有些 import 可能是项目内部模块）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    code_dir = workspace.root / "code"
    if not code_dir.exists():
        return CheckResult(ok=True, missing=[], errors=[], warnings=[])

    # 收集 requirements.txt 中的包名
    declared_deps: set[str] = set()
    for req_rel in ("code/backend/requirements.txt", "code/requirements.txt", "requirements.txt"):
        if workspace.file_exists(req_rel):
            try:
                for line in workspace.read_file(req_rel).splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # 取包名（去掉版本约束）
                    pkg = re.split(r"[<>=!\[ ]", line, 1)[0].strip().lower().replace("-", "_")
                    if pkg:
                        declared_deps.add(pkg)
            except Exception:
                pass

    # 收集项目内部模块（code/ 下的 .py 文件名，去掉扩展名）
    internal_modules: set[str] = set()
    for p in code_dir.rglob("*.py"):
        internal_modules.add(p.stem)

    import_re = re.compile(
        r"^\s*(?:from\s+([a-zA-Z_][\w.]*)|import\s+([a-zA-Z_][\w.,\s]*))",
        re.MULTILINE,
    )

    for p in sorted(code_dir.rglob("*.py")):
        rel = p.relative_to(workspace.root).as_posix()
        try:
            content = workspace.read_file(rel)
        except Exception:
            continue
        for m in import_re.finditer(content):
            mod = (m.group(1) or m.group(2) or "").split(",")[0].strip().split(" as ")[0]
            if not mod:
                continue
            top = mod.split(".")[0]
            if top in _PY_STDLIB_MODULES:
                continue
            if top in internal_modules:
                continue
            if top in declared_deps:
                continue
            # 未识别：可能是未声明的第三方包或内部模块
            warnings.append(f"{rel}: import {top} 未在 requirements.txt 声明且非标准库/内部模块")

    return CheckResult(ok=not errors, missing=[], errors=errors, warnings=warnings)


def check_package_json_scripts(workspace: Workspace) -> CheckResult:
    """检查 code/ 下 package.json 的 scripts 完整性。

    要求 scripts.start 存在，且其引用的入口文件实际存在。
    """
    import json as _json
    errors: list[str] = []
    warnings: list[str] = []
    checked = False
    code_dir = workspace.root / "code"
    if not code_dir.exists():
        return CheckResult(ok=True, missing=[], errors=[], warnings=[])

    for p in sorted(code_dir.rglob("package.json")):
        checked = True
        rel = p.relative_to(workspace.root).as_posix()
        try:
            data = _json.loads(workspace.read_file(rel))
        except Exception as e:
            errors.append(f"{rel}: JSON 解析失败: {e}")
            continue
        scripts = data.get("scripts", {}) or {}
        if "start" not in scripts:
            warnings.append(f"{rel}: 缺少 scripts.start")
            continue
        start_cmd = str(scripts["start"])
        # 提取引用的入口文件（粗略：找 xxx.js / xxx.ts）
        for ref in re.findall(r"[\w./-]+\.(?:js|ts|jsx|tsx|mjs|cjs)", start_cmd):
            ref_path = ref.lstrip("./")
            # 相对 package.json 所在目录
            pkg_dir = p.parent
            entry = pkg_dir / ref_path
            if not entry.exists():
                warnings.append(f"{rel}: scripts.start 引用的 {ref} 不存在")

    if not checked:
        return CheckResult(ok=True, missing=[], errors=[], warnings=[])
    return CheckResult(ok=not errors, missing=[], errors=errors, warnings=warnings)

