"""工作区管理：创建、扫描、上下文构建、文件读写。

对应 Modex-MH-Agent 的 workflow_engine._scan_workspace /
_generate_claude_md / _build_context_summary / _inject_once。

改进：
- 用 CONTEXT.md 替代 CLAUDE.md（不绑定特定 LLM 品牌）
- 用 project.json 结构化配置（替代从 markdown 解析 project_type）
- 上下文摘要按字符预算截断，优先保留关键文件
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from .config import WORKSPACES_DIR

log = logging.getLogger(__name__)


# 扫描时排除的文件/目录名
_EXCLUDED_NAMES = {
    ".git", ".idea", ".vscode", "__pycache__", "node_modules",
    ".DS_Store", "Thumbs.db",
}

# 扫描时排除的特定文件
_EXCLUDED_FILES = {"CONTEXT.md", "project.json"}

# 关键文件类型（构建上下文摘要时优先读取）
_PRIORITY_EXTS = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}

# 单文件读取上限（字符数）
_MAX_FILE_CHARS = 4000

# 上下文摘要总上限（字符数）
_DEFAULT_CONTEXT_BUDGET = 12000


@dataclass
class ProjectMeta:
    """项目元数据（替代 CLAUDE.md 的 params 段）。"""
    title: str = ""
    template: str = ""
    project_type: str = "fullstack"
    auto_proceed: bool = False
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "ProjectMeta":
        d = json.loads(s)
        return cls(
            title=d.get("title", ""),
            template=d.get("template", ""),
            project_type=d.get("project_type", "fullstack"),
            auto_proceed=d.get("auto_proceed", False),
            extra=d.get("extra", {}),
        )


class Workspace:
    """单个工作流的隔离工作区。"""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        self.root = WORKSPACES_DIR / workflow_id
        self.root.mkdir(parents=True, exist_ok=True)

    # === 文件操作 ===

    def write_file(self, rel_path: str, content: str) -> Path:
        """写入文件（自动创建父目录）。"""
        # 防路径穿越
        safe = self._safe_rel(rel_path)
        full = self.root / safe
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        log.debug("workspace %s: wrote %s (%d bytes)", self.workflow_id, safe, len(content))
        return full

    def write_file_atomic(self, rel_path: str, content: str) -> Path:
        """原子写入文件：写临时文件 → fsync → os.replace 原子替换。

        用于 state.json 等关键文件，避免写到一半进程被 kill 留下损坏 JSON。
        """
        safe = self._safe_rel(rel_path)
        full = self.root / safe
        full.parent.mkdir(parents=True, exist_ok=True)
        tmp = full.with_suffix(full.suffix + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            # fsync 确保落盘
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
            os.replace(tmp, full)
        except Exception:
            # 出错时清理临时文件
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        log.debug("workspace %s: atomic wrote %s (%d bytes)", self.workflow_id, safe, len(content))
        return full

    def backup_file(self, rel_path: str) -> bool:
        """把文件备份为 rel_path + .bak，存在则覆盖。返回是否成功。"""
        safe = self._safe_rel(rel_path)
        full = self.root / safe
        if not full.exists():
            return False
        bak = full.with_suffix(full.suffix + ".bak")
        shutil.copy2(full, bak)
        return True

    def read_file(self, rel_path: str) -> str:
        """读取文件内容。"""
        safe = self._safe_rel(rel_path)
        return (self.root / safe).read_text(encoding="utf-8")

    def file_exists(self, rel_path: str) -> bool:
        safe = self._safe_rel(rel_path)
        return (self.root / safe).exists()

    def file_size(self, rel_path: str) -> int:
        safe = self._safe_rel(rel_path)
        p = self.root / safe
        return p.stat().st_size if p.exists() else 0

    def _safe_rel(self, rel_path: str) -> Path:
        """防路径穿越：把 rel_path 限制在 root 内。"""
        rel = Path(rel_path.replace("\\", "/"))
        # 不允许绝对路径或 .. 上跳
        if rel.is_absolute() or any(p == ".." for p in rel.parts):
            raise ValueError(f"Unsafe path: {rel_path}")
        return rel

    # === 扫描 ===

    def scan(self) -> list[str]:
        """扫描工作区，返回非隐藏文件相对路径列表。

        排除 _EXCLUDED_NAMES 中的目录、_EXCLUDED_FILES 中的文件。
        """
        result: list[str] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            # 检查路径中是否有排除的目录名
            parts = p.relative_to(self.root).parts
            if any(part in _EXCLUDED_NAMES for part in parts):
                continue
            if p.name in _EXCLUDED_FILES:
                continue
            rel = p.relative_to(self.root).as_posix()
            result.append(rel)
        return result

    @staticmethod
    def classify_file(rel_path: str) -> str:
        """对文件分类，用于文件清单增强与上下文分层。

        返回: entry / config / doc / source / asset / other
        """
        name = rel_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        ext = Path(rel_path).suffix.lower()
        # 入口文件
        if name in ("main.py", "app.py", "server.py", "__main__.py", "manage.py",
                    "index.js", "index.ts", "main.js", "main.ts", "app.js", "app.ts",
                    "index.html", "cli.py", "run.py"):
            return "entry"
        # 配置文件
        if name in ("package.json", "requirements.txt", "pyproject.toml",
                    "tsconfig.json", "vite.config.js", "vite.config.ts",
                    "project.json", "setup.py", "setup.cfg", "Pipfile", "pom.xml",
                    "cargo.toml") or ext in (".ini", ".cfg", ".toml", ".yaml", ".yml"):
            return "config"
        # 文档
        if ext in (".md", ".txt", ".rst"):
            return "doc"
        # 源码
        if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
                   ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php"):
            return "source"
        # 资源
        if ext in (".css", ".scss", ".less", ".html", ".htm", ".json", ".xml",
                   ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"):
            return "asset"
        return "other"

    # === 上下文构建 ===

    def build_context_summary(
        self,
        files: list[str] | None = None,
        max_chars: int = _DEFAULT_CONTEXT_BUDGET,
        layered: bool = False,
    ) -> str:
        """读取工作区文件的内容摘要，做字符预算截断。

        优先读取 _PRIORITY_EXTS 中的文件，其次读取其他文件。
        单文件最多读 _MAX_FILE_CHARS 字符。

        Args:
            layered: 若 True，先输出「清单层」（所有文件名+大小+分类，恒定保留），
                     再按预算填充「内容层」（关键文件全文）。这样即使预算紧张，
                     LLM 也至少能看到完整文件清单，避免盲猜。
        """
        files = files if files is not None else self.scan()
        # 按优先级排序：优先 .md/.json 等，其次其他
        def priority(f: str) -> int:
            ext = Path(f).suffix.lower()
            return 0 if ext in _PRIORITY_EXTS else 1
        files_sorted = sorted(files, key=priority)

        # 清单层：恒定输出，让 LLM 知道工作区有哪些文件
        list_layer = "## 工作区文件清单\n"
        for f in files_sorted:
            size = self.file_size(f)
            cls = self.classify_file(f)
            list_layer += f"- {f} ({size}B, {cls})\n"

        if not layered:
            # 旧行为：纯内容截断
            parts: list[str] = []
            used = 0
            for f in files_sorted:
                try:
                    content = self.read_file(f)
                except Exception as e:
                    log.debug("skip unreadable file %s: %s", f, e)
                    continue
                if len(content) > _MAX_FILE_CHARS:
                    content = content[:_MAX_FILE_CHARS] + f"\n... (truncated, {len(content) - _MAX_FILE_CHARS} chars omitted)"
                block = f"### {f}\n```\n{content}\n```\n"
                if used + len(block) > max_chars:
                    break
                parts.append(block)
                used += len(block)
            return "\n".join(parts)

        # 分层模式：清单层 + 内容层（内容层用剩余预算）
        content_budget = max(0, max_chars - len(list_layer))
        parts: list[str] = [list_layer, "\n## 关键文件内容"]
        used = 0
        for f in files_sorted:
            try:
                content = self.read_file(f)
            except Exception as e:
                log.debug("skip unreadable file %s: %s", f, e)
                continue
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + f"\n... (truncated, {len(content) - _MAX_FILE_CHARS} chars omitted)"
            block = f"### {f}\n```\n{content}\n```\n"
            if used + len(block) > content_budget:
                break
            parts.append(block)
            used += len(block)
        return "\n".join(parts)

    # === CONTEXT.md ===

    def write_context_md(
        self,
        title: str,
        template: str,
        meta: ProjectMeta,
        files: list[str] | None = None,
        context_summary: str | None = None,
    ) -> Path:
        """生成 CONTEXT.md（替代 CLAUDE.md）。

        包含：项目标题、模板、参数、工作区文件清单、上下文摘要。
        """
        files = files if files is not None else self.scan()
        context_summary = context_summary if context_summary is not None else self.build_context_summary(files)

        md = f"# {title}\n\n"
        md += f"## 模板\n{template}\n\n"
        md += "## 参数\n"
        md += f"- project_type: {meta.project_type}\n"
        md += f"- auto_proceed: {meta.auto_proceed}\n"
        if meta.extra:
            for k, v in meta.extra.items():
                md += f"- {k}: {v}\n"
        md += "\n## 工作区文件\n"
        if files:
            for f in files:
                size = self.file_size(f)
                md += f"- {f} ({size} bytes)\n"
        else:
            md += "(空)\n"
        md += "\n## 上下文摘要\n"
        md += context_summary if context_summary else "(无)\n"

        return self.write_file("CONTEXT.md", md)

    def inject_once(self, marker: str, content: str) -> bool:
        """幂等地把 content 追加到 CONTEXT.md。

        如果 marker 已存在则不重复注入，返回 False。
        对应 Modex-MH-Agent 的 _inject_once。
        """
        ctx_path = self.root / "CONTEXT.md"
        if not ctx_path.exists():
            return False
        text = ctx_path.read_text(encoding="utf-8")
        if marker in text:
            return False
        block = f"\n\n## {marker}\n{content}\n"
        ctx_path.write_text(text + block, encoding="utf-8")
        return True

    # === project.json ===

    def write_project_meta(self, meta: ProjectMeta) -> Path:
        """写 project.json（结构化配置）。"""
        return self.write_file("project.json", meta.to_json())

    def read_project_meta(self) -> ProjectMeta | None:
        """读 project.json，不存在返回 None。"""
        p = self.root / "project.json"
        if not p.exists():
            return None
        try:
            return ProjectMeta.from_json(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("read project.json failed: %s", e)
            return None

    def detect_project_type(self) -> str:
        """检测项目类型。

        优先读 project.json，不存在则尝试从 CONTEXT.md 解析，都没有则返回默认 fullstack。
        对应 Modex-MH-Agent 的 _detect_grad_project_type。
        """
        meta = self.read_project_meta()
        if meta and meta.project_type:
            return meta.project_type

        ctx = self.root / "CONTEXT.md"
        if ctx.exists():
            text = ctx.read_text(encoding="utf-8")
            m = re.search(r"project_type:\s*(\w+)", text)
            if m:
                return m.group(1)

        return "fullstack"
