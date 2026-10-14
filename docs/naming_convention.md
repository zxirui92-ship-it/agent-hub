# 模块接口命名规范

| 文档属性 | 内容                                                      |
| ---- | ------------------------------------------------------- |
| 文档名称 | 模块接口命名规范（Interface Naming Convention）                   |
| 版本   | v1.1（迁移修订草案，待小组评审）                                          |
| 编写日期 | 2026-10-12                                              |
| 适用项目 | Agent Hub / 企业级「智能运营中枢」Agent 平台                         |
| 适用对象 | M1–M7 模块负责人、数据库负责人、平台编排负责人、集成测试负责人                      |
| 上级依据 | 《项目作业：企业级「智能运营中枢」Agent 平台》第四章第 3 条；PRD 第 5 章「公共接口与数据契约」 |

---

## 0. 文档定位

本文档只解决一件事：**七个模块对平台、对彼此、对数据层“叫什么名字”统一**。

它定义的是**词汇表和字符串字面量**，不定义行为逻辑。命名不规范不会导致代码合并不上，但会导致集成时字段对不上、状态判断写错、每接一个模块要写一层适配代码。本文档的目标就是让这类返工不发生。

**范围**：

- 在范围内：能力 ID、工具名、Skill 名、契约字段名、状态与枚举值、错误码、业务数据字段、ID 格式、日志字段、环境变量、文件/目录/测试名。
- 不在范围内：模块内部的算法、Prompt 内容、计划步骤的拆分策略、数据库选型、Git 分支与提交规范（见 `docs/collaboration.md`）。

**强制性**：标记为「**必须**」的条目，任何 PR 违反即打回；标记为「**建议**」的条目由模块负责人自行决定。

---

## 1. 与现有文档的关系（权威边界）

已核对第一阶段代码：ICD 已使用 invoke；本次直接迁移唯一公共契约，并同步修订本文与 ICD。

| 位置                           | 现状                                                 | 本文档口径                                          |
| ---------------------------- | -------------------------------------------------- | ---------------------------------------------- |
| `docs/requirement.md` §5.1                | 模块对外入口 `invoke(request) -> AgentResult`            | **采用**，为模块级统一入口                                |
| `docs/interface_contract.md` | 模块对外入口 `invoke(AgentRequest) -> AgentResult` | **采用**；原 v1.0 对 ICD 的事实描述错误，已更正 |
| 作业要求 §三 M4                   | Skill 层 `class Skill: def run(self, input) -> str` | **采用**，但仅限 M4 内部 Skill；M4 模块对平台仍走 `invoke`     |
| `docs/requirement.md` §5.1                | 只有同步 `def invoke`                                  | 沿用；D-04（同步/异步）未决前，**所有模块先按同步实现**，异步由平台适配层包装    |

> `invoke` 与 `run` 并不矛盾：`invoke` 是**模块对平台**的边界，`run` 是**M4 内部 Skill 对 Router** 的边界。两者层级不同，命名各自独立。

---

## 2. 命名总则（风格基线）

1. 所有接口相关的标识符**必须**使用英文小写 + 下划线（`snake_case`），不使用拼音、不使用中文、不使用空格与连字符。
2. 一律使用**美式拼写**（`color` 不写 `colour`，`canceled` 不写 `cancelled`）。
3. 使用**单数**形式命名业务对象（`order` 不写 `orders`），使用**复数**形式命名列表/集合（`items`、`steps`）。
4. 不使用无意义缩写。允许的缩写白名单：`id`、`url`、`api`、`llm`、`kb`（知识库）、`sku`、`faq`、`mcp`。其余缩写由评审决定。
5. 不使用否定式与双重否定（`is_not_valid` → `is_invalid`）。
6. 名称长度通常 **3–40 字符**。特定规则优先：Python 类名、常量、错误码、含点能力 ID、含连字符 ID 和 s1/ts 等已明确字段按对应章节执行。

---

## 3. 模块标识与责任人

