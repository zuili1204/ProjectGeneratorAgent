"""pytest 公共 fixture。"""
from __future__ import annotations

import pytest

import agent.workspace as workspace_mod


@pytest.fixture
def ws_dir(tmp_path, monkeypatch):
    """把工作区根目录重定向到临时目录，避免污染真实 workspaces/。"""
    monkeypatch.setattr(workspace_mod, "WORKSPACES_DIR", tmp_path)
    return tmp_path
