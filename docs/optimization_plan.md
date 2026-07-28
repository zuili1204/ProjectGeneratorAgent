# ProjectGeneratorAgent 优化与完善方案

> 本方案基于对 `agent/` 全部模块、`skills/*/SKILL.md`、`templates/grad_project.yaml` 的实际源码审查，针对三类问题提出可落地的改进：① 意外 / 连接失败 / 生成失败事件的应对；② SKILL 流的提优与完善；③ 架构与工程层面的补强。每条问题均标注源码位置，每条建议尽量给出实施要点。

---

## 一、意外事件 / 连接失败 / 生成失败事件应对方案

当前代码对失败的容忍度偏低：LLM 调用失败直接返回、工具失败只记录 ERROR、健康检查重试无退避、崩溃后无半成品清理。下面按失败发生的层次逐项分析。

### 1.1 LLM 调用层失败

**现状问题**

- [llm_client.py:44-51](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/llm_client.py#L44-L51) 构造 `AsyncOpenAI` 时只传了 `timeout`，没有配置 `max_retries`。OpenAI SDK 默认对 429/5xx 重试 2 次，但间隔固定且不可控，对 DeepSeek/Qwen 等第三方网关的限流不一定友好。
- [agent_loop.py:243-252](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L243-L252) `chat_stream` 抛任何异常都直接 `return result`，把整个 agent 循环终止。一次网络抖动就废掉一整步。
- [llm_client.py:154-160](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/llm_client.py#L154-L160) 流式 `tool_call` 的 `arguments` JSON 解析失败时降级为空 dict `{}`，工具名还在但参数全丢，下游会执行一个「无参数」的工具调用，产生不可预期的写入。
- 没有针对 `429 Too Many Requests` 的 `Retry-After` 头解析，也没有针对连接重置（`ConnectionResetError`、`httpx.RemoteProtocolError`）的专门处理。

**应对方案**

1. **分层重试（建议新增 `agent/llm_retry.py`）**
   - 第 1 层：HTTP 层重试，交给 OpenAI SDK 的 `max_retries`，配置为 3，覆盖 408/409/429/5xx。
   - 第 2 层：业务层重试，在 `chat_stream` 外包一层 `retry_async`，针对 `asyncio.TimeoutError`、`httpx.TransportError`、`openai.APIConnectionError` 做指数退避（基础 2s，上限 30s，抖动 ±20%）。
   - 第 3 层：agent_loop 层重试，单次 LLM 调用失败时重试 1 次（不重置 messages，因为 messages 已包含历史），仅在连续 2 次都失败才终止该步。
2. **429 专门处理**：读取响应头 `Retry-After`，按其值 sleep 后重试；无该头则按指数退避。
3. **tool_call JSON 修复**：解析失败时不直接降级为 `{}`，而是把残缺的 arguments 原样回填给 LLM（作为一条 `tool` 消息 content 标注「arguments JSON 不完整，请重新调用」），让 LLM 自纠正，而不是默默执行空参数写入。
4. **配置化**：在 [config.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/config.py) 的 `LLMConfig` 增加 `max_retries: int = 3`、`retry_base_delay: float = 2.0`、`retry_max_delay: float = 30.0`，环境变量 `LLM_MAX_RETRIES` 等。

### 1.2 Agent 循环层异常

**现状问题**

- [agent_loop.py:321-324](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L321-L324) 达到 `max_iter`（默认 50）直接 `truncated=True` 返回，不区分「真的需要这么多迭代」和「LLM 陷入死循环反复调同一工具」。
- `DEFAULT_INACTIVITY_TIMEOUT = 2400`（[config.py:34](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/config.py#L34)）定义了但 **agent_loop 里完全没有使用**——无输出超时检测缺失。LLM 卡住不返回时整个工作流会一直挂着。
- 没有「重复工具调用」检测：LLM 若反复 `read_file` 同一文件、或反复 `write_file` 同一文件相同内容，会白耗迭代次数。
- 没有 token 预算检测：messages 越积越长，到某次调用直接 `context_length_exceeded` 报错终止。

**应对方案**

1. **无输出超时**：在 `run_agent_loop` 内引入「最近一次收到 delta 的时间戳」，配合一个看门狗协程，超过 `inactivity_timeout`（来自 `WorkflowConfig`，当前 2400s 偏长，建议默认 300s）则取消当前 LLM 调用并进入重试或失败。
2. **循环检测**：维护一个滑动窗口（最近 6 次工具调用），若同一 `(tool_name, args_hash)` 出现 ≥ 3 次，注入一条 system 消息提醒 LLM「你已重复调用 X，请换思路或结束」，再犯则强制终止并标记 `error`。
3. **token 预算守卫**：每次迭代前估算 messages 总字符数（粗估 1 token ≈ 3.5 字符），超过模型上下文的 70% 时触发上下文压缩（见 1.7）。
4. **max_iter 软硬区分**：达到 max_iter 时，若 `files_written` 非空且健康检查能过，允许「软截断」标记完成；否则才标记失败。

### 1.3 工具执行层失败

**现状问题**

- [agent_loop.py:140-168](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L140-L168) `run_command` 超时 60 秒硬编码，无法按命令类型区分（`pip install` 可能要 3 分钟，`py_compile` 5 秒就够）。
- [agent_loop.py:100-109](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L100-L109) `write_file` 失败只返回 `ERROR: {e}` 字符串，不区分「磁盘满」「权限拒绝」「路径非法」，LLM 拿到后可能反复重试同样的写法。
- `read_file` 截断 8000 字符（[agent_loop.py:118-119](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L118-L119)），但 LLM 不知道还有多少被截断，可能基于不完整内容做判断。

**应对方案**

1. **命令超时分级**：在 `run_command` 工具描述里允许 LLM 传 `timeout` 参数（上限 180s），或按命令前缀自动判定：`pip install`/`npm install` → 180s，`python -m py_compile`/`node --check` → 15s，默认 60s。
2. **错误分类回传**：工具失败时返回结构化错误码（`DISK_FULL` / `PERMISSION_DENIED` / `PATH_INVALID` / `TIMEOUT`），并在 system 消息里告诉 LLM 遇到这些码该怎么换策略（如 `PATH_INVALID` 时改用 `list_files` 先确认路径）。
3. **截断可见性**：`read_file` 截断时明确返回「已截断前 8000 字符，原文共 N 字符，如需后续内容请用 offset 参数」并支持分段读。建议给 `read_file` 增加 `offset`/`limit` 参数。

### 1.4 健康检查失败

**现状问题**

- [workflow_engine.py:367-487](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L367-L487) 健康检查失败重试固定 2 次，无退避，且重试 prompt 是写死的「补全模式」。如果失败原因是 LLM 能力不足（而非漏写文件），补全模式也救不回来，白白消耗 2 轮 token。
- [health_check.py:27-48](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/health_check.py#L27-L48) `dev-code` 的必需文件按 `project_type` 静态查表，但 LLM 实际可能把后端入口命名为 `app.py`/`server.py` 而非 `main.py`，导致误判失败。
- [workflow_engine.py:621-638](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L621-L638) `dev-code` 阶段语法错误不阻断（交给 dev-selfcheck），但 dev-selfcheck 的重试也是同一套补全 prompt，如果错误太多 2 次也修不完。
- [health_check.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/health_check.py) 没有 CSS 检查、没有 `import` 依赖存在性检查、没有 `package.json` 的 `scripts` 完整性检查。

**应对方案**

1. **失败原因分类驱动重试策略**：
   - 主产物缺失 → 补全 prompt（当前做法）。
   - 主产物过小 → 「内容不足」prompt，把现有内容回填给 LLM 要求扩写。
   - 语法错误 → 把 `compile()` 的错误行号 + 错误信息精确回填，要求 LLM 只改这一个文件这一处。
   - 二级文件缺失 → 列出缺失清单要求逐个补。
   不同原因用不同 prompt，而非一刀切。
2. **入口文件柔性识别**：`dev-code` 健康检查不只认 `main.py`，允许 `app.py`/`server.py`/`__main__.py` 任一存在即算通过；或在 SKILL.md 里强制要求入口必须叫 `main.py`（当前 [dev-code/SKILL.md](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-code/SKILL.md) 已有此要求，则应保留硬约束，但要在 RUN.md 里校验引用一致）。
3. **重试退避**：重试间加 2-5 秒 sleep，避免对限流中的 API 雪上加霜。
4. **重试次数可配**：在 `WorkflowConfig` 增加 `health_retry: int = 2`，复杂项目可调高。
5. **语法检查增强**：新增 `check_imports_exist`（扫描 `.py` 的 `import` 语句，对照 `requirements.txt` 与标准库判断）、`check_package_json_scripts`（`scripts.start` 必须存在且引用的文件存在）。

### 1.5 检查点异常

**现状问题**

- [workflow_engine.py:197-205](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L197-L205) 检查点超时 600 秒后 **自动 approve**。这意味着用户离开 10 分钟，一个有问题的 REQUIREMENT.md 会被自动放行进入后续步骤，后续都建立在错误需求上。
- 打回后 [workflow_engine.py:513-524](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L513-L524) 把步骤标记 `failed`、工作流 `paused`，但**没有把打回反馈注入到重跑的 prompt 里**——用户写了一大段反馈，rerun 时反馈丢了（反馈只在前置 `_build_extra_context` 里取「上一步」的反馈，而打回后 rerun 同一步时 `current_idx` 不变，取不到）。
- 检查点响应只有 `approved` + `feedback` 两字段，无法表达「打回并要求换技术栈」「通过但要改某节」这类结构化指令。

**应对方案**

1. **超时策略可配**：`checkpoint_timeout` 超时后的行为改为可选：`auto_approve`（当前）/ `auto_reject`（更安全，默认改为这个）/ `wait_forever`。在 `WorkflowConfig` 增加 `checkpoint_timeout_action: str = "auto_reject"`。
2. **打回反馈持久化并注入重跑**：打回时把反馈写入 `step_state.checkpoint_response`（已做）并额外写入 `CONTEXT.md`（用 `inject_once`，目前没做）。`rerun_step` 时在 `_build_extra_context` 里检测当前步的 `checkpoint_response.feedback`，若存在则作为「上轮打回反馈」注入。
3. **结构化检查点响应**：扩展响应 schema，支持 `action: approve|reject|revise`、`target_section: string`（要求改哪一节）、`severity: blocker|suggestion`，让反馈更精准。

### 1.6 进程崩溃与中断恢复

**现状问题**

- [workflow_engine.py:690-698](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L690-L698) `state.json` 是覆盖写，如果写到一半进程被 kill，会留下损坏的 JSON，`_load_state` 直接抛异常，工作流再也无法恢复。
- `run_workflow` 中途异常时 [workflow_engine.py:558-564](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L558-L564) 把状态置 `failed`，但**没有记录失败时的工作区快照**，事后难排查。
- agent_loop 写了一半文件就崩溃，留下半成品 `.py`，下次 rerun 时健康检查会因语法错误失败，但 LLM 不知道这是上次崩溃的残留。
- 没有「断点续跑」的显式入口：`run_workflow` 会跳过 `completed` 步骤，但 `failed` 步骤会 `break` 而非等待人工 rerun，状态语义不清晰。

**应对方案**

1. **原子写状态**：`_save_state` 改为「写临时文件 → fsync → rename」原子替换，避免半写损坏。建议在 [workspace.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workspace.py) 增加 `write_file_atomic` 方法。
2. **状态备份**：每次 `_save_state` 前把上一版 `state.json` 复制为 `state.json.bak`，损坏时可回退。
3. **崩溃恢复向导**：`run_workflow` 启动时检测 `state.json` 是否可解析，不可解析则尝试 `state.json.bak`，仍不行则标记 `corrupted` 并提示用户。
4. **失败快照**：步骤失败时把当前 `state.json`、`CONTEXT.md`、失败步骤的 error_message 打包到 `workspaces/{id}/_failure_snapshot/`，方便事后排查。
5. **半成品清理**：rerun 某步前，可选清理该步的主产物（如 rerun `dev-code` 前清空 `code/` 目录），避免残留干扰。增加 `rerun --clean` 选项。

### 1.7 上下文超限

**现状问题**

- [workspace.py:37-41](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workspace.py#L37-L41) 上下文摘要硬限 12000 字符、单文件 4000 字符，纯截断。dev-code 步骤要读 REQUIREMENT.md + DESIGN.md + 整个 code/ 目录，很容易超。
- [skill_loader.py:73-81](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/skill_loader.py#L73-L81) 把工作区文件清单和 extra_context 全拼到 prompt 末尾，加上 SKILL.md 本身（dev-code 的 SKILL.md 有 218 行），单次 prompt 很容易突破 16K。
- 没有 token 计数，没有「上下文压缩」触发机制（Modex-MH-Agent 原版有 `_compress_claude_md`，本项目未实现）。
- `agent_loop` 的 messages 列表只增不减，长任务必然爆。

**应对方案**

1. **token 估算与预算**：引入 `tiktoken`（或粗估函数），在 `render_skill_prompt` 和每次 agent 迭代前估算总 token，超过模型上限 60% 时触发压缩。
2. **上下文压缩策略**（对应 Modex-MH-Agent 的 `_compress_claude_md`）：
   - 已写入的代码文件内容从 messages 中移除（反正已落盘，LLM 需要 `read_file` 重新读）。
   - 历次工具结果超过 2000 字符的截断为摘要。
   - `CONTEXT.md` 的「上下文摘要」段按文件重要性裁剪：保留 REQUIREMENT.md / DESIGN.md 全文，code/ 文件只保留文件名清单。
3. **摘要分层**：`build_context_summary` 输出两层——「清单层」（所有文件名 + 大小）恒定保留，「内容层」（关键文件全文）按预算动态纳入。
4. **agent_loop 滑动窗口**：对 tool 结果消息做窗口管理，保留最近 10 条全文，更早的截断为「(已执行 write_file code/backend/main.py，成功)」一行摘要。

### 1.8 工作流卡死

**现状问题**

- 没有全局工作流超时：一个工作流理论上可以跑无限久（agent_loop 50 迭代 × 4 步，每迭代 LLM 调用 600s 超时，最坏 33 小时）。
- `server.py` 的后台任务 [server.py:474-485](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py#L474-L485) 若协程挂起，`_running_tasks` 里的引用永远不会释放。
- WebSocket 心跳 [server.py:390-419](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py#L390-L419) 有，但工作流协程本身没有心跳，无法发现「协程还活着但卡在 LLM 调用」。

**应对方案**

1. **全局超时**：`run_workflow` 外层包一个 `asyncio.wait_for(..., timeout=workflow_config.global_timeout)`，默认 3600s，超时标记 `timeout` 状态。
2. **步骤级超时**：单步 agent_loop 外层也加超时（默认 900s），防止单步耗尽全局预算。
3. **僵尸任务检测**：server 启动时扫描 `state.json` 中 status=`running` 但进程已不存在的工作流，标记为 `interrupted`，提示用户 resume 或 delete。

---

## 二、SKILL 流提优与完善方案

当前 4 个 SKILL.md 结构完整（任务目标 / 前置校验 / 执行步骤 / 后置自检 / 强红线 / 工程规范 / 工具与异常 / 关键约束），是项目的亮点。但仍可在以下方面提优。

### 2.1 SKILL 指令书完善

**现状问题**

- 四个 SKILL.md 都没有 **版本号**、没有 **适用模型** 标注、没有 **预期耗时 / token 预算** 提示。
- [dev-requirement/SKILL.md](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-requirement/SKILL.md) 的 `$ARGUMENTS` 是用户原始一句话，但没有要求 LLM 在歧义时**主动提问**而非猜测，容易产出跑偏的 REQUIREMENT.md。
- SKILL 之间是「文件约定」耦合（dev-design 读 REQUIREMENT.md，dev-code 读 DESIGN.md），但**没有契约校验**：dev-design 若漏写「技术栈」节，dev-code 会凭空发挥。
- 没有 **示例（few-shot）**：每个 SKILL.md 都是规则描述，没有一个「正确产物」的样例片段，LLM 容易理解偏差。

**完善方案**

1. **SKILL 元数据头**：每个 SKILL.md 顶部增加 YAML front matter：
   ```yaml
   ---
   name: dev-requirement
   version: 1.0.0
   inputs: [$ARGUMENTS]
   outputs: [REQUIREMENT.md]
   depends_on: []
   est_tokens: 4000
   est_iters: 8
   ---
   ```
   `skill_loader.py` 解析后可用于：依赖校验（前置产物是否存在）、预算预估、版本兼容性检查。
2. **歧义澄清模式**：dev-requirement 增加规则「若需求存在两种以上合理理解，在 REQUIREMENT.md 顶部用『待确认』节列出，并选一种默认理解继续，不要静默猜测」。
3. **产物契约 Schema**：为 REQUIREMENT.md / DESIGN.md / RUN.md / SELF_CHECK.md 定义必需章节清单（[dev-requirement/SKILL.md:116-129](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-requirement/SKILL.md#L116-L129) 已有模板，但未作为契约校验）。在 `health_check.py` 增加 `check_md_sections(rel_path, required_sections)`，dev-design 启动前校验 REQUIREMENT.md 含 `## 技术栈`/`## 功能需求` 等节，缺失则报错让用户先 rerun dev-requirement。
4. **few-shot 示例**：每个 SKILL.md 末尾或 `references/` 子目录放一个「优秀产物片段」（如一份精简的 REQUIREMENT.md 范例），LLM 照着对齐风格与粒度。建议在 `skills/dev-requirement/references/example_requirement.md` 放范例。
5. **失败模式提示**：在 SKILL.md 增加「常见错误」节，列举 LLM 易犯的错（如「把 fetch 加载本地 JSON」「漏写 RUN.md」「技术栈与 REQUIREMENT.md 不一致」），提前警示。

### 2.2 上下文传递优化

**现状问题**

- [workflow_engine.py:644-688](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L644-L688) `_build_extra_context` 只传「项目配置 + 上一步反馈」，**不传上一步产物的摘要**。dev-code 启动时拿不到 DESIGN.md 的要点摘要，只能靠 `build_context_summary` 把整个 DESIGN.md 塞进 prompt（可能被 4000 字符截断）。
- [skill_loader.py:73-81](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/skill_loader.py#L73-L81) 工作区文件清单只列文件名，不带大小和类型，LLM 不知道哪个文件大、哪个是入口。
- 用户反馈注入用 `inject_once` 写进 CONTEXT.md（[workflow_engine.py:527-532](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L527-L532)），但 CONTEXT.md 不在 agent_loop 的 messages 里，**LLM 是否会读 CONTEXT.md 取决于它是否主动 read_file**，不保证。

**完善方案**

1. **结构化上下文传递**：每步完成后，由引擎（而非 LLM）生成一份「产物摘要」写入 `workspaces/{id}/_summaries/{step}.md`，内容为：主产物路径 + 大小 + 关键章节标题 + 技术栈/项目类型等结构化字段。下一步的 `extra_context` 显式注入这份摘要。这样 dev-code 一定能拿到 DESIGN.md 的要点，不依赖 LLM 是否 read_file。
2. **文件清单增强**：`render_skill_prompt` 拼接的文件清单改为 `- {path} ({size}B, {type})`，type 标注 `entry`/`config`/`doc`/`source`，帮助 LLM 快速定位入口。
3. **CONTEXT.md 强制注入**：在 agent_loop 的首条 user 消息里，除了 SKILL prompt，再拼一段「工作区上下文索引」指向 CONTEXT.md，并显式要求「执行任务前先 read_file CONTEXT.md 了解项目元数据」。

### 2.3 多角色协作（reviewer）

**现状问题**

- 当前是单 LLM 角色串行执行，dev-code 写完直接进 dev-selfcheck 自检。**自己检查自己**容易漏（认知盲区）。
- dev-selfcheck 的检查项是预设的（语法/标签/路径/依赖/启动命令），无法发现「功能与需求不符」「架构与设计不符」这类语义问题。

**完善方案**

1. **引入 reviewer 角色**：在 dev-code 与 dev-selfcheck 之间插入一个轻量 `dev-review` 步骤（可设为无检查点、不产出主产物，只产出 `REVIEW.md`）。该步骤用**相同 LLM 但不同 SKILL**（reviewer 视角），对照 REQUIREMENT.md + DESIGN.md 审视 code/，输出「需求覆盖度」「设计一致性」「潜在缺陷」三段。review 意见注入 dev-selfcheck 的上下文，让它针对性修复。
2. **多模型协作（可选）**：`LLMConfig` 支持 `review_model` 字段，reviewer 步骤用更强/不同的模型交叉检查，避免同模型自检盲区。
3. **成本控制**：reviewer 步骤默认关闭，在模板里 `has_checkpoint: false` + `optional: true`，用户在 params 里 `enable_review: true` 才启用。

### 2.4 增量生成与断点续跑

**现状问题**

- `rerun_step` ([workflow_engine.py:763-778](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L763-L778)) 把当前步重置为 pending 后重跑，但**会清空该步 output_files 记录**，且后续步骤状态不变。如果 rerun dev-code，dev-selfcheck 仍是 completed 状态，会被跳过，但 code/ 已大改，selfcheck 结果失效。
- 没有「只重跑失败的部分」的细粒度：dev-selfcheck 发现 3 个语法错误，rerun 会把整个 selfcheck 步骤从头跑，而非只修这 3 处。

**完善方案**

1. **rerun 级联失效**：rerun 某步后，自动把其后所有步骤标记为 `stale`（新增状态），run_workflow 遇到 `stale` 当作 pending 处理。这样 rerun dev-code 后 dev-selfcheck 会自动重跑。
2. **定向修复模式**：dev-selfcheck 失败时，把失败项（文件 + 行号 + 错误）作为 rerun 的 prompt，只要求 LLM 修这些点，不重新扫描全项目。对应 1.4 的「失败原因分类驱动重试」。
3. **产物指纹**：每步完成时记录主产物的 hash，rerun 前对比 hash 判断是否真的变化，避免无效重跑。

### 2.5 SKILL 版本化与可扩展性

**现状问题**

- `list_skills` ([skill_loader.py:86-93](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/skill_loader.py#L86-L93)) 只看目录名，无版本概念。SKILL.md 改动后，旧工作流的 rerun 会用新 SKILL，可能行为不一致。
- 模板 `grad_project.yaml` 只有一个，无法支持「生成论文」「生成数据脚本」等其他场景（虽然架构支持，但没有示例模板）。

**完善方案**

1. **SKILL 版本目录**：`skills/dev-requirement/1.0/SKILL.md`、`skills/dev-requirement/1.1/SKILL.md`，`state.json` 记录每步用的版本号，rerun 时默认用原版本，`rerun --latest` 才升级。
2. **模板示例**：增加 `templates/script_only.yaml`（纯脚本）、`templates/api_only.yaml`（纯后端 API）等示例模板，展示框架可扩展性，也让 `pga templates` 更有内容。
3. **SKILL 组合规则**：模板的 `sub_steps` 支持条件分支（如 `when: project_type == "fullstack"` 才插入 dev-review），让同一模板适配多场景。

### 2.6 SKILL 测试与回归

**现状问题**

- SKILL.md 是自然语言指令，改动后没有回归测试。改一句强红线，可能在某个项目类型上回归。

**完善方案**

1. **黄金用例集**：`tests/golden/` 下放 3-5 个典型需求（待办 fullstack、计算器 frontend_only、文件重命名 cli、爬虫脚本），每个有期望的产物文件清单 + 关键章节。
2. **SKILL 回归脚本**：`python -m tests.regress_skill dev-requirement --case todo_app`，跑单步并对产物做断言（REQUIREMENT.md 存在、含「技术栈」节、project_type 合法）。
3. **LLM 评估**：由于输出非确定，用 LLM-as-judge 跑评估（另一个 prompt 给产物打分），记录分数变化趋势。

---

## 三、架构与工程完善方案

### 3.1 重试与退避统一机制

**现状**：重试逻辑散落各处（agent_loop 无重试、workflow_engine 健康检查重试 2 次无退避、llm_client 依赖 SDK 默认）。

**方案**：新增 `agent/resilience.py`，提供：
- `retry_async(max_retries, base_delay, max_delay, exceptions, on_retry)` 装饰器
- `circuit_breaker(failure_threshold, reset_timeout)` 熔断器（连续 N 次失败快速短路，避免对挂掉的 API 持续打）
- 全局 `RetryPolicy` 配置，LLM 调用 / 工具执行 / 健康检查分别引用不同策略。

### 3.2 状态持久化增强

**现状**：[workflow_engine.py:690-698](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L690-L698) 覆盖写 `state.json`，无锁、无备份、无原子性。

**方案**：
1. 原子写（写 `.tmp` → `os.replace`）。
2. 保留 `state.json.bak`。
3. `WorkflowState` 增加 `schema_version` 字段，未来字段变更时可迁移。
4. 由于每个工作流独立目录，并发写风险低，暂不需要文件锁；但 `server.py` 同时启动多个工作流时，`_running_tasks` 已做互斥（[server.py:474-485](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py#L474-L485)），建议显式加注释说明此约定。

### 3.3 可观测性

**现状**：日志通过 `_broadcast_log` 广播，CLI/WS 可见，但**无文件落盘**（state.json 里 logs 只保留 500 条且随状态一起覆盖），无指标，无 trace。

**方案**：
1. **日志落盘**：每步的 `_broadcast_log` 同时 append 到 `workspaces/{id}/run.log`，崩溃后可查。
2. **指标记录**：`state.json` 增加 `metrics` 段：每步的 `iterations`/`tokens`/`duration_sec`/`llm_calls`/`tool_calls`/`retries`。当前只记了 `iterations` 和 `tokens`（[workflow_engine.py:456-457](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L456-L457)），补齐其余。
3. **事件追踪**：定义事件类型枚举（`step_start`/`llm_call`/`tool_call`/`health_check`/`checkpoint`/`retry`/`step_done`），每个事件带 `timestamp`/`step`/`duration`，写入 `events.jsonl`，便于事后回放与性能分析。
4. **成本统计**：`LLMConfig` 增加 `price_per_1k_input`/`price_per_1k_output`（按模型预设），`state.json` 汇总每步 USD 成本，CLI `show` 命令展示。

### 3.4 并发控制

**现状**：[server.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py) 用 `_running_tasks` dict 做互斥，同一工作流不会并发跑，但**不同工作流可并发**，会同时打多个 LLM 请求，可能触发限流。

**方案**：
1. **全局并发信号量**：`asyncio.Semaphore(max_concurrent_workflows)`，默认 2，可配。`run_workflow` 进入前 acquire。
2. **LLM 调用并发限制**：单独的 `asyncio.Semaphore(max_concurrent_llm_calls)`，默认 4，防止单工作流内 agent_loop 并发（虽然当前 agent_loop 是串行的，但未来若并行工具执行需要）。
3. **队列化**：超出并发的工作流排队，state 增加 `queued` 状态。

### 3.5 安全加固

**现状问题**

- [server.py:97-104](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py#L97-L104) CORS 允许所有来源（`*`），生产环境有风险。
- [server.py:214-240](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py#L214-L240) `/api/workflows/{id}/files/{file_path:path}` 可读取工作区任意文件，包括 `state.json`，**无路径限制**（虽然 `_safe_rel` 在 workspace 层有防护，但此端点直接读文件，需确认是否走了 `_safe_rel`）。
- `run_command` 工具（[agent_loop.py:140-168](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L140-L168)）执行任意 shell，LLM 若被 prompt 注入可能执行危险命令（如 `rm -rf`）。
- 无认证：任何人访问 `127.0.0.1:8000` 即可创建工作流、读文件。

**方案**

1. **CORS 白名单**：默认只允许 `http://localhost:*`，可通过配置 `allowed_origins` 扩展。
2. **文件读取端点加固**：`/files/{path}` 端点必须走 `Workspace._safe_rel`，并禁止读取 `state.json`/`project.json`/`CONTEXT.md` 之外的元数据文件。
3. **命令沙箱**：`run_command` 增加命令黑名单（`rm -rf`/`del /s`/`format`/`shutdown`/`curl`/`wget` 外发请求），或白名单（只允许 `python`/`node`/`pip`/`npm`/`py_compile`/`http.server` 等开发命令）。在 [agent_loop.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py) 的 `_exec_run_command` 前加 `_validate_command` 检查。
4. **本地 token 认证**：server 启动时生成随机 token，写入 `~/.project_generator/server_token`，客户端（CLI/前端）需带 `Authorization: Bearer <token>`。绑定 `127.0.0.1` 已是基础防护，token 是第二层。
5. **工作区配额**：限制单个工作区文件数与总大小，防 LLM 失控写爆磁盘。

### 3.6 代码质量与小改进

- [agent_loop.py:266](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py#L266) 用 `__import__("json")` 不优雅，顶部已可 `import json`。
- [workflow_engine.py:405-430](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py#L405-L430) 在循环内定义 `on_output`/`on_tool_call`/`on_tool_result` 闭包，每次迭代重建，且闭包捕获了循环变量 `step_def`/`state`，Python 闭包延迟绑定可能引发隐患（当前因同步 await 暂无 bug，但建议提到循环外或用默认参数固定）。
- [config.py:23](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/config.py#L23) `STATE_DB_PATH` 定义了但全项目未使用（已改用 state.json），可删除避免误导。
- [health_check.py:27-48](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/health_check.py#L27-L48) `_CODE_REQUIRED_BY_TYPE` 有 `backend_only`，但 [grad_project.yaml:13](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/templates/grad_project.yaml#L13) 注释和 dev-requirement SKILL 都把 `backend_only` 列为合法类型，而 [workspace.py:240-256](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workspace.py#L240-L256) 的 `detect_project_type` 默认 `fullstack`，类型枚举在多处定义但不统一，建议在 config.py 集中定义 `VALID_PROJECT_TYPES`。

---

## 四、实施路线图

按「风险驱动 + 收益成本比」排序，分三批落地。

### 第一批（P0，止血加固，1-2 天）

解决会导致工作流直接挂掉或静默产出错误结果的问题：

1. LLM 调用业务层重试 + 指数退避（1.1）
2. agent_loop 无输出超时看门狗（1.2）
3. `state.json` 原子写 + 备份（1.6）
4. 检查点超时默认改为 `auto_reject`（1.5）
5. 打回反馈注入 rerun（1.5）
6. `run_command` 命令黑名单（3.5）

### 第二批（P1，质量提升，3-5 天）

提升生成质量与可维护性：

7. 健康检查失败原因分类驱动重试 prompt（1.4）
8. 上下文压缩（1.7）
9. 产物契约校验 + 结构化上下文传递（2.1、2.2）
10. rerun 级联失效（2.4）
11. 日志落盘 + 指标记录（3.3）
12. SKILL 元数据头 + few-shot 示例（2.1）

### 第三批（P2，能力扩展，按需）

扩展能力与可观测性：

13. reviewer 角色（2.3）
14. 全局并发控制（3.4）
15. SKILL 版本化 + 多模板示例（2.5）
16. 黄金用例回归测试（2.6）
17. 成本统计（3.3）
18. 本地 token 认证（3.5）

---

## 五、优先级矩阵速查

| 问题 | 发生概率 | 影响 | 修复成本 | 优先级 |
|---|---|---|---|---|
| LLM 调用无重试 | 高 | 步骤直接失败 | 低 | P0 |
| state.json 非原子写 | 中 | 工作流不可恢复 | 低 | P0 |
| 检查点超时自动 approve | 中 | 错误需求扩散 | 低 | P0 |
| 无输出超时缺失 | 中 | 工作流挂死 | 中 | P0 |
| run_command 任意命令 | 低 | 安全风险 | 中 | P0 |
| 健康检查一刀切重试 | 高 | 浪费 token / 修不好 | 中 | P1 |
| 上下文超限 | 高 | 截断 / 报错 | 中 | P1 |
| 产物契约无校验 | 中 | 步骤间断链 | 中 | P1 |
| 单角色自检 | 中 | 漏检语义错误 | 高 | P2 |
| SKILL 无版本 | 低 | 回归风险 | 中 | P2 |

---

> 本方案旨在作为后续迭代的依据，并非一次性全量实施。建议从第一批 6 项入手，每项改动后跑一次 `pga run "做一个待办事项 Web 应用"` 全流程验证，确保不引入回归。

---

## 六、实施完成记录

> 本节记录各批次的落地情况，便于回溯。所有改动均通过 `python -m py_compile` 全量编译与 `python -m tests.test_smoke`（114 项断言）回归。

### 第一批（P0）— 已完成

| # | 项 | 落地位置 |
|---|---|---|
| 1 | LLM 业务层重试 + 指数退避 | [resilience.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/resilience.py) `RetryPolicy` / `retry_async`；[llm_client.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/llm_client.py) 接入 |
| 2 | agent_loop 无输出超时看门狗 | [agent_loop.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py) `on_output_watch` + `inactivity_timeout` |
| 3 | state.json 原子写 + .bak 备份 | [workspace.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workspace.py) `write_file_atomic` / `backup_file`；[workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `_save_state` / `_load_state` 崩溃回退 |
| 4 | 检查点超时默认 auto_reject | [config.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/config.py) `checkpoint_timeout_action="auto_reject"` |
| 5 | 打回反馈注入 rerun | [workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `_build_extra_context` 回填当前步打回反馈 |
| 6 | run_command 命令黑名单 | [security.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/security.py) `validate_command`（含 Windows 盘符 `rm -rf C:\` / 通配 `rm -rf *`） |

### 第二批（P1）— 已完成

| # | 项 | 落地位置 |
|---|---|---|
| 7 | 健康检查失败原因分类驱动重试 prompt | [workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `_build_retry_prompt`（primary_missing / primary_small / companions_missing / syntax_error 四类） |
| 8 | 上下文压缩 | [workspace.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workspace.py) 分层摘要；[agent_loop.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py) token 预算 + 滑动窗口 + 循环检测 |
| 9 | 产物契约校验 + 结构化上下文传递 | [health_check.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/health_check.py) `check_md_sections` / `check_imports_exist` / `check_package_json_scripts`；[workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `_write_step_summary` / `_read_step_summary` |
| 10 | rerun 级联失效 | [workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `rerun_step` 后续步标记 `stale`，`_run_workflow_impl` 遇 stale 自动重跑 |
| 11 | 日志落盘 + 指标记录 | [workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `_broadcast_log` append `run.log`；`StepState` 增 `llm_calls`/`tool_calls`/`duration_sec`/`retries` |
| 12 | SKILL 元数据头 + few-shot 示例 | 四个 SKILL.md 顶部 YAML front matter；[dev-requirement/references/example_requirement.md](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-requirement/references/example_requirement.md)；[skill_loader.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/skill_loader.py) `_parse_front_matter` |

### 第三批（P2）— 已完成

| # | 项 | 落地位置 | 状态 |
|---|---|---|---|
| 13 | reviewer 角色 | [skills/dev-review/SKILL.md](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-review/SKILL.md)（三维度评审：需求覆盖度/设计一致性/潜在缺陷）+ [example_review.md](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/skills/dev-review/references/example_review.md) | 完成 |
| 14 | 全局并发控制 | [server.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py) `_concurrency_sem`（默认 2，`server_max_concurrent_workflows` 可配） | 完成 |
| 15 | SKILL 版本化 + 多模板示例 | front matter `version` 字段已解析；新增 [script_only.yaml](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/templates/script_only.yaml) / [api_only.yaml](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/templates/api_only.yaml)；`StepDef.when` 条件分支；目录级版本化（见 P3-1） | 完成 |
| 16 | 黄金用例回归测试 | [tests/](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/tests/) `test_smoke.py`（158 断言）+ `regress_skill.py` + 4 个 golden 用例（todo_app/calculator/file_rename/crawler） | 完成 |
| 17 | 成本统计 | `StepState` 记 tokens/llm_calls/duration + USD 折算（见 P3-2）；`pga show` 展示版本/成本列与总计 | 完成 |
| 18 | 本地 token 认证 | [server.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py) `_require_auth` + `~/.project_generator/server_token`；`server_enable_auth=false` 可关 | 完成 |

### P2 额外加固（超出原计划）

- **CORS 白名单**：[server.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py) 自定义中间件，默认仅 `http://localhost:*` / `http://127.0.0.1:*`，`server_allowed_origins` 可扩展（原 `*` 已替换）
- **文件读取安全**：`/api/workflows/{id}/files/{path}` 端点拦截 `state.json`/`project.json`/`run.log`/`_summaries/*`/`_failure_snapshot/*` 等受保护文件
- **僵尸任务检测**：server 启动时扫描 `status=running` 但无活后台任务的工作流，标记 `interrupted`
- **WebSocket 主动退订**：WS 关闭时 `unsubscribe_broadcast`，修复旧实现 `finally: pass` 导致的死回调堆积
- **rerun --clean**：[cli.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/cli.py) `pga rerun <id> <skill> --clean` 清理主产物后重跑
- **show 指标汇总**：`pga show` 展示 LLM调用/工具调用/耗时/重试 列与总计
- **命令沙箱增强**：拦截 Windows 盘符 `rm -rf C:\` 与通配 `rm -rf *`
- **skills 列表增强**：`pga skills` 展示版本/主产物/描述（跳过 front matter）

### 验证

```bash
# 全量编译
python -m py_compile agent/*.py tests/*.py

# 冒烟测试（114 项，不调 LLM）
python -m tests.test_smoke

# golden 用例 dry-run（不调 LLM）
python -m tests.regress_skill dev-requirement --all --dry-run

# golden 用例列表
python -m tests.regress_skill --list
```

### 第四批（P3）— 已完成

原 P2 表中标记「按需/未做」的四项已全部落地，验证规模从 114 断言扩到 158 断言。

| # | 项 | 落地位置 | 状态 |
|---|---|---|---|
| P3-1 | SKILL 目录级版本化 | [skill_loader.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/skill_loader.py) `_parse_semver` / `list_skill_versions` / `resolve_skill_path`（双布局：平铺 `skills/<name>/SKILL.md` + 版本目录 `skills/<name>/<ver>/SKILL.md`，semver 降序排序，无版本目录时回退平铺）；[workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `StepState.skill_version` 记录每步实际版本，`_run_single_step` 启动时解析并写回，`rerun_step(latest=True)` 清空版本触发重新解析到最新；[cli.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/cli.py) `pga rerun <id> <skill> --latest` | 完成 |
| P3-2 | USD 成本折算 | [config.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/config.py) `MODEL_PRICING` 价目表（DeepSeek/OpenAI/Anthropic/Qwen/Moonshot，USD/1M tokens）+ `lookup_model_pricing`（子串匹配，大小写不敏感）+ `LLMConfig.price_input_per_1m`/`price_output_per_1m`（<0 触发自动查表）+ `estimate_cost`；[agent_loop.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/agent_loop.py) `AgentRunResult.prompt_tokens`/`completion_tokens` 从 `resp.usage` 累计；[workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `StepState.prompt_tokens`/`completion_tokens`/`cost_usd` 跨 attempt 累加，`WorkflowState.total_cost_usd` 完成时刷新 + `computed_cost_usd` 实时属性；[cli.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/cli.py) `pga show` 展示版本/成本列与总计 | 完成 |
| P3-3 | LLM-as-judge 语义评估 | [tests/llm_judge.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/tests/llm_judge.py) 五维度评分（需求覆盖度/设计一致性/代码质量/可运行性/文档完整度，0-10 分），`temperature=0.0` 提高可复现性，强制 JSON 输出，记录写入 `tests/judge_history.jsonl`；`--trend` 查看历史趋势（均值汇总），`--case` 按 golden 用例过滤 | 完成 |
| P3-4 | 结构化检查点响应 schema | [workflow_engine.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/workflow_engine.py) `normalize_checkpoint_response` 归一化新旧 schema（`action: approve\|reject\|revise` + `target_section` + `severity: blocker\|major\|minor\|nit` + `specific_issues[{file,line,issue,suggestion}]`，旧 `approved` 字段自动转换并保留向后兼容）；`_run_single_step` 检查点分支把结构化反馈拼成多段注入 CONTEXT.md；[server.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/server.py) `CheckpointRequest` 含新字段；[cli.py](file:///f:/Cursor%20Files/Github/ProjectGeneratorAgent/agent/cli.py) `pga revise <id> <反馈> --target-section --severity` | 完成 |

### P3 验证

```bash
# 全量编译
python -m py_compile agent/*.py tests/*.py

# 冒烟测试（158 项，不调 LLM；含版本化/价目/检查点归一化用例）
python -m tests.test_smoke

# golden 用例 dry-run（4 个，不调 LLM）
python -m tests.regress_skill dev-requirement --all --dry-run

# LLM-as-judge（需已配置 API Key 且有完成的工作流）
python -m tests.llm_judge <workflow_id> --requirement "..." --case todo_app
python -m tests.llm_judge --trend
```

### 仍按需（未纳入本轮）

- **SKILL 多版本共存实践**：目录级版本化机制已就绪，但当前 5 个 skill 均为平铺布局。若未来 SKILL.md 有破坏性改动，可新建 `skills/dev-requirement/2.0.0/SKILL.md` 并保留 `1.0.0/`，旧工作流 rerun 沿用原版本，新工作流默认取最新。
- **LLM-as-judge 阈值告警**：当前仅记录趋势，未设回归告警阈值。可在 CI 中加 `--min-score` 失败门禁，或对比上次均值下降超 1 分时告警。
