"""工作流引擎：模板加载、步骤调度、检查点、状态持久化。

对应 Modex-MH-Agent 的 workflow_engine 模块，改进：
- 模板用 YAML 配置文件（非硬编码）
- 状态用 JSON 文件存（每个工作流一个 state.json，避免 DB 锁）
- 检查点用 asyncio.Event 实现
- 日志通过回调广播（兼容 CLI 和 WebSocket）

进一步改进（相对初版）：
- state.json 原子写 + .bak 备份 + 崩溃恢复
- 检查点超时动作可配（auto_approve / auto_reject / wait_forever），默认 auto_reject
- 打回反馈注入 CONTEXT.md 并在 rerun 时回填
- 健康检查失败按原因分类驱动重试 prompt
- rerun 级联失效：rerun 某步后后续步骤标记 stale 自动重跑
- 结构化上下文摘要：每步产出 _summaries/{step}.md 供下一步引用
- 全局 / 步骤级超时
- 日志落盘 run.log + 指标记录（llm_calls/tool_calls/duration）
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Awaitable

import yaml

from . import checkpoint_store
from .agent_loop import run_agent_loop, AgentRunResult
from .config import (
    LLMConfig, WorkflowConfig, TEMPLATES_DIR, WORKSPACES_DIR,
)
from .health_check import (
    check_primary_output, check_step_companions, check_all_code_files,
    check_all_skill_outputs, check_self_check_completeness, CheckResult,
    run_verification_gate, VerificationReport,
)
from .llm_client import LLMClient
from .skill_loader import render_skill_prompt
from .workspace import Workspace, ProjectMeta

log = logging.getLogger(__name__)


# === 模板定义 ===

@dataclass
class StepDef:
    """单步定义（来自 YAML 模板）。

    `when` 为条件分支表达式，空字符串表示无条件执行。支持的安全语法：
        project_type == "fullstack"
        project_type != "script"
        project_type in ["fullstack", "backend_only"]
        project_type not in ["script"]
        enable_review == true
    多个条件可用 `and` / `or` 连接（不支持括号分组，保持简单）。
    表达式不通过时该步骤标记为 `skipped`，不执行。
    """
    skill_name: str
    display_name: str
    has_checkpoint: bool = False
    checkpoint_type: str | None = None
    primary_output: str = ""
    min_size: int = 100
    required_companions: list[str] = field(default_factory=list)
    required_companions_dynamic: bool = False
    when: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "StepDef":
        return cls(
            skill_name=d["skill_name"],
            display_name=d.get("display_name", d["skill_name"]),
            has_checkpoint=bool(d.get("has_checkpoint", False)),
            checkpoint_type=d.get("checkpoint_type"),
            primary_output=d.get("primary_output", ""),
            min_size=int(d.get("min_size", 100)),
            required_companions=list(d.get("required_companions", [])),
            required_companions_dynamic=bool(d.get("required_companions_dynamic", False)),
            when=str(d.get("when", "")),
        )


@dataclass
class TemplateDef:
    """工作流模板定义。"""
    name: str
    template_key: str
    pipeline_skill: str
    default_project_type: str = "fullstack"
    sub_steps: list[StepDef] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "TemplateDef":
        return cls(
            name=d["name"],
            template_key=d["template_key"],
            pipeline_skill=d.get("pipeline_skill", ""),
            default_project_type=d.get("default_project_type", "fullstack"),
            sub_steps=[StepDef.from_dict(s) for s in d.get("sub_steps", [])],
        )


def load_template(template_key: str) -> TemplateDef:
    """加载 YAML 模板文件。"""
    path = TEMPLATES_DIR / f"{template_key}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"模板不存在: {template_key} (期望路径: {path})")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TemplateDef.from_dict(data)


def list_templates() -> list[str]:
    """列出所有可用模板 key。"""
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.yaml"))


# === 条件分支表达式求值 ===

# 安全的 when 表达式子句模式（不用 eval，避免代码注入）
# 支持: key == "val" | key != "val" | key == true|false | key in [...] | key not in [...]
_WHEN_CLAUSE_RE = re.compile(
    r'^\s*(\w+)\s*(==|!=|in|not\s+in)\s*(.+?)\s*$'
)


def _eval_when(when: str, params: dict) -> bool:
    """安全求值模板步骤的 when 条件表达式。

    支持 `and` / `or` 连接的子句（先 and 后 or，无括号）。
    任何解析失败的子句视为 False，并打 warning。

    Examples:
        _eval_when('project_type == "fullstack"', {"project_type": "fullstack"}) -> True
        _eval_when('project_type in ["fullstack", "cli"]', {"project_type": "cli"}) -> True
        _eval_when('enable_review == true', {"enable_review": True}) -> True
    """
    when = (when or "").strip()
    if not when:
        return True

    # 先按 or 拆，再按 and 拆
    or_parts = re.split(r'\s+or\s+', when)
    for or_part in or_parts:
        and_parts = re.split(r'\s+and\s+', or_part)
        if all(_eval_when_clause(p, params) for p in and_parts):
            return True
    return False


def _eval_when_clause(clause: str, params: dict) -> bool:
    """求值单个 when 子句。"""
    m = _WHEN_CLAUSE_RE.match(clause)
    if not m:
        log.warning("invalid when clause: %r", clause)
        return False
    key, op, raw_val = m.group(1), m.group(2), m.group(3)
    actual = params.get(key)

    # 解析右值
    raw_val = raw_val.strip()
    if raw_val == "true":
        val: Any = True
    elif raw_val == "false":
        val = False
    elif raw_val.startswith('"') and raw_val.endswith('"'):
        val = raw_val[1:-1]
    elif raw_val.startswith("'") and raw_val.endswith("'"):
        val = raw_val[1:-1]
    elif raw_val.startswith("[") and raw_val.endswith("]"):
        # 列表字面量
        inner = raw_val[1:-1]
        items = re.findall(r'"([^"]*)"|\'([^\']*)\'|(\w+)', inner)
        val = [a or b or c for a, b, c in items]
    else:
        # 裸标识符或数字，按字符串处理
        val = raw_val

    try:
        if op == "==":
            return actual == val
        if op == "!=":
            return actual != val
        if op == "in":
            return actual in val
        if op == "not in":
            return actual not in val
    except TypeError:
        return False
    return False


# === 工作流状态 ===

# 状态 schema 版本，字段变更时递增，便于未来迁移
STATE_SCHEMA_VERSION = 4

# StepState 允许的状态
# pending | running | waiting_checkpoint | completed | failed | skipped | stale
# stale: 上游步骤被 rerun 后，本步骤产物可能失效，需重跑

@dataclass
class StepState:
    """单步运行时状态。"""
    skill_name: str
    display_name: str
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str = ""
    output_files: list[str] = field(default_factory=list)
    checkpoint_response: dict | None = None
    iterations: int = 0
    tokens: int = 0
    # 新增指标
    llm_calls: int = 0
    tool_calls: int = 0
    duration_sec: float = 0.0
    retries: int = 0
    soft_truncated: bool = False
    # 目录级版本化：记录本步实际使用的 skill 版本（"1.0.0" 或 "" 表示平铺默认）
    skill_version: str = ""
    # 成本指标（P3-2）
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    # Git 集成（P3-1）：本步完成后产出的 commit hash（空表示无 git 或无变更）
    commit_hash: str = ""
    # 基线 commit（P3-2）：本步开始时的 HEAD，用于 dev-review 做 diff 评审的 base
    base_commit: str = ""


@dataclass
class WorkflowState:
    """工作流完整状态（持久化到 state.json）。"""
    workflow_id: str
    template: str
    title: str
    params: dict
    status: str = "pending"  # pending|running|paused|completed|failed|interrupted|corrupted
    current_step: str = ""
    steps: list[StepState] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = STATE_SCHEMA_VERSION
    # 成本汇总（P3-2）：各步 cost_usd 之和，run 结束时刷新
    total_cost_usd: float = 0.0

    @property
    def computed_cost_usd(self) -> float:
        """实时计算各步成本之和（不依赖 total_cost_usd 字段刷新）。"""
        return round(sum(s.cost_usd for s in self.steps), 6)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "WorkflowState":
        d = json.loads(s)
        d["steps"] = [StepState(**s) for s in d.get("steps", [])]
        # 向前兼容：旧 state.json 无 schema_version
        d.setdefault("schema_version", 1)
        # 移除未知字段（防止旧字段残留）
        known = {f for f in cls.__dataclass_fields__}
        d = {k: v for k, v in d.items() if k in known}
        return cls(**d)

    def add_log(self, step: str, level: str, message: str) -> None:
        self.logs.append({
            "timestamp": _now_iso(),
            "step": step,
            "level": level,
            "message": message,
        })
        # 限制日志数量（保留最近 500 条）
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _gate_findings(
    report: VerificationReport, strict: bool = False,
) -> tuple[list[str], list[str]]:
    """把验证门禁报告拆成 (阻断性错误, 警告)。

    测试目录 / 测试文件 / 测试执行 始终阻断；
    运行时验证仅在 strict 模式下阻断（uvicorn / 依赖安装受环境影响较大，
    默认降级为警告，避免把环境问题误判为代码问题）。
    """
    errors: list[str] = []
    warnings: list[str] = []

    def _detail(res: CheckResult) -> str:
        return (
            "; ".join(res.errors)
            or "; ".join(f"缺失 {m}" for m in res.missing)
            or "; ".join(res.warnings)
            or "未通过"
        )

    for label, res in (
        ("测试目录", report.test_dir_exists),
        ("测试文件", report.test_files_exist),
        ("测试执行", report.tests_pass),
    ):
        if not res.ok:
            errors.append(f"{label}: {_detail(res)}")

    if not report.runtime_ok.ok:
        detail = _detail(report.runtime_ok)
        if strict:
            errors.append(f"运行时验证: {detail}")
        else:
            warnings.append(f"运行时验证未通过（verification_gate=tests，不阻断）: {detail}")

    return errors, warnings


# === 检查点机制 ===

class CheckpointManager:
    """检查点同步管理。

    用 asyncio.Event 实现轻量级等待，超时按动作策略处理。
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}
        self._responses: dict[str, dict] = {}

    def get_event(self, workflow_id: str) -> asyncio.Event:
        if workflow_id not in self._events:
            self._events[workflow_id] = asyncio.Event()
        return self._events[workflow_id]

    def set_response(self, workflow_id: str, response: dict) -> None:
        self._responses[workflow_id] = response
        event = self._events.get(workflow_id)
        if event:
            event.set()

    def get_response(self, workflow_id: str) -> dict | None:
        return self._responses.get(workflow_id)

    def clear(self, workflow_id: str) -> None:
        self._events.pop(workflow_id, None)
        self._responses.pop(workflow_id, None)


