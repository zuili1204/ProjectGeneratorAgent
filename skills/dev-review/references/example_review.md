# REVIEW.md Example (few-shot reference)

> This file is an "excellent artifact" sample for the dev-review step, provided so the LLM can align its style and granularity.
> When generating for real, follow the actual code and requirements — do NOT copy this example's content.
> NOTE: The example body below is in Chinese because all generated project artifacts MUST be in Chinese.

---

# 评审概要

- 项目类型: fullstack
- 评审范围: code/ 目录共 12 个文件（Python 5 / JavaScript 4 / HTML 1 / 配置 2）
- 评审时间: 2026-07-28 14:30
- 整体结论: 有条件通过

# 需求覆盖度

## P0 功能核对

| 功能项 | 状态 | 定位文件 | 备注 |
| --- | --- | --- | --- |
| 用户通过邮箱注册账号 | 已实现 | code/backend/main.py:45 `register` | 含密码 hash |
| 用户通过邮箱登录 | 已实现 | code/backend/main.py:78 `login` | 返回 JWT |
| 创建待办事项 | 已实现 | code/backend/main.py:120 `create_todo` | |
| 查看待办列表 | 已实现 | code/backend/main.py:135 `list_todos` | 支持分页 |
| 标记完成 | 已实现 | code/backend/main.py:152 `mark_done` | |
| 删除待办 | 已实现 | code/backend/main.py:168 `delete_todo` | |

## P1 功能核对

| 功能项 | 状态 | 定位文件 | 备注 |
| --- | --- | --- | --- |
| 按标签筛选 | 未实现 | - | 警告：P1 漏实现 |
| 优先级排序 | 已实现 | code/backend/main.py:180 | |
| 前端待办列表页 | 已实现 | code/frontend/src/TodoList.jsx | |

## 过度实现

- code/backend/main.py:200 新增了 `/api/export` 导出接口，REQUIREMENT.md 未要求。属合理扩展，记为 nit。

# 设计一致性

## 目录结构对比

- 设计: code/backend/main.py + code/frontend/src/ → 一致
- 偏离: 设计要求 `code/backend/models.py`，实际写在 `main.py` 内 → minor，建议拆分

## 接口对比

| DESIGN.md 接口 | 实际实现 | 一致性 |
| --- | --- | --- |
| POST /api/register | POST /api/register | 一致 |
| POST /api/login | POST /api/login | 一致 |
| GET /api/todos | GET /api/todos | 一致 |
| PATCH /api/todos/:id | PUT /api/todos/:id | 偏离：方法 PUT vs PATCH |

## 数据模型对比

- todos 表字段与 ER 图一致：id / user_id / title / done / created_at
- 偏离: 设计有 `priority` 字段，表里也有；但 `tag` 字段设计有，表里无 → 对应 P1 漏实现

# 潜在缺陷

## blocker

- 无

## major

- code/backend/main.py:85 `verify_password` 未对空密码做校验 → 建议增加空值检查
- code/frontend/src/api.js:12 `localStorage.setItem('token', token)` 未做 XSS 防护 → 建议加 HttpOnly Cookie 或至少输入转义

## minor

- code/backend/main.py:150 `mark_done` 未捕获数据库异常 → 建议加 try/except
- code/frontend/src/TodoList.jsx:40 直接拼接 HTML（`innerHTML`）→ 有 XSS 风险，建议用 textContent

## nit

- code/backend/main.py 函数均无 docstring → 建议补关键函数注释

# 维度评分

- 需求覆盖度: 警告 — P1「按标签筛选」漏实现，且数据模型缺 tag 字段
- 设计一致性: 警告 — PATCH/PUT 方法不一致；models 未拆分
- 潜在缺陷: 警告 — 2 个 major（空密码 / XSS 风险）

# 整体结论与建议

整体结论: 有条件通过。P0 全部覆盖，可进入 dev-selfcheck，但建议 dev-selfcheck 优先修复以下项:

1. (major) code/backend/main.py:85 空密码校验
2. (major) code/frontend/src/api.js:12 token 存储 XSS 防护
3. (minor) code/frontend/src/TodoList.jsx:40 innerHTML → textContent

P1「按标签筛选」漏实现属需求范畴，若用户确认可延后到下一迭代，则在 SELF_CHECK.md 中记为「未修复问题」并说明原因。
