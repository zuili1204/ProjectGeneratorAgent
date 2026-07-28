"""健康检查：文件大小、二级文件齐全、语法检查、测试执行。

对应 Modex-MH-Agent 的：
- _min_size_for (主产物大小检查)
- _check_step_companions (二级文件齐全)
- _required_companions_for (必需文件列表)

改进：
- Python 用 compile() 做真语法检查（不只看大小）
- JS/TS 用括号匹配
- HTML 用标签闭合检查
- 按 project_type 动态决定 dev-code 的必需文件
- 测试执行门禁：check_test_directory_exists + check_tests_pass（P0）
- 运行时验证：check_runtime_succeeds（启动后端 / CLI --help）
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
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


def check_all_skill_outputs(
    workspace: Workspace, outputs: list[str], min_size: int = 50,
) -> CheckResult:
    """检查 skill 声明的所有 outputs 是否存在且大小达标。

    与 check_primary_output 不同，此函数检查全部 outputs 列表
    （如 dev-design 的 [DESIGN.md, DESIGN_SYSTEM.md]），
    确保非主产物（如 DESIGN_SYSTEM.md）也被产出。
    主产物由 check_primary_output 单独检查（使用更大的 min_size），
    此函数检查列表中剩余的次要产物。

    支持目录型 outputs（以 / 结尾，如 code/tests/）：
    检查目录存在且非空，不做文件大小检查。
    """
    missing: list[str] = []
    errors: list[str] = []
    for rel in outputs:
        # 目录型 outputs（以 / 结尾）：检查目录存在且非空
        if rel.endswith("/"):
            dir_path = workspace.root / rel.rstrip("/")
            if not dir_path.is_dir():
                missing.append(rel)
                continue
            has_files = any(p.is_file() for p in dir_path.rglob("*"))
            if not has_files:
                errors.append(f"{rel} 目录为空")
            continue
        # 文件型 outputs：检查存在 + 大小
        if not workspace.file_exists(rel):
            missing.append(rel)
            continue
        size = workspace.file_size(rel)
        if size < min_size:
            errors.append(f"{rel} 太小（{size} 字节 < {min_size}）")
    ok = not missing and not errors
    return CheckResult(ok=ok, missing=missing, errors=errors, warnings=[])


# 空模板残留标志（dev-selfcheck 未实际执行时遗留的占位符）
_PENDING_MARKERS = ("pending", "待填充", "待完成", "待检查")


def check_self_check_completeness(workspace: Workspace) -> CheckResult:
    """检查 SELF_CHECK.md 是否已填充完毕（无 pending / 待填充 残留）。

    dev-selfcheck 的 Post-checks 要求 "no pending check left over"，
    但此前健康检查只验证 SELF_CHECK.md 存在，不验证内容完整性。
    此函数检测空模板残留，防止自检报告未实际执行就通过门禁。
    """
    if not workspace.file_exists("SELF_CHECK.md"):
        return CheckResult(ok=False, missing=["SELF_CHECK.md"], errors=[], warnings=[])
    try:
        content = workspace.read_file("SELF_CHECK.md")
    except Exception as e:
        return CheckResult(ok=False, missing=[], errors=[f"读取失败: {e}"], warnings=[])

    # 统计残留标志数（不区分大小写）
    lower = content.lower()
    residual = sum(lower.count(m.lower()) for m in _PENDING_MARKERS)

    if residual > 3:
        return CheckResult(
            ok=False, missing=[],
            errors=[
                f"SELF_CHECK.md 含 {residual} 处未完成标志（pending/待填充/待完成/待检查），"
                "自检未实际执行——必须逐项检查并填写结论，不能留空模板"
            ],
            warnings=[],
        )
    if residual > 0:
        return CheckResult(
            ok=True, missing=[], errors=[],
            warnings=[f"SELF_CHECK.md 含 {residual} 处未完成标志（在容忍阈值内）"],
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


# === 测试执行门禁（P0） ===
#
# 借鉴 superpowers verification-before-completion：
#   NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
#
# 这里的 check_tests_pass 是「证据门」：跑实际测试命令，要求 0 failures。
# 不再接受「文件存在 + 大小达标」作为完成凭证。


# 测试目录候选（按优先级）：code/tests/、code/backend/tests/、code/test/、code/__tests__/
_TEST_DIR_CANDIDATES: tuple[str, ...] = (
    "code/tests",
    "code/backend/tests",
    "code/test",
    "code/__tests__",
    "code/frontend/tests",
    "code/frontend/src/__tests__",
)


def check_test_directory_exists(workspace: Workspace) -> CheckResult:
    """检查 code/ 下是否存在测试目录。

    Returns:
        CheckResult.ok=True 时 missing=[]，warnings 含找到的测试目录路径。
        CheckResult.ok=False 时 missing 含所有候选路径，errors 说明无测试目录。
    """
    found: list[str] = []
    for cand in _TEST_DIR_CANDIDATES:
        if workspace.file_exists(cand):
            found.append(cand)
    if found:
        return CheckResult(
            ok=True, missing=[], errors=[],
            warnings=[f"找到测试目录: {found[0]}"],
        )
    return CheckResult(
        ok=False,
        missing=list(_TEST_DIR_CANDIDATES),
        errors=[
            "未找到测试目录（已检查: " + ", ".join(_TEST_DIR_CANDIDATES) + "）。"
            "dev-code 必须产出 code/tests/ 或类似目录，含至少一个测试文件。"
        ],
        warnings=[],
    )


def check_test_files_exist(workspace: Workspace, test_dir: str = "") -> CheckResult:
    """检查测试目录下是否存在测试文件（.py / .js / .ts 等）。"""
    target = test_dir or _resolve_test_dir(workspace)
    if not target:
        return CheckResult(
            ok=False, missing=[], errors=["无测试目录，无法检查测试文件"], warnings=[]
        )
    test_exts = {".py", ".js", ".ts", ".jsx", ".tsx"}
    test_prefixes = ("test_", "test.", "_test.", "_test-", "tests_")
    test_suffixes = ("_test.py", "_test.js", "_test.ts", ".test.js", ".test.ts", ".spec.js", ".spec.ts")
    found_files: list[str] = []
    code_dir = workspace.root / target
    if not code_dir.exists():
        return CheckResult(ok=False, missing=[target], errors=[], warnings=[])
    for p in sorted(code_dir.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        ext = p.suffix.lower()
        if ext not in test_exts:
            continue
        # pytest/unittest 风格：test_*.py
        # jest 风格：*.test.js / *.spec.js
        # go 风格：*_test.go
        if name.startswith(test_prefixes) or any(name.endswith(s) for s in test_suffixes):
            rel = p.relative_to(workspace.root).as_posix()
            found_files.append(rel)
    if not found_files:
        return CheckResult(
            ok=False, missing=[], errors=[],
            warnings=[f"测试目录 {target} 存在但未发现测试文件（需 test_*.py 或 *.test.js 命名）"],
        )
    return CheckResult(ok=True, missing=[], errors=[], warnings=found_files[:5])


def _resolve_test_dir(workspace: Workspace) -> str:
    """返回工作区中实际存在的测试目录（首个命中），无则空串。"""
    for cand in _TEST_DIR_CANDIDATES:
        if workspace.file_exists(cand):
            return cand
    return ""


async def _run_command_capture(
    workspace: Workspace, command: str, timeout: int = 60,
) -> tuple[int, str, str]:
    """在工作区执行命令并捕获 (exit_code, stdout, stderr)。

    不走 security.validate_command，因为这里命令由健康检查构造而非 LLM。
    超时返回 (124, "", "timeout")。
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        return -1, "", f"spawn failed: {e}"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return 124, "", f"command timed out after {timeout}s"
    out = stdout.decode("utf-8", errors="replace") if stdout else ""
    err = stderr.decode("utf-8", errors="replace") if stderr else ""
    return proc.returncode if proc.returncode is not None else -1, out, err