# 全局检查点管理器（单例）
_checkpoint_mgr = CheckpointManager()


def submit_checkpoint(workflow_id: str, response: dict, step: str = "") -> None:
    """提交检查点响应（供 CLI / 服务端调用）。

    同时做两件事：
    1. 写 `_checkpoints/{step}.json`（跨进程信号，运行中的工作流轮询读取）
    2. 设置进程内 Event（同进程直接唤醒，省一次轮询）

    接受两种 schema：
    - 旧版: {approved: bool, feedback: str}
    - 新版: {action: approve|reject|revise, feedback, target_section, severity, specific_issues}
    内部统一归一化为新版存储。

    Args:
        step: 目标步骤名；为空时从 state.json 的 waiting_checkpoint 步骤推断。
    """
    normalized = normalize_checkpoint_response(response)
    workspace = Workspace(workflow_id)
    target = step or checkpoint_store.resolve_waiting_step(workspace.root)
    if target:
        try:
            checkpoint_store.write_response(workspace.root, target, normalized)
        except OSError as e:
            log.warning("write checkpoint response failed for %s: %s", target, e)
    else:
        log.warning("submit_checkpoint: 未找到 waiting_checkpoint 步骤 (workflow=%s)", workflow_id)
    _checkpoint_mgr.set_response(workflow_id, normalized)


# 结构化检查点响应的合法 action
VALID_CHECKPOINT_ACTIONS: tuple[str, ...] = ("approve", "reject", "revise")
VALID_CHECKPOINT_SEVERITY: tuple[str, ...] = ("blocker", "major", "minor", "nit", "")


def normalize_checkpoint_response(raw: dict | None) -> dict:
    """把检查点响应归一化为结构化 schema。

    旧版 {approved: bool, feedback} → 新版 {action, feedback, ...}
    新版 {action: approve|reject|revise, ...} → 原样补全默认字段。

    归一化后的字段：
      action: approve | reject | revise   （approve 放行；reject/revise 打回）
      feedback: str                       总体反馈
      target_section: str                 指定要修改的文件/章节（revise 用）
      severity: blocker|major|minor|nit   问题严重度
      specific_issues: list[dict]         具体问题清单 [{file, line, issue, suggestion}]
      auto: bool                          是否超时自动产生（非用户主动）
    """
    raw = raw or {}
    # 已是新版 schema（含 action 字段）
    if "action" in raw:
        action = str(raw["action"]).lower().strip()
        if action not in VALID_CHECKPOINT_ACTIONS:
            action = "reject"
        severity = str(raw.get("severity", "")).lower().strip()
        if severity and severity not in VALID_CHECKPOINT_SEVERITY:
            severity = ""
        return {
            "action": action,
            "feedback": str(raw.get("feedback", "")),
            "target_section": str(raw.get("target_section", "")),
            "severity": severity,
            "specific_issues": list(raw.get("specific_issues", [])),
            "auto": bool(raw.get("auto", False)),
            # 向后兼容：approved 字段保留
            "approved": action == "approve",
        }
    # 旧版 schema（approved 字段）
    approved = bool(raw.get("approved", True))
    return {
        "action": "approve" if approved else "reject",
        "feedback": str(raw.get("feedback", "")),
        "target_section": "",
        "severity": "",
        "specific_issues": [],
        "auto": bool(raw.get("auto", False)),
        "approved": approved,
    }


# 检查点轮询间隔（秒）：兼顾响应及时性与磁盘 IO
_CHECKPOINT_POLL_INTERVAL = 0.5


async def wait_checkpoint(
    workflow_id: str,
    step: str,
    timeout: int,
    timeout_action: str = "auto_reject",
) -> dict:
    """等待检查点响应（支持跨进程）。

    先写 `_checkpoints/{step}.json`（status=waiting），随后以 0.5s 间隔轮询两个来源：
    - 进程内 `asyncio.Event`（同进程提交时立即命中）
    - 落盘文件 status=responded（`pga approve/reject/revise` 跨进程信号）

    Args:
        step: 步骤名，用于定位检查点文件
        timeout: 超时秒数
        timeout_action: 超时动作
            - auto_approve: 超时自动通过（旧行为，不安全）
            - auto_reject: 超时自动打回（默认，更安全）
            - wait_forever: 永不超时（直到用户响应）
    """
    workspace = Workspace(workflow_id)
    checkpoint_store.write_request(workspace.root, step, timeout_action)

    deadline = None
    if timeout_action != "wait_forever":
        deadline = time.monotonic() + max(0, timeout)

    while True:
        # 1) 进程内信号
        resp = _checkpoint_mgr.get_response(workflow_id)
        if resp:
            checkpoint_store.mark_consumed(workspace.root, step, resp)
            return resp

        # 2) 落盘信号（跨进程）
        data = checkpoint_store.read(workspace.root, step)
        if data and data.get("status") == "responded":
            resp = normalize_checkpoint_response(data)
            checkpoint_store.mark_consumed(workspace.root, step, resp)
            log.info(
                "checkpoint %s/%s got file response: action=%s",
                workflow_id, step, resp.get("action"),
            )
            return resp

        # 3) 超时判定
        if deadline is not None and time.monotonic() >= deadline:
            log.warning(
                "checkpoint %s/%s timed out after %ds, action=%s",
                workflow_id, step, timeout, timeout_action,
            )
            if timeout_action == "auto_approve":
                resp = normalize_checkpoint_response({"approved": True, "auto": True})
            else:
                resp = normalize_checkpoint_response(
                    {"approved": False, "feedback": "检查点超时未响应，自动打回", "auto": True}
                )
            checkpoint_store.mark_timeout(workspace.root, step, resp)
            return resp

        await asyncio.sleep(_CHECKPOINT_POLL_INTERVAL)


# === 日志广播 ===

LogCallback = Callable[[dict], Awaitable[None]]


class BroadcastManager:
    """日志广播管理（兼容 CLI 和 WebSocket）。"""

    def __init__(self) -> None:
        self._callbacks: list[LogCallback] = []

    def subscribe(self, cb: LogCallback) -> None:
        self._callbacks.append(cb)

    def unsubscribe(self, cb: LogCallback) -> None:
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    async def broadcast(self, event: dict) -> None:
        for cb in list(self._callbacks):
            try:
                await cb(event)
            except Exception as e:
                log.warning("broadcast callback failed: %s", e)


_broadcast = BroadcastManager()