模块代号 `M1`–`M7` 为**对外唯一代号**，禁止使用 `module1`、`agent_1`、`客服模块` 等变体。

| 模块代号 | 模块名称                  | 代码路径                                       | 能力 ID 前缀 | 负责人 |
| ---- | --------------------- | ------------------------------------------ | -------- | --- |
| M1   | 单 Agent 智能客服（简单会话）    | `agents/single_agent.py`                   | `m1.`    | 张新宇 |
| M2   | ReAct 实时业务查询          | `agents/react_agent.py`                    | `m2.`    | 董超  |
| M3   | Plan\&Execute 周报生成    | `agents/plan_execute.py`                   | `m3.`    | 邵子谦 |
| M4   | Router+Skill 能力网关     | `agents/router/` + `agents/router/skills/` | `m4.`    | 张熙睿 |
| M5   | Multi-Agent 大促方案协同    | `agents/multi_agent.py`                    | `m5.`    | 程炜  |
| M6   | Blackboard 数据融合       | `agents/blackboard.py`                     | `m6.`    | 奉逸飞 |
| M7   | Graph/Workflow 退款合规流程 | `agents/workflow/`                         | `m7.`    | 郑江  |
| —    | 数据库 / Mock 数据层        | `data/fixtures/`、`common/` 数据访问部分          | —        | 李泽源 |

**规则**：

- 代码中的模块标识**必须**用小写 `m1`–`m7`；文档和答辩中的展示名可用大写 `M1`–`M7`。
- 模块代号后**必须**跟点号再跟业务能力名，格式 `m{n}.{capability}`。

---

## 4. 能力 ID（`capability_id`）命名 —— 本文档核心

### 4.1 语法

```
m{n}.{business_capability}

m      字面量，小写
{n}    模块序号，1–7 的单个数字，不补零（m1 而非 m01）
.      分隔符，且仅此一个
business_capability  小写字母、数字、下划线组成，2–3 段，段内 snake_case
```

### 4.2 硬性约束

1. **按业务能力命名，不按技术架构命名。** 用 `m2.order_tracking`，禁止 `m2.react_agent`、`m5.multi_agent` —— Planner 是按任务语义选择能力的，技术名词无法被选择。
2. **不带版本号**。版本通过 Manifest 的 `version` 字段表达，禁止 `m2.order_tracking_v2`。
3. **全局唯一**。跨模块不得重名（前缀已保证）。
4. 长度**不超过 40 字符**，只允许一段点号分隔符。

### 4.3 全项目能力 ID 清单（冻结，新增须走评审）

| capability_id           | 模块 | 能力描述                 | 负责人 |
| ----------------------- | -- | -------------------- | --- |
| `m1.faq_chat`           | M1 | FAQ 与闲聊多轮应答          | 张新宇 |
| `m2.order_tracking`     | M2 | 订单与物流实时查询            | 董超  |
| `m3.weekly_report`      | M3 | 运营周报生成               | 邵子谦 |
| `m4.capability_gateway` | M4 | 统一能力网关（搜索/知识库/代码/生图） | 张熙睿 |
| `m5.promotion_plan`     | M5 | 大促方案多角色协同            | 程炜  |
| `m6.data_fusion`        | M6 | 多源数据融合               | 奉逸飞 |
| `m7.refund_approval`    | M7 | 退款合规审批               | 郑江  |

各模块**必须**使用上表 ID 注册能力，不得自行改写。Registry 是通用机制，允许扩展与测试能力注册；上表约束七个业务模块，不在 Executor 中硬编码能力白名单。

### 4.4 契约版本号

Manifest 的 `version` 使用 `MAJOR.MINOR` 两段：

- `MAJOR`：破坏性变更（字段删除、类型变更、状态语义变更）→ 递增，需评审。
- `MINOR`：向后兼容的新增（新字段、新错误码）→ 递增。

示例：`"version": "1.0"`。

2026-10-13 本地 M5 接入修订：M5 Manifest 升为 `2.0`（旧 Mock 的入参和 roles 类型发生破坏性变更），其他模块仍为 `1.0`。这不是团队远端的冻结记录，迁移说明见 `m5_interface_alignment.md`。

