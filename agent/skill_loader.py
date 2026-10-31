"""Skill 加载器：读取明文 SKILL.md，替换占位符，拼接上下文。

对应 Modex-MH-Agent 的 claude_runner._load_skill_prompt，但用明文 markdown
（无加密），且把工作区上下文以结构化方式注入 prompt。

改进（相对初版）：
- 解析 SKILL.md 顶部 YAML front matter 元数据（name/version/inputs/outputs/depends_on/est_tokens）
- 文件清单增强：附带大小与分类（entry/config/doc/source/asset）
- 提供前置产物依赖校验接口
- 目录级版本化：支持 skills/<name>/<version>/SKILL.md 与 skills/<name>/SKILL.md 两种布局
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import SKILLS_DIR

log = logging.getLogger(__name__)


# slash command 引用清理（如 /dev-code → dev-code）
_SLASH_CMD_RE = re.compile(r"^/\S+\s*", re.MULTILINE)

# YAML front matter: ---\n...\n---
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass
class SkillMeta:
    """SKILL.md 元数据（来自 YAML front matter）。

    `description` 采用 superpowers 式「Use when ...」触发条件描述，
    便于未来按语义检索 skill（而非仅靠目录名匹配）。
    """
    name: str = ""
    version: str = ""
    description: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    # 需要注入的 skills/_shared/*.md（按需声明，未声明则不注入）
    shared: list[str] = field(default_factory=list)
    est_tokens: int = 0
    est_iters: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def has_meta(self) -> bool:
        return bool(self.raw)


def _parse_front_matter(text: str) -> tuple[SkillMeta, str]:
    """解析 SKILL.md 的 YAML front matter，返回 (元数据, 正文)。

    无 front matter 时返回 (空元数据, 原文)。
    用纯文本解析避免引入 pyyaml 依赖（front matter 字段简单）。
    """
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return SkillMeta(), text

    fm_text = m.group(1)
    body = m.group(2)

    # 简单 YAML 解析：仅支持 key: value 与 key: [a, b] 形式
    raw: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        raw[key] = val

    def _parse_list(v: str) -> list[str]:
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = v[1:-1]
        items = [x.strip().strip("\"'") for x in v.split(",") if x.strip()]
        return items

    meta = SkillMeta(
        name=raw.get("name", ""),
        version=raw.get("version", ""),
        description=raw.get("description", ""),
        inputs=_parse_list(raw.get("inputs", "")),
        outputs=_parse_list(raw.get("outputs", "")),
        depends_on=_parse_list(raw.get("depends_on", "")),
        shared=_parse_list(raw.get("shared", "")),
        est_tokens=int(raw["est_tokens"]) if raw.get("est_tokens", "").isdigit() else 0,
        est_iters=int(raw["est_iters"]) if raw.get("est_iters", "").isdigit() else 0,
        raw=raw,
    )
    return meta, body


def _parse_semver(version: str) -> tuple[int, int, int]:
    """把 '1.2.3' 解析为 (1, 2, 3) 用于排序。非 semver 返回 (0,0,0)。"""
    m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", version or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def list_skill_versions(skill_name: str) -> list[str]:
    """列出某个 skill 的所有可用版本目录。

    返回按 semver 降序排列的版本号列表（最新在前）。
    仅扫描 skills/<name>/<version>/SKILL.md 形式的版本目录；
    平铺布局 skills/<name>/SKILL.md 不计入（视为隐式默认版本）。
    """
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        return []
    versions: list[tuple[tuple[int, int, int], str]] = []
    for sub in skill_dir.iterdir():
        if not sub.is_dir():
            continue
        if not (sub / "SKILL.md").exists():
            continue
        ver = sub.name
        versions.append((_parse_semver(ver), ver))
    versions.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in versions]


def resolve_skill_path(skill_name: str, version: str | None = None) -> Path:
    """解析 SKILL.md 的实际路径，支持目录级版本化。

    解析顺序：
    1. version 显式指定：
       - "latest" 或 "" → 选最新版本目录；若无版本目录则回退平铺布局
       - "1.0.0" 等 → 精确匹配 skills/<name>/<version>/SKILL.md
    2. version 为 None（默认）：优先平铺布局 skills/<name>/SKILL.md；
       若不存在则回退到最新版本目录。

    两种布局：
      平铺:  skills/<name>/SKILL.md          （隐式默认版本）
      版本:  skills/<name>/<version>/SKILL.md  （显式版本，可多版本共存）
    """
    flat = SKILLS_DIR / skill_name / "SKILL.md"

    if version is None:
        # 默认：平铺优先，否则最新版本目录
        if flat.exists():
            return flat
        versions = list_skill_versions(skill_name)
        if versions:
            return SKILLS_DIR / skill_name / versions[0] / "SKILL.md"
        raise FileNotFoundError(
            f"Skill not found: {skill_name} (期望 {flat} 或 {SKILLS_DIR / skill_name} /<version>/SKILL.md)"
        )

    # 显式版本
    version = version.strip()
    if version in ("", "latest"):
        versions = list_skill_versions(skill_name)
        if versions:
            return SKILLS_DIR / skill_name / versions[0] / "SKILL.md"
        # 无版本目录，回退平铺
        if flat.exists():
            return flat
        raise FileNotFoundError(f"Skill {skill_name} 无版本目录，且平铺 SKILL.md 不存在")

    # 精确版本
    versioned = SKILLS_DIR / skill_name / version / "SKILL.md"
    if versioned.exists():
        return versioned
    raise FileNotFoundError(
        f"Skill version not found: {skill_name}@{version} (期望 {versioned})"
    )


def _load_skill_references(skill_path: Path, shared: list[str] | None = None) -> str:
    """加载 skill 目录下的 references/*.md 与按需声明的 _shared/*.md。

    `_shared` 不再全量注入：SKILL.md front matter 用 `shared: [a, b]` 显式声明
    需要哪些共享知识（如 dev-requirement 不需要前端设计知识），避免每个 skill
    都背上 ~34KB 无关上下文。

    Args:
        shared: 共享知识文件名（可带或不带 .md），为空表示不加载。
    """
    parts: list[str] = []

    # 1. skill 目录下的 references/*.md
    skill_dir = skill_path.parent
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        for ref_file in sorted(ref_dir.glob("*.md")):
            try:
                content = ref_file.read_text(encoding="utf-8")
                parts.append(f"\n\n---\n# Reference: {ref_file.name}\n{content}")
            except Exception as e:
                log.warning("Failed to load reference %s: %s", ref_file, e)

    # 2. 按声明加载全局 _shared/*.md
    shared_dir = SKILLS_DIR / "_shared"
    if shared and shared_dir.is_dir():
        for name in shared:
            filename = name if name.endswith(".md") else f"{name}.md"
            shared_file = shared_dir / filename
            if not shared_file.exists():
                log.warning("declared shared knowledge not found: %s", shared_file)
                continue
            try:
                content = shared_file.read_text(encoding="utf-8")
                parts.append(f"\n\n---\n# Shared Knowledge: {filename}\n{content}")
            except Exception as e:
                log.warning("Failed to load shared %s: %s", shared_file, e)

    return "".join(parts)


def load_skill_md(skill_name: str, version: str | None = None) -> str:
    """读取 SKILL.md 内容（明文，无加密），保留 front matter。

    Args:
        version: 指定版本号；None 表示默认（平铺优先），"latest" 表示最新版本目录。
    """
    skill_path = resolve_skill_path(skill_name, version)
    if not skill_path.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_name} (expected at {skill_path})"
        )
    return skill_path.read_text(encoding="utf-8")


def load_skill_meta(skill_name: str, version: str | None = None) -> SkillMeta:
    """只加载 SKILL.md 的元数据（front matter）。"""
    text = load_skill_md(skill_name, version)
    meta, _ = _parse_front_matter(text)
    if not meta.name:
        meta.name = skill_name
    return meta


def render_skill_prompt(
    skill_name: str,
    arguments: str,
    extra_context: str | None = None,
    workspace_files: list[str] | None = None,
    workspace=None,
    version: str | None = None,
) -> str:
    """加载 SKILL.md 并渲染最终 prompt。

    步骤：
    1. 读取 SKILL.md 明文（含 front matter）
    2. 剥离 front matter（不送入 LLM）
    3. 替换 $ARGUMENTS 占位符为用户输入
    4. 清理 slash command 引用
    5. 拼接工作区文件清单（增强：大小+分类）
    6. 拼接额外上下文

    Args:
        workspace: 可选，传入 Workspace 以读取文件大小与分类，使文件清单更丰富。
                   若为 None 则退化为纯文件名清单。
        version: 可选，指定 skill 版本；None 表示默认，"latest" 取最新版本目录。
    """
    md = load_skill_md(skill_name, version)
    # 剥离 front matter（不送入 LLM，避免浪费 token），同时拿到 shared 声明
    meta, md = _parse_front_matter(md)

    # 替换 $ARGUMENTS
    md = md.replace("$ARGUMENTS", arguments)

    # 清理 slash command 引用
    md = _SLASH_CMD_RE.sub("", md)

    # 拼接 skill references 与按需声明的 _shared 知识库
    skill_path = resolve_skill_path(skill_name, version)
    md += _load_skill_references(skill_path, meta.shared)

    # 拼接工作区文件清单（增强版：带大小与分类）
    if workspace_files:
        files_block = "\n\n## 当前工作区文件\n"
        if workspace is not None:
            for f in workspace_files:
                try:
                    size = workspace.file_size(f)
                    cls = workspace.classify_file(f)
                    files_block += f"- {f} ({size}B, {cls})\n"
                except Exception:
                    files_block += f"- {f}\n"
        else:
            for f in workspace_files:
                files_block += f"- {f}\n"
        md += files_block

    # 拼接额外上下文
    if extra_context:
        md += f"\n\n## 补充上下文\n{extra_context}"

    return md


def list_skills() -> list[str]:
    """列出所有可用的 skill 名称。"""
    if not SKILLS_DIR.exists():
        return []
    return sorted(
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def check_dependencies(skill_name: str, workspace, version: str | None = None) -> tuple[bool, list[str]]:
    """检查 skill 的前置产物依赖是否满足。

    读取 SKILL.md front matter 的 depends_on 字段（产物文件路径列表），
    校验这些文件是否都存在于工作区。

    Returns:
        (是否满足, 缺失文件列表)
    """
    meta = load_skill_meta(skill_name, version)
    missing: list[str] = []
    for dep in meta.depends_on:
        if not workspace.file_exists(dep):
            missing.append(dep)
    return (not missing, missing)
