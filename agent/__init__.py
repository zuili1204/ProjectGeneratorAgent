"""ProjectGeneratorAgent — 一句话生成项目的独立智能体应用。

基于 Modex-MH-Agent 工作流学习方法重新设计：
- 不依赖 Claude Code CLI，直接调用 OpenAI 兼容 LLM API + tool calling
- 明文 SKILL.md，可读可改
- YAML 工作流模板，可配置
- 强健康检查（Python compile / JS 括号 / HTML 标签）
- 检查点暂停/恢复
- CLI + REST API 双模式
"""
__version__ = "1.0.0"
