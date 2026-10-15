# ICD v1.0 候选接口（未冻结）

本文件描述命名迁移后已实现的接口，供八人团队评审。来源为 PRD 第 5 章，未修改 PRD 业务验收标准。
类型真源是 `common/contracts.py`；模型可通过 `model_json_schema()` 导出。此处尚无冻结或通过评审的声明。

## 2026-10-15 金额单位变更与 M4 格式修复

这是前后端契约的破坏性单位变更，不能只升级其中一端。所有对外 `_amount` 改为元；M2/3/5/6/7 Manifest 版本依次为 2.0/3.0/3.0/2.0/3.0。M1/M4 不受金额字段版本影响。Schema 使用 `type=number, format=cny-yuan`，输入最多两位小数；页面固定显示两位。JSON 数值的尾随零不影响语义。计数仍为严格整数。

`common/money.py` 统一 Decimal 计算、ROUND_HALF_UP 到两位、格式化与已知归档分→元转换。退款边界 499.99/500.00 自动、500.01 等待（高风险仍人工）；申请必须与订单金额一致。超过两位小数输入拒绝而不静默舍入，计算结果如客单价才四舍五入。group02 原始 JSON/Excel 和清单哈希不修改，BusinessData.read 返回元，勿把其返回值当作分重新写回来源归档。自定义订单加载器/M6_DATA_DIR 及新计划需直接提供元。旧进程内会话/计划需重新开始，不接受通过猜测单位的兼容映射。

M4 路由与 code_gen 共用 ChatModel JSON mode；仅兼容一个完整 JSON Markdown 包裹，内容仍须严格符合字段契约。程序校验失败会反馈具体错误给同一模型，最多修正一次（合计两次尝试）。成功校验后才调用 Skill，工具执行不参与该重试。鉴权、限流、余额等服务错误直接返回。失败说明包含路由/Skill 阶段和尝试次数，完整错误关联信息可在前端展开复制。LangGraph 可以实现同类有界循环，本次沿用简单循环，不改变 M7 的图或 Executor。

## 2026-10-14 可选审批恢复扩展

原 `AgentModule.invoke` 保持不变。提供恢复的模块可以实现 `ApprovalResumable.resume_approval(continuation_token: str, decision: ApprovalDecision) -> AgentResult`；当前真实 M7 已接入，Mock M7 仍不支持恢复。平台没有 M7 名称分支。

`ApprovalDecision` 只接受 `approved`（严格布尔）、`reviewer`（非空白字符串）、`material_complete`（严格布尔），禁止额外字段和字符串/数字转布尔。审核决定必须由明确接口提交，Planner 和自然语言“同意”均不能替代人工决定。

模块返回原 request_id/task_id/trace_id/capability_id。等待结果仍满足 may_wait、supports_resume 与 token 规则；M7 每次成功返回结果消费旧 token，仍待审核则发放新 token。已提交决定后的响应失败可用原决定重试，不重跑图。模块拒绝调用时抛 ServiceError 并保留 token；平台不更新已保存等待报告，并透传 retryable；M7 明确允许恢复的临时响应失败也采用此路径。其他失败结果仍终止步骤。未知异常或返回结果违反契约会使该步骤失败并阻断下游，不自动重试。

`Executor.resume(task_id, step_id, decision)` 使用该实例保存的原计划、输入、上下文和步骤记录；不接受从外部导入的报告作为可执行状态。只恢复指定 waiting_approval 步骤，随后拓扑执行 pending 步骤；已完成、已失败及其他等待步骤不重跑。返回报告是深复制快照，保留原关联 ID 和连续事件序号，事件记录审核人、决定与材料标志。业务审核拒绝仍属于 completed + approval_status=rejected，下游可消费拒绝结果；这不等于审批通过。

`Conversation.review(step_id, decision, task_id=None)` 默认审核当前任务，显式 task_id 可审核当前会话历史中的等待任务。`/review` 是其 CLI 入口。接口仅支持同进程串行使用；重启、跨进程恢复、并发审核互斥、审核身份认证与真实支付不在当前范围。`/reset` 丢弃本会话的平台恢复入口，不产生审批决定或支付操作。

## 调用协议与兼容性影响

```python
class AgentModule(Protocol):
    def invoke(self, request: AgentRequest) -> AgentResult: ...
```