---

## 5. 工具（Tool）命名

工具名**必须**为 `snake_case`，采用 `{动词}_{业务对象}` 结构。

### 5.1 动词白名单

| 动词        | 语义               | 副作用          |
| --------- | ---------------- | ------------ |
| `get_`    | 取单个已知对象          | 只读           |
| `query_`  | 按条件检索            | 只读           |
| `lookup_` | 查静态/参考数据（FAQ、政策） | 只读           |
| `list_`   | 列出一组对象           | 只读           |
| `search_` | 全文/模糊搜索          | 只读           |
| `create_` | 新建               | **有副作用，须声明** |
| `update_` | 修改               | **有副作用，须声明** |
| `cancel_` | 取消               | **有副作用，须声明** |

M4 的 `web_search`、`kb_qa`、`code_gen`、`image_gen` 为 §6 明确特例，优先于一般动词规则。

白名单外的动词（如 `fetch_`、`do_`、`handle_`、`process_`、`check_`）**禁止**用于工具名。

### 5.2 各模块工具清单

| 工具名                  | 所属模块 | 说明                   |
| -------------------- | ---- | -------------------- |
| `lookup_faq`         | M1   | 查询 FAQ 标准答案（只读 Mock） |
| `get_service_policy` | M1   | 获取服务政策条款（只读 Mock）    |
| `query_order`        | M2   | 查询订单基础事实（只读）         |
| `query_logistics`    | M2   | 查询物流状态（只读）           |
| `web_search`         | M4   | 联网搜索 Skill           |
| `kb_qa`              | M4   | 企业知识库问答 Skill        |
| `code_gen`           | M4   | 代码生成 Skill           |
| `image_gen`          | M4   | 图片生成 Skill           |

### 5.3 工具契约对象命名

工具的请求/响应模型**必须**为 `{ToolName}Request` / `{ToolName}Response`，PascalCase：

```python
class QueryOrderRequest(BaseModel):
    order_id: str

class QueryOrderResponse(BaseModel):
    order_id: str
    order_status: str
    tracking_number: str | None = None
```

---

## 6. Skill 命名（M4 专用）

作业要求 M4 的 Skill 走统一接口 `class Skill: def run(self, input) -> str`。

| 项          | 规范                                                                                     |
| ---------- | -------------------------------------------------------------------------------------- |
| Skill 类名   | `{Name}Skill`，PascalCase，如 `WebSearchSkill`、`KbQaSkill`、`CodeGenSkill`、`ImageGenSkill` |
| Skill 注册名  | 与 §5.2 的工具名一致（`web_search` 等），**必须**两侧同名                                               |
| Skill 实现文件 | `agents/router/skills/{skill_name}.py`，如 `web_search.py`                               |
| Skill 统一入口 | `run(self, payload: dict) -> str`，签名不得改动                                               |
| Skill 归类常量 | `SKILL_CATEGORIES`，`UPPER_SNAKE_CASE`                                                  |

**关键约束**：新增 Skill **必须**只新增文件 + 一行注册，不得修改 Router 主逻辑（作业硬性验收点）。Router 内部**禁止**出现 `if skill_name == "..."` 式的模块名分支。

---

## 7. 平台契约字段命名

### 7.1 `AgentRequest`

| 字段              | 类型   | 必须 | 说明             |
| --------------- | ---- | -- | -------------- |
| `request_id`    | str  | 是  | 单次请求标识，见 §11   |
| `task_id`       | str  | 是  | 所属平台任务标识       |
| `capability_id` | str  | 是  | §4 定义的业务能力 ID  |
| `payload`       | dict | 是  | 业务入参，键名遵循 §10  |
| `context`       | dict | 否  | 非敏感关联元数据，默认空字典 |
| `trace_id` | str | 是 | 平台入口生成，全链路原样透传 |

### 7.2 `AgentResult`

