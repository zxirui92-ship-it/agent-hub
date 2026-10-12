# 第一阶段开发交付报告

交付日期：2026-10-12（Asia/Tokyo）。状态：本阶段功能已实现并验证，公共契约仍为待小组评审的候选版本。

## 需求审查结论

工作目录 `D:\agent 项目` 初始为空，没有仓库代码、测试、依赖、公共模型或 AGENTS.md，需要新建工程骨架。
用户重写的 PRD 原样保存在 `docs/requirement.md`，原始作业保存在 `docs/original_assignment.md`。已用 SHA-256 比较确认两份副本与用户源文件完全一致。
用户粘贴的第一阶段开发指令是本轮实施授权；PRD 和原始作业提供需求上下文，不能将完整课程交付误作本轮范围。

没有阻塞性冲突。按用户指令使用 `hub_platform/`，避免 PRD 建议的 `platform/` 遮蔽标准库；真实 LLM、LangGraph、七种架构及完整恢复延后，不改变它们最终的课程验收要求。
目录不是已有 Git 仓库，本轮没有自动初始化、提交、推送或伪造课程所需的五次提交记录。

## 已实现并验证

- Pydantic 公共模型：AgentRequest、AgentResult、CapabilityManifest、ExecutionPlan、ExecutionStep、StepStatus、结构化错误和报告；AgentModule 为 Protocol。
- 独立注册表：注册、查找、列表、Manifest 快照、重复注册和未知能力错误。
- 七个无外部依赖的 Mock：FAQ、订单物流、周报、网关、大促方案、经营融合、退款审批。
- 验证器：计划结构、唯一步骤、能力存在、依赖存在、无环、上游引用、输出字段与类型、输入数据、步骤数量。
- 顺序拓扑执行器：字面值/引用解析、数据深复制、输入输出校验、每步状态、原始输出、关联 ID、事件轨迹、叶子结果汇总。
- 明确失败和依赖跳过；M7 >500 等待审核，待续下游保持 pending，独立分支继续运行。
- JSON 计划 CLI，文本摘要、完整 JSON、能力清单、退出码、四份可复现演示 Fixture。
- 注册任意新能力的适配器测试及菱形依赖图测试，证明调度不绑定七个模块名称或两条固定链路。

## 架构和接口

依赖关系为 `公共契约 ← 注册表/验证器/执行器 ← CLI 组装入口`；模块通过 `invoke(AgentRequest) -> AgentResult` 接入。
平台根据注册信息调度，不导入模块内部流程。CLI 才导入测试 Mock。

采用同步接口作为暂定实现，未来异步模块需提供适配器或经过团队评审统一改为异步边界。没有增加通用 Agent 基类。
Request 包含 request_id/task_id/trace_id/capability_id/payload/context；Result 包含对应关联信息及 completed/failed/waiting_approval、data、error 和等待原因。
Manifest 声明能力元数据、输入输出 Schema、前提、副作用、执行模式、恢复标志及 owner。
Plan 使用 `literal` 或 `step.data.field` 引用绑定；不执行字符串中的代码。

完整定义、相对 PRD 的字段兼容影响、Schema 子集、错误列表和状态聚合口径见 `docs/interface_contract.md`；架构图见 `docs/phase1_architecture.md`。

## 实际验证结果

测试环境：Windows / Python 3.14.5 / Pydantic 2.14.1 / jsonschema 4.26.0 / pytest 9.1.1。
精确测试依赖记录在 `requirements-tested.txt`，声明依赖范围在 `requirements.txt` 和 `pyproject.toml`。
项目声明 Python 3.10+，本轮未运行跨 Python 版本矩阵。

```text
Command: .\.venv\Scripts\python.exe -m pytest -q
65 passed in 4.52s
```

最终测试没有失败或警告。初次运行曾出现 64 passed / 1 setup error（沙箱系统临时目录权限）及一条 pytest 参数化弃用警告；已分别通过项目专用临时目录和 list 参数修复。
环境安装时遇到 ensurepip 和沙箱网络限制，已补齐 venv 的依赖及 pip，没有修改全局 Python 包。

|实际 CLI 场景|观察结果|退出码|记录|
|---|---|---:|---|
|经营融合→周报→大促|completed；顺序由依赖决定，周报内容传入方案|0|tests/artifacts/operations.json|
|订单→699 元退款|waiting_approval；保留订单和审批输出|3|tests/artifacts/refund_waiting.json|
|不存在订单→退款|订单 failed，退款 skipped|1|tests/artifacts/failure.json|
|未知能力|UNKNOWN_CAPABILITY，在调用前拒绝|2|tests/artifacts/invalid_plan.json|

