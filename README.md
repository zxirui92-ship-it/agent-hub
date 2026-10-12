# Agent Hub · 统一契约与 M4 Router + Skill

当前提供公共候选契约 1.0、Capability Registry、Validator、Executor、七个确定性 Mock，以及首个真实架构模块 M4。M4 的 Router/Skill 注册与执行是实际代码；真实模型、搜索和生图调用必须显式配置，尚无本轮外部 API 验证结果。

权威文档：`docs/naming_convention.md` 负责命名；`docs/interface_contract.md` 解释接口和状态；PRD 与原始作业决定业务职责。完整交付与限制见 `docs/migration_m4_delivery.md`。

## 安装与离线测试

Python 3.10+；本轮实际环境 Windows Python 3.14.5。以下命令在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

测试默认禁止网络连接，真实 API 用例默认跳过。`requirements-tested.txt` 是实际验证的依赖版本。临时测试目录位于项目内 `.pytest_cache/tmp`，测试入口会创建所需父目录。

## M4 独立运行

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
- `M4_SEARCH_URL`、`M4_SEARCH_API_KEY`：Tavily 兼容搜索，例如 `https://api.tavily.com/search`。
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

未实现真实 M1/M2/M3/M5/M6/M7、平台 Dynamic Planner、M7 恢复、分布式执行或前端。历史第一阶段文档/记录保留为历史证据，以本次交付报告及最新 ICD 为准。