async def check_tests_pass(workspace: Workspace, timeout: int = 60) -> CheckResult:
    """执行测试套件，要求 0 failures 才算通过。

    策略：
    1. 优先 pytest（Python 项目）
    2. 其次 npm test / jest（Node 项目）
    3. 都没有则返回 ok=False，errors 说明无测试 runner

    Returns:
        CheckResult.ok=True: 测试通过，warnings 含测试输出摘要
        CheckResult.ok=False: 测试失败或无 runner，errors 含失败详情
    """
    test_dir = _resolve_test_dir(workspace)
    if not test_dir:
        return CheckResult(
            ok=False, missing=[], errors=["无测试目录，无法执行测试"], warnings=[]
        )

    errors: list[str] = []
    warnings: list[str] = []

    # 检测 Python 测试：测试目录下有 .py 文件 + 代码目录有 requirements.txt
    has_py_tests = any(
        (workspace.root / test_dir / p).exists()
        for p in _walk_py_files(workspace, test_dir)
    ) if test_dir else False

    # 检测 Node 测试：package.json 含 jest/vitest/mocha
    has_node_tests = _has_node_test_runner(workspace)

    if has_py_tests:
        # 优先 pytest，失败回退 python -m unittest
        pytest_cmd = f"python -m pytest {test_dir} -v --tb=short 2>&1"
        exit_code, out, err = await _run_command_capture(workspace, pytest_cmd, timeout)
        if exit_code == 0:
            warnings.append(f"pytest 通过（exit=0）")
            # 摘要末尾 5 行
            tail = "\n".join((out or "").splitlines()[-5:])
            if tail:
                warnings.append(f"输出摘要:\n{tail}")
            return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
        # pytest 失败：可能是 pytest 未安装，回退 unittest
        if "No module named pytest" in (out + err):
            warnings.append("pytest 未安装，回退 unittest")
            unittest_cmd = f"python -m unittest discover -s {test_dir} -v 2>&1"
            ec2, out2, err2 = await _run_command_capture(workspace, unittest_cmd, timeout)
            if ec2 == 0:
                warnings.append("unittest 通过（exit=0）")
                return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
            errors.append(f"unittest 失败（exit={ec2}）:\n{out2[-1500:]}\n{err2[-500:]}")
            return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)
        # pytest 真失败
        errors.append(f"pytest 失败（exit={exit_code}）:\n{out[-1500:]}\n{err[-500:]}")
        return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)

    if has_node_tests:
        # 优先 npm test，失败尝试 npx jest
        npm_cmd = "npm test --silent 2>&1"
        exit_code, out, err = await _run_command_capture(workspace, npm_cmd, timeout=120)
        if exit_code == 0:
            warnings.append("npm test 通过（exit=0）")
            tail = "\n".join((out or "").splitlines()[-5:])
            if tail:
                warnings.append(f"输出摘要:\n{tail}")
            return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
        errors.append(f"npm test 失败（exit={exit_code}）:\n{out[-1500:]}\n{err[-500:]}")
        return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)

    return CheckResult(
        ok=False, missing=[], errors=[
            f"测试目录 {test_dir} 存在但未识别到 Python/Node 测试 runner。"
            "请在 requirements.txt 声明 pytest，或在 package.json 声明 jest/vitest。"
        ], warnings=warnings
    )