| 字段                   | 类型          | 必须 | 说明                                       |
| -------------------- | ----------- | -- | ---------------------------------------- |
| `request_id`         | str         | 是  | 原样回传输入的 `request_id`                     |
| `capability_id`      | str         | 是  | 原样回传                                     |
| `status`             | str         | 是  | §8 枚举，**不得**返回其他值                        |
| `data` | dict | 否 | JSON 对象，默认 {}；不使用 null，保持现有确定性契约 |
| `error` | ErrorDetail 或 None | 否 | 失败时必填，含 code/message/retryable 与关联字段 |
| `trace_id`           | str         | 是  | 见 §11                                    |
| `continuation_token` | str 或 None | 否 | 仅等待状态且 supports_resume=true 时必填；不支持恢复时必须为空 |
| `task_id` | str | 是 | 原样回传请求 task_id |
| `waiting_reason` | str 或 None | 否 | 等待时必须说明原因，其余状态为空 |

### 7.3 Capability Manifest

字段名**必须**为：`capability_id`、`version`、`name`、`description`、`input_schema`、`output_schema`、`preconditions`、`side_effects`、`execution_mode`、`supports_resume`、`owner`。

- `side_effects` 取值仅限：`read_only` / `writes_mock_state` / `requires_approval`。
- `execution_mode` 取值仅限：`immediate` / `may_wait`。
- `owner` 填真实姓名（如 `"董超"`），便于变更时定位责任人。

### 7.4 Execution Plan

| 字段              | 规范                                                                     |
| --------------- | ---------------------------------------------------------------------- |
| `plan_id`       | `plan-{yyyyMMdd}-{3位序号}`，如 `plan-20261012-001`                         |
| `goal`          | 自然语言原样保留用户目标                                                           |
| `steps[]`       | 步骤数组                                                                   |
| `step_id`       | `s` + 从 1 开始的序号，如 `s1`、`s2`；单计划内唯一                                     |
| `capability_id` | 必须命中 §4.3 清单                                                           |
| `depends_on`    | `step_id` 数组，无依赖写 `[]`                                                 |
| `inputs`        | 每项的值只能是 `{"literal": <值>}` 或 `{"ref": "<step_id>.data.<字段路径>"}` 两种形态之一 |

---

## 8. 状态与枚举值命名

**本节解决当前的状态词表冲突**：`done` 与 `completed` 混用必须终止。

| 枚举                           | 适用范围           | 允许取值                                                                  |
| ---------------------------- | -------------- | --------------------------------------------------------------------- |
| 模块返回状态（`AgentResult.status`） | 模块 → 平台的返回     | `completed`、`failed`、`waiting_approval`                               |
| 步骤执行状态（`StepState`）          | 平台 Executor 内部 | `pending`、`running`、`completed`、`failed`、`waiting_approval`、`skipped` |
| 审核决策（M7）                     | 人工审核结果         | `approved`、`rejected`                                                 |

**硬性约束**：

1. 枚举值**必须**为小写 `snake_case`。
2. 模块/步骤生命周期中**禁止**使用 `done`、`finished`、`success`、`ok`、`error`、`pending_approval`、`waiting`、`pass`、`fail`。
3. `waiting_approval` 是**正常挂起**，不是失败，也不是成功。判断时必须单独分支。
4. 业务对象状态不等于执行状态：订单可为 paid；审批输出 approval_status 可为 approved/rejected/waiting_approval，后者不是人工决策。
5. 枚举值一旦进入契约，**禁止**改名；新增值需评审。

---

## 9. 错误码命名

错误码**必须**为 `UPPER_SNAKE_CASE` 字符串，全项目共用一张表：

