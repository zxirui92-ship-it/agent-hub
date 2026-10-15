# Agent Hub · 顶层语义规划、会话上下文与模块编排

当前提供顶层动态 Planner、内存多轮会话、公共候选契约、Capability Registry、Validator、Executor、七个确定性 Mock，以及 M1–M7 的真实架构代码。默认业务模块仍为 Mock，可通过 `--real-m1` 至 `--real-m7` 逐个替换。顶层与业务模块已完成真实模型抽样验证，百炼生图、国内联网搜索及两条真实编排链通过；搜索支持直接调用和平台经 M4 调用。测试与问题修复记录见 [本机 API 验收报告](docs/local_api_acceptance.md)。

联网准备入口见 [分批实测说明](docs/live_acceptance.md)：先运行 `python -m scripts.check_live_config` 检查缺项，再分别开启业务模型、M4 外部服务及真实编排链测试。业务 live 测试默认关闭，配置检查不会输出密钥或发送网络请求。文本模块统一读取本机配置，LLM_PROVIDER 可选择 deepseek 或 bailian。

权威文档：`docs/naming_convention.md` 负责命名；`docs/interface_contract.md` 解释接口和状态；PRD 与原始作业决定业务职责。完整交付与限制见 `docs/migration_m4_delivery.md`。

最新模块整理与契约迁移见 [M1/M2/M6 集成说明](docs/m1_m2_m6_integration.md) 和 [M3/M7 集成说明](docs/m3_m7_integration.md)，顶层功能见 `docs/top_level_planner.md`；早期交付报告保留各阶段历史。项目根是 `D:\模组\agent-hub`，`D:\模组` 是父目录，包含早期规划记录和辅助脚本。

## 自然语言入口与多轮会话

2026-10-14 已接入 `group_02` 的星潮电商仿真资料（24 条 FAQ、10 条政策、79 个订单与 4 周经营数据），详见 [数据接入与离线演示](docs/group02_data_integration.md)。`HUB_DATA_DIR=data/group02` 供真实模块使用；旧 Mock 保留基线。新资料周次为 **2025-W40～W43**，存在待业务确认的记录冲突，请使用该说明中的新示例，不混用下方旧 Fixture 的日期、订单 ID 和金额。

在 `D:\模组\agent-hub` 的 `.env` 中设置 `LLM_BASE_URL`（含 `/v1`）、`LLM_API_KEY`、`LLM_MODEL`。平台复用现有 Chat Completions Adapter，不硬编码模型。首次使用可复制 `.env.example` 为 `.env`；已有 `.env` 时直接编辑，不覆盖。

本机已有 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_API_KEY` 时，无需复制密钥到 `.env`：顶层 Planner 在上述三项 `LLM_*` 均为空时直接读取这组环境变量。默认模型为已实测的 `deepseek-flash`，可用 `DEEPSEEK_MODEL` 指定，或用 `HUB_PLANNER_MODEL` 仅覆盖顶层模型。只填写部分 `LLM_*` 时会保留该配置并报告缺项，不跨服务商拼接密钥。当前此配置也被 M1/M2/M3/M4/M5 复用；LLM_PROVIDER=bailian 可切换为 BAILIAN_BASE_URL/BAILIAN_API_KEY，默认文本模型 qwen-plus，BAILIAN_TEXT_MODEL 可覆盖。显式 LLM_* 配置仍整组优先；HUB_PLANNER_MODEL 仅覆盖顶层模型。

真实路由验证记录见 [顶层 API 接入报告](docs/planner_api_connection.md)。本轮只需要下面的默认 `--goal`/`--chat` 命令，不加 `--real-m*` 即可保持业务执行为 Mock。

```powershell
Set-Location 'D:\模组\agent-hub'

# 真实 LLM 规划 → 默认七个 Mock 执行
.\.venv\Scripts\python.exe -m hub_platform --goal '查询订单2025101234的物流状态'
.\.venv\Scripts\python.exe -m hub_platform --goal '融合2026年第41周经营数据，生成周报，再制定大促方案，预算10万元' --json

# 只生成并校验计划
.\.venv\Scripts\python.exe -m hub_platform --goal '查询订单2025101234并申请整单退款，原因是买错了' --plan-only

# 多轮：可先说“查订单”，再补充订单号；上下文保存在当前进程
.\.venv\Scripts\python.exe -m hub_platform --chat

