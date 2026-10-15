# 接口迁移与 M4 交付记录

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

日期：2026-10-12。工作目录：`D:\模组\agent-hub`；本地分支：`feat/naming-migration-m4`。未推送、未合并 PR、未改写 main。

## 来源与阶段门禁

- 原始 main：`1aaea1f`，原有 65 项测试实际全部通过。
- PR #1 为未合并草稿，命名分支 `docs/unify-naming-convention-v1` 的 head 为 `e4c8b879830a3b10a1ca8eca10f01c642b322218`。规范文件通过 GitHub 连接器读取，以它为迁移基线。
- 直连 GitHub 克隆失败后，从本机干净的同源 `D:\agent 项目` 克隆至当前目录，main SHA 与远程核验一致；原目录保持不变。
- 阶段 A 本地检查点：`6039473`。阶段 A 91 项测试通过后，才开始阶段 B。
- 规范修订只集中于原 naming_convention.md 和 interface_contract.md；本记录描述交付事实，不建立另一套规范。

## 阶段 A：已实现且已测试

1. M1 能力 ID 改为 `m1.faq_chat`，其余六项对齐指定清单；不保留隐式旧 ID 映射。
2. 保留请求 trace_id、结果 task_id/waiting_reason。ErrorDetail 使用集中 ErrorCode、retryable 和 request/task/trace/step 关联字段；模块失败的 request_id 必须对应本次调用。
3. Manifest version 使用两段 `1.0`，owner 填规范中的负责人；side_effects 接受 read_only/writes_mock_state/requires_approval。
4. 统一 task/request/trace/plan/step ID；步骤枚举类为 StepState，生命周期字面量未改变。事件 timestamp/message 迁为 ts/reason，保留 sequence，补充 level/request_id。
5. 金额采用严格整数分，包括拒绝整数值浮点数和 bool。M6 revenue/orders 改为 revenue_amount/order_count；周格式检查为 YYYY-Www。
6. M2/M7 共同读取 data/fixtures/order_basic.json。订单 699 元输出 69900 分。M7 整单退款必须与订单事实一致，不能通过传入小金额绕过审批；49999/50000/50001 分覆盖边界两侧。
7. 七 Mock 的核心输出和 Manifest Schema 完成同步；M7 内层 refund- 申请 ID 与外层 req- 调用 ID 分离。
8. 原有拓扑执行、字面值/引用、深复制、Schema 校验、循环检测、失败传播和等待状态均保留。经营链 Fixture 仍为打乱数组顺序的计划。

### 规范冲突及解决

| 条目 | 处理 |
| --- | --- |
| §1 误称 ICD 使用 run(Task) | 更正为已经存在的 invoke(AgentRequest) -> AgentResult；Skill.run 单独分层 |
| §7 遗漏关联字段和等待原因 | 补齐 trace_id、task_id、waiting_reason，保留 data={} 对象语义 |
| §9 错误码清单不全 | 补充 UNKNOWN_CAPABILITY、DUPLICATE_CAPABILITY、INVALID_PLAN、INVALID_PLAN_FILE、DUPLICATE_STEP、INVALID_DEPENDENCY、CYCLIC_DEPENDENCY、INVALID_SCHEMA、UNSUPPORTED_SCHEMA、INVALID_REFERENCE；集中在 common/errors.py |
| §7.2 强制所有等待结果有 token | supports_resume=true 的等待结果必须有 token；false 必须无 token；Executor 校验一致性，Mock 不伪装恢复 |
| §5 工具动词与 §6 Skill 注册名冲突 | M4 四个规定名称作为明确特例 |
| 一般 snake_case/长度与 s1、ID、类名等冲突 | 特定章节规则优先；注册键保持业务要求的小写 |
| 生命周期与业务状态混用 | 订单 paid 等业务状态独立；approval_status 的 waiting_approval 是等待态，不是人工审批决定 |
| 冻结七业务 ID 与注册表扩展性冲突 | 七个模块必须用冻结 ID；通用 Registry 仍接受新增/测试能力，不在 Executor 写白名单 |
| 日志白名单遗漏现有诊断信息 | 明确 sequence/reason 为必要扩展，平台事件不冒充模块内部日志 |
| §10.3 只列字段而未给完整类型 | 在现有文档中明确最小类型和 M2 的 order_amount；M4 三字段均为 str |

没有遗留会破坏本轮集成的契约冲突。候选契约仍待团队正式冻结；部分退款、真实 M7 状态恢复及其业务规则由后续需求决定。

## 阶段 B：架构与实现状态