| 错误码                 | 语义                | `retryable` 默认 |
| ------------------- | ----------------- | -------------- |
| `INVALID_INPUT`     | 入参缺失或类型错误         | `false`        |
| `NOT_FOUND`         | 目标业务对象不存在         | `false`        |
| `TOOL_UNAVAILABLE`  | 依赖工具/外部服务不可用      | `true`         |
| `DEPENDENCY_FAILED` | 上游步骤失败导致本步未执行     | `false`        |
| `EXECUTION_LIMIT`   | 达到轮次/步骤/超时上限      | `false`        |
| `CONTRACT_MISMATCH` | 请求不符合能力声明的 Schema | `false`        |
| `INTERNAL_ERROR`    | 未归类的内部异常          | `true`         |

**约束**：

- 禁止自定义表外错误码。确需新增的走评审并追加至本表。
- `error.message` 面向开发者，可含上下文；**禁止**包含密钥、完整堆栈或模型隐藏推理。
- 错误码常量在代码中定义于 `common/errors.py`，类名 `ErrorCode`，成员名与错误码字符串同名。

---


平台必要补充项（retryable 默认均为 false，集中定义在同一 ErrorCode）：

| 错误码 | 场景 |
| --- | --- |
| UNKNOWN_CAPABILITY / DUPLICATE_CAPABILITY | 能力未注册 / 重复注册 |
| INVALID_PLAN / INVALID_PLAN_FILE | 计划模型错误 / 文件读取或 JSON 错误 |
| DUPLICATE_STEP / INVALID_DEPENDENCY / CYCLIC_DEPENDENCY | 步骤与依赖图错误 |
| INVALID_SCHEMA / UNSUPPORTED_SCHEMA | 非法 Schema / 超出支持子集 |
| INVALID_REFERENCE | 引用来源、字段或运行时字段错误 |

ErrorDetail 还包含 trace_id、task_id、可选 request_id/step_id。模块失败必须回传本次 request_id；尚未产生模块调用的计划错误可为空。retryable 是建议元数据，当前 Executor 不自动重试。

## 10. 业务数据字段命名

### 10.1 通用后缀规则

| 后缀                           | 含义               | 示例                                        |
| ---------------------------- | ---------------- | ----------------------------------------- |
| `_id`                        | 业务对象标识           | `order_id`、`customer_id`、`sku_id`         |
| `_at`                        | 时间点，ISO 8601 含时区 | `created_at`、`paid_at`                    |
| `_date`                      | 日期，`YYYY-MM-DD`  | `report_date`                             |
| `_amount`                    | 金额，**整数，单位「分」**  | `refund_amount`、`budget_amount`           |
| `_count`                     | 计数，整数            | `order_count`、`retry_count`               |
| `_status`                    | 状态，取值见 §8        | `order_status`、`approval_status`          |
| `_url`                       | 链接               | `source_url`、`image_url`                  |
| `is_` / `has_` / `supports_` | 布尔               | `is_anomaly`、`has_risk`、`supports_resume` |

### 10.2 金额与时间的强制约定

- **金额一律用整数「分」**，字段名以 `_amount` 结尾。禁止用浮点数表示金额。展示层负责转「元」。  
  例：退款 500 元写 `50000`，M7 阈值判断写 `refund_amount <= 50000`。
- **时间一律用 ISO 8601 字符串并带时区**，如 `2026-10-12T16:05:00+08:00`。禁止 Unix 时间戳裸整数、禁止 `10/12/2026` 之类的本地格式。
- **周次用 ISO 周字符串**，字段名 `week`，格式 `YYYY-Www`（如 `2026-W41`），周内两位补零。

### 10.3 各模块核心输出字段（冻结）

| capability_id           | 必填输出字段                                                                             |
| ----------------------- | ---------------------------------------------------------------------------------- |
| `m1.faq_chat`           | `answer`、`session_id`                                                              |
| `m2.order_tracking`     | `order_id`、`order_status`、`tracking_number`、`actions`、`observations`、`stop_reason` |
| `m3.weekly_report`      | `week`、`report_markdown`、`steps`                                                   |
| `m4.capability_gateway` | `skill_name`、`result`、`route_reason`                                               |
| `m5.promotion_plan`     | `plan_markdown`、`roles`                                                            |
| `m6.data_fusion`        | `fused_data`、`field_definitions`、`update_events`                                   |
| `m7.refund_approval`    | `request_id`、`approval_status`、`node_trace`、`state_view`                           |