# 使用真实 M4/M5 架构和配置的服务，其余模块仍为 Mock
.\.venv\Scripts\python.exe -m hub_platform --chat --real-m4 --real-m5
```

会话命令：`/new` 开始新任务并保留历史，`/reset` 清空整个会话，`/context` 查看当前任务与历史结果，`/exit` 退出。缺参澄清在同一任务内继续；完成后下一条请求成为新任务，仍能参考历史真实结果。程序退出后内存会话不保留，单次 `--goal` 调用之间也不共享上下文。

顶部 Planner 选择注册能力并生成依赖计划；M4 自己选择内部 Skill，M5 自己协调角色。没有硬编码关键词选链路；一次正常规划只需一次模型调用。非法输出默认反馈一次校验错误给模型修正，业务执行失败不自动重跑。

输出展示生成计划和实际结果，不将模型的执行说明当作已完成答案。缺参、不支持或非法计划都不调用业务模块。等待审核保留原报告；同一 `--chat` 进程可通过明确的 `/review` 决定恢复支持该协议的能力，并继续原计划下游。不能仅用自然语言“同意”重跑退款链；不支持重启后恢复。

```text
/review {"step_id":"s2","approved":true,"reviewer":"审核员姓名","material_complete":false}
/review {"step_id":"s2","approved":true,"reviewer":"审核员姓名","material_complete":true}
```

上述两行展示“材料不足→反思回跳→补齐后续跑”，应使用实际审核决定。拒绝时填写 `approved:false`。若已 `/new` 切换任务，可额外传入 `/context` 中原任务的 `task_id`；Mock M7 不支持恢复，演示需 `--real-m7`。完整的无网络七模块演练：`python -m scripts.demo_prd`；流程见 [课堂演示脚本](docs/demo_script.md)，验收映射见 [PRD 验收记录](docs/prd_acceptance.md)。

自然语言单次入口退出码：0=完成/计划就绪，1=规划或执行失败，2=不支持/参数错误，3=等待审核，4=需要补充信息。`--chat --json` 每个响应输出一行 JSON；提示语写 stderr。

## 安装与离线测试

Python 3.10+；本轮实际环境 Windows Python 3.14.5。以下命令在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

测试默认禁止网络连接，真实 API 用例默认跳过。`requirements-tested.txt` 是实际验证的依赖版本。临时测试目录位于项目内 `.pytest_cache/tmp`，测试入口会创建所需父目录。

## 模块独立运行与插拔

M3/M7 可先离线运行：

```powershell
# 在 D:\模组\agent-hub 执行；不调用外部模型或支付接口
.\.venv\Scripts\python.exe -m agents.plan_execute --week 2026-W41 --mode local
.\.venv\Scripts\python.exe -m agents.workflow.refund_graph --order-id order-low --refund-amount 19900
$env:M3_MODE='local'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m3 --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json --real-m7 --json
# 上一命令退出码 3 代表正常等待人工审批
```

M3 的共享契约为 `fused_data` + 可选 `previous_fused_data`，每次输出真实执行步骤数组；M7 整单退款金额校验沿用 M2 的共享订单事实。两个模块都已适配 Registry，可与 M4/M5 同时替换。配置 LLM 后设置 `M3_MODE=live` 可开启 M3 模型规划与建议；不会失败后退回本地结果。

```powershell
# 需要配置 LLM；M4 的搜索/图片服务需另配。M1/M2/M6 仍为 Mock。
$env:M3_MODE='live'
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m hub_platform --chat --real-m3 --real-m4 --real-m5 --real-m7
```

M7 模块级 `submit_decision` 的同进程示例、检查点范围和源码清理清单见 `docs/m3_m7_integration.md`。

### M4

```powershell
$env:M4_MODE='mock'
.\.venv\Scripts\python.exe -m agents.router --list-skills
.\.venv\Scripts\python.exe -m agents.router 'web_search: 搜索最新电商新闻'
.\.venv\Scripts\python.exe -m agents.router 'kb_qa: 大促优惠券可以叠加吗'
.\.venv\Scripts\python.exe -m agents.router 'code_gen: 用 Python 编写求和函数'
.\.venv\Scripts\python.exe -m agents.router 'image_gen: 绘制蓝色小鸟'
.\.venv\Scripts\python.exe -m agents.router '无法路由的请求'
```

Mock 路由采用显式 `skill_name:` 前缀，仅演示插件分发，不宣称语义理解。搜索/代码/图片结果标记 `mode=mock`；图片返回实际的一像素 PNG 测试字节，无伪造图片地址。知识库是真实本地检索，返回 `mode=local`，默认使用标明来源的示例条目。

直接测试某个 Skill（绕过语义路由，仍使用统一 AgentResult）：

```powershell
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m agents.router --skill kb_qa '退款需要人工审核吗'
# 未配置服务时明确失败，绝不退回 Mock
.\.venv\Scripts\python.exe -m agents.router --skill web_search '最新新闻'
```

`M4_KB_PATH` 可指定 UTF-8 JSON 数组，每项包含 `entry_id`、`title`、`content`、`keywords`（非空字符串数组）。没有匹配时返回 NOT_FOUND，不生成无依据回答。

## 真实 LLM 与外部服务

从 `.env.example` 复制到 `.env`，填写自己的服务配置；不要提交密钥。环境变量优先于 `.env`。`M4_MODE=live` 使用 LLM 读取动态 Skill 描述并选择能力：

- `LLM_BASE_URL`（含 `/v1`）、`LLM_API_KEY`、`LLM_MODEL`：Chat Completions 兼容服务，用于路由和代码生成；模型自行选择，不硬编码。
- 国内搜索默认复用 `BAILIAN_BASE_URL`、`BAILIAN_API_KEY`，`BAILIAN_SEARCH_MODEL` 默认 `qwen-plus`。通过百炼原生接口启用强制联网及来源返回，来源列表来自服务元数据；模型回答单列 `answer`，不伪装网页原文。它与 `kb_qa` 本地知识库独立。
- `M4_SEARCH_PROVIDER` 可显式选 `bailian` 或 `tavily`；`M4_SEARCH_URL`、`M4_SEARCH_API_KEY`、`M4_SEARCH_MODEL` 中任意非空则使用整组覆盖，不借用百炼密钥。Bailian URL 接受同业务空间的 `/compatible-mode/v1` 地址；Tavily 使用搜索端点，例如 `https://api.tavily.com/search`。未配置、服务失败或百炼未返回来源均明确失败，不降级 Mock。
- `M4_IMAGE_BASE_URL`（含 `/v1`）、`M4_IMAGE_API_KEY`、`M4_IMAGE_MODEL`：Images Generations 兼容服务。
- 超时由 `LLM_TIMEOUT_SECONDS` 与 `M4_SERVICE_TIMEOUT_SECONDS` 配置；每次请求只尝试一次。

