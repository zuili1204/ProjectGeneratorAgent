"""静态 UI 质量门：把 SKILL 里的 UI 检查变成可执行门禁。

只做**无需浏览器**的静态检查，避免引入 Playwright 依赖：
- token 纪律：token 文件存在且被引用；组件不得出现裸 hex
- 对比度：解析 `--x` / `--on-x` token 配对，按 WCAG 计算
- 可访问性：img alt、button 可访问名、input 标签、focus、reduced-motion
- 响应式：viewport meta、@media
- 图标纪律：交互元素仅用 emoji 作结构图标（启发式，警告）
- 触控目标：button/.btn 显式 min-height/min-width < 44px（启发式，警告）

真实渲染后的尺寸与计算色值仍需浏览器，不在本模块范围。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .workspace import Workspace

# 扫描的源码类型
_SCAN_EXTS = {
    ".css", ".scss", ".less",
    ".html", ".htm",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
}

# 不参与 UI 检查的目录（scan() 已排除 node_modules 等，这里再兜一层）
_SKIP_DIRS = {
    "node_modules", "dist", "build", "vendor", ".git", ".next", ".nuxt", "coverage",
    # 测试夹具可能故意使用裸 hex / 不完整页面，不纳入交付质量门
    "tests", "test", "__tests__", "spec",
}

# token 文件命名约定：tokens.css / variables.css / design-system.css / theme.css
_TOKEN_FILE_RE = re.compile(
    r"(?:^|/)(?:tokens?|variables?|design-system|theme)[^/]*\.(?:css|scss|less)$",
    re.IGNORECASE,
)

_HEX_RE = re.compile(
    # (?<!&) 排除 HTML 数字实体，如 &#9790;（雪人符号）
    r"(?<!&)#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])"
)
_DECL_RE = re.compile(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;")
_MEDIA_RE = re.compile(r"@media\b", re.IGNORECASE)
_VIEWPORT_RE = re.compile(
    r"<meta[^>]+name\s*=\s*[\"']viewport[\"']", re.IGNORECASE
)
_ATTR_RE = re.compile(
    r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))"
)
_EMOJI_ONLY_RE = re.compile(
    r"^[\s\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+$"
)
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)


@dataclass
class UiFinding:
    """单条 UI 门禁发现。"""
    level: str          # blocker | warn
    code: str           # RAW_HEX / MISSING_ALT ...
    file: str
    line: int
    message: str
    hint: str = ""


@dataclass
class UiGateReport:
    """UI 门禁结果。"""
    project_type: str
    checked_files: int = 0
    findings: list[UiFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[UiFinding]:
        return [f for f in self.findings if f.level == "blocker"]

    @property
    def warnings(self) -> list[UiFinding]:
        return [f for f in self.findings if f.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.blockers

    @property
    def summary(self) -> str:
        if not self.findings:
            return f"✓ UI 门禁通过（{self.checked_files} 个文件）"
        return (
            f"{'✓' if self.ok else '✗'} UI 门禁："
            f"{len(self.blockers)} blockers / {len(self.warnings)} warnings "
            f"（{self.checked_files} 个文件）"
        )

    def to_markdown(self, max_items: int = 60) -> str:
        lines = [
            "# UI Quality Gate",
            "",
            f"- 项目类型: {self.project_type}",
            f"- 检查文件: {self.checked_files}",
            f"- 结论: {self.summary}",
            "- 说明: 静态检查（不包含浏览器渲染后的尺寸/计算色值）",
            "",
        ]
        if self.notes:
            lines.append("## 说明")
            for n in self.notes:
                lines.append(f"- {n}")
            lines.append("")
        for title, items in (("Blockers", self.blockers), ("Warnings", self.warnings)):
            lines.append(f"## {title} ({len(items)})")
            if not items:
                lines.append("- 无")
            for f in items[:max_items]:
                hint = f"；建议: {f.hint}" if f.hint else ""
                lines.append(
                    f"- `{f.file}:{f.line}` **[{f.code}]** {f.message}{hint}"
                )
            if len(items) > max_items:
                lines.append(f"- ... 其余 {len(items) - max_items} 项省略")
            lines.append("")
        return "\n".join(lines)


# === 颜色工具 ===

def _parse_hex(value: str) -> tuple[int, int, int] | None:
    s = value.lstrip("#")
    if len(s) in (3, 4):
        s = "".join(ch * 2 for ch in s[:3])
    elif len(s) in (6, 8):
        s = s[:6]
    else:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(fg: str, bg: str) -> float | None:
    """WCAG 对比度；任一颜色无法解析返回 None。"""
    a, b = _parse_hex(fg), _parse_hex(bg)
    if not a or not b:
        return None
    la = 0.2126 * _linear(a[0]) + 0.7152 * _linear(a[1]) + 0.0722 * _linear(a[2])
    lb = 0.2126 * _linear(b[0]) + 0.7152 * _linear(b[1]) + 0.0722 * _linear(b[2])
    high, low = (la, lb) if la >= lb else (lb, la)
    return round((high + 0.05) / (low + 0.05), 2)


# === 扫描工具 ===

def _read(workspace: Workspace, rel: str) -> str:
    try:
        return (workspace.root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def _attrs(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for m in _ATTR_RE.finditer(raw):
        result[m.group(1).lower()] = next(
            (g for g in (m.group(2), m.group(3), m.group(4)) if g is not None), ""
        )
    return result


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _scan_files(workspace: Workspace) -> tuple[list[str], list[str], list[str]]:
    """返回 (全部扫描文件, css 文件, html 文件)。只处理 code/ 下文件。"""
    all_files: list[str] = []
    css_files: list[str] = []
    html_files: list[str] = []
    for rel in workspace.scan():
        if not rel.startswith("code/"):
            continue
        parts = Path(rel).parts
        if any(p in _SKIP_DIRS for p in parts):
            continue
        if Path(rel).suffix.lower() not in _SCAN_EXTS:
            continue
        all_files.append(rel)
        ext = Path(rel).suffix.lower()
        if ext in (".css", ".scss", ".less"):
            css_files.append(rel)
        elif ext in (".html", ".htm"):
            html_files.append(rel)
    return all_files, css_files, html_files


# === 各项检查 ===

def _check_tokens(
    workspace: Workspace, files: list[str], report: UiGateReport,
) -> list[str]:
    """token 文件存在性与引用；返回 token 文件列表。"""
    has_design_system = workspace.file_exists("DESIGN_SYSTEM.md")
    token_files = [f for f in files if _TOKEN_FILE_RE.search(f)]

    if not token_files:
        if has_design_system:
            report.findings.append(UiFinding(
                "blocker", "TOKENS_MISSING", "code/", 0,
                "存在 DESIGN_SYSTEM.md，但未找到 tokens.css / variables.css",
                "按 DESIGN_SYSTEM.md 落地 token 文件（如 code/css/tokens.css）",
            ))
        else:
            report.findings.append(UiFinding(
                "warn", "TOKENS_MISSING", "code/", 0,
                "未找到 token 文件（tokens.css / variables.css）",
                "建议集中定义语义 token，组件通过 var(--*) 消费",
            ))
        return token_files

    token_set = set(token_files)
    non_token = [f for f in files if f not in token_set]
    uses_var = any("var(--" in _read(workspace, f) for f in non_token)
    has_tailwind = any(
        Path(f).name.startswith("tailwind.config") for f in files
    )
    if not uses_var and not has_tailwind:
        report.findings.append(UiFinding(
            "blocker", "TOKENS_UNUSED", token_files[0], 1,
            "存在 token 文件，但组件未使用 var(--*)（也没有 Tailwind token 配置）",
            "组件改用 var(--token) 或 Tailwind token 类，避免绕过设计系统",
        ))
    return token_files


def _check_raw_hex(
    workspace: Workspace, files: list[str], token_files: list[str], report: UiGateReport,
) -> None:
    token_set = set(token_files)
    allowed_names = ("tailwind.config", "postcss.config", "vite.config")
    total = 0
    for rel in files:
        if rel in token_set:
            continue
        # 内容数据（文章封面色等）不属于组件样式，跳过避免误报
        if "/data/" in rel:
            continue
        name = Path(rel).name
        if name.startswith(allowed_names) or ".min." in name:
            continue
        text = _read(workspace, rel)
        matches = list(_HEX_RE.finditer(text))
        if not matches:
            continue
        for m in matches[:5]:
            total += 1
            if total > 30:
                report.notes.append("裸 hex 发现超过 30 处，报告已截断")
                return
            report.findings.append(UiFinding(
                "blocker", "RAW_HEX", rel, _line_of(text, m.start()),
                f"组件中出现裸 hex 色值 {m.group(0)}",
                "改为 var(--color-token)；token 只在 tokens.css / variables.css 中定义",
            ))


def _check_contrast(
    workspace: Workspace, token_files: list[str], report: UiGateReport,
) -> None:
    tokens: dict[str, str] = {}
    for rel in token_files:
        for m in _DECL_RE.finditer(_read(workspace, rel)):
            tokens[m.group(1)] = m.group(2)

    if not tokens:
        report.notes.append("未解析到 token 颜色，跳过对比度检查")
        return

    pairs: list[tuple[str, str]] = []
    for name in tokens:
        if name.startswith("--on-"):
            continue
        on_name = f"--on-{name[2:]}"
        if on_name in tokens:
            pairs.append((name, on_name))
    for a, b in (
        ("--background", "--foreground"),
        ("--bg", "--fg"),
        ("--surface", "--on-surface"),
    ):
        if a in tokens and b in tokens:
            pairs.append((a, b))

    seen: set[tuple[str, str]] = set()
    for fg, bg in pairs:
        key = (fg, bg) if fg < bg else (bg, fg)
        if key in seen:
            continue
        seen.add(key)
        ratio = contrast_ratio(tokens[fg], tokens[bg])
        if ratio is None:
            continue
        if ratio < 3.0:
            report.findings.append(UiFinding(
                "blocker", "CONTRAST_LOW", token_files[0], 1,
                f"{fg} 与 {bg} 对比度 {ratio}:1，低于 3:1",
                "调整 token 色值，正文目标 ≥4.5:1，大文本 ≥3:1",
            ))
        elif ratio < 4.5:
            report.findings.append(UiFinding(
                "warn", "CONTRAST_WARN", token_files[0], 1,
                f"{fg} 与 {bg} 对比度 {ratio}:1，低于正文 4.5:1",
                "若用于正文需提高对比度；仅大文本可接受 3:1",
            ))


def _check_html(
    workspace: Workspace, html_files: list[str], report: UiGateReport,
) -> None:
    for rel in html_files:
        text = _read(workspace, rel)
        if not text:
            continue

        # viewport：仅检查整页（含 <html> 或 <!doctype>）
        if ("<html" in text.lower() or "<!doctype" in text.lower()) and not _VIEWPORT_RE.search(text):
            report.findings.append(UiFinding(
                "blocker", "NO_VIEWPORT", rel, 1,
                "页面缺少 <meta name=\"viewport\">，移动端无法正确缩放",
                "在 <head> 添加 width=device-width, initial-scale=1",
            ))

        # img alt
        for m in re.finditer(r"<img\b([^>]*)>", text, re.IGNORECASE):
            attrs = _attrs(m.group(1))
            if "alt" not in attrs:
                report.findings.append(UiFinding(
                    "blocker", "MISSING_ALT", rel, _line_of(text, m.start()),
                    "<img> 缺少 alt 属性",
                    "补 alt（装饰图用 alt=\"\"）；不要用文件名当 alt",
                ))

        # button 可访问名 + emoji 结构图标
        for m in re.finditer(
            r"<button\b([^>]*)>(.*?)</button>", text, re.IGNORECASE | re.DOTALL
        ):
            attrs = _attrs(m.group(1))
            inner = _strip_tags(m.group(2))
            has_name = bool(attrs.get("aria-label") or attrs.get("title") or inner)
            if not has_name:
                report.findings.append(UiFinding(
                    "blocker", "BUTTON_NO_NAME", rel, _line_of(text, m.start()),
                    "<button> 既无文本，也无 aria-label/title",
                    "补可见文本或 aria-label",
                ))
            elif inner and _EMOJI_ONLY_RE.match(inner):
                report.findings.append(UiFinding(
                    "warn", "EMOJI_ICON", rel, _line_of(text, m.start()),
                    f"按钮仅用 emoji 作图标：{inner[:8]}",
                    "改用内联 SVG 或几何符号，emoji 不作为结构图标",
                ))

        # a 仅 emoji
        for m in re.finditer(
            r"<a\b([^>]*)>(.*?)</a>", text, re.IGNORECASE | re.DOTALL
        ):
            inner = _strip_tags(m.group(2))
            if inner and _EMOJI_ONLY_RE.match(inner):
                report.findings.append(UiFinding(
                    "warn", "EMOJI_ICON", rel, _line_of(text, m.start()),
                    f"链接仅用 emoji 作图标：{inner[:8]}",
                    "改用内联 SVG 或几何符号，并提供 aria-label",
                ))

        # input 标签
        label_ids = set(re.findall(
            r"<label[^>]+for\s*=\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE
        ))
        for m in re.finditer(r"<input\b([^>]*)>", text, re.IGNORECASE):
            attrs = _attrs(m.group(1))
            input_type = attrs.get("type", "text").lower()
            if input_type in ("hidden", "submit", "button", "reset", "image"):
                continue
            if attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("title"):
                continue
            input_id = attrs.get("id", "")
            if input_id and input_id in label_ids:
                continue
            report.findings.append(UiFinding(
                "warn", "INPUT_NO_LABEL", rel, _line_of(text, m.start()),
                f"<input id=\"{input_id}\"> 未关联 <label for> 或 aria-label",
                "添加 <label for> 或 aria-label",
            ))


def _check_css(
    workspace: Workspace, css_files: list[str], report: UiGateReport,
) -> None:
    has_media = False
    has_motion = False
    has_reduced_motion = False

    for rel in css_files:
        text = _read(workspace, rel)
        if not text:
            continue
        if _MEDIA_RE.search(text):
            has_media = True
        if "prefers-reduced-motion" in text:
            has_reduced_motion = True
        if re.search(r"(?:animation|transition)\s*:", text, re.IGNORECASE):
            has_motion = True

        # outline: none 必须配 :focus-visible，或在 :focus 规则里给出可见替代
        if re.search(r"outline\s*:\s*(?:none|0)\b", text, re.IGNORECASE):
            has_alt = ":focus-visible" in text or bool(re.search(
                r":focus[^{]*\{[^}]*(?:box-shadow|border(?:-[a-z]+)?\s*:)",
                text,
                re.IGNORECASE,
            ))
            if not has_alt:
                report.findings.append(UiFinding(
                    "warn", "FOCUS_REMOVED", rel, 1,
                    "移除了 outline，但没有 :focus-visible 或可见 focus 替代样式",
                    "为键盘用户补可见焦点环（box-shadow / border / outline）",
                ))

        # 触控目标：button/.btn 规则里显式 min-height/min-width < 44px
        for m in _RULE_RE.finditer(text):
            selector, body = m.group(1), m.group(2)
            if not re.search(r"\bbutton\b|\.btn\b|\.icon-btn\b", selector):
                continue
            for dim in ("min-height", "min-width"):
                dm = re.search(rf"{dim}\s*:\s*(\d+)px", body)
                if dm and int(dm.group(1)) < 44:
                    report.findings.append(UiFinding(
                        "warn", "TOUCH_TARGET", rel, 1,
                        f"交互控件 {dim}={dm.group(1)}px，小于 44px",
                        "触控目标建议 ≥44×44px",
                    ))

    if has_motion and not has_reduced_motion:
        report.findings.append(UiFinding(
            "warn", "NO_REDUCED_MOTION", css_files[0], 1,
            "存在 animation/transition，但全站未处理 prefers-reduced-motion",
            "加 @media (prefers-reduced-motion: reduce) 关闭/弱化动效",
        ))

    if css_files and not has_media:
        report.findings.append(UiFinding(
            "warn", "NO_MEDIA_QUERY", css_files[0], 1,
            "CSS 中没有任何 @media 断点",
            "补移动端断点（375/768/1024/1440）",
        ))


# === 入口 ===

def run_ui_gate(workspace: Workspace, project_type: str) -> UiGateReport:
    """对前端项目执行静态 UI 质量门。"""
    report = UiGateReport(project_type=project_type)

    if project_type not in ("fullstack", "frontend_only"):
        report.notes.append(f"project_type={project_type}，非前端项目，跳过 UI 门禁")
        return report

    files, css_files, html_files = _scan_files(workspace)
    report.checked_files = len(files)
    if not files:
        report.notes.append("code/ 下未发现可检查的前端文件")
        return report
    report.notes.append(
        f"扫描 {len(files)} 个文件（css={len(css_files)}, html={len(html_files)}）"
    )

    token_files = _check_tokens(workspace, files, report)
    _check_raw_hex(workspace, files, token_files, report)
    _check_contrast(workspace, token_files, report)
    _check_html(workspace, html_files, report)
    _check_css(workspace, css_files, report)

    return report
