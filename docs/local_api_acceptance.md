# 本机模型配置与真实 API 验收

2026-10-14（Asia/Tokyo）。用户授权使用本机环境执行真实 API 测试；本轮未写入密钥、未提交或推送。

## 结果

文本模块、M4 生图、国内搜索及两条编排链已经进行真实调用。搜索接入前离线回归 388 passed / 23 skipped；最新全量为 **409 passed / 24 skipped，37.13 秒**。联网用例保持默认关闭。这些是样例验证，不是生产准确率或业务收益证明。

| 本轮真实调用批次 | 结果 | 证据（tests/artifacts/） |
|---|---|---|
| DeepSeek M1 问答与记忆 | 1 passed，6.18 秒 | business_m1_live.xml |
| DeepSeek M2 正常/不存在订单、M3 规划分析、M5 四角色汇总 | 4 passed，180.75 秒；M5 初次内容存在金额误读，见下文 | business_modules_live.xml |
| M4 语义路由、代码生成、百炼生图 | 7 passed / 1 skipped，7.80 秒；搜索缺配置 | m4_bailian_live.xml |
| 百炼 qwen-plus 的 M1 问答与记忆 | 1 passed，2.72 秒 | business_qwen_live.xml |
| 真实 Planner + 经营链 / 退款链初轮 | 经营链通过、退款链失败，176.51 秒；保留原始失败记录 | business_e2e_live.xml |
| M2 金额查询与真实退款链修复复验 | 2 passed，6.87 秒 | business_refund_retest_live.xml |

本轮累计 16 个成功测试执行、1 次已修复并复验的失败、1 项缺配置跳过；计数包含不同模型配置和复验场景，不是 16 个唯一功能。未重复执行已通过的经营链来覆盖原始失败记录。

生图实际使用 `qwen-image-2.0`，API 返回一张有效 HTTP(S) 图片资源；未下载图片，未做视觉质量评分。Qwen 文本实际使用 `qwen-plus`；主要业务及 Planner 使用 `deepseek-flash`。模型列表由本机配置的百炼端点查询确认。

## 本机配置如何生效

所有使用文本模型的模块（M1/M2/M3/M4/M5）与 Planner 共用 `common/model_config.py`：

