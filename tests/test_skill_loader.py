"""技能加载：_shared 按需注入，避免每个 skill 背全部设计知识。"""
from __future__ import annotations

from agent.skill_loader import load_skill_meta, render_skill_prompt


def test_meta_parses_shared_declaration():
    assert load_skill_meta("dev-code").shared == ["color-theory", "typography-pairing"]
    assert load_skill_meta("dev-requirement").shared == []


def test_requirement_prompt_does_not_load_design_shared():
    prompt = render_skill_prompt("dev-requirement", "做一个博客", workspace_files=[])

    assert "Shared Knowledge" not in prompt
    assert "WCAG" not in prompt


def test_design_prompt_loads_declared_shared_only():
    prompt = render_skill_prompt("dev-design", "做一个博客", workspace_files=[])

    assert "# Shared Knowledge: color-theory.md" in prompt
    assert "# Shared Knowledge: motion-basics.md" in prompt
    # 未声明的文件不应出现
    assert "# Shared Knowledge: accessibility-checklist.md" in prompt  # dev-design 声明了全部 5 篇
    assert "# Shared Knowledge: typography-pairing.md" in prompt


def test_code_prompt_skips_motion_and_accessibility():
    prompt = render_skill_prompt("dev-code", "做一个博客", workspace_files=[])

    assert "# Shared Knowledge: color-theory.md" in prompt
    assert "# Shared Knowledge: typography-pairing.md" in prompt
    assert "# Shared Knowledge: motion-basics.md" not in prompt
    assert "# Shared Knowledge: accessibility-checklist.md" not in prompt
