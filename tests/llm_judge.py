"""LLM-as-judge 语义评估脚本：对工作流产出做多维度打分，记录趋势。

与 regress_skill 的区别：
- regress_skill 断言「结构性约束」（文件存在/章节齐全），是 pass/fail 的。
- llm_judge 评估「语义质量」（需求覆盖度/设计合理性/代码质量/可运行性/文档完整度），
  是 0-10 分的连续值，记录历史趋势而非 pass/fail。

由于 LLM 输出非确定，单次分数有噪声；重点看**多次运行的均值与趋势**，
若某维度分数持续下降，提示 SKILL.md 改动可能引入回归。

用法：
    # 评估某个已运行完的工作流
    python -m tests.llm_judge <workflow_id>

    # 评估并附带原始需求作为对照基准
    python -m tests.llm_judge <workflow_id> --requirement "做一个待办事项 Web 应用"

    # 查看历史趋势
    python -m tests.llm_judge --trend

    # 查看某个 case 的历史趋势
    python -m tests.llm_judge --trend --case todo_app

历史记录写入 tests/judge_history.jsonl，每行一条评估记录。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

HISTORY_FILE = PROJECT_ROOT / "tests" / "judge_history.jsonl"

# 评估维度（0-10 分）
DIMENSIONS = [
    ("requirement_coverage", "需求覆盖度", "P0/P1 功能是否都有对应实现"),
    ("design_consistency", "设计一致性", "代码是否与 DESIGN.md 的目录/接口/数据模型一致"),
    ("code_quality", "代码质量", "代码结构、命名、错误处理、可维护性"),
    ("runnability", "可运行性", "RUN.md 启动命令是否可执行、依赖是否齐全、入口是否规范"),
    ("documentation", "文档完整度", "REQUIREMENT/DESIGN/RUN 文档章节是否齐全且自包含"),
]


# === 工作区产物收集 ===

def _read_workspace_files(ws_root: Path) -> dict[str, str]:
    """读取工作区关键产物，返回 {rel_path: content}。"""
    files: dict[str, str] = {}
    for rel in ("REQUIREMENT.md", "DESIGN.md", "RUN.md", "REVIEW.md", "SELF_CHECK.md"):
        p = ws_root / rel
        if p.exists():
            files[rel] = p.read_text(encoding="utf-8")[:8000]  # 截断防爆 token
    # code/ 目录扫描（限制总大小）
    code_dir = ws_root / "code"
    if code_dir.exists():
        for p in sorted(code_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in (".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json"):
                continue
            rel = str(p.relative_to(ws_root))
            try:
                files[rel] = p.read_text(encoding="utf-8")[:4000]
            except Exception:
                pass
            if sum(len(v) for v in files.values()) > 60000:
                break
    return files


# === Judge prompt 构造 ===

def _build_judge_prompt(files: dict[str, str], requirement: str = "") -> str:
    """构造 judge 评估 prompt，强制 JSON 输出。"""
    files_block = ""
    for rel, content in files.items():
        files_block += f"\n\n### 文件: {rel}\n```\n{content}\n```"

    dims_desc = "\n".join(
        f"- {key}（{name}）: {desc}，0-10 分"
        for key, name, desc in DIMENSIONS
    )

    return f"""你是一个严格的项目评审专家。请评估以下工作流产出的质量。

## 原始需求
{requirement or "（见工作区 REQUIREMENT.md）"}

## 工作区产物
{files_block}

## 评估维度
{dims_desc}

## 评分规则
- 每个维度打 0-10 分（整数），10 分为完美，0 分为完全不合格
- 需求覆盖度：P0 功能漏一个扣 3 分，P1 漏一个扣 1 分
- 设计一致性：与 DESIGN.md 偏离每处扣 1 分
- 代码质量：伪代码/TODO/硬编码密钥每处扣 2 分
- 可运行性：RUN.md 不可执行扣 5 分，依赖遗漏扣 2 分，入口命名不规范扣 1 分
- 文档完整度：必含章节缺失每个扣 2 分

## 输出格式（严格 JSON，不要任何额外文字）
```json
{{
  "requirement_coverage": <0-10>,
  "design_consistency": <0-10>,
  "code_quality": <0-10>,
  "runnability": <0-10>,
  "documentation": <0-10>,
  "overall": <0-10>,
  "rationale": "<总体评价，100 字内>",
  "key_issues": ["<关键问题1>", "<关键问题2>"]
}}
```

