"""检查点落盘存储：让检查点信号跨进程生效。

背景：检查点原实现基于进程内 ``asyncio.Event``，而 ``pga approve`` 是独立进程，
无法唤醒另一个进程里阻塞等待的工作流。本模块把「请求」与「响应」都写到
工作区的 ``_checkpoints/{step}.json``：

- 运行中的工作流写 ``status=waiting``，随后轮询该文件；
- ``pga approve/reject/revise`` 只写 ``status=responded`` 并退出；
- 运行进程读到 responded 即继续，实现跨进程握手。

文件 schema::

    {
      "step": "dev-code",
      "status": "waiting | responded | consumed | timeout",
      "timeout_action": "auto_reject",
      "created_at": "2026-10-31T11:40:00",
      "responded_at": "",
      "consumed_at": "",
      "action": "approve | reject | revise",
      "feedback": "",
      "target_section": "",
      "severity": "",
      "specific_issues": [],
      "auto": false
    }

写入统一走「临时文件 + os.replace」，保证读方不会看到半截 JSON。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CHECKPOINT_DIR = "_checkpoints"

# 步骤名只保留安全字符，避免路径穿越
_SAFE_STEP_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def checkpoint_dir(root: Path) -> Path:
    """返回工作区的检查点目录（不存在则创建）。"""
    d = root / CHECKPOINT_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(root: Path, step: str) -> Path:
    safe = _SAFE_STEP_RE.sub("_", step or "_current")
    return checkpoint_dir(root) / f"{safe}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """原子写 JSON（Windows 下 os.replace 可覆盖）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_request(root: Path, step: str, timeout_action: str = "auto_reject") -> dict:
    """写入一次检查点请求（status=waiting）。

    若已存在 ``status=responded`` 的记录则保留——用户可能在「状态已落盘、进程
    尚未开始轮询」的窗口内提交了决策，覆盖会丢信号。rerun / 重跑前由调用方
    显式 ``clear``，保证不会误用上一轮决策。
    """
    current = read(root, step)
    if current and current.get("status") == "responded":
        return current
    data = {
        "step": step,
        "status": "waiting",
        "timeout_action": timeout_action,
        "created_at": _now_iso(),
        "responded_at": "",
        "consumed_at": "",
        "action": "",
        "feedback": "",
        "target_section": "",
        "severity": "",
        "specific_issues": [],
        "auto": False,
    }
    try:
        _atomic_write(_path(root, step), data)
    except OSError as e:
        log.warning("write checkpoint request failed for %s: %s", step, e)
    return data


def write_response(root: Path, step: str, response: dict) -> dict:
    """写入用户决策（status=responded）。

    保留原 request 的 created_at / timeout_action；若请求文件不存在（例如
    进程崩溃后补交决策），也允许直接创建。
    """
    current = read(root, step) or {}
    data: dict[str, Any] = {
        "step": step,
        "status": "responded",
        "timeout_action": current.get("timeout_action", "auto_reject"),
        "created_at": current.get("created_at", _now_iso()),
        "responded_at": _now_iso(),
        "consumed_at": "",
        "action": str(response.get("action", "approve")),
        "feedback": str(response.get("feedback", "")),
        "target_section": str(response.get("target_section", "")),
        "severity": str(response.get("severity", "")),
        "specific_issues": list(response.get("specific_issues", []) or []),
        "auto": bool(response.get("auto", False)),
    }
    _atomic_write(_path(root, step), data)
    return data


def read(root: Path, step: str) -> dict | None:
    """读取检查点文件；不存在或损坏返回 None。"""
    p = _path(root, step)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("read checkpoint %s failed: %s", step, e)
        return None


def mark_consumed(root: Path, step: str, response: dict) -> None:
    """标记已消费（保留审计痕迹，不再作为信号）。"""
    data = read(root, step) or {}
    data.update({
        "status": "consumed",
        "consumed_at": _now_iso(),
        "action": str(response.get("action", data.get("action", ""))),
        "feedback": str(response.get("feedback", data.get("feedback", ""))),
        "auto": bool(response.get("auto", data.get("auto", False))),
    })
    try:
        _atomic_write(_path(root, step), data)
    except OSError as e:
        log.warning("mark checkpoint consumed failed for %s: %s", step, e)


def mark_timeout(root: Path, step: str, response: dict) -> None:
    """记录检查点超时（保留自动决策内容，便于事后排查）。"""
    data = read(root, step) or {}
    data.update({
        "status": "timeout",
        "responded_at": _now_iso(),
        "consumed_at": _now_iso(),
        "action": str(response.get("action", "")),
        "feedback": str(response.get("feedback", "")),
        "auto": True,
    })
    try:
        _atomic_write(_path(root, step), data)
    except OSError as e:
        log.warning("mark checkpoint timeout failed for %s: %s", step, e)


def clear(root: Path, step: str) -> None:
    """删除检查点文件（rerun 前清理，避免旧信号生效）。"""
    try:
        _path(root, step).unlink(missing_ok=True)
    except OSError as e:
        log.warning("clear checkpoint %s failed: %s", step, e)


def resolve_waiting_step(root: Path) -> str:
    """从 state.json 中找出当前处于 waiting_checkpoint 的步骤名。

    仅读原始 JSON（不依赖 WorkflowState），供 CLI/服务端在提交决策时定位步骤。
    """
    state_file = root / "state.json"
    if not state_file.exists():
        return ""
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for step in data.get("steps", []):
        if step.get("status") == "waiting_checkpoint":
            return str(step.get("skill_name", ""))
    return ""