def set_broadcast(cb: LogCallback) -> None:
    """设置全局广播回调（向后兼容旧 API）。"""
    _broadcast.subscribe(cb)


def unsubscribe_broadcast(cb: LogCallback) -> None:
    """取消广播回调。"""
    _broadcast.unsubscribe(cb)


# === 工作流引擎 ===

class WorkflowEngine:
    """工作流引擎：创建、运行、暂停、恢复、查询。"""

    def __init__(
        self,
        llm_config: LLMConfig | None = None,
        workflow_config: WorkflowConfig | None = None,
    ) -> None:
        self.llm_config = llm_config or LLMConfig.from_env()
        self.workflow_config = workflow_config or WorkflowConfig()
        self._llm: LLMClient | None = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(self.llm_config)
        return self._llm

    # === 创建 ===

    def create_workflow(
        self,
        template_key: str,
        title: str,
        params: dict | None = None,
    ) -> str:
        """创建工作流。"""
        params = params or {}
        tmpl = load_template(template_key)
        workflow_id = uuid.uuid4().hex[:16]

        workspace = Workspace(workflow_id)

        project_type = params.get("project_type", tmpl.default_project_type)
        meta = ProjectMeta(
            title=title,
            template=template_key,
            project_type=project_type,
            auto_proceed=bool(params.get("auto_proceed", self.workflow_config.auto_proceed)),
            extra={k: v for k, v in params.items() if k not in ("project_type", "auto_proceed")},
        )
        workspace.write_project_meta(meta)

        workspace.write_context_md(title, template_key, meta)

        # Git 初始化（P3-1）：create_workflow 时 git init + 初始 commit，
        # 为后续每步 commit 与 diff 评审建立基线。enable_git 关闭或 git 不可用时跳过。
        wf_cfg = WorkflowConfig.from_dict({**asdict(self.workflow_config), **params})
        if wf_cfg.enable_git:
            if workspace.git_init():
                # 写 .gitignore 排除噪声文件（日志/快照/缓存），保留 code/ 与设计文档
                workspace.write_file(".gitignore", "\n".join([
                    "# PGA 工作区噪声文件",
                    "__pycache__/",
                    "*.pyc",
                    "*.bak",
                    "run.log",
                    "_failure_snapshot/",
                    "_checkpoints/",
                    "_runtime/",
                    "node_modules/",
                    ".venv/",
                    "venv/",
                    "dist/",
                    "build/",
                    ".DS_Store",
                    "Thumbs.db",
                ]) + "\n")
                init_hash = workspace.git_commit(
                    f"init: {title} (template={template_key}, type={project_type})",
                    allow_empty=True,
                )
                if init_hash:
                    state_log_msg = f"git 基线 commit: {init_hash[:8]}"
                else:
                    state_log_msg = "git init 成功但初始 commit 失败"
            else:
                state_log_msg = "git 不可用，跳过版本控制"
        else:
            state_log_msg = "git 集成已关闭（enable_git=False）"

        state = WorkflowState(
            workflow_id=workflow_id,
            template=template_key,
            title=title,
            params=params,
            status="pending",
            steps=[
                StepState(skill_name=s.skill_name, display_name=s.display_name)
                for s in tmpl.sub_steps
            ],
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        state.add_log("", "info", f"工作流已创建: {title}")
        state.add_log("", "info", f"模板: {template_key}, project_type: {project_type}")
        state.add_log("", "info", state_log_msg)
        self._save_state(workspace, state)

        log.info("workflow created: id=%s template=%s title=%s", workflow_id, template_key, title)
        return workflow_id

    # === 运行 ===

    async def run_workflow(self, workflow_id: str) -> WorkflowState:
        """运行工作流（异步，支持暂停/恢复）。

        全局超时由 workflow_config.global_timeout 控制。
        运行期间每 10s 写一次 `_runtime/heartbeat`，供服务端启动时的僵尸
        检测区分「真僵尸」与「另一个进程正在跑」。
        """
        workspace = Workspace(workflow_id)
        state = self._load_state(workspace)
        if state.status == "corrupted":
            return state

        tmpl = load_template(state.template)

        wf_config = WorkflowConfig.from_dict({**asdict(self.workflow_config), **state.params})

        heartbeat = asyncio.create_task(self._heartbeat_loop(workspace))
        try:
            return await asyncio.wait_for(
                self._run_workflow_impl(workspace, state, tmpl, wf_config, workflow_id),
                timeout=wf_config.global_timeout,
            )
        except asyncio.TimeoutError:
            log.error("workflow %s global timeout after %ds", workflow_id, wf_config.global_timeout)
            state = self._load_state(workspace)
            state.status = "failed"
            state.add_log("", "error", f"工作流全局超时（{wf_config.global_timeout}s）")
            self._save_state(workspace, state)
            return state
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass
            try:
                (workspace.root / "_runtime" / "heartbeat").unlink(missing_ok=True)
            except OSError:
                pass

    async def _heartbeat_loop(self, workspace: Workspace) -> None:
        """每 10s 刷新心跳文件（异常静默，不影响主流程）。"""
        path = workspace.root / "_runtime" / "heartbeat"
        while True:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_now_iso(), encoding="utf-8")
            except OSError:
                log.debug("write heartbeat failed", exc_info=True)
            await asyncio.sleep(10)

    async def _run_workflow_impl(
        self, workspace: Workspace, state: WorkflowState, tmpl: TemplateDef,
        wf_config: WorkflowConfig, workflow_id: str,
    ) -> WorkflowState:
        # 恢复语义：failed 步骤代表「上一轮失败/被打回」，恢复时必须重跑，
        # 否则下面的循环会把它当作已处理而跳过，最终误判为 completed。
        reset_failed = [s.skill_name for s in state.steps if s.status == "failed"]
        for s in state.steps:
            if s.status == "failed":
                s.status = "pending"
                s.error_message = ""
                # 检查点反馈保留在 checkpoint_response 中，供 _build_extra_context 回填

        state.status = "running"
        state.updated_at = _now_iso()
        self._save_state(workspace, state)
        await self._broadcast_log(state, workflow_id, "", "info", "工作流开始执行")
        if reset_failed:
            await self._broadcast_log(
                state, workflow_id, "", "info",
                f"恢复工作流：{', '.join(reset_failed)} 重置为待执行并重跑"
            )

        try:
            # 进程在等待检查点时退出：恢复时先消费落盘决策（不重跑该步）
            if any(s.status == "waiting_checkpoint" for s in state.steps):
                await self._resume_waiting_checkpoints(
                    workspace, state, tmpl, wf_config, workflow_id
                )
                if state.status in ("paused", "failed"):
                    return state

            for idx, step_def in enumerate(tmpl.sub_steps):
                step_state = state.steps[idx]

                # 跳过已完成
                if step_state.status == "completed":
                    continue
                # stale 当作 pending 处理（rerun 级联失效）
                if step_state.status == "stale":
                    step_state.status = "pending"
                # 仍有 failed（理论上归一化后不会出现）：保留失败状态，禁止误判完成
                if step_state.status == "failed":
                    state.status = "failed"
                    state.updated_at = _now_iso()
                    self._save_state(workspace, state)
                    return state

                # 条件分支：when 不满足则跳过该步
                if step_def.when and not _eval_when(step_def.when, state.params):
                    if step_state.status != "skipped":
                        step_state.status = "skipped"
                        step_state.completed_at = _now_iso()
                        state.updated_at = _now_iso()
                        self._save_state(workspace, state)
                        await self._broadcast_log(
                            state, workflow_id, step_def.skill_name, "info",
                            f"步骤跳过（when 条件不满足: {step_def.when}）: {step_def.display_name}"
                        )
                    continue

                # 步骤级超时
                try:
                    await asyncio.wait_for(
                        self._run_single_step(workspace, state, tmpl, wf_config, workflow_id, idx, step_def),
                        timeout=wf_config.step_timeout,
                    )
                except asyncio.TimeoutError:
                    step_state = state.steps[idx]
                    step_state.status = "failed"
                    step_state.error_message = f"步骤超时（{wf_config.step_timeout}s）"
                    state.status = "failed"
                    state.updated_at = _now_iso()
                    self._save_state(workspace, state)
                    await self._broadcast_log(
                        state, workflow_id, step_def.skill_name, "error",
                        f"步骤超时: {step_def.display_name}（{wf_config.step_timeout}s）"
                    )
                    return state

                # 步骤失败则终止（_run_single_step 已设状态）
                if step_state.status == "failed":
                    return state
                # 暂停（检查点打回）
                if state.status == "paused":
                    return state

            # 完成校验：必须所有步骤都是 completed / skipped，
            # 避免 failed/pending 被「循环结束」误判为成功。
            unfinished = [
                s.skill_name for s in state.steps
                if s.status not in ("completed", "skipped")
            ]
            if unfinished:
                state.status = "failed"
                state.current_step = ""
                state.updated_at = _now_iso()
                state.add_log(
                    "", "error",
                    f"工作流未真正完成，以下步骤未完成: {', '.join(unfinished)}"
                )
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, "", "error",
                    f"工作流未完成: {', '.join(unfinished)}"
                )
                return state

            # 全部完成
            state.status = "completed"
            state.current_step = ""
            state.updated_at = _now_iso()
            state.total_cost_usd = state.computed_cost_usd
            self._save_state(workspace, state)
            await self._broadcast_log(
                state, workflow_id, "", "info",
                f"工作流执行完成 (总成本=${state.total_cost_usd:.4f})"
            )
            return state

        except Exception as e:
            log.exception("workflow run failed")
            state.status = "failed"
            state.updated_at = _now_iso()
            state.add_log("", "error", f"工作流异常: {e}")
            self._save_state(workspace, state)
            return state

    async def _run_single_step(
        self, workspace: Workspace, state: WorkflowState, tmpl: TemplateDef,
        wf_config: WorkflowConfig, workflow_id: str, idx: int, step_def: StepDef,
    ) -> None:
        """执行单步（渲染 prompt → agent 循环 → 健康检查分类重试 → 检查点）。"""
        step_state = state.steps[idx]
        state.current_step = step_def.skill_name
        state.updated_at = _now_iso()
        step_state.status = "running"
        step_state.started_at = _now_iso()
        step_state.error_message = ""
        # 本步重新执行：清理上一轮检查点信号（reject 反馈已存 checkpoint_response）
        checkpoint_store.clear(workspace.root, step_def.skill_name)
        # 记录本步开始时的 git HEAD（P3-2 diff 评审的 base）
        if workspace.git_has_repo():
            step_state.base_commit = workspace.git_current_branch() or ""
            # 当前 HEAD hash 作为 base，便于后续 diff base..head
            _, out, _ = workspace._git("rev-parse", "HEAD")
            step_state.base_commit = out.strip() if out.strip() else step_state.base_commit
        self._save_state(workspace, state)
        await self._broadcast_log(
            state, workflow_id, step_def.skill_name, "info",
            f"步骤开始: {step_def.display_name} ({step_def.skill_name})"
        )

        # 健康检查分类重试
        health_error = ""
        max_retries = wf_config.health_retry
        run_result: AgentRunResult | None = None

        # 目录级版本化：记录本步实际使用的 skill 版本
        # step_state.skill_version 已存在（rerun 保留版本）则沿用，否则默认解析
        skill_version = step_state.skill_version or None
        try:
            from .skill_loader import load_skill_meta as _load_meta
            resolved_meta = _load_meta(step_def.skill_name, skill_version)
            step_state.skill_version = resolved_meta.version or ""
        except Exception:
            step_state.skill_version = step_state.skill_version or ""

        for attempt in range(max_retries + 1):
            files = workspace.scan()
            extra_context = self._build_extra_context(state, idx, workspace)

            if attempt > 0:
                # 按失败原因分类生成补全 prompt
                prompt = self._build_retry_prompt(step_def, health_error, workspace, files)
                step_state.retries = attempt
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "warn",
                    f"健康检查失败，启动第 {attempt} 次重试（分类补全）"
                )
                # 重试间退避
                await asyncio.sleep(min(2 * attempt, 5))
            else:
                prompt = render_skill_prompt(
                    skill_name=step_def.skill_name,
                    arguments=state.title,
                    extra_context=extra_context,
                    workspace_files=files,
                    workspace=workspace,
                    version=skill_version,
                )

            # 日志缓冲器
            _log_buf = {"text": ""}

            async def on_output(text: str) -> None:
                _log_buf["text"] += text
                while "\n" in _log_buf["text"]:
                    line, _log_buf["text"] = _log_buf["text"].split("\n", 1)
                    line = line.strip()
                    if line:
                        await self._broadcast_log(
                            state, workflow_id, step_def.skill_name, "progress", line
                        )

            async def on_tool_call(name: str, args: dict) -> None:
                remaining = _log_buf["text"].strip()
                if remaining:
                    await self._broadcast_log(
                        state, workflow_id, step_def.skill_name, "progress", remaining
                    )
                    _log_buf["text"] = ""
                args_preview = json.dumps(args, ensure_ascii=False)[:200]
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "info",
                    f"调用工具: {name}({args_preview})"
                )

            async def on_tool_result(name: str, result: str) -> None:
                preview = result[:200].replace("\n", " ")
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "debug",
                    f"工具结果: {name} -> {preview}"
                )

            iter_limit = wf_config.agent_max_iter if attempt == 0 else min(10, wf_config.agent_max_iter)

            try:
                run_result = await run_agent_loop(
                    llm=self.llm,
                    workspace=workspace,
                    prompt=prompt,
                    max_iter=iter_limit,
                    on_output=on_output,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    inactivity_timeout=wf_config.inactivity_timeout,
                    context_window=self.llm_config.context_window,
                )
            except Exception as e:
                run_result = AgentRunResult(error=str(e))
                log.exception("agent loop failed for step %s", step_def.skill_name)

            step_state.iterations = run_result.iterations
            step_state.tokens = run_result.total_tokens
            step_state.llm_calls = run_result.llm_calls
            step_state.tool_calls = run_result.tool_calls
            step_state.duration_sec += run_result.duration_sec
            step_state.soft_truncated = run_result.soft_truncated
            step_state.output_files = run_result.files_written
            # 成本累计（跨 attempt 累加，重试也消耗 token）
            step_state.prompt_tokens += run_result.prompt_tokens
            step_state.completion_tokens += run_result.completion_tokens
            step_state.cost_usd += self.llm_config.estimate_cost(
                run_result.prompt_tokens, run_result.completion_tokens
            )

            if run_result.error and not run_result.files_written:
                step_state.status = "failed"
                step_state.error_message = run_result.error
                state.status = "failed"
                state.updated_at = _now_iso()
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "error",
                    f"步骤失败: {run_result.error}"
                )
                return

            # 健康检查
            health_ok, health_error, _ = await self._run_health_checks(
                workspace, state, workflow_id, step_def, wf_config
            )
            if health_ok:
                break
            if attempt >= max_retries:
                step_state.status = "failed"
                step_state.error_message = health_error
                state.status = "failed"
                state.updated_at = _now_iso()
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "error",
                    f"健康检查失败（重试 {max_retries} 次仍未通过）: {health_error}"
                )
                # 失败快照
                self._save_failure_snapshot(workspace, step_def.skill_name, health_error)
                return

        # 检查点
        if step_def.has_checkpoint and wf_config.enable_checkpoints and not wf_config.auto_proceed:
            step_state.status = "waiting_checkpoint"
            state.updated_at = _now_iso()
            self._save_state(workspace, state)
            await self._broadcast_log(
                state, workflow_id, step_def.skill_name, "info",
                f"等待检查点确认 (类型: {step_def.checkpoint_type}, "
                f"超时动作: {wf_config.checkpoint_timeout_action})"
            )
            await self._broadcast_event(workflow_id, {
                "event": "checkpoint",
                "workflow_id": workflow_id,
                "step": step_def.skill_name,
                "display_name": step_def.display_name,
                "checkpoint_type": step_def.checkpoint_type,
                "output_files": step_state.output_files,
            })

            response = await wait_checkpoint(
                workflow_id,
                step_def.skill_name,
                timeout=wf_config.checkpoint_timeout,
                timeout_action=wf_config.checkpoint_timeout_action,
            )
            step_state.checkpoint_response = response

            approved = await self._apply_checkpoint_response(
                workspace, state, workflow_id, step_def, step_state, response
            )
            if not approved:
                return

        await self._finalize_step(
            workspace, state, step_def, step_state, wf_config, workflow_id
        )

    async def _apply_checkpoint_response(
        self,
        workspace: Workspace,
        state: WorkflowState,
        workflow_id: str,
        step_def: StepDef,
        step_state: StepState,
        response: dict,
    ) -> bool:
        """应用检查点决策。

        Returns:
            True  —— 放行（approve），调用方继续收尾/下一步
            False —— 打回（reject/revise），已把步骤置 failed、工作流置 paused
        """
        _checkpoint_mgr.clear(workflow_id)

        action = response.get("action", "approve")
        feedback = response.get("feedback", "")
        target_section = response.get("target_section", "")
        severity = response.get("severity", "")
        specific_issues = response.get("specific_issues", [])

        # reject / revise 都打回（暂停工作流），区别在反馈粒度
        if action in ("reject", "revise"):
            # 拼接结构化反馈：总体反馈 + 目标章节 + 严重度 + 具体问题清单
            structured = []
            if feedback:
                structured.append(feedback)
            if target_section:
                structured.append(f"目标章节/文件: {target_section}")
            if severity:
                structured.append(f"严重度: {severity}")
            if specific_issues:
                structured.append("具体问题:")
                for issue in specific_issues:
                    loc = issue.get("file", "")
                    if issue.get("line"):
                        loc += f":{issue['line']}"
                    structured.append(
                        f"  - [{loc}] {issue.get('issue', '')}"
                        f" → 建议: {issue.get('suggestion', '')}"
                    )
            full_feedback = "\n".join(structured) or feedback

            step_state.status = "failed"
            step_state.error_message = f"用户{action}（{severity or '未分级'}）: {feedback[:200]}"
            state.status = "paused"
            state.updated_at = _now_iso()
            if full_feedback:
                workspace.inject_once(
                    f"{action}反馈 - {step_def.skill_name}",
                    full_feedback,
                )
            self._save_state(workspace, state)
            await self._broadcast_log(
                state, workflow_id, step_def.skill_name, "warn",
                f"用户{action}: {full_feedback[:200]}"
            )
            return False

        # approve：用户反馈注入 CONTEXT.md
        if feedback.strip():
            workspace.inject_once(
                f"用户反馈 - {step_def.skill_name}",
                feedback,
            )
            await self._broadcast_log(
                state, workflow_id, step_def.skill_name, "info",
                f"用户反馈已注入: {feedback[:100]}"
            )
        return True

    async def _finalize_step(
        self,
        workspace: Workspace,
        state: WorkflowState,
        step_def: StepDef,
        step_state: StepState,
        wf_config: WorkflowConfig,
        workflow_id: str,
    ) -> None:
        """步骤收尾：写摘要 → 存状态 → git commit → ledger → 广播。

        抽成独立方法，供「正常执行完成」与「恢复时消费已存在的检查点决策」
        两条路径共用，避免恢复路径漏掉 commit / ledger。
        """
        step_state.status = "completed"
        step_state.completed_at = _now_iso()
        state.updated_at = _now_iso()
        self._write_step_summary(workspace, step_def, step_state)
        self._save_state(workspace, state)

        # Git commit（P3-1）：每步完成后提交，message 含 step 名与版本
        commit_short = ""
        if wf_config.enable_git and workspace.git_has_repo():
            commit_msg = (
                f"step: {step_def.skill_name} "
                f"(ver={step_state.skill_version or 'default'}, "
                f"iter={step_state.iterations}, files={len(step_state.output_files)})"
            )
            full_hash = workspace.git_commit(commit_msg)
            if full_hash:
                step_state.commit_hash = full_hash
                commit_short = full_hash[:8]
                state.updated_at = _now_iso()
                self._save_state(workspace, state)

        # Ledger 抗压缩（P1-3）：每步追加结构化记录，rerun 时优先读 ledger
        self._append_ledger(workspace, step_def, step_state, commit_short)

        await self._broadcast_log(
            state, workflow_id, step_def.skill_name, "info",
            f"步骤完成: {step_def.display_name} "
            f"(iter={step_state.iterations}, tokens={step_state.tokens}, "
            f"llm_calls={step_state.llm_calls}, tool_calls={step_state.tool_calls}, "
            f"duration={step_state.duration_sec:.1f}s, "
            f"cost=${step_state.cost_usd:.4f}, "
            f"ver={step_state.skill_version or 'default'}, "
            f"commit={commit_short or 'none'}, "
            f"files={len(step_state.output_files)})"
        )

    async def _resume_waiting_checkpoints(
        self,
        workspace: Workspace,
        state: WorkflowState,
        tmpl: TemplateDef,
        wf_config: WorkflowConfig,
        workflow_id: str,
    ) -> None:
        """恢复「进程退出时正在等待检查点」的步骤。

        优先消费 `_checkpoints/{step}.json` 里已落盘的决策：
        - approve → 直接收尾（不重跑该步，避免重复消耗 token）
        - reject/revise → 打回并暂停（反馈已在文件中）
        - 无决策 → 继续等待，而不是把该步重跑一遍
        """
        for idx, step_state in enumerate(state.steps):
            if step_state.status != "waiting_checkpoint":
                continue
            step_def = tmpl.sub_steps[idx]
            decision = checkpoint_store.read(workspace.root, step_def.skill_name) or {}

            if decision.get("status") == "responded":
                response = normalize_checkpoint_response(decision)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "info",
                    f"恢复：读取到检查点决策 action={response.get('action')}，不重跑该步"
                )
            else:
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "info",
                    "恢复：未发现检查点决策，继续等待确认"
                )
                response = await wait_checkpoint(
                    workflow_id,
                    step_def.skill_name,
                    timeout=wf_config.checkpoint_timeout,
                    timeout_action=wf_config.checkpoint_timeout_action,
                )

            step_state.checkpoint_response = response
            approved = await self._apply_checkpoint_response(
                workspace, state, workflow_id, step_def, step_state, response
            )
            if not approved:
                # resume 的语义是「继续」：打回反馈已注入 CONTEXT.md，
                # 这里直接把步骤重置为待重跑，避免用户还要再 resume 一次。
                step_state.status = "pending"
                step_state.error_message = ""
                state.status = "running"
                state.updated_at = _now_iso()
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "info",
                    "恢复：按打回反馈重跑该步骤"
                )
                continue

            await self._finalize_step(
                workspace, state, step_def, step_state, wf_config, workflow_id
            )

    # === 健康检查 ===

    async def _run_health_checks(
        self,
        workspace: Workspace,
        state: WorkflowState,
        workflow_id: str,
        step_def: StepDef,
        wf_config: WorkflowConfig | None = None,
    ) -> tuple[bool, str, dict]:
        """对当前步骤产出做健康检查。返回 (是否通过, 错误信息, 分类提示)。

        分类提示用于驱动重试 prompt:
          {type: primary_missing|primary_small|companions_missing|syntax_error, detail}
        """
        errors: list[str] = []
        hint: dict = {"type": "", "detail": ""}

        # 1. 主产物大小
        if step_def.primary_output:
            chk = check_primary_output(
                workspace, step_def.primary_output, step_def.min_size
            )
            if not chk.ok:
                if chk.missing:
                    msg = f"主产物检查失败: 缺失 {chk.missing}"
                    hint = {"type": "primary_missing", "detail": f"缺失主产物 {chk.missing}"}
                else:
                    msg = "主产物检查失败: " + "; ".join(chk.errors)
                    hint = {"type": "primary_small", "detail": "; ".join(chk.errors)}
                errors.append(msg)
                state.add_log(step_def.skill_name, "error", msg)
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "error", msg
                )
            else:
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "info",
                    f"主产物检查通过: {step_def.primary_output}"
                )

        # 1b. 非主产物 outputs 检查（如 dev-design 的 DESIGN_SYSTEM.md）
        try:
            from .skill_loader import load_skill_meta as _load_meta
            meta = _load_meta(step_def.skill_name)
            all_outputs = meta.raw.get("outputs", [])
            if isinstance(all_outputs, str):
                all_outputs = [s.strip() for s in all_outputs.strip("[]").split(",") if s.strip()]
            project_type = workspace.detect_project_type()
            secondary_outputs = []
            for out in all_outputs:
                if out == step_def.primary_output:
                    continue
                if out == "DESIGN_SYSTEM.md" and project_type in ("cli", "script"):
                    continue
                secondary_outputs.append(out)
            if secondary_outputs:
                out_chk = check_all_skill_outputs(workspace, secondary_outputs)
                if not out_chk.ok:
                    if out_chk.missing:
                        msg = f"产物检查失败: 缺失 {out_chk.missing}"
                        if not hint["type"]:
                            hint = {"type": "companions_missing", "detail": f"缺失产物: {out_chk.missing}"}
                    else:
                        msg = "产物检查失败: " + "; ".join(out_chk.errors)
                        if not hint["type"]:
                            hint = {"type": "primary_small", "detail": "; ".join(out_chk.errors)}
                    errors.append(msg)
                    state.add_log(step_def.skill_name, "error", msg)
                    self._save_state(workspace, state)
                    await self._broadcast_log(
                        state, workflow_id, step_def.skill_name, "error", msg
                    )
                else:
                    await self._broadcast_log(
                        state, workflow_id, step_def.skill_name, "info",
                        f"全部产物检查通过: {secondary_outputs}"
                    )
        except Exception:
            pass  # skill 元数据加载失败时不阻断主流程

        # 1c. dev-selfcheck 额外检查 SELF_CHECK.md 完成性（防空模板）
        if step_def.skill_name == "dev-selfcheck":
            sc_chk = check_self_check_completeness(workspace)
            if not sc_chk.ok:
                msg = "; ".join(sc_chk.errors)
                errors.append(msg)
                if not hint["type"]:
                    hint = {"type": "primary_small", "detail": msg}
                state.add_log(step_def.skill_name, "error", msg)
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "error", msg
                )
            elif sc_chk.warnings:
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "warn",
                    "; ".join(sc_chk.warnings)
                )

        # 2. 二级文件齐全
        chk = check_step_companions(
            workspace, step_def.skill_name,
            extra_required=step_def.required_companions if not step_def.required_companions_dynamic else None,
        )
        if not chk.ok:
            msg = "二级文件检查失败: "
            if chk.missing:
                msg += f"缺失 {chk.missing}"
                if not hint["type"]:
                    hint = {"type": "companions_missing", "detail": f"缺失二级文件: {chk.missing}"}
            if chk.errors:
                msg += "; " + "; ".join(chk.errors)
            errors.append(msg)
            state.add_log(step_def.skill_name, "error", msg)
            self._save_state(workspace, state)
            await self._broadcast_log(
                state, workflow_id, step_def.skill_name, "error", msg
            )
        else:
            await self._broadcast_log(
                state, workflow_id, step_def.skill_name, "info", "二级文件检查通过"
            )

        # 3. dev-code / dev-selfcheck 额外做代码语法检查
        if step_def.skill_name in ("dev-code", "dev-selfcheck"):
            code_chk = check_all_code_files(workspace)
            if code_chk.errors:
                msg = "代码语法检查失败:\n" + "\n".join(code_chk.errors[:10])
                if len(code_chk.errors) > 10:
                    msg += f"\n... (共 {len(code_chk.errors)} 个错误)"
                state.add_log(step_def.skill_name, "warn", msg)
                self._save_state(workspace, state)
                await self._broadcast_log(
                    state, workflow_id, step_def.skill_name, "warn", msg
                )
                if step_def.skill_name == "dev-code":
                    # dev-code 阶段语法错误不阻断（让 dev-selfcheck 去修）
                    pass
                elif step_def.skill_name == "dev-selfcheck":
                    errors.append(msg)
                    if not hint["type"] or hint["type"] == "":
                        hint = {"type": "syntax_error", "detail": msg}

        # 4. dev-selfcheck：真实执行验证门禁（测试目录 / 测试文件 / 测试通过 / 运行时）
        if step_def.skill_name == "dev-selfcheck" and wf_config is not None:
            gate_mode = getattr(wf_config, "verification_gate", "tests")
            if gate_mode != "off":
                project_type = workspace.detect_project_type()
                report: VerificationReport | None = None
                try:
                    # 默认（tests）只跑测试，不启动生成的项目——避免执行
                    # 生成脚本/后端带来副作用；strict 模式才做运行时验证。
                    report = await run_verification_gate(
                        workspace, project_type,
                        skip_runtime=(gate_mode != "strict"),
                    )
                except Exception as e:
                    msg = f"验证门禁执行异常: {e}"
                    errors.append(msg)
                    if not hint["type"]:
                        hint = {"type": "verification_failed", "detail": msg}
                    state.add_log(step_def.skill_name, "error", msg)
                    self._save_state(workspace, state)
                    await self._broadcast_log(
                        state, workflow_id, step_def.skill_name, "error", msg
                    )

                if report is not None:
                    gate_errors, gate_warnings = _gate_findings(
                        report, strict=(gate_mode == "strict")
                    )
                    for w in gate_warnings:
                        state.add_log(step_def.skill_name, "warn", w)
                        await self._broadcast_log(
                            state, workflow_id, step_def.skill_name, "warn", w
                        )
                    if gate_errors:
                        msg = "验证门禁失败:\n" + "\n".join(gate_errors)
                        errors.append(msg)
                        if not hint["type"]:
                            hint = {"type": "verification_failed", "detail": msg}
                        state.add_log(step_def.skill_name, "error", msg)
                        self._save_state(workspace, state)
                        await self._broadcast_log(
                            state, workflow_id, step_def.skill_name, "error", msg
                        )
                    else:
                        self._save_state(workspace, state)
                        await self._broadcast_log(
                            state, workflow_id, step_def.skill_name, "info",
                            f"验证门禁通过: {report.summary}"
                        )

        return (len(errors) == 0, "\n".join(errors), hint)

    def _build_retry_prompt(
        self, step_def: StepDef, health_error: str,
        workspace: Workspace, files: list[str],
    ) -> str:
        """按健康检查失败原因分类生成补全 prompt。"""
        file_list = "\n".join(f"  - {f}" for f in files) or "  (无)"

        base = (
            f"## 补全任务：上一次执行 {step_def.skill_name} 健康检查未通过\n\n"
            f"### 失败原因\n{health_error}\n\n"
            f"### 当前工作区已有文件\n{file_list}\n\n"
        )

        # 根据失败原因给针对性指令
        if "缺失" in health_error and "主产物" in health_error:
            base += (
                "### 要求\n"
                f"1. 主产物 {step_def.primary_output} 缺失，**立即**用 write_file 写出它\n"
                "2. 不要重新读取已有文件，不要重新扫描\n"
                "3. 写完主产物后立即结束\n"
            )
        elif "主产物检查失败" in health_error:
            base += (
                "### 要求\n"
                f"1. 主产物 {step_def.primary_output} 内容不足，用 read_file 读取现有内容后扩写\n"
                "2. 用 write_file 覆盖写入完整内容（不少于 200 字符）\n"
                "3. 完成后立即结束\n"
            )
        elif "二级文件检查失败" in health_error and "缺失" in health_error:
            base += (
                "### 要求\n"
                "1. 上述缺失的二级文件需要用 write_file 逐个补写\n"
                "2. 不要重新检查已有文件\n"
                "3. 全部补写完成后立即结束\n"
            )
        elif "语法检查失败" in health_error or "语法错误" in health_error:
            base += (
                "### 要求\n"
                "1. 上面的语法错误需要逐个修复：用 read_file 读取报错文件，"
                "用 write_file 覆盖写入修复后的完整文件\n"
                "2. **只修有问题的文件**，不要重写整个项目\n"
                "3. 修复完所有报错后立即结束\n"
            )
        elif "验证门禁失败" in health_error or "验证门禁执行异常" in health_error:
            base += (
                "### 要求\n"
                "1. 测试必须真实通过：用 run_command 执行 pytest / npm test，"
                "并在 SELF_CHECK.md 中贴出 exit_code: 0 的证据\n"
                "2. 缺少测试目录或测试文件时，补写 test_*.py / *.test.js（不要留空壳测试）\n"
                "3. 测试失败时修代码或修测试，**禁止删除断言、跳过用例、伪造通过输出**\n"
                "4. 运行时验证失败（strict 模式）时修启动入口/依赖，然后重新执行验证命令\n"
                "5. 完成后立即结束，不要重写整个项目\n"
            )
        else:
            base += (
                "### 要求\n"
                "1. 立即用 write_file 补写缺失的文件\n"
                "2. 不要重新检查代码，不要重新读取已有文件\n"
                "3. 写完缺失文件后立即结束\n"
            )

        return base

    # === 上下文 ===

    def _build_extra_context(
        self, state: WorkflowState, current_idx: int, workspace: Workspace,
    ) -> str:
        """构建额外上下文：技术栈 + 设计风格 + 上一步摘要 + 当前步打回反馈。"""
        parts: list[str] = []

        params = state.params or {}
        project_type = params.get("project_type", "")
        design_style = params.get("design_style", "")
        design_style_desc = params.get("design_style_desc", "")
        tech_stack = params.get("tech_stack", {})

        if project_type or tech_stack or design_style:
            parts.append("## 项目配置")
            type_map = {
                "fullstack": "全栈 Web 应用（前端+后端+数据库）",
                "frontend_only": "纯前端页面（静态站/交互页面）",
                "backend_only": "纯后端服务（API/服务端）",
                "cli": "命令行工具（CLI 程序）",
                "script": "Python 脚本（自动化/小工具）",
            }
            if project_type:
                parts.append(f"- 项目类型: {type_map.get(project_type, project_type)}")
            if tech_stack:
                ts_lines = []
                for k, v in tech_stack.items():
                    ts_lines.append(f"  - {k}: {v}")
                parts.append("- 技术栈:\n" + "\n".join(ts_lines))
            style_map = {
                "auto": "系统自动（AI 按项目类型选择）",
                "minimal": "极简专业（工具/SaaS 风格）",
                "tech": "科技感（深色/开发者风格）",
                "colorful": "活泼多彩（消费级风格）",
                "elegant": "优雅留白（展示/高端风格）",
                "retro": "复古（怀旧/个性风格）",
                "custom": f"自定义: {design_style_desc}" if design_style_desc else "自定义",
            }
            if design_style:
                parts.append(f"- 设计风格: {style_map.get(design_style, design_style)}")

        # 上一步的结构化摘要
        if current_idx > 0:
            prev = state.steps[current_idx - 1]
            prev_summary = self._read_step_summary(workspace, prev.skill_name)
            if prev_summary:
                parts.append(f"## 上一步（{prev.display_name}）产物摘要\n{prev_summary}")
            elif prev.checkpoint_response and prev.checkpoint_response.get("feedback"):
                parts.append(
                    f"上一步（{prev.display_name}）的用户反馈:\n{prev.checkpoint_response['feedback']}"
                )

        # 当前步的打回反馈（rerun 同一步时回填）
        curr = state.steps[current_idx]
        if curr.checkpoint_response and curr.checkpoint_response.get("feedback"):
            fb = curr.checkpoint_response["feedback"]
            if not curr.checkpoint_response.get("approved", True):
                parts.append(
                    f"## ⚠️ 上轮打回反馈（请重点处理）\n{fb}"
                )

        # Ledger concerns（P1-3）：rerun 时把上轮遗留隐患注入 prompt，
        # 让 LLM 知道上轮哪里出了问题（软截断 / 重试 / 打回），针对性修复。
        if curr.status == "pending" and curr.retries == 0 and curr.iterations == 0:
            # 仅在 rerun 场景（已被重置为 pending 且无运行记录）读 ledger
            ledger_step = self._read_ledger_step(workspace, curr.skill_name)
            if ledger_step:
                lc = ledger_step.get("concerns", "(无)")
                if lc and lc != "(无)":
                    parts.append(
                        f"## ⚠️ 上轮遗留隐患（来自 ledger，请优先解决）\n{lc}"
                    )

        return "\n\n".join(parts) if parts else ""

    # === 步骤摘要 ===

    def _write_step_summary(
        self, workspace: Workspace, step_def: StepDef, step_state: StepState,
    ) -> None:
        """步骤完成后写结构化摘要到 _summaries/{step}.md，供下一步引用。"""
        parts: list[str] = [f"# {step_def.display_name} ({step_def.skill_name}) 产物摘要"]
        parts.append(f"- 主产物: {step_def.primary_output or '(无)'}")
        if step_def.primary_output and workspace.file_exists(step_def.primary_output):
            size = workspace.file_size(step_def.primary_output)
            parts.append(f"- 主产物大小: {size} 字节")
            # 提取 md 章节标题
            try:
                content = workspace.read_file(step_def.primary_output)
                headings = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
                if headings:
                    parts.append("- 主要章节:")
                    for h in headings[:20]:
                        parts.append(f"  - {h}")
            except Exception:
                pass
        if step_state.output_files:
            parts.append("- 产出文件:")
            for f in step_state.output_files:
                parts.append(f"  - {f}")
        parts.append(f"- 指标: iter={step_state.iterations}, tokens={step_state.tokens}, "
                     f"duration={step_state.duration_sec:.1f}s")
        # project_type
        try:
            meta = workspace.read_project_meta()
            if meta:
                parts.append(f"- 项目类型: {meta.project_type}")
        except Exception:
            pass

        summ_dir = workspace.root / "_summaries"
        summ_dir.mkdir(parents=True, exist_ok=True)
        (summ_dir / f"{step_def.skill_name}.md").write_text(
            "\n".join(parts), encoding="utf-8"
        )

    def _read_step_summary(self, workspace: Workspace, skill_name: str) -> str:
        """读取上一步的结构化摘要。"""
        p = workspace.root / "_summaries" / f"{skill_name}.md"
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""

    # === Ledger 抗压缩（P1-3） ===
    #
    # 每步完成后追加一条结构化记录到 _ledger.md，包含 step / status / commits / concerns。
    # rerun 时优先读 ledger 重建上下文，而非从 state.json 推断或重跑扫描。
    # Ledger 是人类可读 + 机器可解析（正则）的 markdown，不会因 state.json 损坏而丢失。

    def _append_ledger(
        self, workspace: Workspace, step_def: StepDef,
        step_state: StepState, commit_short: str,
    ) -> None:
        """追加一条步骤记录到 _ledger.md。

        每条记录包含：step 名 / 版本 / 状态 / 起止时间 / commit / base_commit /
        产出文件 / 指标（iter/tokens/cost）/ concerns（健康检查或打回反馈遗留的隐患）。
        """
        # 提取 concerns：打回反馈 / 软截断 / 重试
        concerns: list[str] = []
        if step_state.soft_truncated:
            concerns.append(f"软截断：达到迭代上限（有 {len(step_state.output_files)} 产出但未经完整验证）")
        if step_state.retries > 0:
            concerns.append(f"健康检查重试 {step_state.retries} 次才通过")
        if step_state.checkpoint_response:
            fb = step_state.checkpoint_response.get("feedback", "")
            sev = step_state.checkpoint_response.get("severity", "")
            if fb and not step_state.checkpoint_response.get("approved", True):
                concerns.append(f"检查点打回（{sev or '未分级'}）: {fb[:120]}")
        if step_state.error_message:
            concerns.append(f"错误信息: {step_state.error_message[:120]}")

        files_list = ", ".join(step_state.output_files) if step_state.output_files else "(无)"
        concerns_text = "\n".join(f"  - {c}" for c in concerns) if concerns else "  (无)"

        entry = (
            f"\n## Step: {step_def.skill_name} (ver={step_state.skill_version or 'default'})\n"
            f"- status: {step_state.status}\n"
            f"- started: {step_state.started_at or '-'}\n"
            f"- completed: {step_state.completed_at or '-'}\n"
            f"- commit: {commit_short or 'none'}\n"
            f"- base_commit: {step_state.base_commit or 'none'}\n"
            f"- files: {files_list}\n"
            f"- metrics: iter={step_state.iterations}, tokens={step_state.tokens}, "
            f"cost=${step_state.cost_usd:.4f}, duration={step_state.duration_sec:.1f}s\n"
            f"- concerns:\n{concerns_text}\n"
        )

        ledger_path = workspace.root / "_ledger.md"
        try:
            existing = ""
            if ledger_path.exists():
                existing = ledger_path.read_text(encoding="utf-8")
                # 同一步重跑时，移除旧记录（整块：header + body），保留其他步骤记录。
                # 旧版用 (?=- |$) 只删 header 行，残留 body（含旧 commit）——改为
                # 匹配到下一个 ## Step: 或字符串末尾。
                pattern = re.compile(
                    r"\n## Step: " + re.escape(step_def.skill_name) + r" \(ver=.*?(?=\n## Step:|\Z)",
                    re.DOTALL,
                )
                existing = pattern.sub("", existing)
            else:
                existing = "# Workflow Ledger\n\n每步完成后的结构化记录，rerun 时优先读取此文件重建上下文。\n"
            ledger_path.write_text(existing + entry, encoding="utf-8")
        except Exception:
            log.debug("append ledger failed", exc_info=True)

    def _read_ledger(self, workspace: Workspace) -> str:
        """读取完整 ledger（供 rerun 重建上下文）。"""
        p = workspace.root / "_ledger.md"
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _read_ledger_step(self, workspace: Workspace, skill_name: str) -> dict:
        """解析指定步骤的 ledger 记录，返回结构化 dict。

        用于 rerun 时快速获取上轮该步的 commit / concerns，无需重跑扫描。
        """
        ledger = self._read_ledger(workspace)
        if not ledger:
            return {}
        # 匹配指定 step 的块
        pattern = re.compile(
            r"## Step: " + re.escape(skill_name) + r" \(ver=(.*?)\)\n(.*?)(?=\n## Step:|$)",
            re.DOTALL,
        )
        m = pattern.search(ledger)
        if not m:
            return {}
        version = m.group(1)
        block = m.group(2)
        result: dict[str, Any] = {"skill_name": skill_name, "version": version}
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                kv = line[2:]
                if ":" in kv:
                    k, _, v = kv.partition(":")
                    result[k.strip()] = v.strip()
        return result

    # === 状态持久化 ===

    def _save_state(self, workspace: Workspace, state: WorkflowState) -> None:
        """原子持久化状态到 state.json，并保留 .bak 备份。"""
        # 先备份现有版本（若存在）
        workspace.backup_file("state.json")
        workspace.write_file_atomic("state.json", state.to_json())

    def _load_state(self, workspace: Workspace) -> WorkflowState:
        """从 state.json 加载状态，损坏时回退 .bak。"""
        if not workspace.file_exists("state.json"):
            # 尝试 .bak
            bak = workspace.root / "state.json.bak"
            if bak.exists():
                log.warning("state.json missing, trying .bak for workflow %s", workspace.workflow_id)
                try:
                    return WorkflowState.from_json(bak.read_text(encoding="utf-8"))
                except Exception as e:
                    log.error("state.json.bak also unparseable: %s", e)
            raise RuntimeError(f"工作流状态不存在: {workspace.workflow_id}")
        try:
            return WorkflowState.from_json(workspace.read_file("state.json"))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            # 损坏 → 尝试 .bak
            log.error("state.json corrupt for %s: %s, trying .bak", workspace.workflow_id, e)
            bak = workspace.root / "state.json.bak"
            if bak.exists():
                try:
                    state = WorkflowState.from_json(bak.read_text(encoding="utf-8"))
                    state.add_log("", "warn", f"state.json 损坏已从 .bak 恢复: {e}")
                    self._save_state(workspace, state)
                    return state
                except Exception:
                    pass
            # 无法恢复
            state = WorkflowState(
                workflow_id=workspace.workflow_id, template="", title="",
                params={}, status="corrupted", created_at=_now_iso(), updated_at=_now_iso(),
            )
            state.add_log("", "error", f"state.json 损坏且无可用备份: {e}")
            return state

    def _save_failure_snapshot(
        self, workspace: Workspace, skill_name: str, error: str,
    ) -> None:
        """步骤失败时保存快照，便于事后排查。"""
        try:
            snap_dir = workspace.root / "_failure_snapshot"
            snap_dir.mkdir(parents=True, exist_ok=True)
            ts = _now_iso().replace(":", "-")
            (snap_dir / f"{skill_name}_{ts}.md").write_text(
                f"# 失败快照: {skill_name}\n\n时间: {_now_iso()}\n\n## 错误\n{error}\n",
                encoding="utf-8",
            )
        except Exception:
            log.debug("save failure snapshot failed", exc_info=True)

    async def _broadcast_log(
        self, state: WorkflowState, workflow_id: str,
        step: str, level: str, message: str,
    ) -> None:
        """记录日志、落盘 run.log、并广播。"""
        state.add_log(step, level, message)
        # 落盘 run.log（append，崩溃后可查）
        try:
            log_path = Workspace(workflow_id).root / "run.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{_now_iso()}] [{level}] [{step}] {message}\n")
        except Exception:
            pass
        await self._broadcast_event(workflow_id, {
            "event": "log",
            "workflow_id": workflow_id,
            "step": step,
            "level": level,
            "message": message,
            "timestamp": _now_iso(),
        })

    async def _broadcast_event(self, workflow_id: str, event: dict) -> None:
        await _broadcast.broadcast(event)

    # === 查询 ===

    def get_state(self, workflow_id: str) -> WorkflowState | None:
        """获取工作流状态。"""
        workspace = Workspace(workflow_id)
        if not workspace.file_exists("state.json"):
            return None
        return self._load_state(workspace)

    def list_workflows(self) -> list[dict]:
        """列出所有工作流（基本信息）。"""
        result: list[dict] = []
        if not WORKSPACES_DIR.exists():
            return result
        for d in sorted(WORKSPACES_DIR.iterdir()):
            if not d.is_dir():
                continue
            state_file = d / "state.json"
            if not state_file.exists():
                continue
            try:
                state = WorkflowState.from_json(state_file.read_text(encoding="utf-8"))
                result.append({
                    "workflow_id": state.workflow_id,
                    "template": state.template,
                    "title": state.title,
                    "status": state.status,
                    "current_step": state.current_step,
                    "created_at": state.created_at,
                    "updated_at": state.updated_at,
                })
            except Exception as e:
                log.warning("failed to load workflow state %s: %s", d.name, e)
        return result

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流（包括工作区目录）。"""
        import shutil
        workspace = Workspace(workflow_id)
        if not workspace.root.exists():
            return False
        shutil.rmtree(workspace.root, ignore_errors=True)
        _checkpoint_mgr.clear(workflow_id)
        return True

    async def rerun_step(
        self, workflow_id: str, skill_name: str,
        clean: bool = False, latest: bool = False,
    ) -> WorkflowState:
        """重新执行单个步骤。

        Args:
            clean: 若 True，先清理该步主产物（避免残留干扰）。
                   注意：dev-code 的 code/ 目录不整体清空，只清主产物 RUN.md，
                   避免删掉已生成的代码。
            latest: 若 True，重置 skill_version 为空，使 _run_single_step 重新解析
                    到最新版本目录（版本升级场景）。默认 False 沿用原版本。

        改进：rerun 后把后续所有步骤标记为 stale，run_workflow 遇到 stale 自动重跑。
        """
        workspace = Workspace(workflow_id)
        state = self._load_state(workspace)
        tmpl = load_template(state.template)

        # 找到步骤索引
        target_idx = -1
        for i, s in enumerate(state.steps):
            if s.skill_name == skill_name:
                target_idx = i
                break
        if target_idx < 0:
            return state

        step_def = tmpl.sub_steps[target_idx]

        # 清理主产物
        if clean and step_def.primary_output and workspace.file_exists(step_def.primary_output):
            try:
                (workspace.root / step_def.primary_output).unlink()
            except OSError:
                pass

        # 重置当前步
        s = state.steps[target_idx]
        s.status = "pending"
        s.started_at = None
        s.completed_at = None
        s.error_message = ""
        s.output_files = []
        s.checkpoint_response = None
        s.iterations = 0
        s.tokens = 0
        s.llm_calls = 0
        s.tool_calls = 0
        s.duration_sec = 0.0
        s.retries = 0
        s.soft_truncated = False
        # 成本与版本字段重置
        s.prompt_tokens = 0
        s.completion_tokens = 0
        s.cost_usd = 0.0
        # Git 字段重置
        s.commit_hash = ""
        s.base_commit = ""

        # 清理检查点信号：目标步骤及后续 stale 步骤会重新执行，
        # 旧决策（approve/reject）不能再次生效。
        _checkpoint_mgr.clear(workflow_id)
        for j in range(target_idx, len(state.steps)):
            checkpoint_store.clear(workspace.root, state.steps[j].skill_name)

        # Git 分支隔离（P3-1）：rerun 新建分支，失败可回滚到原分支
        if workspace.git_has_repo():
            ts = _now_iso().replace(":", "-").replace("T", "-")
            branch_name = f"rerun/{skill_name}/{ts}"
            if workspace.git_create_branch(branch_name):
                state.add_log(skill_name, "info", f"rerun: 已切换到分支 {branch_name}")
            else:
                state.add_log(skill_name, "warn", "rerun: git 分支创建失败，在原分支继续")

        # Ledger 读取（P1-3）：把上轮该步的 concerns 注入日志，供 rerun 上下文参考
        prev_ledger = self._read_ledger_step(workspace, skill_name)
        if prev_ledger:
            prev_concerns = prev_ledger.get("concerns", "(无)")
            prev_commit = prev_ledger.get("commit", "none")
            prev_ver = prev_ledger.get("version", "default")
            state.add_log(skill_name, "info",
                          f"rerun: 上轮 ledger 记录 ver={prev_ver}, commit={prev_commit}")
            if prev_concerns and prev_concerns != "(无)":
                state.add_log(skill_name, "warn",
                              f"rerun: 上轮 concerns:\n{prev_concerns}")

        if latest:
            # 清空版本，_run_single_step 会重新解析到最新版本目录
            s.skill_version = ""
            # 探测最新版本并记录到日志
            try:
                from .skill_loader import list_skill_versions
                versions = list_skill_versions(skill_name)
                if versions:
                    state.add_log(skill_name, "info",
                                  f"rerun --latest: 将从 {skill_name} 升级到版本 {versions[0]}")
                else:
                    state.add_log(skill_name, "info",
                                  f"rerun --latest: {skill_name} 无版本目录，沿用平铺布局")
            except Exception:
                pass

        # 后续步骤标记 stale（级联失效）
        for j in range(target_idx + 1, len(state.steps)):
            state.steps[j].status = "stale"

        state.status = "running"
        self._save_state(workspace, state)
        return await self.run_workflow(workflow_id)

    async def close(self) -> None:
        if self._llm:
            await self._llm.close()