结果类型统一：M1 两字段为 str；M2 标识/状态/追踪号/终止原因为 str，actions/observations 为 list[str]；M3 week/report_markdown 为 str、steps 为对象数组，每项含 step_id/description/status/result_summary/duration_ms（业务契约 2.0）；M4 三字段均为 str（result 可为 Skill 的 JSON 文本）；M5 plan_markdown 为 str、roles 为四角色数组，每项含 role/contribution/rationale，角色值为 product/operation/data/service；M6 fused_data 为对象、field_definitions/update_events 为 list[str]；M7 request_id/approval_status 为 str、node_trace 为含 node_name 的对象数组、state_view 为对象。

M2 补充 order_amount（整数分）；M7 真实流程和 Mock 都使用本地订单样例，仅支持整单退款，refund_amount 必须等于共享订单事实的 order_amount；部分退款和真实打款不在当前范围。M7.data.request_id 是 refund- 前缀的退款申请 ID，AgentResult.request_id 是 req- 前缀的模块调用 ID，二者不得混用。M7 业务契约 2.0 的 approval_status 为 approved/rejected/waiting_approval，内部尚未审核的状态为 pending；真实模块支持同进程 token 恢复，Mock 不支持。

各模块 `output_schema` **必须**覆盖上表字段，名字不得改动 —— 这是平台 Plan 中 `ref` 表达式能通过校验的前提。

2026-10-14 接入补充：M1/M2 的 1.1 Manifest 分别增加可选 session_id/query，原有必填输入和输出不变。M6 保持 1.0 的平面经营视图；真实 observations（M2）和 update_events（M6）仍为 list[str]，每项允许是可解析的 JSON 文本。M6 的 revenue_amount 指样例源 gmv_amount（成交金额），不是会计收入；conversion_rate 为 0–1 比率，不能与百分数混用。缺少营销实绩/完整漏斗时须明确缺口，不能以预算计算 ROI。具体业务 Schema 集中于 common/customer_contract.py 与 common/fusion_contract.py，并由 Mock 和真实模块共享。

---

## 11. 标识符（ID）命名

| 标识符                  | 格式                       | 生成方         | 生命周期      |
| -------------------- | ------------------------ | ----------- | --------- |
| `task_id`            | `task-{12位小写hex}`        | 平台入口        | 一次用户任务    |
| `request_id`         | `req-{12位小写hex}`         | 平台 Executor | 一次模块调用    |
| `trace_id`           | `trace-{16位小写hex}`       | 平台入口，全链路透传  | 一次链路追踪    |
| `session_id`         | `sess-{12位小写hex}`        | 平台会话层或独立 M1 入口 | 一段多轮会话    |
| `plan_id`            | `plan-{yyyyMMdd}-{3位序号}` | 平台 Planner  | 一份执行计划    |
| `step_id`            | `s{序号}`                  | 平台 Planner  | 计划内唯一     |
| `continuation_token` | 不透明字符串，`cont-{16位小写hex}` | 支持恢复的模块（M7） | 一次挂起-恢复配对 |

**约束**：

1. `trace_id` 在调用链中**原样透传**，任何模块与工具都不得重新生成。
2. 引用关系：一个 `task_id` 对应多次 `request_id`，全部共享同一 `trace_id`。
3. `continuation_token` 对平台**不透明**：平台只负责保存与回传，不解析其内容。
4. `continuation_token` **必须幂等**：同一 token 重复提交同一决策，只产生一次状态迁移。
5. ID 一律小写，禁止大写 hex。

---

## 12. 日志字段命名

结构化日志的键名**必须**使用下列固定词表：

`ts`、`level`、`trace_id`、`task_id`、`request_id`、`capability_id`、`step_id`、`module`、`status`、`tool_name`、`node_name`、`error_code`、`duration_ms`、`iteration`

