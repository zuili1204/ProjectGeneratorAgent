"""ProjectGeneratorAgent 测试套件。

模块组织：
- tests/test_smoke.py         非依赖 LLM 的冒烟测试（模板/Skill/when 求值/安全沙箱）
- tests/regress_skill.py      SKILL 回归脚本（按 golden 用例跑单步并断言产物）
- tests/golden/               黄金用例集（每个用例一份 case.yaml + 可选期望产物）

回归脚本用法：
    python -m tests.regress_skill dev-requirement --case todo_app --dry-run
    python -m tests.regress_skill dev-requirement --case todo_app        # 调 LLM 实跑
    python -m tests.regress_skill --list
"""
