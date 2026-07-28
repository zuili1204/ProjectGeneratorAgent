# REQUIREMENT.md 示例（few-shot 参考）

> 本文件是 dev-requirement 步骤的「优秀产物」样例，供 LLM 对齐风格与粒度。
> 实际生成时以用户需求为准，不要照抄本例的业务内容。

---

# 待办事项 Web 应用 需求文档

## 项目概述

做一个带用户登录的待办事项 Web 应用，前后端分离。用户注册登录后可创建、编辑、删除、标记完成待办事项，支持按状态筛选。解决个人任务管理的需求。

## 项目类型

`project_type`: fullstack

判定依据：命中「登录」「用户」「Web 应用」等全栈信号，需前端页面 + 后端服务 + 数据持久化。

## 技术栈

- 前端框架：React + Vite。理由：启动快、生态成熟、组件化适合待办列表交互。
- 后端框架：FastAPI。理由：异步性能好、自动生成 OpenAPI 文档、Pydantic 校验入参。
- 数据库：SQLite。理由：零配置、单文件，适合原型与中小项目，后续可平滑迁移 MySQL。
- 编程语言：Python 3.10+（后端）、JavaScript（前端）。

## 用户角色

- 匿名访客：仅可访问登录/注册页。
- 注册用户：管理自己的待办事项（增删改查、筛选、标记完成）。

权限矩阵：注册用户可操作「待办 CRUD」「标记完成」；匿名访客无待办操作权限。

## 功能需求

### P0（必须）

- 用户通过邮箱注册账号（邮箱 + 密码）
- 用户通过邮箱密码登录，获取会话 token
- 创建待办事项（标题 + 可选描述 + 优先级）
- 查看自己的待办列表
- 编辑待办事项
- 删除待办事项
- 标记待办完成/取消完成

### P1（重要）

- 按状态（全部/未完成/已完成）筛选
- 按优先级排序
- 待办列表分页（每页 20 条）

### P2（可选）

- 待办到期时间提醒
- 多人共享待办列表

## 项目类型对应清单

### 页面清单

| 路由 | 页面名称 | 主要交互 | 鉴权 |
| --- | --- | --- | --- |
| /login | 登录页 | 邮箱密码登录 | 否 |
| /register | 注册页 | 邮箱密码注册 | 否 |
| / | 待办列表页 | CRUD、筛选、排序 | 是 |

### API 接口清单

| 方法 | 路径 | 入参 | 返回 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| POST | /api/register | email, password | {token} | 201/400 | 否 |
| POST | /api/login | email, password | {token} | 200/401 | 否 |
| GET | /api/todos | status?, page? | {items, total} | 200 | 是 |
| POST | /api/todos | title, desc?, priority? | {todo} | 201 | 是 |
| PUT | /api/todos/{id} | title?, status? | {todo} | 200 | 是 |
| DELETE | /api/todos/{id} | - | - | 204 | 是 |

### 数据库表设计

- users: id(int, PK), email(string, unique), password_hash(string), created_at(datetime)
- todos: id(int, PK), user_id(int, FK→users.id), title(string), description(string), priority(int), status(string), created_at(datetime), updated_at(datetime)

## 数据模型概要

主要实体：User、Todo（1:N 关系，一个用户有多条待办）。字段见上表。

## 非功能需求

- 性能：列表接口 P95 响应 < 200ms（1000 条数据下）
- 安全：密码 bcrypt 哈希存储；token 用 JWT；接口防 SQL 注入（ORM 参数化）
- 可维护性：后端分层（router/service/model）；前端组件化

## 验收标准

- 注册 → 登录 → 创建待办 → 标记完成 → 删除，全流程跑通
- 未登录访问 / 重定向到 /login
- 删除不存在的待办返回 404

## 假设与待确认

- 假设：单用户场景，不考虑团队协作（P2 才支持共享）。
- 待确认：密码强度策略是否强制（当前默认最短 8 位）。
