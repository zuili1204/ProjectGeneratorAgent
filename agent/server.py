"""可选的 FastAPI 服务：提供 REST API + WebSocket 实时日志。

启动：
    python -m agent.server --host 127.0.0.1 --port 8000

主要端点：
    POST   /api/workflows                 创建工作流
    POST   /api/workflows/{id}/start      启动工作流（异步后台执行）
    GET    /api/workflows                 列出工作流
    GET    /api/workflows/{id}            查看工作流详情
    DELETE /api/workflows/{id}            删除工作流
    POST   /api/workflows/{id}/checkpoint 提交检查点响应
    POST   /api/workflows/{id}/rerun/{skill} 重跑某步骤
    GET    /api/templates                 列出模板
    GET    /api/skills                    列出 skills
    GET    /api/config                    查看配置
    PUT    /api/config                    更新配置
    GET    /api/health                    健康检查
    WS     /ws/workflows/{id}             WebSocket 实时日志

设计要点：
- 工作流运行在 asyncio.Task 后台任务中
- WebSocket 通过 BroadcastManager 广播日志（按 workflow_id 过滤）
- 检查点响应通过 submit_checkpoint 提交，自动唤醒等待中的工作流
"""
from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request, Depends, Header
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from rich.logging import RichHandler

from .config import (
    LLMConfig, WorkflowConfig, PROJECT_ROOT, WORKSPACES_DIR,
    _load_user_config, set_user_config, _config_path, _config_path as _user_config_path,
)
from .workflow_engine import (
    WorkflowEngine, WorkflowState,
    list_templates, load_template,
    submit_checkpoint, set_broadcast, unsubscribe_broadcast,
)
from .skill_loader import list_skills
from .workspace import Workspace

# Web 前端目录
WEB_DIR = PROJECT_ROOT / "web"

log = logging.getLogger("pga.server")

# === 全局状态 ===
# 运行中的工作流任务（workflow_id -> asyncio.Task）
_running_tasks: dict[str, asyncio.Task] = {}

# 并发信号量（限制同时运行的工作流数，防 LLM 限流）
_concurrency_sem: asyncio.Semaphore | None = None


def _get_concurrency_sem() -> asyncio.Semaphore:
    """懒初始化并发信号量（需在 event loop 内调用）。"""
    global _concurrency_sem
    if _concurrency_sem is None:
        cfg = _load_user_config()
        max_wf = int(cfg.get("server_max_concurrent_workflows", 2))
        _concurrency_sem = asyncio.Semaphore(max_wf)
    return _concurrency_sem


# === 安全配置 ===

# 受保护的文件/目录：/api/workflows/{id}/files/{path} 端点禁止读取
# 避免泄露 state.json（含完整日志）、运行时元数据、失败快照等
_PROTECTED_FILE_PATTERNS = (
    "state.json", "state.json.bak", "state.json.tmp",
    "project.json",
    "run.log",
    "CONTEXT.md",
    "_summaries/*",
    "_failure_snapshot/*",
)


def _is_protected_path(rel_path: str) -> bool:
    """判断相对路径是否命中受保护文件模式。"""
    # 规范化：去掉前导 ./
    p = rel_path.lstrip("./")
    for pat in _PROTECTED_FILE_PATTERNS:
        if fnmatch.fnmatch(p, pat):
            return True
    return False


def _get_allowed_origins() -> list[str]:
    """获取 CORS 允许的来源。

    默认仅允许本机回环；可通过 config.json 的 server_allowed_origins 扩展。
    支持 shell 通配符（如 http://localhost:*）。
    """
    cfg = _load_user_config()
    origins = cfg.get("server_allowed_origins", "")
    if isinstance(origins, list):
        return [str(o) for o in origins]
    if isinstance(origins, str) and origins.strip():
        return [o.strip() for o in origins.split(",") if o.strip()]
    # 默认：仅本机回环（覆盖前后端分离开发场景）
    return ["http://localhost:*", "http://127.0.0.1:*"]


def _origin_allowed(origin: str, patterns: list[str]) -> bool:
    """检查 Origin 是否匹配任一通配符模式。"""
    return any(fnmatch.fnmatch(origin, pat) for pat in patterns)