采用同步调用：顺序执行简单、Mock 可独立测试、无额外事件循环。真实模块可在自有适配器内部使用自己的架构。
后续若改为异步，需要团队明确统一 `async invoke` 或同步/异步适配边界，并调整 Executor 调用边界及测试；不能直接混入 coroutine 返回值。
现在返回字典、字符串或其他对象会得到 `CONTRACT_MISMATCH`。

相对 PRD 示例的候选差异：

|变化|目的|未来模块的适配影响|
|---|---|---|
|AgentRequest 新增必填 trace_id|请求与结果全链路关联|适配器必须接收并透传|
|AgentResult 新增必填 task_id|校验任务关联|适配器必须透传|
|data 统一为 JSON 对象，默认空对象|避免失败结果中的 null 分支|旧返回 null 需转为空对象|
|error 改为 ErrorDetail|明确错误码和关联信息|旧字典需匹配结构|
|waiting_reason 新增，等待时必填|说明挂起原因|等待结果要明确原因|
|严格拒绝额外字段|避免接口拼写错误被忽略|扩展字段需评审后声明|
|Step ID 限制为 s + 正整数|消除点路径歧义|迁移为 s1、s2 等，依赖关系保持不变|

## 数据模型

|模型|字段与含义|
|---|---|
|AgentRequest|request_id（每次调用唯一）、task_id（本次运行）、trace_id、capability_id、payload（业务 JSON 对象）、context（独立复制的关联元数据）|
|AgentResult|同上四个关联字段；status 为 completed / failed / waiting_approval；data、error、waiting_reason、continuation_token|
|ErrorDetail|code（ErrorCode）、message、retryable、trace_id、task_id、可选 request_id/step_id|
|CapabilityManifest|capability_id、version、name、description、input_schema、output_schema、preconditions、side_effects、execution_mode、supports_resume、owner|
|ExecutionPlan|plan_id、goal、steps（至少一个步骤）|
|ExecutionStep|step_id、capability_id、depends_on（默认空列表）、inputs（字段名到绑定）|
|StepRecord|步骤 ID、能力、依赖、request_id、状态、已解析输入、原始 AgentResult、执行错误、原因|
|ExecutionReport|plan_id、task_id、trace_id、总体状态、所有 StepRecord、events、final_results|

结果规则：仅失败必须携带 error；completed 和 waiting_approval 不得携带 error。仅等待允许 waiting_reason / continuation_token。
错误 request_id/trace_id/task_id 必须与结果一致，Executor 还校验四个关联字段与原请求一致。
失败可保留部分 data；只对 completed 和 waiting_approval 的 data 校验 Manifest 输出 Schema。
违反输出契约时，步骤记为 failed，能合法解析的原始 AgentResult 仍保存在 StepRecord，最终结果不包含该步骤。

`continuation_token` 仅在 waiting_approval 且 supports_resume=true 时必填；不支持恢复时必须为空。所有 Mock supports_resume=false，不生成伪 token。此项是命名草案 §7.2 的明确修订，等待语义不变。基础 invoke 协议不变；Executor 可通过本文件顶部的可选审批扩展继续原计划。

## Manifest 与 Schema 范围

side_effects：read_only / writes_mock_state / requires_approval。execution_mode：immediate / may_wait。
`preconditions` 是给开发者和未来 Planner 的业务描述，不是可执行谓词；实际字段条件用 Schema 表达。
副作用字段是描述，不是本轮的权限系统。M7 表达审批业务语义，但 Mock 没有真实退款副作用。
`owner` 已按 naming_convention §3 填写真实负责人；`version` 使用两段版本号，M3/M5/M7 本地业务接口为 2.0，M1 为 1.1、M2 为 1.2、M4/M6 为 1.0。Registry 仅允许每个 capability_id 注册一次，不做多版本协商；公共 envelope 仍为 v1.0 候选。

支持 JSON Schema Draft 2020-12 的显式子集：

- 每个节点必须有单一 `type`：object / array / string / number / integer / boolean / null。
- 对象支持 properties、required，必须 additionalProperties=false；输入输出根必须 object。
- 数组必须声明 items，可声明 minItems/maxItems。
- 标量支持 enum、minimum/maximum、minLength/maxLength/pattern；字符串额外支持 format=iso-week（真实 ISO 日历周），其他 format 不支持。所有 number 只接受有限值。元数据支持 title、description、$schema。
- 不支持 $ref、$defs、oneOf、anyOf、allOf、类型联合、动态属性、布尔 Schema 或远程引用。