```powershell
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m agents.router '查找今天的电商新闻并给出来源'
# 以下明确允许真实调用，可能收费；无需在普通回归中运行
$env:M4_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live --run-live -q
```

服务缺配置返回 TOOL_UNAVAILABLE/not_configured；接口失败保留分类和可重试信息。代码只返回文本，永不执行。图片只返回服务实际给出的 URL 或 base64，不自动下载、不伪造路径。兼容服务对模型/接口的支持需要使用方实际验证。

## 平台运行与 M4 替换

```powershell
.\.venv\Scripts\python.exe -m hub_platform --list-capabilities
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/failure.json --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/invalid_plan.json --json
$env:M4_MODE='mock'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/m4_gateway.json --real-m4 --json
```

`--real-m4` 只在组装入口用 RouterAgent 替换 Mock M4；M4_MODE 控制其路由与外部服务路径，其余六个 Mock 保留。Executor 无模块名称分支。平台退出码 0=完成、1=执行失败、2=无效计划/参数、3=等待审核；M4 独立 CLI 0=完成、1=模块失败、2=启动参数/配置错误。

新增真实模块：提供 Manifest 与 `invoke(request: AgentRequest) -> AgentResult`，在新的 Registry 中注册同一 capability_id；禁止重复注册覆盖。M4 新增 Skill：实现 `run(self, payload: dict) -> str`，在 factory 中增加一行 `registry.register(...)`，Router 主逻辑不变。

## 契约要点