平台 TraceEvent 额外保留 sequence（事件顺序）和 reason（公开状态说明），不能删除必要诊断信息。request_id 在步骤实际开始处理前为空，随后与 StepRecord 和 AgentResult 一致。平台事件不伪装为 m1–m7 的内部 module 日志。ts 是带时区的 ISO 8601。

模块诊断允许扩展 event/actions/mode，以及 M2 的 round/action/decision_summary/result、M6 黑板的 key/author。这些记录表示公开选择依据与工具事实，不输出隐藏推理。所有模块日志仍携带顶层关联 ID、ts 和 level；不据此修改平台 TraceEvent 的结构。

M5 内部消息事件额外使用 role 表达四角色及 aggregator；其 step_id 是模块内部步骤（s1–s4、agg），通过 request_id 与平台步骤对应，不作为跨模块 ExecutionPlan 的步骤 ID。


**约束**：

- 时间字段**必须**叫 `ts`，不用 `time`、`timestamp`、`created_at`。
- `module` 取值 `m1`–`m7`。
- M2 的推理轨迹三段**必须**用固定键名：`decision_summary`（对应 Thought 阶段）、`action`、`observation`。
- M7 节点轨迹字段为 `node_name`，缓存的全局状态为 `state_view`。
- 日志**禁止**输出 API Key、完整堆栈、模型隐藏推理原文。

---

## 13. 环境变量与配置命名

**必须**为 `UPPER_SNAKE_CASE`，统一在 `.env.example` 声明，走 `python-dotenv` 加载。

| 变量名 | 说明 |
| --- | --- |
| `LLM_API_KEY` | LLM 密钥，**禁止**硬编码入库 |
| `LLM_BASE_URL` | LLM 服务地址 |
| `LLM_MODEL` | 模型名 |
| `LLM_TIMEOUT_SECONDS` | 单次调用超时 |
| `MAX_REACT_ITERATIONS` | M2 最大轮次 |
| `MAX_PLAN_STEPS` | 平台计划最大步骤数 |
| `MAX_REPLAN_TIMES` | 有限重规划次数 |
| `LOG_LEVEL` | 日志级别 |

模块私有配置**必须**加模块前缀，如 `M3_REPORT_MAX_ROWS`。禁止出现 `PLAN_MAX_STEPS` 与 `MAX_PLAN_STEPS` 这类同义异名。

---

## 14. Python 代码内部命名

沿用作业要求，并做细化：

| 对象 | 风格 | 示例 |
| --- | --- | --- |
| 模块、包、函数、变量、参数 | `snake_case` | `query_order`、`max_iterations` |
| 类、异常类、Pydantic 模型、Protocol | `PascalCase` | `ReactAgent`、`AgentResult`、`OrderQueryTool` |
| 常量、枚举成员 | `UPPER_SNAKE_CASE` | `MAX_RETRY`、`ErrorCode.NOT_FOUND` |
| 私有成员 | 前导单下划线 | `_blackboard`、`_internal_step()` |
| 不使用 | 前导双下划线、`l`/`O`/`I` 单字符名 | — |

注册表键按其业务层规则保持小写：capability_id 见 §4，Skill 注册名见 §6。

**模块级统一入口**：每个 M 模块**必须**暴露 `invoke(request: AgentRequest) -> AgentResult`，供平台调用；模块内部函数命名自由，但**禁止**跨模块导入其他 M 模块的内部函数。

---

## 15. 文件、目录与测试命名

### 15.1 目录与文件

作业已指定以下路径，**不得改名**：

```
agents/single_agent.py      # M1
agents/react_agent.py       # M2
agents/plan_execute.py      # M3
agents/router/              # M4
agents/router/skills/       # M4 Skill 插件
agents/multi_agent.py       # M5
agents/blackboard.py        # M6
agents/workflow/            # M7
common/                     # 工具、LLM 封装、日志、数据契约
data/fixtures/              # Mock 数据
tests/                      # 测试
```

- 文件名、目录名一律 `snake_case`。
- Mock 数据文件名：`{domain}_{name}.json`，如 `order_basic.json`、`user_behavior.json`、`marketing_campaign.json`。