不支持的 Schema 在注册时明确拒绝，绝不静默降级。真实模块若由 Pydantic 自动生成嵌套 `$defs` Schema，需先转换为内联支持子集，或经团队评审扩展 Schema 处理器。
Pydantic 生成的 **ExecutionPlan 自身 Schema** 可用于下一阶段结构化输出，它和 Manifest 的业务数据 Schema 子集是两个不同层次。

## 输入绑定与校验阶段

```json
{"week": {"literal": "2026-W41"}}
```

```json
{"fused_data": {"ref": "s1.data.fused_data"}}
```

字面值可以是任意符合目标业务 Schema 的 JSON 值，包括对象、数组和 null。
引用允许 `step.data` 整个业务对象及 `step.data.field.nested` 字段路径；目标必须是直接或传递依赖。
不支持数组下标、插值、函数、条件表达式或代码执行。对象/数组通过深复制传递，模块不能修改已保存的上游输出或共享 context。

验证器在任何能力被调用前检查：计划模型、步骤数（默认 32，可配置）、唯一 ID、注册能力、有效依赖、无环、必填输入、无额外输入、字面值类型和值约束、引用来源及声明字段、类型与嵌套结构兼容性。
引用类型允许 integer → number，反向不允许；对象检查目标必填字段及未知字段，数组递归检查元素类型。

引用的 enum、数值范围、字符串长度等**值约束**不做静态 Schema 包含关系证明，解析出真实值后、调用下游前进行完整校验。
引用到上游声明的可选字段时，允许计划通过；实际缺失会产生 INVALID_REFERENCE，下游不被调用。

## 执行状态与聚合

步骤状态为 pending → running → completed / failed / waiting_approval；依赖失败产生 skipped。
等待的直接及传递下游保持 pending，有原因但不标记失败；其他无关分支继续执行。
失败与等待同时存在时，总体状态为 failed，各步骤仍保留自己的等待状态。优先级为 failed > waiting_approval > completed。
`final_results` 只收集已完成叶子步骤的业务 data；所有中间结果、部分失败输出及等待输出都保存在 `steps`。
轨迹为有序事件：sequence、ts（带时区 ISO 8601）、level、trace_id、task_id、request_id、step_id、capability_id、status、reason、error_code。
内存快照和 JSON 报告是观察数据，不是可导入恢复的检查点。

## 错误约定

|错误码|场景|
|---|---|
|INVALID_PLAN / INVALID_PLAN_FILE|模型不符 / 文件无法读取或不是合法 JSON|
|DUPLICATE_STEP / INVALID_DEPENDENCY / CYCLIC_DEPENDENCY|步骤或图结构错误|
|UNKNOWN_CAPABILITY / DUPLICATE_CAPABILITY|注册和查询错误|
|INVALID_SCHEMA / UNSUPPORTED_SCHEMA|Manifest Schema 错误或超出本阶段支持范围|
|INVALID_REFERENCE|非上游、未声明字段或运行时字段缺失|
|INVALID_INPUT|必填项、输入值或类型不符|
|CONTRACT_MISMATCH|绑定结构不兼容、返回类型、输出、关联 ID 或等待声明不符|
|EXECUTION_LIMIT|超过平台步骤上限、M2 决策轮次或 M6 融合轮次|
|NOT_FOUND / TOOL_UNAVAILABLE|业务对象/周次不存在，或工具、数据文件、模型服务不可用|
|DEPENDENCY_FAILED|依赖失败，下游跳过|
|INTERNAL_ERROR|适配器抛出未约定异常，保留类型与消息，不重试|

代码内的配置和计划异常为 HubError（code、message、可选 step_id）；CLI 转为带 task_id/trace_id 的 ErrorDetail。
Executor 只在适配器 `invoke` 边界捕获未知 Exception，其余错误按具体类型处理；不会伪造成功或静默忽略。


## 本次迁移与类型细则

命名基线来自 PR #1 的 docs/unify-naming-convention-v1（e4c8b87），无需合并该 PR。最新命名与必要修订集中在 naming_convention.md；历史 PRD 的候选命名由其覆盖，业务职责不变。