1. 任一 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL` 非空时采用这整组配置；缺项就报错，不从别的服务借用密钥。
2. 没有显式 LLM_* 时，`LLM_PROVIDER=deepseek`（默认）读取本机 `DEEPSEEK_BASE_URL/DEEPSEEK_API_KEY`，默认模型 deepseek-flash，可用 DEEPSEEK_MODEL 覆盖。
3. `LLM_PROVIDER=bailian` 读取 `BAILIAN_BASE_URL/BAILIAN_API_KEY`，默认 qwen-plus，可用 BAILIAN_TEXT_MODEL 覆盖。
4. HUB_PLANNER_MODEL 只覆盖 Planner 的模型名；不会把密钥或配置写回环境、文件。M6/M7 当前没有模型调用。

生图与文本独立：没有显式 M4_IMAGE_* 配置时，存在 BAILIAN_BASE_URL/API_KEY 就选百炼，BAILIAN_IMAGE_MODEL 默认 qwen-image-2.0。M4_IMAGE_PROVIDER 可显式指定 bailian/openai；已有完整的兼容接口路径仍保留。不会将不完整的 M4_IMAGE_* 组与另一服务密钥拼接。

百炼的兼容文本 URL 和生图 URL 不同。根据[官方 Qwen-Image API](https://help.aliyun.com/zh/model-studio/qwen-image-api)，适配器保持用户配置的业务空间域名，把 `/compatible-mode/v1` 转为 `/api/v1/services/aigc/multimodal-generation/generation`，发送原生 messages 参数并解析 output.choices 中的图片。单次生成一张，不加任务队列或自动重试；超时由 M4_IMAGE_TIMEOUT_SECONDS 控制（默认 180 秒）。

Windows 新增用户环境变量不会自动更新已启动的进程。本轮起初未找到 BAILIAN 配置，用户补存后已确认。新终端可直接使用；旧终端可仅在本进程刷新，不显示密钥：

```powershell
$env:BAILIAN_API_KEY=[Environment]::GetEnvironmentVariable('BAILIAN_API_KEY','User')
$env:BAILIAN_BASE_URL=[Environment]::GetEnvironmentVariable('BAILIAN_BASE_URL','User')
.\.venv\Scripts\python.exe -m scripts.check_live_config
```

不要打印 API_KEY，不需要把密钥粘贴到聊天或仓库。国内搜索配置及后续真实调用见下节；能把问题路由到搜索不等于执行搜索成功。

## 国内联网搜索补充验收

按用户要求使用中国大陆服务，复用现有百炼北京业务空间的 BAILIAN_BASE_URL/API_KEY，不另建账号、不把密钥复制进文件。BAILIAN_SEARCH_MODEL 默认 qwen-plus，独立于路由模型（当前为 DeepSeek）。按[百炼官方搜索协议](https://help.aliyun.com/zh/model-studio/web-search)使用原生 text-generation 端点，启用 forced_search 和 enable_source。知识库 kb_qa 仍是独立的本地检索。

返回 result JSON 保持 mode/query/results，并补充 provider/model/answer；source_url/title/index 只来自 output.search_info.search_results。原生接口未提供网页原文，所以 content 留空、source_content_available=false，模型摘要放在 answer 中。服务缺配置、返回畸形数据或未提供任何来源时明确失败，不用模型生成的链接伪装检索证据。

| 搜索验收 | 结果 | 证据（tests/artifacts/） |
|---|---|---|
| 初次真实路由与两项搜索 | 1 passed / 2 failed，3.67 秒；搜索 HTTP 403 | m4_domestic_search_live.xml（已脱敏） |
| 用户充值后直接搜索与 Executor → M4 → 搜索 | **2 passed，17.14 秒** | m4_domestic_search_retest_live.xml |
| 全量离线回归 | **409 passed / 24 skipped，37.13 秒** | domestic_search_offline.xml |

初次错误为 AccessDenied.Unpurchased；最小诊断中普通 qwen-plus 文本、原生 qwen-flash、Responses 搜索同样返回该错误。用户说明欠费并充值后，原生 qwen-plus 搜索直接复验成功，无需更换供应商或协议。未再次测试 Responses，也未保留其适配代码。

两次成功搜索各返回 10 条来源。直接搜索 Python 文档得到 docs.python.org 来源；平台查询百炼搜索官方文档时得到若干阿里云开发者社区文章，但答案未找到指定官方帮助页。**已验证实际联网、来源提取和公共契约链路；检索精度和生成摘要事实准确性尚未系统评估。** 搜索结果由服务当时返回，不是预设 Fixture。

首次 pytest 失败回溯自动展开了 HTTP 函数中的密钥参数；已立即脱敏本地 XML，并为控制台回溯、捕获日志与 JUnit 属性加入脱敏 hook 及回归测试。已出现的聊天工具输出无法通过修改仓库撤回，建议用户轮换本次百炼密钥；后续只更新本机环境变量。

独立使用（在 D:\模组\agent-hub 的新终端，无需配置 Tavily）：

```powershell
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m agents.router --skill web_search '搜索今天的公开电商新闻，提供来源'
# 不传 --skill 时由真实 LLM Router 选择 Skill
.\.venv\Scripts\python.exe -m agents.router '请联网搜索公开的电商新闻并给出来源'
# 显式联网复验（会产生调用费用）
$env:M4_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k 'external_skill and web_search or search_through_executor' -q --tb=short
```

本次修改：agents/router/skills/bailian_search.py、config.py、factory.py、scripts/check_live_config.py、.env.example；新增百炼搜索单测，更新 live 搜索测试、tests/conftest.py 和配置脱敏测试；同步 README、验收/进度文档及规划记录。Executor 核心和知识库实现未改，未提交/推送。

## 实测发现与修复

**M5 金额口径与事实缺失。** 初次结构测试通过，但人工检查发现角色把 1268430000 分当作元，写出错误的 GMV；汇总模型原先只收到角色建议，没有完整原始事实。现由程序提供精确“分→元”换算、完整经营数据及数据缺口，角色和汇总均读取；未知库存、人力、峰值、成本须说明是假设或待确认。新增两个离线回归。修复后经营链实测输出正确写明 1,268,430,000 分 = 12,684,300.00 元，预算 10,000,000 分 = 100,000.00 元，并明确无法计算 ROI，计划目标是建议而非观测事实。依然需要对生成建议进行业务审核。

**M2 提前终止。** 退款链的 Planner 生成“查询金额与状态”的 query，M2 模型查询订单后自行返回未注册动作 finish。原实现按契约失败并阻断 M7，没有伪造成功。现每轮明确传入 remaining_actions，说明完整契约仍要求订单和物流两项观察，停止由程序决定，禁止输出 finish。新增同输入离线/live 回归，复验通过；69900 分的 M7 保持 waiting_approval。

**离线子进程隔离。** 新增本机配置回退后，两个旧“缺配置”CLI 测试只清空 LLM_*，继承了 DeepSeek 配置并尝试连接，连接失败、没有获得模型响应。已同步清空新增来源，并让普通 pytest 的子进程继承空 API Key；socket 禁网仍保留。最终全量无失败。记录保存在 progress.md，未删除或弱化缺配置断言。

## 使用方式

在 `D:\模组\agent-hub`：

```powershell
# 下面的 live 命令会产生真实模型/服务调用费用
$env:LLM_PROVIDER='deepseek'
$env:BUSINESS_RUN_LIVE_TESTS='1'
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m pytest tests/live/test_business_live.py --run-live -q

# 千问文本替换（同一公共接口）
$env:LLM_PROVIDER='bailian'
.\.venv\Scripts\python.exe -m pytest tests/live/test_business_live.py --run-live -k m1 -q

# 百炼生图；只生成一张
$env:M4_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k 'external_skill and image_gen' -q
```

这些命令是复现入口，本轮已经完成上述证据中的调用，无需立即重复。普通 `pytest -q` 不启用 live，只有显式 --run-live 与相应环境开关同时开启才调用外部服务。

当前边界：订单、物流、经营数据仍为明确的本地样例；知识库仍为本地样例条目。M6 是实际黑板融合，M7 是实际 LangGraph 流程，但未连接生产数据/支付；顶层计划恢复尚未实现。搜索、业务模型和生图已抽样实测，不能将这些结果扩大为所有服务或所有输入均已验收。

## 修改范围

新增 common/model_config.py、agents/router/skills/bailian_image.py，以及对应配置、百炼、M5 金额回归测试。调整 M1/M2/M3/M4/M5 与 Planner 的配置读取、M4 工厂和 Settings、M2 完成条件提示、M5 事实传递；更新 live 测试、离线子进程隔离、配置检查脚本、环境示例及文档。Executor、Validator 和 Registry 核心逻辑未改。
