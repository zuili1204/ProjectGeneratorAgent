"""SKILL 回归脚本：按 golden 用例跑单步并断言产物。

由于 LLM 输出非确定，本脚本提供两种模式：
- ``--dry-run``：不调 LLM，仅校验 golden 用例 fixture 自身合法（case.yaml 可解析、
  引用的 skill / template 存在）。用于 CI 快速回归，捕获「改了 SKILL.md / 模板
  导致用例引用断裂」这类问题。
- 默认（实跑）：调用 LLM 真实执行单步，对产物做断言（文件存在 / 必含章节 /
  project_type 字段 / 无占位符等）。需要配置 LLM_API_KEY。

用法：
    python -m tests.regress_skill --list
    python -m tests.regress_skill dev-requirement --case todo_app --dry-run
    python -m tests.regress_skill dev-requirement --case todo_app
    python -m tests.regress_skill dev-requirement --all --dry-run

断言规则见 tests/golden/<case>/case.yaml 的 steps[].assertions。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.skill_loader import list_skills, load_skill_meta  # noqa: E402
from agent.workflow_engine import list_templates, load_template, _eval_when  # noqa: E402

GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"


# === 用例加载 ===

@dataclass
class StepCase:
    skill: str
    expected_outputs: list[str] = field(default_factory=list)
    min_size: int = 0
    required_sections: dict[str, list[str]] = field(default_factory=dict)
    required_files: list[str] = field(default_factory=list)
    assertions: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoldenCase:
    name: str
    description: str
    requirement: str
    project_type: str
    template: str
    steps: list[StepCase]

    @property
    def dir(self) -> Path:
        return GOLDEN_DIR / self.name


def load_case(name: str) -> GoldenCase:
    case_path = GOLDEN_DIR / name / "case.yaml"
    if not case_path.exists():
        raise FileNotFoundError(f"用例不存在: {name} (期望 {case_path})")
    data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    steps = [
        StepCase(
            skill=s["skill"],
            expected_outputs=s.get("expected_outputs", []),
            min_size=s.get("min_size", 0),
            required_sections=s.get("required_sections", {}),
            required_files=s.get("required_files", []),
            assertions=s.get("assertions", {}),
        )
        for s in data.get("steps", [])
    ]
    return GoldenCase(
        name=data["name"],
        description=data.get("description", ""),
        requirement=data["requirement"],
        project_type=data["project_type"],
        template=data["template"],
        steps=steps,
    )


def list_cases() -> list[str]:
    if not GOLDEN_DIR.exists():
        return []
    return sorted(
        d.name for d in GOLDEN_DIR.iterdir()
        if d.is_dir() and (d / "case.yaml").exists()
    )


# === 断言 ===

@dataclass
class AssertResult:
    ok: bool
    message: str


def assert_file_exists(ws_root: Path, rel: str) -> AssertResult:
    p = ws_root / rel
    if not p.exists():
        return AssertResult(False, f"文件缺失: {rel}")
    return AssertResult(True, f"文件存在: {rel}")


def assert_min_size(ws_root: Path, rel: str, min_size: int) -> AssertResult:
    p = ws_root / rel
    if not p.exists():
        return AssertResult(False, f"文件缺失: {rel}")
    size = p.stat().st_size
    if size < min_size:
        return AssertResult(False, f"{rel} 过小: {size}B < {min_size}B")
    return AssertResult(True, f"{rel} 大小合格: {size}B")


def assert_sections(ws_root: Path, rel: str, sections: list[str]) -> AssertResult:
    p = ws_root / rel
    if not p.exists():
        return AssertResult(False, f"文件缺失: {rel}")
    content = p.read_text(encoding="utf-8")
    # markdown 章节匹配：## 标题 或 # 标题，含字面即可
    headings = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
    headings_lower = [h.strip().lower() for h in headings]
    missing = [s for s in sections if s.lower() not in headings_lower]
    if missing:
        return AssertResult(False, f"{rel} 缺失章节: {missing}")
    return AssertResult(True, f"{rel} 章节齐全: {sections}")


def assert_project_type_field(ws_root: Path, expected: str) -> AssertResult:
    req = ws_root / "REQUIREMENT.md"
    if not req.exists():
        return AssertResult(False, "REQUIREMENT.md 缺失")
    content = req.read_text(encoding="utf-8")
    # 宽松匹配：含 project_type: fullstack 或 ## 项目类型 ... fullstack
    if re.search(rf"project_type[:\s]*['\"]?{re.escape(expected)}['\"]?", content, re.IGNORECASE):
        return AssertResult(True, f"project_type 字段 = {expected}")
    # 兜底：项目类型章节含期望值
    m = re.search(r"##\s*项目类型.*?(?=^##|\Z)", content, re.MULTILINE | re.DOTALL)
    if m and expected in m.group(0):
        return AssertResult(True, f"项目类型章节含 {expected}")
    return AssertResult(False, f"project_type 字段未找到 {expected}")


def assert_no_placeholder_in_tree(ws_root: Path) -> AssertResult:
    design = ws_root / "DESIGN.md"
    if not design.exists():
        return AssertResult(False, "DESIGN.md 缺失")
    content = design.read_text(encoding="utf-8")
    # tree 图代码块里的 ... 占位
    tree_blocks = re.findall(r"```[^\n]*\n(.*?)(?:```|\Z)", content, re.DOTALL)
    for block in tree_blocks:
        if "..." in block or "省略" in block:
            return AssertResult(False, "目录结构 tree 图含 ... 占位符")
    return AssertResult(True, "目录结构无 ... 占位")


def assert_run_md_executable(ws_root: Path) -> AssertResult:
    run_md = ws_root / "code" / "RUN.md"
    if not run_md.exists():
        return AssertResult(False, "code/RUN.md 缺失")
    content = run_md.read_text(encoding="utf-8")
    # 启动命令应含可执行命令，而非「直接打开 index.html」
    if "直接打开 index.html" in content:
        return AssertResult(False, "RUN.md 写了不可执行的「直接打开 index.html」")
    if not re.search(r"(python|npm|node|pip)\s", content):
        return AssertResult(False, "RUN.md 缺少可执行启动命令（python/npm/node/pip）")
    return AssertResult(True, "RUN.md 含可执行启动命令")


def assert_no_fetch_local_json(ws_root: Path) -> AssertResult:
    """扫描 code/ 下 JS 文件，禁止 fetch 加载本地 .json。"""
    code_dir = ws_root / "code"
    if not code_dir.exists():
        return AssertResult(False, "code/ 目录缺失")
    for p in code_dir.rglob("*"):
        if p.suffix not in (".js", ".ts", ".jsx", ".tsx"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if re.search(r"fetch\s*\(\s*['\"][^'\"]*\.json['\"]", content):
            return AssertResult(False, f"{p.relative_to(ws_root)} 含 fetch 加载本地 JSON")
    return AssertResult(True, "未发现 fetch 加载本地 JSON")


# === dry-run 校验 ===

def dry_run_check(case: GoldenCase) -> list[AssertResult]:
    """不调 LLM，仅校验用例 fixture 引用合法。"""
    results: list[AssertResult] = []

    # template 存在
    if case.template not in list_templates():
        results.append(AssertResult(False, f"模板不存在: {case.template}"))
    else:
        results.append(AssertResult(True, f"模板存在: {case.template}"))

    # 每个 skill 存在
    available_skills = set(list_skills())
    for step in case.steps:
        if step.skill not in available_skills:
            results.append(AssertResult(False, f"skill 不存在: {step.skill}"))
        else:
            results.append(AssertResult(True, f"skill 存在: {step.skill}"))

    # skill 元数据可解析
    for step in case.steps:
        try:
            meta = load_skill_meta(step.skill)
            results.append(AssertResult(True, f"{step.skill} 元数据可解析 (name={meta.name}, ver={meta.version})"))
        except Exception as e:
            results.append(AssertResult(False, f"{step.skill} 元数据解析失败: {e}"))

    return results


# === 实跑（调 LLM） ===

async def run_skill_against_case(skill: str, case: GoldenCase) -> Path:
    """真实调用 LLM 跑单步，返回工作区根路径。"""
    from agent.config import LLMConfig, WorkflowConfig
    from agent.workflow_engine import WorkflowEngine

    llm_config = LLMConfig.from_env()
    llm_config.validate()
    wf_config = WorkflowConfig.from_dict({"project_type": case.project_type})
    engine = WorkflowEngine(llm_config=llm_config, workflow_config=wf_config)

    # 创建工作流
    wf_id = engine.create_workflow(
        template_key=case.template,
        title=case.requirement,
        params={"project_type": case.project_type, "auto_proceed": True},
    )
    ws_root = PROJECT_ROOT / "workspaces" / wf_id

    # 跑指定 skill（用 rerun_step 机制：先创建后 rerun 目标步）
    # 这里简化：直接调 run_workflow 跑完整流，但只断言目标步产物。
    # 真正的单步隔离测试需更复杂脚手架，这里用全流程 + 选择性断言近似。
    state = await engine.run_workflow(wf_id)
    await engine.close()
    return ws_root


def evaluate_assertions(ws_root: Path, step: StepCase) -> list[AssertResult]:
    """对工作区产物执行断言。"""
    results: list[AssertResult] = []

    # 主产物存在
    for out in step.expected_outputs:
        results.append(assert_file_exists(ws_root, out))
        if step.min_size:
            results.append(assert_min_size(ws_root, out, step.min_size))

    # 必需文件
    for f in step.required_files:
        results.append(assert_file_exists(ws_root, f))

    # 必需章节
    for rel, sections in step.required_sections.items():
        results.append(assert_sections(ws_root, rel, sections))

    # assertions 字典
    for key, val in step.assertions.items():
        if key == "project_type_field":
            results.append(assert_project_type_field(ws_root, val))
        elif key == "no_placeholder_in_tree":
            if val:
                results.append(assert_no_placeholder_in_tree(ws_root))
        elif key == "run_md_has_executable_cmd":
            if val:
                results.append(assert_run_md_executable(ws_root))
        elif key == "no_fetch_local_json":
            if val:
                results.append(assert_no_fetch_local_json(ws_root))
        else:
            results.append(AssertResult(True, f"（跳过未知断言 {key}）"))

    return results


# === CLI ===

def _print_result(r: AssertResult, indent: str = "  ") -> None:
    mark = "✓" if r.ok else "✗"
    color = "\033[32m" if r.ok else "\033[31m"
    reset = "\033[0m"
    print(f"{indent}{color}{mark}{reset} {r.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="regress_skill", description="SKILL 回归测试")
    parser.add_argument("skill", nargs="?", help="要回归的 skill 名（如 dev-requirement）")
    parser.add_argument("--case", help="指定 golden 用例名")
    parser.add_argument("--all", action="store_true", help="对所有用例回归")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调 LLM，仅校验 fixture 引用合法（CI 快速回归）")
    parser.add_argument("--list", action="store_true", help="列出所有 golden 用例")
    args = parser.parse_args(argv)

    if args.list:
        cases = list_cases()
        print(f"可用 golden 用例 ({len(cases)}):")
        for c in cases:
            case = load_case(c)
            print(f"  {c}: {case.description}")
            print(f"    requirement: {case.requirement}")
            print(f"    project_type: {case.project_type}, template: {case.template}")
        return 0

    if not args.skill:
        parser.error("需要指定 skill 或 --list")

    # 选定用例
    if args.all:
        case_names = list_cases()
    elif args.case:
        case_names = [args.case]
    else:
        parser.error("需要 --case <name> 或 --all")

    all_ok = True
    for cname in case_names:
        try:
            case = load_case(cname)
        except Exception as e:
            print(f"\n[{cname}] 加载失败: {e}")
            all_ok = False
            continue

        print(f"\n[{cname}] skill={args.skill} dry_run={args.dry_run}")

        # 找到对应的 step case
        step_case = next((s for s in case.steps if s.skill == args.skill), None)
        if step_case is None:
            print(f"  用例 {cname} 未定义 skill {args.skill} 的回归步骤，跳过")
            continue

        if args.dry_run:
            results = dry_run_check(case)
        else:
            ws_root = asyncio.run(run_skill_against_case(args.skill, case))
            results = evaluate_assertions(ws_root, step_case)

        step_ok = True
        for r in results:
            _print_result(r)
            if not r.ok:
                step_ok = False
        if not step_ok:
            all_ok = False
            print(f"  → {cname} 回归失败")
        else:
            print(f"  → {cname} 回归通过")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