- m1.faq_chat 替代旧 ID，不保留别名；StepState 替代 StepStatus，状态字面量不变。
- task_id=task-12hex、request_id=req-12hex、trace_id=trace-16hex；小写。plan_id=plan-YYYYMMDD-NNN（序号最少三位，超过 999 自然扩展），step_id=sN，输入引用同步迁移。
- 所有数值必须有限，拒绝 NaN/±Infinity 和 JSON 指数溢出；金额全部为人民币元（JSON number / Python int 或 float），最多两位小数，拒绝 bool、超过两位小数和超过 999999999999.99 的金额；M6 revenue_amount/order_count 替代 revenue/orders。
- M2/M7 共用安装包 common/fixtures/order_basic.json（data/fixtures/order_basic.json 为同内容源码示例）；Mock 仅模拟整单退款，refund_amount 与订单金额不同即 INVALID_INPUT，不能由 Planner 降低金额绕过审核。
- M7.data.request_id 是 refund- 前缀业务申请号，外层 request_id 是模块调用号。Mock 等待时无恢复能力、无 token；真实 M7 supports_resume=true，等待时返回 token，由同一模块实例接收审批。顶层提供同进程显式 resume；等待期间下游阻塞但独立分支继续。
- 公共 data 保持对象；各模块核心输出字段和类型见 naming_convention §10.3。M4 result 为字符串，与 Skill.run 返回类型一致。
- TraceEvent 的 sequence/reason 是必要扩展；旧 timestamp/message 改为 ts/reason。事件 request_id 与实际步骤调用关联。
- Registry 不硬编码七能力名单，允许新增测试能力及后续经评审的能力；七模块自身必须采用规定 ID。

公共契约和业务 Schema 同步更新，未经团队正式冻结；没有旧字段适配层。

## M4 真实实现接入

实现位于 agents/router，内部 Skill.run(payload: dict) -> str，与对外 invoke 分层。
M4 继续使用相同 common/gateway_contract.py Manifest。默认 live 使用 LLM 根据动态 Skill 描述路由；mock 使用明确前缀作离线演示，不能视为语义路由质量验证。
result 字符串内的 JSON 包含 mode=live/mock/local；服务未配置时 AgentResult.status=failed、error.code=TOOL_UNAVAILABLE，消息明确 not_configured，不降级伪造成功。
read_only 在此指不修改平台或订单业务状态；外部生成服务仍可能产生资源与费用，不代表免费、无远程调用或自动重试许可。
新增 Skill 只修改注册组装入口，不修改 Router 分发代码；平台 CLI 的 --real-m4 同样是组装选项，Executor 不包含 M4 特例。

## M5 真实实现接入（2026-10-13 本地迁移）

M5 真实模块与 Mock 共用 `common/promotion_contract.py` 的 2.0 Manifest，capability_id 保持 `m5.promotion_plan`。本次仅本地统一，未在 Gitee 发布或宣称团队已冻结。

- 输入必填 `goal`（非空白字符串）；可选 `week`、`budget_amount`（非负元（最多两位小数））、`report_markdown`（非空白字符串）、`fused_data`。可选字段不提供时省略，不能填 null。顶层 week 与 fused_data.week 必须是实际存在的 ISO 周，前者表示目标活动周、后者表示历史经营数据期间，二者可以不同并分别传入最终聚合。
- `fused_data` 使用当前 M6 的完整经营视图：week、revenue_amount、order_count、conversion_rate、anomaly。所有对象禁止额外字段，不接受任意无 Schema 数据。
- 输出为 `plan_markdown`、`roles`；roles 是四项数组，每项包含 role、contribution、rationale。角色固定为 product / operation / data / service。contribution 非空；上游格式解析兜底时 rationale 可为空，保留原实现语义。
- 请求和返回的 request_id/task_id/trace_id/capability_id 完整透传；trace_id 只取请求顶层，不从 context 覆盖或在模块内重建。
- 模块返回本地 AgentResult/ErrorDetail；缺少模型配置返回不可重试 TOOL_UNAVAILABLE；服务重试标志按 transport 原样保留；非法请求在任何模型调用前拒绝。
- 旧 Mock 必填 report 改为 goal + 可选 report_markdown；旧 roles 对象改为数组；source_report 输出移除，来源保留在平台 StepRecord.inputs。该变更不兼容旧计划，版本升至 2.0；operations.json 已迁移。
- `PromotionAgent.invoke` 可注册到现有 Registry；模块级 `invoke` 供独立调用。`--real-m5` 只改变组装，Validator/Executor 未增加 M5 特例。

原角色职责、同步派发、消息日志及 Aggregator 流程保留。公开模块输出和接口已离线验证，不代表真实 LLM 内容质量已验收。详细来源及测试见 `m5_interface_alignment.md`。

## 顶部 Planner 与会话协议（2026-10-13）