def _walk_py_files(workspace: Workspace, test_dir: str) -> list[str]:
    """列出测试目录下所有 .py 文件的相对路径（用于判定是否有 Python 测试）。"""
    code_dir = workspace.root / test_dir
    if not code_dir.exists():
        return []
    result: list[str] = []
    for p in code_dir.rglob("*.py"):
        rel = p.relative_to(workspace.root).as_posix()
        result.append(rel)
    return result


def _has_node_test_runner(workspace: Workspace) -> bool:
    """检查 code/ 下任一 package.json 是否声明了测试 runner。"""
    import json as _json
    code_dir = workspace.root / "code"
    if not code_dir.exists():
        return False
    for p in code_dir.rglob("package.json"):
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        if any(k in deps for k in ("jest", "vitest", "mocha", "@playwright/test")):
            return True
        scripts = data.get("scripts") or {}
        if "test" in scripts and str(scripts["test"]).strip():
            return True
    return False


async def check_runtime_succeeds(workspace: Workspace, project_type: str, timeout: int = 30) -> CheckResult:
    """运行时验证：启动项目并验证关键端点/命令可运行。

    按 project_type 选择验证策略：
    - fullstack / backend_only: 启动后端，调 /health 验证 200
    - cli: 跑 python main.py --help 验证退出码 0
    - script: 跑 python main.py --help（若支持）
    - frontend_only: 跳过（无法在无浏览器环境下验证）

    Returns:
        CheckResult.ok=True: 运行时验证通过
        CheckResult.ok=False: 启动失败或端点不可达
    """
    errors: list[str] = []
    warnings: list[str] = []

    if project_type == "frontend_only":
        return CheckResult(
            ok=True, missing=[], errors=[],
            warnings=["frontend_only 项目跳过运行时验证（需浏览器环境）"],
        )

    if project_type in ("fullstack", "backend_only"):
        # 定位后端入口
        backend_main = workspace.root / "code" / "backend" / "main.py"
        if not backend_main.exists():
            return CheckResult(
                ok=False, missing=["code/backend/main.py"],
                errors=["后端入口 code/backend/main.py 不存在"], warnings=[]
            )
        # 后台启动 uvicorn，sleep 3s，curl /health，最后 kill
        import time
        start_cmd = (
            f"python -m uvicorn code.backend.main:app --host 127.0.0.1 --port 8765 2>&1"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                start_cmd,
                cwd=str(workspace.root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return CheckResult(
                ok=False, missing=[], errors=[f"启动后端失败: {e}"], warnings=[]
            )
        try:
            # 等待服务启动
            await asyncio.sleep(3)
            # 调 /health
            curl_cmd = "python -c \"import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=5); print(r.status, r.read().decode()[:200])\" 2>&1"
            ec, out, err = await _run_command_capture(workspace, curl_cmd, timeout=10)
            if ec == 0 and "200" in out:
                warnings.append(f"后端 /health 返回 200: {out.strip()[:200]}")
                return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
            errors.append(f"/health 调用失败（exit={ec}）: {out[-500:]}\n{err[-300:]}")
            return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    if project_type in ("cli", "script"):
        main_py = workspace.root / "code" / "main.py"
        if not main_py.exists():
            return CheckResult(
                ok=False, missing=["code/main.py"],
                errors=["入口 code/main.py 不存在"], warnings=[]
            )
        cmd = "python code/main.py --help 2>&1"
        ec, out, err = await _run_command_capture(workspace, cmd, timeout=15)
        if ec == 0:
            warnings.append(f"python main.py --help 退出码 0: {out.strip()[:200]}")
            return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
        # --help 不支持时，尝试 python main.py（可能需要参数）
        if "unrecognized arguments" in (out + err) or "no such option" in (out + err).lower():
            warnings.append("--help 不支持，尝试 python code/main.py")
            ec2, out2, err2 = await _run_command_capture(workspace, "python code/main.py 2>&1", timeout=10)
            if ec2 == 0:
                warnings.append("python main.py 退出码 0")
                return CheckResult(ok=True, missing=[], errors=[], warnings=warnings)
            errors.append(f"python main.py 失败（exit={ec2}）: {out2[-500:]}")
            return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)
        errors.append(f"python main.py --help 失败（exit={ec}）: {out[-500:]}\n{err[-300:]}")
        return CheckResult(ok=False, missing=[], errors=errors, warnings=warnings)

    return CheckResult(
        ok=True, missing=[], errors=[],
        warnings=[f"未知 project_type={project_type}，跳过运行时验证"],
    )


# === 综合验证门禁（P0） ===

@dataclass
class VerificationReport:
    """verification-before-completion 综合报告。

    汇总测试目录 / 测试文件 / 测试执行 / 运行时验证四项证据，
    全部 ok=True 才允许步骤标记 completed。
    """
    test_dir_exists: CheckResult
    test_files_exist: CheckResult
    tests_pass: CheckResult
    runtime_ok: CheckResult
    overall_ok: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "test_dir_exists": self.test_dir_exists.ok,
            "test_files_exist": self.test_files_exist.ok,
            "tests_pass": self.tests_pass.ok,
            "runtime_ok": self.runtime_ok.ok,
            "overall_ok": self.overall_ok,
            "summary": self.summary,
            "details": {
                "test_dir_exists_errors": self.test_dir_exists.errors,
                "test_files_exist_warnings": self.test_files_exist.warnings,
                "tests_pass_errors": self.tests_pass.errors,
                "tests_pass_warnings": self.tests_pass.warnings,
                "runtime_errors": self.runtime_ok.errors,
                "runtime_warnings": self.runtime_ok.warnings,
            },
        }