- 七个规定 ID 从 `m1.faq_chat` 到 `m7.refund_approval`，无旧 ID 映射。
- 金额用整数分；M2/M7 共用订单 Fixture，整单退款必须与订单金额一致，50000 分自动审批边界。
- task/request/trace ID 使用规定前缀与小写 hex；step_id=s1 等。Fixture 的经营链仍故意打乱数组顺序。
- waiting_approval 不是完成或失败。无恢复能力时 token 必须为空；相关下游等待，无关分支继续。
- M4 data 为 `skill_name`、`result`、`route_reason` 三个字符串；result 内 JSON 文本表示 Skill 业务结果。

## M5 本地接口统一

来源、字段迁移与验证记录见 `docs/m5_interface_alignment.md`。M5 与 M5 Mock 共用 `common/promotion_contract.py`：必填 `goal`，可选 `week`、`budget_amount`（整数分）、`report_markdown`、`fused_data`；返回 `plan_markdown` 和四角色 `roles` 数组。旧版 `report` 入参及 `source_report` 输出已移除，现有经营链 Fixture 已迁移。

以下命令在本项目根目录 `D:\模组\agent-hub` 执行：

```powershell
# 查看契约，不调用模型
.\.venv\Scripts\python.exe -m agents.multi_agent --manifest

# 独立契约与集成验证，注入 FakeLLM，不调用外部服务
.\.venv\Scripts\python.exe -m pytest tests/unit/test_m5_multi_agent.py tests/contract/test_m5_contract.py tests/integration/test_m5_platform.py -q

# 默认仍为七个 Mock，离线执行同一份经营链计划
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --json

# 下列命令使用真实 LLM，需要先配置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
.\.venv\Scripts\python.exe -m agents.multi_agent '制定双十一大促方案' --budget-amount 10000000
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m5 --json
```

`--real-m5` 仅在组装入口替换 M5，可以和 `--real-m4` 同时使用。`M4_MODE=mock` 不影响 M5；M5 不静默返回 Mock，缺配置明确失败。M5 每次成功执行包含四次角色调用及一次汇总调用，默认单次尝试，不自动重试。可用 `M5_TIMEOUT_SECONDS` 单独指定超时，未设置时依次使用 `LLM_TIMEOUT_SECONDS` 或 120 秒。

M5 阶段历史回归：206 passed，8 skipped（M4 真实 API 用例），10.86 秒。当时尚未实测模型效果；后续实测及金额单位修复见本机 API 验收报告。

Planner 初版历史回归：247 passed，14 skipped，35.48 秒。真实语义评估使用以下命令，执行的业务模块仍是 Mock：

```powershell
$env:HUB_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live/test_planner_live.py --run-live -q
```

当前七模块架构均已接入，M7 支持模块内同进程恢复；顶层恢复和跨进程会话存储尚未实现。Planner 的后续联网验证见 API 报告，业务模型与搜索完成有限样例实测，不能据此声明普遍语义准确率；正式业务数据仍未接入。当前接口以最新 ICD 与功能说明为准。

## M1 / M2 / M6 独立运行与平台替换

在 `D:\模组\agent-hub` 执行以下离线命令，无需 API Key：

```powershell
.\.venv\Scripts\python.exe -m agents.single_agent '七天退货有什么条件？' --mode mock
.\.venv\Scripts\python.exe -m agents.react_agent --order-id 2025101234 --mode local
.\.venv\Scripts\python.exe -m agents.blackboard --week 2026-W41
$env:M2_MODE='local'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json --real-m2 --real-m7 --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m6 --real-m3 --json
.\.venv\Scripts\python.exe -m pytest tests/unit/test_m1_single_agent.py tests/unit/test_m2_react_agent.py tests/unit/test_m6_blackboard.py tests/integration/test_m1_m2_m6_platform.py -q
```

最后一条经营演示使用 M5 Mock；测试中已用注入模型响应的真实 M5 验证三模块经营链。三个独立入口均输出 AgentResult JSON，退出码 0=完成、1=模块失败。M1 的 mock 是标记明确的固定回答；M2 的 local 是确定性动作选择；M6 是真实融合计算但数据来自样例。M1/M2 的 live 使用公共模型解析器（显式 LLM_* 或所选本机服务变量），无配置则失败。M1 多轮记忆需要复用同一 SingleAgent 实例和 session_id；独立 CLI 每次启动是新进程。

`--real-m1` 至 `--real-m7` 可组合使用；`--list-capabilities` 加全部开关只查看 Manifest，不调用模型。无需修改 Executor、Validator 或 Planner。