此协议位于平台层，不改变模块 AgentRequest/AgentResult。

- PlannerDecision：status=ready/needs_clarification/unsupported，message 为公开说明，steps 为 ExecutionStep 数组。仅 ready 有非空步骤。
- PlanningResult：校验后的 decision、可执行 ExecutionPlan 或 null、planning_attempts。
- TurnResult：session_id/task_id/trace_id、状态、message、plan、report、error、planning_attempts。状态还包括 completed/failed/waiting_approval。
- SessionContext：内存 session_id、当前 TaskContext 和历史任务；TaskContext 保存原始消息、计划、执行报告。需要澄清时保留任务关联 ID；业务模块 context 仅接收 session_id。
- plan_id 由平台生成，日期为 UTC，序号最少三位、超过 999 自然扩展；Planner 实例内单调递增，不按日期重置或取模，唯一性范围为实例；task_id/trace_id 是运行关联标识。历史任务输出若需复用，由新计划显式作为 literal 绑定；跨任务 step_id 不构成有效 ref。
- 无效计划只修正模型输出，不调用业务模块；默认修正一次。业务失败与等待状态继续沿用原执行器语义。即使总体为 failed，只要任一步骤仍 waiting_approval，会话后续消息也不得重新规划或重放任务；原报告和各步骤错误全部保留。/new 与 /reset 仍是显式离开当前任务的方式。

源码与 CLI、验收题集和使用边界见 `top_level_planner.md`。会话为进程内状态，不是持久化检查点，支持显式 M7 同进程恢复。

## M3 / M7 清洁导入与业务契约 2.0

- M3 共享 `common/weekly_contract.py`。必填 `fused_data`，保持当前 M6 的扁平视图；可选 `previous_fused_data` 必须为相邻上一 ISO 周的同口径视图。由数据中的 week 确定周次，拒绝上游旧式 `{week: ...}` 和嵌套 order_data/behavior_data。独立 CLI 的 --week 是本地样例加载入口，不是另一套平台契约。
- M3 输出仍为 week/report_markdown/steps；steps 从 list[str] 迁移为对象数组，每项含 step_id、description、status=completed、result_summary、duration_ms。现有经营链没有引用 steps，输入计划无需修改。缺上一周数据时明确标缺失，不混用本地历史样例、不补零。
- M7 共享 `common/refund_contract.py`。输入 order_id/refund_amount/reason 不变；输出 request_id/approval_status/node_trace/state_view 不变，approval_status 增加 rejected。审批驳回属于已完成的业务结果，AgentResult.status=completed；调用、金额校验错误才是 failed。
- 真实 M7 和 Mock 的 input/output schema 相同，仅 supports_resume 不同。真实 M7 的模块私有 submit_decision(token, approved=bool, reviewer=str, material_complete=bool) 在同一进程恢复，返回原始关联 ID 的 AgentResult；每次成功返回审批结果后消费旧 token，再次等待产生新 token。无效输入保留 token；未知/已消费 token 抛出 ServiceError(NOT_FOUND)，因为无法恢复关联 ID。已提交决定后的读取或构造结果失败保留原 token；同一决定重试只读取已提交状态，不再次执行审核。成功返回后仍消费旧 token；若流程再次等待则发放新 token。
- M7 保留原 LangGraph 拓扑、节点轨迹、检查点历史和回滚。静态断点在 manual_review 之前；缺材料时原合规规则触发 reflect，再次等待。自动模拟审核人和打款承诺已删除。默认策略为本地示例：500.00 元阈值、最多三次不通过后驳回。低额高风险订单同样等待人工审核；自动审批不得声称材料齐全。只有 paid/shipped/delivered/completed 状态可退款，未知订单状态按数据契约错误拒绝。
- common/order_data.py 是 M2 真实模块/Mock 与 M7 的同一订单来源。M3/M6 的同名周汇总 order_basic.json 隔离在 data/fixtures/m3/，不覆盖订单事实表。

详细文件取舍、能力边界和复现步骤见 `m3_m7_integration.md`。

### group_02 共享资料补充（2026-10-14）

上文旧 Fixture 行为仍适用于未选择新资料源的运行。设置 `HUB_DATA_DIR` 后，真实 M1/M4 共用 FAQ/政策，真实 M2/M7 共用导入订单事实，M6 使用独立周汇总；Mock 继续使用旧资料，不跨源拼接。配置目录缺数据明确失败。M2 `observations` 中的来源增加 `imported_simulation`，可含物流轨迹与时间；公共输出字段不变。无运单记录仍不能满足现有成功 Schema，返回失败而非空运单。