async def run_verification_gate(
    workspace: Workspace, project_type: str, skip_runtime: bool = False,
) -> VerificationReport:
    """运行完整验证门禁（dev-selfcheck 调用）。

    四项证据全部通过才允许标记 completed：
    1. test_dir_exists: code/tests/ 等目录存在
    2. test_files_exist: 测试目录下有 test_*.py / *.test.js 文件
    3. tests_pass: pytest / npm test 退出码 0
    4. runtime_ok: 后端 /health 200 或 CLI --help 退出码 0

    Args:
        skip_runtime: True 时跳过运行时验证（适用于无后端/CLI 的纯库项目）
    """
    dir_check = check_test_directory_exists(workspace)
    files_check = check_test_files_exist(workspace)
    tests_check = await check_tests_pass(workspace)
    if skip_runtime:
        runtime_check = CheckResult(
            ok=True, missing=[], errors=[],
            warnings=["运行时验证已跳过（skip_runtime=True）"],
        )
    else:
        runtime_check = await check_runtime_succeeds(workspace, project_type)

    overall = dir_check.ok and files_check.ok and tests_check.ok and runtime_check.ok
    parts = [
        f"测试目录={'通过' if dir_check.ok else '失败'}",
        f"测试文件={'通过' if files_check.ok else '失败'}",
        f"测试执行={'通过' if tests_check.ok else '失败'}",
        f"运行时验证={'通过' if runtime_check.ok else '失败'}",
    ]
    summary = " | ".join(parts)
    if overall:
        summary = f"✓ 验证通过: {summary}"
    else:
        summary = f"✗ 验证未通过: {summary}"

    return VerificationReport(
        test_dir_exists=dir_check,
        test_files_exist=files_check,
        tests_pass=tests_check,
        runtime_ok=runtime_check,
        overall_ok=overall,
        summary=summary,
    )