只输出 JSON，不要解释。"""


# === LLM 调用 ===

async def _judge_with_llm(prompt: str) -> dict:
    """调用 LLM 评估，返回解析后的评分 dict。"""
    from agent.config import LLMConfig
    from agent.llm_client import LLMClient

    config = LLMConfig.from_env()
    config.validate()
    client = LLMClient(config)

    try:
        resp = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,  # 评估用 0 温度提高可复现性
            max_tokens=2000,
        )
    finally:
        await client.close()

    text = resp.text.strip()
    # 提取 JSON（容错：LLM 可能包裹在 ```json 里）
    import re
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {"error": f"LLM 未返回有效 JSON: {text[:200]}"}
    try:
        result = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON 解析失败: {e}; 原文: {text[:200]}"}

    # 补全默认值
    for key, _, _ in DIMENSIONS:
        if key not in result:
            result[key] = -1  # -1 表示未评分
    result.setdefault("overall", -1)
    result.setdefault("rationale", "")
    result.setdefault("key_issues", [])
    return result


# === 历史记录 ===

def _append_history(record: dict) -> None:
    """追加一条评估记录到 judge_history.jsonl。"""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_history(case: str | None = None) -> list[dict]:
    """加载历史评估记录。"""
    if not HISTORY_FILE.exists():
        return []
    records = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if case and rec.get("case") != case:
                continue
            records.append(rec)
        except json.JSONDecodeError:
            continue
    return records


def _show_trend(case: str | None = None) -> int:
    """显示历史趋势。"""
    records = _load_history(case)
    if not records:
        print("暂无历史评估记录" + (f"（case={case}）" if case else ""))
        return 0

    print(f"历史评估记录（{len(records)} 条）" + (f" case={case}" if case else ""))
    print(f"{'时间':<20} {'case':<14} {'工作流':<10} ", end="")
    for key, name, _ in DIMENSIONS:
        print(f"{name:<8}", end="")
    print(f"{'总分':<8} {'成本($)':<10}")
    print("-" * 110)
    for rec in records:
        ts = rec.get("timestamp", "")[:19]
        cname = rec.get("case", "-")[:14]
        wf = rec.get("workflow_id", "-")[:10]
        print(f"{ts:<20} {cname:<14} {wf:<10} ", end="")
        for key, _, _ in DIMENSIONS:
            v = rec.get(key, -1)
            print(f"{str(v):<8}", end="")
        print(f"{rec.get('overall', -1):<8} {rec.get('cost_usd', 0):.4f}")

    # 均值
    print("-" * 110)
    print("均值: ".ljust(46), end="")
    for key, _, _ in DIMENSIONS:
        vals = [r.get(key, -1) for r in records if r.get(key, -1) >= 0]
        avg = sum(vals) / len(vals) if vals else 0
        print(f"{avg:<8.1f}", end="")
    overall_vals = [r.get("overall", -1) for r in records if r.get("overall", -1) >= 0]
    overall_avg = sum(overall_vals) / len(overall_vals) if overall_vals else 0
    print(f"{overall_avg:<8.1f}")
    return 0


# === 主入口 ===

async def _judge_workflow(workflow_id: str, requirement: str = "", case: str = "") -> int:
    """评估单个工作流。"""
    from agent.workflow_engine import WorkflowEngine

    ws_root = PROJECT_ROOT / "workspaces" / workflow_id
    if not ws_root.exists():
        print(f"工作区不存在: {ws_root}")
        return 1

    engine = WorkflowEngine()
    state = engine.get_state(workflow_id)
    if not state:
        print(f"工作流不存在: {workflow_id}")
        return 1

    files = _read_workspace_files(ws_root)
    if not files:
        print("工作区无产物可评估")
        return 1

    req = requirement or state.title
    print(f"评估工作流 {workflow_id}（{state.title}）...")
    print(f"  产物文件数: {len(files)}")

    prompt = _build_judge_prompt(files, req)
    result = await _judge_with_llm(prompt)

    if "error" in result:
        print(f"评估失败: {result['error']}")
        return 2

    # 展示结果
    print(f"\n{'维度':<20} {'分数':<8}")
    print("-" * 30)
    for key, name, _ in DIMENSIONS:
        v = result.get(key, -1)
        bar = "█" * int(v) if v >= 0 else "?"
        print(f"{name:<20} {v:<8} {bar}")
    print("-" * 30)
    print(f"{'总分':<20} {result.get('overall', -1):<8}")
    if result.get("rationale"):
        print(f"\n评价: {result['rationale']}")
    if result.get("key_issues"):
        print("\n关键问题:")
        for issue in result["key_issues"]:
            print(f"  - {issue}")

    # 记录历史
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "workflow_id": workflow_id,
        "case": case or "",
        "title": state.title,
        "template": state.template,
        "cost_usd": state.computed_cost_usd,
        "overall": result.get("overall", -1),
        "rationale": result.get("rationale", ""),
        "key_issues": result.get("key_issues", []),
    }
    for key, _, _ in DIMENSIONS:
        record[key] = result.get(key, -1)
    _append_history(record)
    print(f"\n已记录到 {HISTORY_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_judge", description="LLM-as-judge 语义评估")
    parser.add_argument("workflow_id", nargs="?", help="要评估的工作流 ID")
    parser.add_argument("--requirement", default="", help="原始需求（对照基准）")
    parser.add_argument("--case", default="", help="golden 用例名（记入历史便于趋势分析）")
    parser.add_argument("--trend", action="store_true", help="查看历史趋势")
    args = parser.parse_args(argv)

    if args.trend:
        return _show_trend(args.case or None)

    if not args.workflow_id:
        parser.error("需要 workflow_id 或 --trend")

    return asyncio.run(_judge_workflow(args.workflow_id, args.requirement, args.case))


if __name__ == "__main__":
    sys.exit(main())
