# ICD v1.0 候选接口（未冻结）

本文件描述命名迁移后已实现的接口，供八人团队评审。来源为 PRD 第 5 章，未修改 PRD 业务验收标准。
类型真源是 `common/contracts.py`；模型可通过 `model_json_schema()` 导出。此处尚无冻结或通过评审的声明。

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

`continuation_token` 仅在 waiting_approval 且 supports_resume=true 时必填；不支持恢复时必须为空。所有 Mock supports_resume=false，不生成伪 token。此项是命名草案 §7.2 的明确修订，等待语义不变。Protocol 和 Executor 均无 resume。
即使未来适配器声明支持恢复，当前 Executor 也不会调用恢复入口。

## Manifest 与 Schema 范围

side_effects：read_only / writes_mock_state / requires_approval。execution_mode：immediate / may_wait。
`preconditions` 是给开发者和未来 Planner 的业务描述，不是可执行谓词；实际字段条件用 Schema 表达。
副作用字段是描述，不是本轮的权限系统。M7 表达审批业务语义，但 Mock 没有真实退款副作用。
`owner` 已按 naming_convention §3 填写真实负责人；`version` 为两段 1.0 候选版本，Registry 仅允许每个 capability_id 注册一次，不做多版本协商。

支持 JSON Schema Draft 2020-12 的显式子集：

- 每个节点必须有单一 `type`：object / array / string / number / integer / boolean / null。
- 对象支持 properties、required，必须 additionalProperties=false；输入输出根必须 object。
- 数组必须声明 items，可声明 minItems/maxItems。
- 标量支持 enum、minimum/maximum、minLength/maxLength/pattern；元数据支持 title、description、$schema。
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
|EXECUTION_LIMIT|超过配置步骤上限|
|NOT_FOUND / TOOL_UNAVAILABLE|Mock 订单未命中 / 模拟服务不可用|
|DEPENDENCY_FAILED|依赖失败，下游跳过|
|INTERNAL_ERROR|适配器抛出未约定异常，保留类型与消息，不重试|

代码内的配置和计划异常为 HubError（code、message、可选 step_id）；CLI 转为带 task_id/trace_id 的 ErrorDetail。
Executor 只在适配器 `invoke` 边界捕获未知 Exception，其余错误按具体类型处理；不会伪造成功或静默忽略。


## 本次迁移与类型细则

命名基线来自 PR #1 的 docs/unify-naming-convention-v1（e4c8b87），无需合并该 PR。最新命名与必要修订集中在 naming_convention.md；历史 PRD 的候选命名由其覆盖，业务职责不变。

- m1.faq_chat 替代旧 ID，不保留别名；StepState 替代 StepStatus，状态字面量不变。
- task_id=task-12hex、request_id=req-12hex、trace_id=trace-16hex；小写。plan_id=plan-YYYYMMDD-NNN，step_id=sN，输入引用同步迁移。
- 金额全部为 JSON/Python 整数分，拒绝浮点数（包括 50000.0）与布尔值；M6 revenue_amount/order_count 替代 revenue/orders。
- M2/M7 共用 data/fixtures/order_basic.json；Mock 仅模拟整单退款，refund_amount 与订单金额不同即 INVALID_INPUT，不能由 Planner 降低金额绕过审核。
- M7.data.request_id 是 refund- 前缀业务申请号，外层 request_id 是模块调用号。waiting_approval 时无恢复能力、无 token；下游阻塞但独立分支继续。
- 公共 data 保持对象；各模块核心输出字段和类型见 naming_convention §10.3。M4 result 为字符串，与 Skill.run 返回类型一致。
- TraceEvent 的 sequence/reason 是必要扩展；旧 timestamp/message 改为 ts/reason。事件 request_id 与实际步骤调用关联。
- Registry 不硬编码七能力名单，允许新增测试能力及后续经评审的能力；七模块自身必须采用规定 ID。

公共契约和业务 Schema 同步更新，未经团队正式冻结；没有旧字段适配层。