```text
agents/
  __init__.py
  router/
    __init__.py
    __main__.py
    agent.py
    config.py
    factory.py
    registry.py
    routing.py
    skills/
      __init__.py
      web_search.py
      kb_qa.py
      code_gen.py
      image_gen.py
      knowledge_sample.json
```

RouterAgent 校验请求后，把输入与当时注册的 Skill 描述交给 IntentRouter；LlmRouter 用公共 ChatModel 选择 Skill，返回 RouteDecision；SkillRegistry 查询并调用 Skill.run；RouterAgent 整理为 AgentResult，并记录选择、完成或失败事件。不会调用 M1–M7，不做平台动态计划。

| 能力 | 已实现 | 本轮验证边界 |
| --- | --- | --- |
| Router | 真实 LLM 路径、描述驱动的动态候选集、未匹配失败、非法选择拒绝 | 模拟 LLM 响应验证结构与契约；尚未用真实模型证明语义路由效果 |
| web_search | Tavily 兼容 JSON 请求、结果归一化、缺配置/服务错误处理 | 仅模拟 HTTP 及明确离线样例；未实际联网搜索 |
| kb_qa | 本地 JSON 条目检索、依据原文回答、来源条目、未命中失败 | 已实际运行本地检索；默认条目为示例，非企业生产知识库 |
| code_gen | 共用 LLM Adapter，根据自然语言请求返回 language/code | 仅模拟模型响应验证；不执行生成代码 |
| image_gen | Images Generations 兼容入口，归一化服务 URL/base64 | 仅模拟 HTTP；Mock 返回真实一像素 PNG 字节并标为 mock，未调用图片服务 |
| Skill Registry | 注册、查询、描述、列表、调用、重复拒绝、输入深复制 | 已测试第 5 个 translate_text Skill；原 Router 无需改动 |
| 平台集成 | 真实 RouterAgent 替换 Mock M4，其余六 Mock 保留 | 已通过 Executor 和 CLI 集成；阶段 B 对 executor.py 的 diff 为空 |

新增 Skill 只需实现文件并在 factory 注册。ExplicitMockRouter 使用明确的 skill_name: 前缀，是离线结构演示，不是关键词语义路由。live 路径不自动退化为 mock。

服务缺配置时返回 failed/TOOL_UNAVAILABLE，消息明确 not_configured。所有配置来自环境变量或 dotenv，密钥不硬编码；HTTP 错误保留状态码类别，不把原始第三方响应/异常对象传给平台。每次外部请求只尝试一次，有可配置超时。

## 测试结果与复现

| 阶段 | 命令（使用本地 .venv 解释器） | 实际结果 | 记录 |
| --- | --- | --- | --- |
| 原始基线 | python -m pytest -q | 65 passed | 本轮运行输出 |
| 阶段 A 门禁 | python -m pytest -q | 91 passed | tests/artifacts/phase_a_pytest.txt |
| 阶段 B | python -m pytest tests/unit tests/integration/test_m4_platform.py tests/live -q | 78 passed, 8 skipped | tests/artifacts/phase_b_pytest.txt |
| 全量回归 | python -m pytest -q | 169 passed, 8 skipped | tests/artifacts/regression_pytest.txt |

所有原有 65 项测试保留并迁移，未删除失败用例。测试默认阻断 socket 连接；子进程测试显式清空外部服务设置，防止 .env 意外启用付费调用。8 个 live 测试必须同时开启 `--run-live` 和 `M4_RUN_LIVE_TESTS=1`；分别覆盖五个真实模型路由场景和搜索/代码/生图实际服务。

**真实外部 API 验证：本轮为 0 次。** 用户尚未选定/提供本轮服务配置，按要求先完成接口、配置和离线测试；没有读取或复用其他项目密钥，没有偷偷调用收费 API。HTTP Adapter 用替身 transport 验证请求、响应、错误码和超时传递，这不等于真实 API 验证。

离线启动：

```powershell
Set-Location 'D:\模组\agent-hub'
$env:M4_MODE='mock'
.\.venv\Scripts\python.exe -m agents.router 'kb_qa: 优惠券可以叠加吗'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/m4_gateway.json --real-m4 --json
.\.venv\Scripts\python.exe -m pytest -q
```

其他四能力命令、环境变量及显式 live 测试命令见 README。独立失败与注册扩展用例位于 tests/unit/test_m4_router.py；平台替换和回归位于 tests/integration/test_m4_platform.py。

## 关键接口与工程决策