### 15.2 测试命名

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| 测试文件 | `test_{模块}_{场景}.py` | `test_m2_react_loop.py` |
| 测试函数 | `test_{被测对象}_{场景}_{预期}()` | `test_query_order_not_found_returns_error()` |
| 测试 ID | 与 PRD 验收项对齐 | `AC-M2-02`、`TEST-PLAT-001` |

---

## 16. 禁用词与同义词统一表

左侧写法**禁止**出现在接口、字段名、日志键与文档示例中，统一改用右侧。

| 禁用 | 统一使用 |
| --- | --- |
| `orderId`、`orderNo`、`oid` | `order_id` |
| `userId`、`uid`、`customer_no` | `customer_id` |
| `done`、`finished`、`success`、`ok` | `completed` |
| `error`、`err`（作为 status） | `failed` |
| `pending_approval`、`waiting`、`on_hold` | `waiting_approval` |
| `pass`、`fail`（作为审核结果） | `approved`、`rejected` |
| `time`、`timestamp`（日志） | `ts` |
| `msg`、`message`（日志） | `error_code` + `error.message` |
| `money`、`price`、`fee` | `{业务}_amount`（整数分） |
| `module1`、`agent1`、`m01` | `m1` |
| `taskId`、`requestId`、`traceId` | `task_id`、`request_id`、`trace_id` |
| `fetch_`、`do_`、`handle_`、`check_`（工具动词） | `get_` / `query_` / `lookup_` |
| `react`、`blackboard`（作为能力 ID） | 按业务命名的 `capability_id` |

---

## 17. 提交前命名自查清单

每个模块负责人提 PR 前逐条确认：

- [ ] 我的能力 ID 与 §4.3 清单一致，未自造。
- [ ] 模块已暴露 `invoke(request: AgentRequest) -> AgentResult`。
- [ ] `status` 只返回 `completed` / `failed` / `waiting_approval`，无 `done`。
- [ ] 输出字段与 §10.3 的必填清单一致，名字未改。
- [ ] 金额字段是整数分，时间字段是带时区的 ISO 8601。
- [ ] 错误码全部来自 §9 表，未自定义。
- [ ] 工具名动词来自 §5.1 白名单。
- [ ] 日志键名来自 §12 词表。
- [ ] 未跨模块导入其他 M 模块的内部函数。
- [ ] Mock 文件名符合 `{domain}_{name}.json`。
- [ ] 未在代码中出现任何密钥；配置项已在 `.env.example` 声明。

---

## 18. 变更与生效

| 级别 | 范围 | 处理 |
| --- | --- | --- |
| N0 私有命名 | 模块内部函数、变量、私有常量 | 模块负责人自行处理 |
| N1 契约命名 | 能力 ID、字段名、枚举值、错误码、工具名 | 先评估影响面，由公共契约负责人审批，同步更新 Mock 与契约测试 |
| N2 命名体系 | 命名风格基线、模块代号、目录结构 | 需小组评审，同步更新本文件与 PRD |

- 本规范与 PRD 第 5 章冲突时，**命名部分以本文件为准**，行为语义部分以 PRD 为准。
- 本文件任何修改**必须**在下方登记。

### 变更记录

| 版本 | 日期 | 变更内容 | 负责人 |
| --- | --- | --- | --- |
| v1.2 | 2026-10-14 | M1/M2 可选输入和会话 ID 来源、M6 数据口径及 JSON 文本事件；共享业务 Schema 和模块诊断字段说明 | 本轮接入 |
| v1.1 | 2026-10-12 | 本轮用户授权迁移：修正 ICD 事实、关联字段、错误码、无恢复例外、Skill 特例、类型与状态边界、金额事实和日志扩展；候选契约仍待团队冻结 | 本轮开发 |
| v1.0 | 2026-10-12 | 首版草案：确立模块代号、能力 ID 清单、状态词表、错误码表、字段与日志命名 | 待指定 |