测试日志位于 `tests/artifacts/pytest.txt`。CLI 四种退出码已在实际运行脚本中逐项检查。

## 可直接运行的命令

```powershell
Set-Location 'D:\agent 项目'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m hub_platform --list-capabilities
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/failure.json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/invalid_plan.json
```

加 `--json` 输出完整报告，加 `--max-steps N` 调整默认 32 步上限。首次安装及真实适配器接入示例见 README。

## 新增文件清单

初始目录为空，以下均为新增文件；没有改写组员代码。

|分类|文件|
|---|---|
|项目配置|README.md、requirements.txt、requirements-tested.txt、pyproject.toml、.gitignore|
|公共契约|common/__init__.py、common/contracts.py|
|平台|hub_platform/__init__.py、hub_platform/__main__.py、hub_platform/errors.py、hub_platform/schema.py、hub_platform/registry.py、hub_platform/validator.py、hub_platform/executor.py、hub_platform/cli.py|
|测试基础|tests/__init__.py、tests/conftest.py|
|Mock|tests/mocks/__init__.py、tests/mocks/agents.py|
|测试用例|tests/contract/test_contracts.py、tests/integration/test_validator.py、tests/integration/test_executor.py、tests/integration/test_cli.py|
|计划 Fixture|tests/fixtures/operations.json、tests/fixtures/refund_waiting.json、tests/fixtures/failure.json、tests/fixtures/invalid_plan.json|
|需求副本|docs/requirement.md、docs/original_assignment.md|
|开发文档|docs/interface_contract.md、docs/phase1_architecture.md、docs/phase1_delivery.md|
|实际验证记录|tests/artifacts/pytest.txt、tests/artifacts/operations.json、tests/artifacts/refund_waiting.json、tests/artifacts/failure.json、tests/artifacts/invalid_plan.json|
|工作状态|task_plan.md、findings.md、progress.md|

`.venv/`、`.pytest_cache/`、`__pycache__/` 为本地生成内容，已配置 Git 忽略。

## 未实现及已知限制

- 没有自然语言 Router / LLM Dynamic Planner，没有真实 M1–M7 内部架构或真实工具服务。Mock 的业务返回不能证明课程七架构验收完成。
- 没有 resume、LangGraph checkpoint、回滚、持久化、审批决策入口或幂等控制；保存 JSON 报告不等于断点恢复。再次执行会重新调用模块。
- 顺序同步调用，没有并行、分布式队列、超时、取消和自动重试；未来真实模块卡住时会阻塞本次运行。
- Schema 是明确支持的子集，不接受 `$ref`/`$defs`/联合类型；团队应先确认是否满足实际模块输出。引用值约束在运行时检查，静态阶段不证明任意 Schema 的包含关系。
- Mock CLI 依赖完整源码中的 tests 包；核心包可以独立使用，但单独发布 wheel 不提供 Mock 演示入口和 Fixture。
- 当前能力异常类型/消息进入本地执行报告；真实适配器接入时需确认错误内容不含密钥及敏感数据。未额外建设安全审查流水线。
- 运行环境已验证 Windows Python 3.14.5，尚未验证 Python 3.10–3.13 或其他操作系统。

## 需要用户及组员评审的候选决定

1. 同步 invoke 是否作为共同基线；异步模块由谁负责适配，是否统一迁移。
2. Request 增加 trace_id、Result 增加 task_id、data 非空对象、结构化 error、waiting_reason 是否接受。
3. Manifest 的能力 ID、owner、版本管理和业务 Schema 子集是否满足各模块的数据契约。
4. 等待只阻塞依赖分支、失败与等待并存时总体 failed、最终结果仅收集完成叶子的口径是否接受。
5. 32 步默认上限、M2 未命中采用 NOT_FOUND、未来超时/重试/恢复/幂等的责任归属。

这些是交付后评审项，不是对契约冻结的宣告，也不阻塞本轮已授权的基础实现。

## 下一阶段建议范围（尚未开发）

开发单一 LLM Planner 适配入口：读取 Registry 的能力清单，将自然语言目标转换为 ExecutionPlan；始终复用现有 Validator 后再执行。
建立固定题集验证不同模块组合、单步骤、未知能力、错误引用及无效计划；记录计划有效率、能力选择结果和失败原因。
仅在验证失败时实施有次数上限的计划修正，不在本阶段默认加入复杂重规划系统。
先评审候选契约，再逐个接入真实模块；M7 的人工决策、resume 和检查点另设清晰任务，区分状态恢复与真实业务补偿。

本轮至此停止扩展。