```python
AgentModule.invoke(self, request: AgentRequest) -> AgentResult
Skill.run(self, payload: dict) -> str
SkillRegistry.register(self, name: str, description: str, skill: Skill) -> None
SkillRegistry.get(self, name: str) -> Skill
SkillRegistry.describe(self, name: str) -> SkillDescription
SkillRegistry.list_skills(self) -> list[SkillDescription]
SkillRegistry.invoke(self, name: str, payload: dict) -> str
IntentRouter.select(self, query: str, skills: list[SkillDescription]) -> RouteDecision
TextModel.complete(self, system: str, query: str) -> str
```

- 公共错误词表和 M4 Manifest 各自只有一份定义；Mock 与真实 M4 共用 schema。
- 仅新增轻量同步 HTTP/LLM Adapter，无框架重建、复杂 RAG 或异步队列。
- 在 CLI 组装入口替换模块，而非 Executor 中增加 M4 分支。
- M4 read_only 指不改业务状态；远程生成仍可能产生费用和远程资源。
- 稳定的 Registry/Validator/Executor 优先复用；阶段 A 仅做契约所需改动和恢复声明一致性检查。

## 当前限制与后续条件

尚未实现：其余六个真实 Agent、平台 Dynamic Planner、真实 M7 resume/回滚、部分退款、持久化/重试/并发、代码执行环境、前端。没有开展这些超出范围的工作。

尚未验证：真实模型的路由质量、代码生成质量、供应商账户权限、搜索与图片服务可达性及费用、所有兼容服务的接口差异。Python 3.10+ 为目标，本轮仅在 Python 3.14.5/Windows 实际运行；尚未做跨版本 CI。

后续真实模块先实现 invoke 和规范 Manifest，通过独立契约测试，再在组装入口替换对应 Mock。M7 应先明确恢复 token、幂等与状态所有权，再声明 supports_resume。其他模块不得导入 M4 内部实现。

下一阶段 Dynamic Planner 的前置条件：团队冻结本次候选契约；明确 LLM 配置和调用预算；只从 Registry 读取能力与 Schema；输出 ExecutionPlan 后交给现有 Validator；保留失败/等待语义，并建立真实模型计划题集与显式付费测试。当前未实现 Planner。

## 接口参考

实现时核对了 [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat)、[OpenAI Images API](https://developers.openai.com/api/reference/resources/images) 和 [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)。模型不硬编码，具体服务须由用户配置并另行实测。

## 完整修改文件清单

以下由相对原始 main 的本地差异生成，包含新增文件；不含虚拟环境、缓存和工作区外的任务记录。

- `.env.example`
- `README.md`
- `agents/__init__.py`
- `agents/router/__init__.py`
- `agents/router/__main__.py`
- `agents/router/agent.py`
- `agents/router/config.py`
- `agents/router/factory.py`
- `agents/router/registry.py`
- `agents/router/routing.py`
- `agents/router/skills/__init__.py`
- `agents/router/skills/code_gen.py`
- `agents/router/skills/image_gen.py`
- `agents/router/skills/kb_qa.py`
- `agents/router/skills/knowledge_sample.json`
- `agents/router/skills/web_search.py`
- `common/contracts.py`
- `common/errors.py`
- `common/gateway_contract.py`
- `common/http_client.py`
- `common/llm.py`
- `data/fixtures/order_basic.json`
- `docs/interface_contract.md`
- `docs/migration_m4_delivery.md`
- `docs/naming_convention.md`
- `hub_platform/cli.py`
- `hub_platform/errors.py`
- `hub_platform/executor.py`
- `hub_platform/registry.py`
- `hub_platform/schema.py`
- `hub_platform/validator.py`
- `pyproject.toml`
- `requirements-tested.txt`
- `requirements.txt`
- `tests/artifacts/failure.json`
- `tests/artifacts/invalid_plan.json`
- `tests/artifacts/operations.json`
- `tests/artifacts/phase_a_pytest.txt`
- `tests/artifacts/phase_b_pytest.txt`
- `tests/artifacts/refund_waiting.json`
- `tests/artifacts/regression_pytest.txt`
- `tests/conftest.py`
- `tests/contract/test_contracts.py`
- `tests/contract/test_naming_migration.py`
- `tests/fixtures/failure.json`
- `tests/fixtures/invalid_plan.json`
- `tests/fixtures/m4_gateway.json`
- `tests/fixtures/operations.json`
- `tests/fixtures/refund_waiting.json`
- `tests/integration/test_executor.py`
- `tests/integration/test_m4_platform.py`
- `tests/integration/test_validator.py`
- `tests/live/test_m4_live.py`
- `tests/mocks/agents.py`
- `tests/unit/test_m4_router.py`
- `tests/unit/test_m4_services.py`
