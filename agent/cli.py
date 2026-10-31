"""命令行入口：pga 命令。

提供「一句话生成项目」工作流的完整 CLI 操作：
    pga run "需求"                    # 一键启动工作流
    pga list                          # 列出所有工作流
    pga show <workflow_id>            # 查看工作流详情
    pga resume <workflow_id>          # 恢复暂停的工作流
    pga approve <workflow_id> [反馈]  # 检查点确认
    pga reject <workflow_id> <反馈>   # 检查点打回
    pga rerun <workflow_id> <skill>   # 重跑某步骤
    pga delete <workflow_id>          # 删除工作流
    pga templates                     # 列出模板
    pga skills                        # 列出 skills
    pga config set <key> <value>      # 设置配置
    pga config get [key]              # 查看配置
    pga config path                   # 显示配置文件路径
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich.syntax import Syntax
    _HAS_RICH = True
except ImportError:  # 降级：rich 未装时用 print
    _HAS_RICH = False
    Console = None  # type: ignore

from .config import (
    LLMConfig, WorkflowConfig,
    set_user_config, _load_user_config, _user_config_path,
    save_user_config,
)
from .workflow_engine import (
    WorkflowEngine, WorkflowState,
    list_templates, load_template,
    submit_checkpoint,
)
from .skill_loader import list_skills, load_skill_md

# === 日志 ===
log = logging.getLogger("pga")

if _HAS_RICH:
    console = Console()
else:
    console = None  # type: ignore


def _print(msg: str = "", style: str | None = None) -> None:
    """统一输出（rich 或 print）。"""
    if _HAS_RICH:
        console.print(msg, style=style)
    else:
        print(msg)


def _err(msg: str) -> None:
    if _HAS_RICH:
        console.print(f"[bold red]错误:[/bold red] {msg}")
    else:
        print(f"错误: {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    if _HAS_RICH:
        console.print(f"[bold green]✓[/bold green] {msg}")
    else:
        print(f"✓ {msg}")


# === 日志广播（实时显示到 console） ===

async def _console_broadcast(event: dict) -> None:
    """把工作流事件实时打印到 console。"""
    etype = event.get("event", "")
    if etype == "log":
        level = event.get("level", "info")
        step = event.get("step", "")
        msg = event.get("message", "")
        ts = event.get("timestamp", "")[11:19]  # HH:MM:SS

        # 颜色映射
        style_map = {
            "info": "cyan",
            "warn": "yellow",
            "error": "bold red",
            "progress": "white",
            "debug": "dim",
        }
        style = style_map.get(level, "white")

        prefix = f"[{ts}]"
        if step:
            prefix += f" [{step}]"
        if _HAS_RICH:
            console.print(f"{prefix} {msg}", style=style)
        else:
            print(f"{prefix} {msg}")
    elif etype == "checkpoint":
        # 检查点事件单独处理（在 run 命令里交互）
        pass


# === run 命令 ===

async def _cmd_run(args: argparse.Namespace) -> int:
    """执行 `pga run "需求"`。"""
    title = args.title.strip()
    if not title:
        _err("需求不能为空")
        return 1

    template_key = args.template
    if template_key not in list_templates():
        _err(f"模板不存在: {template_key}（可用: {', '.join(list_templates())}）")
        return 1

    # 检查 LLM 配置
    try:
        llm_config = LLMConfig.from_env()
        llm_config.validate()
    except RuntimeError as e:
        _err(str(e))
        _print("提示: 运行 `pga config set llm_api_key <your-key>` 配置 API Key", style="yellow")
        return 1

    # 构建 workflow_config
    wf_config = WorkflowConfig.from_dict({
        "agent_max_iter": args.max_iter,
        "enable_checkpoints": not args.no_checkpoint,
        "auto_proceed": args.auto,
        "project_type": args.project_type,
        "verification_gate": args.verification_gate,
    })

    # 创建引擎
    engine = WorkflowEngine(llm_config=llm_config, workflow_config=wf_config)
    # 订阅日志广播
    from .workflow_engine import set_broadcast
    set_broadcast(_console_broadcast)

    # 显示启动信息
    if _HAS_RICH:
        panel = Panel(
            f"[bold]需求:[/bold] {title}\n"
            f"[bold]模板:[/bold] {template_key}\n"
            f"[bold]项目类型:[/bold] {args.project_type}\n"
            f"[bold]检查点:[/bold] {'关闭' if args.no_checkpoint else '开启'}\n"
            f"[bold]自动继续:[/bold] {'是' if args.auto else '否'}",
            title="🚀 启动工作流",
            border_style="cyan",
        )
        console.print(panel)

    # 创建工作流
    workflow_id = engine.create_workflow(
        template_key=template_key,
        title=title,
        params={
            "project_type": args.project_type,
            "auto_proceed": args.auto,
            "enable_review": args.enable_review,
            "verification_gate": args.verification_gate,
        },
    )
    _ok(f"工作流已创建: {workflow_id}")
    _print(f"工作区: {Path('workspaces') / workflow_id}", style="dim")
    _print()

    # 运行
    try:
        state = await engine.run_workflow(workflow_id)
    finally:
        await engine.close()

    # 总结
    _print()
    if state.status == "completed":
        _ok("工作流执行完成")
        _print_summary(engine, workflow_id, state)
        return 0
    elif state.status == "paused":
        _print("工作流已暂停（等待检查点确认）", style="yellow")
        _print(f"运行 `pga approve {workflow_id}` 确认继续", style="yellow")
        _print(f"运行 `pga reject {workflow_id} \"反馈内容\"` 打回修改", style="yellow")
        return 0
    else:
        _err(f"工作流失败: {state.status}")
        for s in state.steps:
            if s.status == "failed":
                _print(f"  失败步骤: {s.skill_name} - {s.error_message}", style="red")
        return 2


def _print_summary(engine: WorkflowEngine, workflow_id: str, state: WorkflowState) -> None:
    """打印工作流总结。"""
    if _HAS_RICH:
        table = Table(title=f"工作流 {workflow_id} 产出", show_header=True, header_style="bold")
        table.add_column("步骤", style="cyan")
        table.add_column("状态", style="green")
        table.add_column("迭代", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("产出文件")
        for s in state.steps:
            files = ", ".join(s.output_files) if s.output_files else "-"
            table.add_row(s.skill_name, s.status, str(s.iterations), str(s.tokens), files)
        console.print(table)
    else:
        print(f"\n=== 工作流 {workflow_id} 产出 ===")
        for s in state.steps:
            print(f"  {s.skill_name}: {s.status} (iter={s.iterations}, tokens={s.tokens})")
            for f in s.output_files:
                print(f"    - {f}")

    # 显示产出文件
    from .workspace import Workspace
    ws = Workspace(workflow_id)
    files = ws.scan()
    if files:
        _print()
        _print("工作区文件:", style="bold")
        for f in files:
            size = ws.file_size(f)
            _print(f"  {f} ({size} bytes)")


# === list 命令 ===

def _cmd_list(args: argparse.Namespace) -> int:
    """执行 `pga list`。"""
    engine = WorkflowEngine()
    workflows = engine.list_workflows()
    if not workflows:
        _print("暂无工作流", style="dim")
        return 0

    if _HAS_RICH:
        table = Table(title="所有工作流", show_header=True, header_style="bold")
        table.add_column("ID", style="cyan")
        table.add_column("模板")
        table.add_column("标题")
        table.add_column("状态", style="green")
        table.add_column("当前步骤")
        table.add_column("创建时间")
        for w in workflows:
            status_style = {
                "completed": "bold green",
                "failed": "bold red",
                "running": "bold yellow",
                "paused": "yellow",
            }.get(w["status"], "white")
            table.add_row(
                w["workflow_id"],
                w["template"],
                w["title"][:40],
                f"[{status_style}]{w['status']}[/{status_style}]",
                w["current_step"] or "-",
                w["created_at"],
            )
        console.print(table)
    else:
        print(f"{'ID':<20} {'模板':<15} {'状态':<12} {'标题'}")
        for w in workflows:
            print(f"{w['workflow_id']:<20} {w['template']:<15} {w['status']:<12} {w['title'][:40]}")
    return 0


# === show 命令 ===

def _cmd_show(args: argparse.Namespace) -> int:
    """执行 `pga show <id>`。"""
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1

    if _HAS_RICH:
        panel = Panel(
            f"[bold]ID:[/bold] {state.workflow_id}\n"
            f"[bold]模板:[/bold] {state.template}\n"
            f"[bold]标题:[/bold] {state.title}\n"
            f"[bold]状态:[/bold] {state.status}\n"
            f"[bold]当前步骤:[/bold] {state.current_step or '-'}\n"
            f"[bold]创建时间:[/bold] {state.created_at}\n"
            f"[bold]更新时间:[/bold] {state.updated_at}",
            title="工作流详情",
            border_style="cyan",
        )
        console.print(panel)

        table = Table(title="步骤详情", show_header=True, header_style="bold")
        table.add_column("步骤", style="cyan")
        table.add_column("版本", style="dim")
        table.add_column("状态", style="green")
        table.add_column("开始时间")
        table.add_column("完成时间")
        table.add_column("迭代", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("LLM调用", justify="right")
        table.add_column("工具调用", justify="right")
        table.add_column("耗时(s)", justify="right")
        table.add_column("成本($)", justify="right")
        table.add_column("重试", justify="right")
        table.add_column("错误")
        for s in state.steps:
            table.add_row(
                s.skill_name,
                s.skill_version or "-",
                s.status,
                s.started_at or "-",
                s.completed_at or "-",
                str(s.iterations),
                str(s.tokens),
                str(s.llm_calls),
                str(s.tool_calls),
                f"{s.duration_sec:.1f}",
                f"{s.cost_usd:.4f}" if s.cost_usd else "-",
                str(s.retries),
                (s.error_message[:40] + "...") if len(s.error_message) > 40 else s.error_message or "-",
            )
        console.print(table)

        # 指标汇总
        total_iter = sum(s.iterations for s in state.steps)
        total_tokens = sum(s.tokens for s in state.steps)
        total_llm = sum(s.llm_calls for s in state.steps)
        total_tool = sum(s.tool_calls for s in state.steps)
        total_dur = sum(s.duration_sec for s in state.steps)
        total_retries = sum(s.retries for s in state.steps)
        total_cost = state.computed_cost_usd
        console.print()
        console.print(
            f"[bold]汇总:[/bold] 迭代={total_iter}  Tokens={total_tokens}  "
            f"LLM调用={total_llm}  工具调用={total_tool}  "
            f"总耗时={total_dur:.1f}s  重试={total_retries}  "
            f"总成本=${total_cost:.4f}"
        )

        # 最近的日志
        if state.logs:
            console.print()
            console.print("[bold]最近日志:[/bold]")
            for entry in state.logs[-20:]:
                ts = entry.get("timestamp", "")[11:19]
                step = entry.get("step", "")
                level = entry.get("level", "info")
                msg = entry.get("message", "")
                style = {"error": "red", "warn": "yellow"}.get(level, "white")
                prefix = f"[{ts}]"
                if step:
                    prefix += f" [{step}]"
                console.print(f"{prefix} {msg}", style=style)
    else:
        print(f"ID: {state.workflow_id}")
        print(f"模板: {state.template}")
        print(f"标题: {state.title}")
        print(f"状态: {state.status}")
        print(f"\n=== 步骤 ===")
        for s in state.steps:
            print(f"  {s.skill_name}: {s.status} (iter={s.iterations})")
        print(f"\n=== 最近日志 ===")
        for entry in state.logs[-20:]:
            print(f"  [{entry.get('timestamp', '')[11:19]}] {entry.get('message', '')}")
    return 0


# === resume / approve / reject ===

async def _cmd_resume(args: argparse.Namespace) -> int:
    """执行 `pga resume <id>`：恢复暂停的工作流。"""
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1
    if state.status not in ("paused", "failed"):
        _err(f"工作流状态为 {state.status}，无需恢复（只有 paused/failed 可恢复）")
        return 1

    from .workflow_engine import set_broadcast
    set_broadcast(_console_broadcast)

    _print(f"恢复工作流 {args.workflow_id}...", style="cyan")
    try:
        state = await engine.run_workflow(args.workflow_id)
    finally:
        await engine.close()

    if state.status == "completed":
        _ok("工作流执行完成")
        _print_summary(engine, args.workflow_id, state)
        return 0
    elif state.status == "paused":
        _print("工作流再次暂停（等待检查点）", style="yellow")
        return 0
    else:
        _err(f"工作流失败: {state.status}")
        return 2


async def _cmd_approve(args: argparse.Namespace) -> int:
    """执行 `pga approve <id> [反馈]`。

    只写检查点信号（`_checkpoints/{step}.json`），不启动引擎：
    - 若 `pga run` 进程仍在运行，它会在 0.5s 内轮询到并继续；
    - 若进程已退出，`pga resume <id>` 会消费该信号且**不重跑**该步。
    """
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1

    # 检查是否在等待检查点
    waiting = next(
        (s.skill_name for s in state.steps if s.status == "waiting_checkpoint"), ""
    )
    if not waiting:
        _err(f"工作流 {args.workflow_id} 当前不在等待检查点")
        return 1

    feedback = args.feedback or ""
    submit_checkpoint(
        args.workflow_id,
        {"action": "approve", "feedback": feedback},
        step=waiting,
    )
    _ok(f"已确认检查点: {args.workflow_id} / {waiting}")
    if feedback:
        _print(f"反馈: {feedback}", style="dim")
    _print(
        "信号已落盘：运行中的进程会自动继续；若进程已退出，请执行 "
        f"`pga resume {args.workflow_id}`",
        style="dim",
    )
    return 0


async def _cmd_reject(args: argparse.Namespace) -> int:
    """执行 `pga reject <id> <反馈>`。"""
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1

    waiting = next(
        (s.skill_name for s in state.steps if s.status == "waiting_checkpoint"), ""
    )
    if not waiting:
        _err(f"工作流 {args.workflow_id} 当前不在等待检查点")
        return 1

    if not args.feedback:
        _err("打回必须提供反馈内容")
        return 1

    submit_checkpoint(
        args.workflow_id,
        {"action": "reject", "feedback": args.feedback},
        step=waiting,
    )
    _ok(f"已打回检查点: {args.workflow_id} / {waiting}")
    _print(f"反馈: {args.feedback}", style="dim")
    _print(
        "运行中的进程会读取该信号并暂停；若进程已退出，"
        f"`pga resume {args.workflow_id}` 会应用反馈并重跑该步",
        style="dim",
    )
    return 0


async def _cmd_revise(args: argparse.Namespace) -> int:
    """执行 `pga revise <id> <反馈> [--target-section] [--severity]`。

    结构化打回：相比 reject，revise 附带 target_section 与 severity，
    反馈会被精准注入 CONTEXT.md 指导 rerun 修改指定部分。
    """
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1

    waiting = next(
        (s.skill_name for s in state.steps if s.status == "waiting_checkpoint"), ""
    )
    if not waiting:
        _err(f"工作流 {args.workflow_id} 当前不在等待检查点")
        return 1

    if not args.feedback:
        _err("revise 必须提供反馈内容")
        return 1

    submit_checkpoint(args.workflow_id, {
        "action": "revise",
        "feedback": args.feedback,
        "target_section": args.target_section or "",
        "severity": args.severity or "",
    }, step=waiting)
    _ok(f"已结构化打回检查点: {args.workflow_id} / {waiting}")
    _print(f"反馈: {args.feedback}", style="dim")
    if args.target_section:
        _print(f"目标章节: {args.target_section}", style="dim")
    if args.severity:
        _print(f"严重度: {args.severity}", style="dim")
    _print(
        f"修复后用 `pga resume {args.workflow_id}` 按此反馈重跑该步",
        style="cyan",
    )
    return 0


# === rerun ===

async def _cmd_rerun(args: argparse.Namespace) -> int:
    """执行 `pga rerun <id> <skill> [--clean] [--latest]`。"""
    engine = WorkflowEngine()
    state = engine.get_state(args.workflow_id)
    if not state:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1

    valid_skills = [s.skill_name for s in state.steps]
    if args.skill not in valid_skills:
        _err(f"无效 skill: {args.skill}（可选: {', '.join(valid_skills)}）")
        return 1

    from .workflow_engine import set_broadcast
    set_broadcast(_console_broadcast)

    flags = []
    if args.clean:
        flags.append("--clean")
    if args.latest:
        flags.append("--latest")
    flag_str = f"（{' '.join(flags)}）" if flags else ""

    if args.latest:
        _print(f"重跑步骤 {args.skill}{flag_str}: 升级到最新 skill 版本...", style="cyan")
    elif args.clean:
        _print(f"重跑步骤 {args.skill}{flag_str}: 先清理该步主产物...", style="cyan")
    else:
        _print(f"重跑步骤 {args.skill}{flag_str}...", style="cyan")
    try:
        state = await engine.rerun_step(
            args.workflow_id, args.skill,
            clean=args.clean, latest=args.latest,
        )
    finally:
        await engine.close()

    if state.status == "completed":
        _ok("工作流执行完成")
        _print_summary(engine, args.workflow_id, state)
        return 0
    else:
        _err(f"工作流状态: {state.status}")
        return 2


# === delete ===

def _cmd_delete(args: argparse.Namespace) -> int:
    """执行 `pga delete <id>`。"""
    engine = WorkflowEngine()
    if not args.force and _HAS_RICH:
        if not Confirm.ask(f"确认删除工作流 {args.workflow_id} 及其所有文件？"):
            _print("已取消", style="yellow")
            return 0
    ok = engine.delete_workflow(args.workflow_id)
    if ok:
        _ok(f"已删除: {args.workflow_id}")
        return 0
    else:
        _err(f"工作流不存在: {args.workflow_id}")
        return 1


# === templates / skills ===

def _cmd_templates(args: argparse.Namespace) -> int:
    """执行 `pga templates`。"""
    templates = list_templates()
    if not templates:
        _print("暂无模板", style="dim")
        return 0

    if _HAS_RICH:
        table = Table(title="可用模板", show_header=True, header_style="bold")
        table.add_column("Key", style="cyan")
        table.add_column("名称")
        table.add_column("默认项目类型")
        table.add_column("步骤数", justify="right")
        table.add_column("步骤")
        for key in templates:
            try:
                tmpl = load_template(key)
                steps_str = " → ".join(s.skill_name for s in tmpl.sub_steps)
                table.add_row(key, tmpl.name, tmpl.default_project_type, str(len(tmpl.sub_steps)), steps_str)
            except Exception as e:
                table.add_row(key, f"[red]加载失败: {e}[/red]", "-", "-", "-")
        console.print(table)
    else:
        for key in templates:
            try:
                tmpl = load_template(key)
                steps = " -> ".join(s.skill_name for s in tmpl.sub_steps)
                print(f"{key}: {tmpl.name} ({len(tmpl.sub_steps)} 步) [{steps}]")
            except Exception as e:
                print(f"{key}: 加载失败 - {e}")
    return 0


def _cmd_skills(args: argparse.Namespace) -> int:
    """执行 `pga skills`。"""
    from .skill_loader import load_skill_meta
    skills = list_skills()
    if not skills:
        _print("暂无 skill", style="dim")
        return 0

    if _HAS_RICH:
        table = Table(title="可用 Skills", show_header=True, header_style="bold")
        table.add_column("名称", style="cyan")
        table.add_column("版本")
        table.add_column("主产物")
        table.add_column("描述")
        for name in skills:
            try:
                meta = load_skill_meta(name)
                # 优先用 front matter 的 description（Use when ... 触发条件），
                # 无则回退到正文首个段落
                desc = (meta.description or "").strip()
                if not desc:
                    md = load_skill_md(name)
                    in_front_matter = False
                    for line in md.split("\n"):
                        line = line.strip()
                        if line == "---":
                            in_front_matter = not in_front_matter
                            continue
                        if in_front_matter:
                            continue
                        if line and not line.startswith("#") and not line.startswith("<!--"):
                            desc = line
                            break
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                outputs = ", ".join(meta.outputs) if meta.outputs else "-"
                table.add_row(name, meta.version or "-", outputs, desc)
            except Exception as e:
                table.add_row(name, "-", "-", f"[red]加载失败: {e}[/red]")
        console.print(table)
    else:
        for name in skills:
            print(f"  {name}")
    return 0


# === config ===

def _cmd_config(args: argparse.Namespace) -> int:
    """执行 `pga config ...`。"""
    action = args.action

    if action == "path":
        _print(str(_user_config_path()))
        return 0

    if action == "get":
        cfg = _load_user_config()
        if args.key:
            if args.key in cfg:
                _print(f"{args.key} = {cfg[args.key]}")
            else:
                _err(f"配置项不存在: {args.key}")
                return 1
        else:
            if not cfg:
                _print("配置文件为空", style="dim")
            else:
                if _HAS_RICH:
                    table = Table(title=f"配置文件: {_user_config_path()}", show_header=True, header_style="bold")
                    table.add_column("Key", style="cyan")
                    table.add_column("Value")
                    for k, v in cfg.items():
                        # 隐藏 API Key 中间部分
                        if "key" in k.lower() and isinstance(v, str) and len(v) > 12:
                            v = v[:6] + "..." + v[-4:]
                        table.add_row(k, str(v))
                    console.print(table)
                else:
                    for k, v in cfg.items():
                        print(f"{k} = {v}")
        return 0

    if action == "set":
        if not args.key or args.value is None:
            _err("用法: pga config set <key> <value>")
            return 1
        set_user_config(args.key, args.value)
        _ok(f"已设置: {args.key} = {args.value}")
        return 0

    if action == "list-keys":
        _print("可配置项:", style="bold")
        keys = [
            ("llm_base_url", "LLM API 地址（默认 https://api.deepseek.com/v1）"),
            ("llm_api_key", "LLM API Key"),
            ("llm_model", "模型名（默认 deepseek-chat）"),
            ("llm_timeout", "超时秒数（默认 600）"),
            ("llm_temperature", "温度（默认 0.7）"),
            ("llm_max_tokens", "最大 tokens（默认 8192）"),
            ("llm_max_retries", "LLM 业务层最大重试次数（默认 3）"),
            ("llm_retry_base_delay", "LLM 重试基础退避秒数（默认 2.0）"),
            ("llm_retry_max_delay", "LLM 重试最大退避秒数（默认 30.0）"),
            ("llm_context_window", "模型上下文窗口 token 数（默认 32768）"),
            ("llm_price_input_per_1m", "输入 token 单价 USD/1M（默认自动查 MODEL_PRICING 表；未命中记 0）"),
            ("llm_price_output_per_1m", "输出 token 单价 USD/1M（默认自动查 MODEL_PRICING 表；未命中记 0）"),
            ("server_allowed_origins", "CORS 白名单，逗号分隔（默认 http://localhost:*,http://127.0.0.1:*）"),
            ("server_max_concurrent_workflows", "同时运行的工作流数上限（默认 2）"),
            ("server_enable_auth", "是否启用 token 认证（默认 true；设 false 关闭）"),
        ]
        for k, desc in keys:
            _print(f"  [cyan]{k}[/cyan]  {desc}" if _HAS_RICH else f"  {k}  {desc}")
        return 0

    _err(f"未知 config action: {action}")
    return 1


# === 主入口 ===

def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="pga",
        description="Project Generator Agent — 一句话生成项目",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  pga run "做一个待办事项 Web 应用，前后端分离"
  pga run "写一个 CLI 计算器" --project-type cli --auto
  pga list
  pga show abc123
  pga approve abc123 "做得不错"
  pga reject abc123 "需求要改：增加登录"
  pga config set llm_api_key sk-xxx
  pga templates
""",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="启动工作流")
    p_run.add_argument("title", help="一句话需求")
    p_run.add_argument("--template", "-t", default="grad_project", help="模板 key（默认 grad_project）")
    p_run.add_argument("--project-type", "-p", default="fullstack",
                       choices=["fullstack", "frontend_only", "backend_only", "cli", "script"],
                       help="项目类型（默认 fullstack）")
    p_run.add_argument("--auto", "-a", action="store_true", help="自动继续（不暂停检查点）")
    p_run.add_argument("--no-checkpoint", action="store_true", help="关闭检查点")
    p_run.add_argument("--enable-review", action="store_true",
                       help="启用 dev-review 评审步骤（需模板支持，默认关闭）")
    p_run.add_argument("--max-iter", type=int, default=30, help="agent 最大迭代次数（默认 30）")
    p_run.add_argument("--verification-gate", default="tests",
                       choices=["strict", "tests", "off"],
                       help="dev-selfcheck 验证门禁（默认 tests：只验证测试通过；strict 额外启动项目做运行时验证）")
    p_run.set_defaults(func=_cmd_run, is_async=True)

    # list
    p_list = sub.add_parser("list", aliases=["ls"], help="列出所有工作流")
    p_list.set_defaults(func=_cmd_list, is_async=False)

    # show
    p_show = sub.add_parser("show", help="查看工作流详情")
    p_show.add_argument("workflow_id", help="工作流 ID")
    p_show.set_defaults(func=_cmd_show, is_async=False)

    # resume
    p_resume = sub.add_parser("resume", help="恢复暂停的工作流")
    p_resume.add_argument("workflow_id", help="工作流 ID")
    p_resume.set_defaults(func=_cmd_resume, is_async=True)

    # approve
    p_approve = sub.add_parser("approve", help="检查点确认通过")
    p_approve.add_argument("workflow_id", help="工作流 ID")
    p_approve.add_argument("feedback", nargs="?", default="", help="可选反馈")
    p_approve.add_argument("--no-run", action="store_true",
                           help="已废弃：approve 只写检查点信号，不再自动拉起引擎")
    p_approve.set_defaults(func=_cmd_approve, is_async=True)

    # reject
    p_reject = sub.add_parser("reject", help="检查点打回")
    p_reject.add_argument("workflow_id", help="工作流 ID")
    p_reject.add_argument("feedback", help="打回反馈")
    p_reject.set_defaults(func=_cmd_reject, is_async=True)

    # revise（结构化打回：带 target_section / severity）
    p_revise = sub.add_parser("revise", help="结构化检查点打回（带目标章节与严重度）")
    p_revise.add_argument("workflow_id", help="工作流 ID")
    p_revise.add_argument("feedback", help="打回反馈")
    p_revise.add_argument("--target-section", default="",
                          help="指定要修改的文件/章节（如 DESIGN.md#数据模型）")
    p_revise.add_argument("--severity", default="",
                          choices=["blocker", "major", "minor", "nit"],
                          help="问题严重度")
    p_revise.set_defaults(func=_cmd_revise, is_async=True)

    # rerun
    p_rerun = sub.add_parser("rerun", help="重跑某步骤")
    p_rerun.add_argument("workflow_id", help="工作流 ID")
    p_rerun.add_argument("skill", help="skill 名称")
    p_rerun.add_argument("--clean", action="store_true",
                         help="重跑前清理该步主产物（避免残留干扰；dev-code 不整体清空 code/）")
    p_rerun.add_argument("--latest", action="store_true",
                         help="升级到最新 skill 版本目录（skills/<name>/<ver>/SKILL.md），用于版本升级场景")
    p_rerun.set_defaults(func=_cmd_rerun, is_async=True)

    # delete
    p_del = sub.add_parser("delete", aliases=["rm"], help="删除工作流")
    p_del.add_argument("workflow_id", help="工作流 ID")
    p_del.add_argument("--force", "-f", action="store_true", help="跳过确认")
    p_del.set_defaults(func=_cmd_delete, is_async=False)

    # templates
    p_tmpl = sub.add_parser("templates", help="列出可用模板")
    p_tmpl.set_defaults(func=_cmd_templates, is_async=False)

    # skills
    p_sk = sub.add_parser("skills", help="列出可用 skills")
    p_sk.set_defaults(func=_cmd_skills, is_async=False)

    # config
    p_cfg = sub.add_parser("config", help="配置管理")
    p_cfg.add_argument("action", choices=["set", "get", "path", "list-keys"],
                       help="操作: set/get/path/list-keys")
    p_cfg.add_argument("key", nargs="?", help="配置项 key")
    p_cfg.add_argument("value", nargs="?", help="配置项 value")
    p_cfg.set_defaults(func=_cmd_config, is_async=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # 配置日志
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 抑制 openai/httpx 的 DEBUG 日志
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    func = args.func
    is_async = getattr(args, "is_async", False)

    try:
        if is_async:
            return asyncio.run(func(args))
        else:
            return func(args)
    except KeyboardInterrupt:
        _print("\n已中断", style="yellow")
        return 130
    except Exception as e:
        log.exception("command failed")
        _err(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