M6 的 group_02 转化率为 `order_uv / uv`；活动成交额/成本不称为利润 ROI，周汇总不与独立演示明细强行对账。M7 原始导入源阈值仍为 50000 分，读取后为 500.00 元、最大反思次数读取源策略（本源为 2）；高风险小额退款先等待人工核验材料，未付款和退款中订单不自动批准。历史退款仅校验一致性，不导入为自动执行命令。所有调用继续使用统一 `invoke`，Executor 不感知数据源或模块内部差异。

## M1 / M2 / M6 接入（2026-10-14）

- 三个模块保持 `invoke(request: AgentRequest) -> AgentResult`，顶层关联 ID 原样透传。真实模块和 Mock 共用 `common/customer_contract.py`（M1/M2）及 `common/fusion_contract.py`（M6）；M3/M5 的 fused_data 使用同一个融合 Schema。
- M1 Manifest 1.1：仍必填 question，新增可选 session_id；输出仍 answer/session_id。session_id 按 payload → context → 新建顺序取值，格式 sess-12hex。记忆限于同一模块实例的最近六条消息，成功后才写入；不持久化。FAQ/服务政策工具为明确的本地样例，不查实时订单。read_only 不代表模块没有内部会话内存。
- M2 Manifest 1.2：仍必填 order_id，新增可选 query 自然语言意图，不能覆盖绑定的订单 ID；输出增加可选 logistics_availability/warnings。实时决策路径使用 TextModel，每轮返回 action/decision_summary，程序固定 order_id 并执行工具、校验 Observation、判断终止。live 代表模型决策，不代表订单数据来自实时系统；目前工具统一读取订单 Fixture。local 是显式确定性演示，不是模型语义验收。
- M2 的 actions/observations 均为 list[str]；真实 observations 项是 JSON 文本，含轮次、公开动作选择依据、工具观察和模式。错误返回 failed，保留已发生的动作/观察及 error；未知订单不是 completed，轮次耗尽为 EXECUTION_LIMIT。物流查询缺失或记录时间/状态冲突时，订单事实仍可完成返回；tracking_number 为空，logistics_availability 为 unavailable/inconsistent，warnings 必须说明原因。available 必须有非空运单。新资料正常记录返回 available 和空 warnings；旧 Fixture/Mock 可省略这两个可选字段。源文件损坏或未知订单仍失败。
- M6 Manifest 1.0：输入仍必填 week，输出仍平面 fused_data 与两个 list[str]。真实 update_events 项为 JSON 文本，包含 ts/event/key/author，记录 read/process/write/react，时间带时区。缺周次为 NOT_FOUND；非法 ISO 周为 INVALID_INPUT；未完成融合为 EXECUTION_LIMIT，不返回部分成功。每次 invoke 使用私有黑板。
- M6 样例源默认使用安装包 common/fixtures/m3 资源（data/fixtures/m3 保留同内容的源码示例），M6_DATA_DIR 可显式更换同结构目录。revenue_amount 沿用成交金额口径，取周汇总 gmv_amount 元（最多两位小数）；conversion_rate 直接使用行为源 0–1 比率。营销预算不能替代实际支出；缺失的 ROI、加购漏斗等不补造，数据缺口写入 anomaly/field_definitions。
- --real-m1/2/6 仅扩充 CLI 组装入口，无核心调度模块特例。来源差异与验收证据见 `m1_m2_m6_integration.md`；本节是契约定义，集成报告不另立规范。


## 2026-10-15 规划金额与结构化输出

配置创建的 Planner 模型启用 JSON object 输出格式；仍须通过 PlannerDecision、PlanValidator 和业务值校验，不能把有效 JSON 当作有效计划。普通客服/报告/营销文本调用保持自由文本。

平台对用户明确写出的单一预算（阿拉伯数字与元/分/万元等人民币单位）用 Decimal 换算并作为 monetary_facts 传给模型。只有计划中恰好一个接受 budget_amount 的消费步骤时，验证该 literal 与明确预算一致；遗漏、错误单位或改写金额进入既有的有界 repair，业务尚不执行。多预算分配、中文数字及无法明确解释的补充不强行猜测或覆盖；仍由语义规划及必要澄清处理。没有模块名称分支，也没有用关键词替代能力选择。

模型依据：[百炼 JSON 输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)、[DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)。