def _get_server_token() -> str:
    """获取或生成本地服务 token。

    首次调用时生成随机 token 并写入 ~/.project_generator/server_token，
    后续从该文件读取。客户端需在 Authorization: Bearer <token> 头中携带。
    绑定 127.0.0.1 已是基础防护，token 是第二层。
    """
    token_path = _user_config_path().parent / "server_token"
    try:
        if token_path.exists():
            tok = token_path.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        tok = secrets.token_urlsafe(32)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(tok, encoding="utf-8")
        # 尽量限制文件权限（Windows 上 chmod 行为有限，忽略报错）
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
        return tok
    except (OSError, PermissionError) as e:
        log.warning("cannot persist server token, generating ephemeral: %s", e)
        return secrets.token_urlsafe(32)


def _require_auth(authorization: str = Header(default="")) -> None:
    """FastAPI 依赖：校验 Bearer token。

    除非 token 为空（未启用），否则要求 Authorization 头匹配。
    """
    if not _SERVER_TOKEN:
        return
    expected = f"Bearer {_SERVER_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="未授权：缺少或错误的 Authorization 头")


# 进程级 token（create_app 时初始化，避免每个请求读文件）
_SERVER_TOKEN: str = ""


def _detect_zombie_workflows() -> list[str]:
    """启动时扫描 status=running 但进程已不存在的工作流，标记为 interrupted。

    返回被标记的 workflow_id 列表。这是「僵尸任务检测」：
    server 上次被 kill 后，state.json 里残留 running 状态的工作流
    再也无法被恢复（协程已死），需要显式标记让用户 resume 或 delete。
    """
    zombies: list[str] = []
    if not WORKSPACES_DIR.exists():
        return zombies
    for d in WORKSPACES_DIR.iterdir():
        if not d.is_dir():
            continue
        state_file = d / "state.json"
        if not state_file.exists():
            continue
        try:
            state = WorkflowState.from_json(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if state.status == "running":
            # 没有任何活的后台任务持有它 → 可能僵尸。
            # 但必须先看心跳：CLI 进程可能在另一个终端里正常跑着，
            # 直接标 interrupted 会把活任务误判为僵尸。
            if state.workflow_id not in _running_tasks:
                hb = d / "_runtime" / "heartbeat"
                if hb.exists():
                    try:
                        if time.time() - hb.stat().st_mtime < 120:
                            continue  # 心跳新鲜，另一个进程仍在运行
                    except OSError:
                        pass
                state.status = "interrupted"
                state.add_log("", "warn", "服务重启检测到僵尸状态，已标记为 interrupted（可 resume 或 delete）")
                state.updated_at = _now_iso_for_server()
                try:
                    WorkflowEngine()._save_state(Workspace(state.workflow_id), state)
                    zombies.append(state.workflow_id)
                except Exception as e:
                    log.warning("failed to mark zombie %s: %s", state.workflow_id, e)
    return zombies


def _now_iso_for_server() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# === Pydantic 模型 ===

class CreateWorkflowRequest(BaseModel):
    title: str = Field(..., description="一句话需求")
    template: str = Field("grad_project", description="模板 key")
    project_type: str = Field("fullstack", description="项目类型: fullstack/frontend_only/cli/script")
    design_style: str = Field("auto", description="设计风格: auto/minimal/tech/colorful/elegant/retro/custom")
    design_style_desc: str = Field("", description="自定义设计风格描述（design_style=custom 时生效）")
    tech_stack: dict = Field(default_factory=dict, description="技术栈选项: frontend_framework/backend_framework/database/language")
    auto_proceed: bool = Field(False, description="自动继续")
    enable_checkpoints: bool = Field(True, description="开启检查点")
    enable_review: bool = Field(False, description="启用 dev-review 评审步骤（需模板支持）")
    verification_gate: str = Field("tests", description="dev-selfcheck 验证门禁: strict/tests/off")
    ui_gate: str = Field("block", description="静态 UI 质量门: block/warn/off")
    max_iter: int = Field(50, description="agent 最大迭代次数")


class CheckpointRequest(BaseModel):
    """检查点响应（结构化 schema，向后兼容旧版 approved 字段）。

    新版用 action 表达意图：
      - approve: 通过，工作流继续
      - reject: 打回，暂停工作流
      - revise: 打回并给出精准修改指引（target_section + specific_issues）
    旧版 approved=true/false 仍兼容（内部归一化为 action）。
    """
    # 新版字段
    action: str = Field("", description="approve|reject|revise（优先于 approved）")
    feedback: str = Field("", description="总体反馈内容")
    target_section: str = Field("", description="指定要修改的文件/章节（revise 用）")
    severity: str = Field("", description="blocker|major|minor|nit")
    specific_issues: list = Field(default_factory=list, description="具体问题清单 [{file,line,issue,suggestion}]")
    # 旧版兼容字段
    approved: bool | None = Field(None, description="旧版：是否通过（action 为空时使用）")
    run: bool = Field(True, description="提交后是否自动恢复工作流（仅 approve 生效）")


class ConfigUpdate(BaseModel):
    key: str
    value: str


# === FastAPI 应用 ===

def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    app = FastAPI(
        title="Project Generator Agent",
        description="一句话生成项目的智能体服务",
        version="1.0.0",
    )

    # 初始化进程级 token（首启写入 ~/.project_generator/server_token）
    global _SERVER_TOKEN
    cfg = _load_user_config()
    # 配置 server_enable_auth=false 可关闭 token 认证（仅本机回环时可选）
    if cfg.get("server_enable_auth", "true") in ("true", "1", "yes", True):
        _SERVER_TOKEN = _get_server_token()
        log.info("server token auth enabled (token at ~/.project_generator/server_token)")
    else:
        _SERVER_TOKEN = ""

    # CORS 白名单：默认仅本机回环，可通过 server_allowed_origins 扩展
    # 用通配符匹配，避免硬编码端口
    allowed_patterns = _get_allowed_origins()

    @app.middleware("http")
    async def cors_and_origin_check(request: Request, call_next):
        origin = request.headers.get("origin", "")
        # 非浏览器请求（无 Origin 头）放行（CLI/curl 等）
        if origin and not _origin_allowed(origin, allowed_patterns):
            return JSONResponse(
                status_code=403,
                content={"detail": f"Origin {origin} 不在 CORS 白名单"},
            )
        response = await call_next(request)
        if origin and _origin_allowed(origin, allowed_patterns):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        return response

    # OPTIONS 预检快速返回
    @app.options("/api/{path:path}")
    async def options_handler(path: str):
        return {"detail": "ok"}

    # 启动事件：僵尸任务检测
    @app.on_event("startup")
    async def _on_startup() -> None:
        try:
            zombies = _detect_zombie_workflows()
            if zombies:
                log.warning("检测到 %d 个僵尸工作流（已标记 interrupted）: %s",
                            len(zombies), ", ".join(zombies))
        except Exception:
            log.debug("zombie detection failed", exc_info=True)

    # === 健康检查 ===
    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "templates": list_templates(),
            "skills": list_skills(),
            "running_workflows": list(_running_tasks.keys()),
        }

    # === 工作流 CRUD ===

    @app.post("/api/workflows")
    async def create_workflow(req: CreateWorkflowRequest, _: None = Depends(_require_auth)) -> dict:
        """创建工作流（不立即启动）。"""
        if req.template not in list_templates():
            raise HTTPException(status_code=400, detail=f"模板不存在: {req.template}")

        # 校验 LLM 配置
        try:
            llm_config = LLMConfig.from_env()
            llm_config.validate()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        wf_config = WorkflowConfig.from_dict({
            "agent_max_iter": req.max_iter,
            "enable_checkpoints": req.enable_checkpoints,
            "auto_proceed": req.auto_proceed,
            "project_type": req.project_type,
            "verification_gate": req.verification_gate,
            "ui_gate": req.ui_gate,
        })
        engine = WorkflowEngine(llm_config=llm_config, workflow_config=wf_config)
        workflow_id = engine.create_workflow(
            template_key=req.template,
            title=req.title,
            params={
                "project_type": req.project_type,
                "design_style": req.design_style,
                "design_style_desc": req.design_style_desc,
                "tech_stack": req.tech_stack,
                "enable_checkpoints": req.enable_checkpoints,
                "auto_proceed": req.auto_proceed,
                "enable_review": req.enable_review,
                "verification_gate": req.verification_gate,
                "ui_gate": req.ui_gate,
            },
        )
        return {
            "workflow_id": workflow_id,
            "status": "pending",
            "message": f"工作流已创建，调用 POST /api/workflows/{workflow_id}/start 启动",
        }

    @app.post("/api/workflows/{workflow_id}/start")
    async def start_workflow(workflow_id: str, background_tasks: BackgroundTasks, _: None = Depends(_require_auth)) -> dict:
        """启动工作流（异步后台执行）。"""
        engine = WorkflowEngine()
        state = engine.get_state(workflow_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        if state.status == "running":
            raise HTTPException(status_code=400, detail="工作流正在运行中")
        if workflow_id in _running_tasks:
            raise HTTPException(status_code=400, detail="工作流已有后台任务在运行")

        # 启动后台任务
        task = asyncio.create_task(_run_workflow_background(workflow_id))
        _running_tasks[workflow_id] = task
        return {"workflow_id": workflow_id, "status": "running"}

    @app.get("/api/workflows")
    async def list_workflows(_: None = Depends(_require_auth)) -> dict:
        """列出所有工作流。"""
        engine = WorkflowEngine()
        return {"workflows": engine.list_workflows()}

    @app.get("/api/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, _: None = Depends(_require_auth)) -> dict:
        """查看工作流详情。"""
        engine = WorkflowEngine()
        state = engine.get_state(workflow_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        return json.loads(state.to_json())

    @app.get("/api/workflows/{workflow_id}/files")
    async def list_workflow_files(workflow_id: str, _: None = Depends(_require_auth)) -> dict:
        """列出工作流工作区的文件。"""
        from .workspace import Workspace
        ws = Workspace(workflow_id)
        if not ws.root.exists():
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        files = ws.scan()
        return {
            "workflow_id": workflow_id,
            "files": [{"path": f, "size": ws.file_size(f)} for f in files],
        }

    @app.get("/api/workflows/{workflow_id}/files/{file_path:path}")
    async def read_workflow_file(workflow_id: str, file_path: str, _: None = Depends(_require_auth)) -> dict:
        """读取工作流工作区中的文件内容。

        安全：受保护文件（state.json / project.json / run.log / _summaries / 等）
        禁止通过此端点读取，避免泄露运行时元数据。
        """
        from .workspace import Workspace
        # 受保护文件检查（先于 path traversal 检查，避免绕过）
        if _is_protected_path(file_path):
            raise HTTPException(status_code=403, detail=f"受保护文件，禁止读取: {file_path}")
        ws = Workspace(workflow_id)
        if not ws.file_exists(file_path):
            raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")
        try:
            content = ws.read_file(file_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"path": file_path, "content": content, "size": len(content)}

    @app.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str, _: None = Depends(_require_auth)) -> dict:
        """删除工作流。"""
        # 取消运行中的任务
        task = _running_tasks.pop(workflow_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        engine = WorkflowEngine()
        ok = engine.delete_workflow(workflow_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")
        return {"deleted": workflow_id}

    @app.get("/api/workflows/{workflow_id}/export")
    async def export_workflow(workflow_id: str, _: None = Depends(_require_auth)):
        """导出工作区所有文件为 zip。"""
        import io
        import zipfile
        ws_dir = WORKSPACES_DIR / workflow_id
        if not ws_dir.exists():
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in ws_dir.rglob("*"):
                if p.is_file():
                    arcname = p.relative_to(ws_dir)
                    zf.write(p, arcname)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={workflow_id}.zip"},
        )

    # === 检查点 ===

    @app.post("/api/workflows/{workflow_id}/checkpoint")
    async def submit_checkpoint_response(workflow_id: str, req: CheckpointRequest, _: None = Depends(_require_auth)) -> dict:
        """提交检查点响应（结构化 schema，向后兼容）。

        新版用 action=approve|reject|revise；旧版 approved=true/false 仍兼容。
        approve 时自动恢复工作流（除非 run=false）；reject/revise 仅打回不恢复。
        """
        engine = WorkflowEngine()
        state = engine.get_state(workflow_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")

        waiting_step = next(
            (s.skill_name for s in state.steps if s.status == "waiting_checkpoint"), ""
        )
        if not waiting_step:
            raise HTTPException(status_code=400, detail="工作流当前不在等待检查点")

        # 构造提交载荷：新版 action 优先，回退旧版 approved
        if req.action:
            payload = {
                "action": req.action,
                "feedback": req.feedback,
                "target_section": req.target_section,
                "severity": req.severity,
                "specific_issues": req.specific_issues,
            }
            is_approve = req.action == "approve"
        else:
            # 旧版兼容
            approved = bool(req.approved) if req.approved is not None else True
            payload = {"approved": approved, "feedback": req.feedback}
            is_approve = approved

        submit_checkpoint(workflow_id, payload, step=waiting_step)

        # 自动恢复（仅当 approve 且 run=true）
        if is_approve and req.run:
            if workflow_id not in _running_tasks or _running_tasks[workflow_id].done():
                task = asyncio.create_task(_run_workflow_background(workflow_id))
                _running_tasks[workflow_id] = task

        return {
            "workflow_id": workflow_id,
            "action": req.action or ("approve" if (req.approved if req.approved is not None else True) else "reject"),
            "feedback": req.feedback,
            "target_section": req.target_section,
            "severity": req.severity,
            "resumed": is_approve and req.run,
        }

    # === 重跑 ===

    @app.post("/api/workflows/{workflow_id}/rerun/{skill_name}")
    async def rerun_step(workflow_id: str, skill_name: str, clean: bool = False, latest: bool = False, _: None = Depends(_require_auth)) -> dict:
        """重跑某步骤。

        Query 参数：
          clean=true  先清理该步主产物（避免残留干扰）
          latest=true 升级到最新 skill 版本目录（版本升级场景）
        """
        engine = WorkflowEngine()
        state = engine.get_state(workflow_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"工作流不存在: {workflow_id}")

        valid_skills = [s.skill_name for s in state.steps]
        if skill_name not in valid_skills:
            raise HTTPException(
                status_code=400,
                detail=f"无效 skill: {skill_name}（可选: {', '.join(valid_skills)}）"
            )

        if workflow_id in _running_tasks and not _running_tasks[workflow_id].done():
            raise HTTPException(status_code=400, detail="工作流已有后台任务在运行")

        # rerun_step 会把目标步骤标记为 pending，然后从该步骤继续
        task = asyncio.create_task(_rerun_step_background(workflow_id, skill_name, clean, latest))
        _running_tasks[workflow_id] = task
        return {"workflow_id": workflow_id, "rerun": skill_name, "clean": clean, "latest": latest, "status": "running"}

    # === 模板 / Skills ===

    @app.get("/api/templates")
    async def get_templates() -> dict:
        """列出所有可用模板。"""
        result = []
        for key in list_templates():
            try:
                tmpl = load_template(key)
                result.append({
                    "key": key,
                    "name": tmpl.name,
                    "default_project_type": tmpl.default_project_type,
                    "sub_steps": [
                        {
                            "skill_name": s.skill_name,
                            "display_name": s.display_name,
                            "has_checkpoint": s.has_checkpoint,
                            "primary_output": s.primary_output,
                        }
                        for s in tmpl.sub_steps
                    ],
                })
            except Exception as e:
                log.warning("load template %s failed: %s", key, e)
        return {"templates": result}

    @app.get("/api/skills")
    async def get_skills() -> dict:
        """列出所有可用 skills。"""
        return {"skills": list_skills()}

    # === 配置 ===

    @app.get("/api/config")
    async def get_config(_: None = Depends(_require_auth)) -> dict:
        """查看配置（API Key 会脱敏）。"""
        cfg = _load_user_config()
        safe = {}
        for k, v in cfg.items():
            if "key" in k.lower() and isinstance(v, str) and len(v) > 12:
                safe[k] = v[:6] + "..." + v[-4:]
            else:
                safe[k] = v
        return {"config": safe, "path": str(_config_path())}

    @app.put("/api/config")
    async def update_config(req: ConfigUpdate, _: None = Depends(_require_auth)) -> dict:
        """更新单个配置项。"""
        set_user_config(req.key, req.value)
        return {"updated": {req.key: req.value}}

    # === WebSocket ===

    @app.websocket("/ws/workflows/{workflow_id}")
    async def workflow_ws(websocket: WebSocket, workflow_id: str) -> None:
        """WebSocket 实时日志推送。

        客户端连接后会收到该 workflow_id 的所有日志事件，
        包括 log/checkpoint/start/finish 事件。

        连接关闭时主动 unsubscribe，避免回调泄漏导致已关闭 WS 仍被广播
        触发（旧实现 finally 里 pass，长期运行会堆积死回调）。

        认证：浏览器 WebSocket 无法设置 Authorization 头，token 通过
        `?token=` 查询参数传递；同时校验 Origin，避免任意网页连上本地服务。
        """
        origin = websocket.headers.get("origin", "")
        if origin and not _origin_allowed(origin, allowed_patterns):
            log.warning("WebSocket rejected: origin %s not allowed", origin)
            await websocket.close(code=1008)
            return
        if _SERVER_TOKEN and websocket.query_params.get("token", "") != _SERVER_TOKEN:
            log.warning("WebSocket rejected: missing/invalid token (workflow=%s)", workflow_id)
            await websocket.close(code=1008)
            return

        await websocket.accept()
        log.info("WebSocket connected: workflow_id=%s", workflow_id)

        # 创建按 workflow_id 过滤的广播回调
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            if event.get("workflow_id") == workflow_id:
                await queue.put(event)

        set_broadcast(on_event)
        subscribed = True

        try:
            # 发送当前状态快照
            engine = WorkflowEngine()
            state = engine.get_state(workflow_id)
            if state:
                await websocket.send_json({
                    "event": "snapshot",
                    "workflow_id": workflow_id,
                    "state": json.loads(state.to_json()),
                })
            else:
                await websocket.send_json({
                    "event": "error",
                    "message": f"工作流不存在: {workflow_id}",
                })
                await websocket.close()
                return

            # 持续推送事件
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                    # 工作流结束事件 → 关闭连接
                    if event.get("event") == "log" and "工作流执行完成" in event.get("message", ""):
                        await websocket.send_json({"event": "finished", "workflow_id": workflow_id})
                        break
                    if event.get("event") == "log" and "工作流失败" in event.get("message", ""):
                        await websocket.send_json({"event": "failed", "workflow_id": workflow_id})
                        break
                except asyncio.TimeoutError:
                    # 心跳保活
                    await websocket.send_json({"event": "heartbeat"})
        except WebSocketDisconnect:
            log.info("WebSocket disconnected: workflow_id=%s", workflow_id)
        except Exception as e:
            log.exception("WebSocket error: workflow_id=%s", workflow_id)
            try:
                await websocket.send_json({"event": "error", "message": str(e)})
            except Exception:
                pass
        finally:
            # 主动退订，避免死回调堆积（修复旧实现 finally 里 pass 的问题）
            if subscribed:
                try:
                    unsubscribe_broadcast(on_event)
                except Exception:
                    log.debug("unsubscribe failed", exc_info=True)

    # === 前端静态文件 ===
    if WEB_DIR.exists():
        # 挂载静态资源（CSS/JS/图片）
        assets_dir = WEB_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        # 根路径 → index.html
        @app.get("/", response_class=HTMLResponse)
        async def index_page() -> HTMLResponse:
            return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))

        # 工作流详情页
        @app.get("/workflow.html", response_class=HTMLResponse)
        async def workflow_page() -> HTMLResponse:
            return HTMLResponse((WEB_DIR / "workflow.html").read_text(encoding="utf-8"))

        # 设置页
        @app.get("/settings.html", response_class=HTMLResponse)
        async def settings_page() -> HTMLResponse:
            return HTMLResponse((WEB_DIR / "settings.html").read_text(encoding="utf-8"))

        log.info("web frontend mounted at %s", WEB_DIR)
    else:
        log.warning("web directory not found: %s (frontend disabled)", WEB_DIR)

    # 项目图标（在项目根目录）
    icon_path = PROJECT_ROOT / "icon.png"
    if icon_path.exists():
        @app.get("/icon.png")
        async def icon_file():
            return FileResponse(str(icon_path), media_type="image/png")

    return app


# === 后台任务 ===

async def _run_workflow_background(workflow_id: str) -> None:
    """后台运行工作流。

    使用全局并发信号量限制同时运行的工作流数（默认 2，可配
    server_max_concurrent_workflows），避免并发打多个 LLM 请求触发限流。
    """
    sem = _get_concurrency_sem()
    async with sem:
        engine = WorkflowEngine()
        try:
            state = await engine.run_workflow(workflow_id)
            log.info("workflow %s finished: status=%s", workflow_id, state.status)
        except Exception as e:
            log.exception("workflow %s failed", workflow_id)
        finally:
            await engine.close()
            _running_tasks.pop(workflow_id, None)


async def _rerun_step_background(workflow_id: str, skill_name: str, clean: bool = False, latest: bool = False) -> None:
    """后台重跑某步骤。"""
    sem = _get_concurrency_sem()
    async with sem:
        engine = WorkflowEngine()
        try:
            state = await engine.rerun_step(workflow_id, skill_name, clean=clean, latest=latest)
            log.info("workflow %s rerun %s finished: status=%s", workflow_id, skill_name, state.status)
        except Exception as e:
            log.exception("workflow %s rerun %s failed", workflow_id, skill_name)
        finally:
            await engine.close()
            _running_tasks.pop(workflow_id, None)


# === 入口 ===

def main(argv: list[str] | None = None) -> int:
    """启动 FastAPI 服务。"""
    parser = argparse.ArgumentParser(prog="pga-server", description="Project Generator Agent Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", "-p", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="热重载（开发用）")
    parser.add_argument("--log-level", default="info",
                        choices=["debug", "info", "warning", "error"])
    args = parser.parse_args(argv)

    # 配置日志
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # 启动服务
    import uvicorn
    app = create_app()
    log.info("starting server at http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
