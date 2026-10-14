# 联网实测准备与分批验收

2026-10-14。代码位于 `D:\模组\agent-hub`。本轮准备不调用外部服务；新增业务 live 用例（当前共 8 个），默认关闭。普通 pytest 禁网。API 请求可能产生费用，不自动重试失败业务，不以离线结果替代真实成功。

## 配置检查

```powershell
Set-Location 'D:\模组\agent-hub'
.\.venv\Scripts\python.exe -m scripts.check_live_config
```

此命令仅显示是否填写及缺少的变量名，不输出配置值、不联网验证密钥。准备时仅顶层 DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY 存在；业务 LLM_*、搜索、生图均未配置。该快照不代表今后配置状态。

业务 LLM 与 Planner 共用 common/model_config.py：显式 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 整组优先，否则 LLM_PROVIDER=deepseek 读取 DEEPSEEK_*，LLM_PROVIDER=bailian 读取 BAILIAN_*。只读取，不把密钥复制进文件。国内搜索自动复用 BAILIAN_BASE_URL/BAILIAN_API_KEY，BAILIAN_SEARCH_MODEL 默认 qwen-plus；也可显式使用 M4_SEARCH_PROVIDER 和整组 M4_SEARCH_URL/M4_SEARCH_API_KEY/M4_SEARCH_MODEL 覆盖。生图可使用完整 M4_IMAGE_* 组，或自动读取 BAILIAN_BASE_URL/BAILIAN_API_KEY（模型由 BAILIAN_IMAGE_MODEL 配置，默认 qwen-image-2.0）。只设置模型 Key 不能证明服务接口兼容或账号权限有效。

环境变量优先于项目 .env。三个测试开关必须在启动 pytest 前设置为进程环境变量；仅写入 .env 不会在测试收集前自动开启。不要用通配方式打印环境变量或提交 .env。

## 第一批：真实业务模型

确认业务 LLM 配置后，按模块运行；每条命令都显式允许真实调用：

```powershell
$env:BUSINESS_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live/test_business_live.py --run-live -k 'not end_to_end' -q --junitxml=tests/artifacts/business_live.xml -o junit_family=legacy
```

覆盖 M1 FAQ 与记忆两次调用、M2 正常/未知订单的观察循环、M3 模型规划与分析、M5 四角色及汇总。合计 6 个用例（含金额查询回归），按测试代码最多 18 次模型调用；不是费用报价。可用 `-k m1`、`-k m2` 等单独选择，首次建议依次跑，失败先定位。显式开启后业务 LLM 缺配置会直接失败，不把缺配置跳过当作验收通过。

自动断言检查契约、昵称记忆、订单事实与工具轨迹、结构化计划/角色输出。XML 记录样例结果供人工检查：政策是否符合工具事实、营销方案是否尊重预算与数据缺口、是否编造活动或已执行动作。结构合法不等于内容质量合格。

## 第二批：M4 语义路由、代码与外部服务

```powershell
$env:M4_MODE='live'
$env:M4_RUN_LIVE_TESTS='1'
# 5 次真实路由模型调用，不执行搜索/生图
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k semantic_routing -q
# 1 次代码生成模型调用，不运行所生成代码
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k 'external_skill and code_gen' -q
# 以下分别为搜索调用、单张图片生成，须先配置对应服务
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k 'external_skill and web_search' -q
# 真实语义路由 → 搜索 → Executor 契约验收，另产生一次搜索和一次路由调用
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k search_through_executor -q
.\.venv\Scripts\python.exe -m pytest tests/live/test_m4_live.py --run-live -k 'external_skill and image_gen' -q
```

现有 M4 live 用例遇到缺配置会 skip；报告必须单列跳过，不能声称全能力联网通过。M4 的企业知识库仍是本地样例，真实语义路由不等于已接入正式知识库。

## 第三批：真实 Planner + 真实业务模型链

```powershell
$env:BUSINESS_RUN_LIVE_TESTS='1'
$env:M4_MODE='live'
.\.venv\Scripts\python.exe -m pytest tests/live/test_business_live.py --run-live -k end_to_end -q --junitxml=tests/artifacts/business_e2e_live.xml -o junit_family=legacy
```

两条链分别是经营融合→周报→大促，以及订单→整单退款。七个架构均注册；测试先检查 Planner 只选择目标能力且不重复，才执行业务。该批不调用搜索/生图服务；最多 12 次模型调用（Planner 不修正重试，M2 最多三轮）。

经营数据和订单仍是本地 Fixture；M6 执行实际融合，M7 执行实际 LangGraph。69900 分退款应停在 waiting_approval，不提交人工决定、不打款。真实订单/经营系统和顶层审批恢复不属于本批验收。

## 结果记录

每批记录命令、测试数量、通过/失败/跳过、模型名、耗时及生成结果的人工评价。日志不记录 Key。XML 中有完整样例结果，分享前检查内容；本批只使用仓库已有测试事实。

结束后关闭开关：

```powershell
$env:BUSINESS_RUN_LIVE_TESTS='0'
$env:M4_RUN_LIVE_TESTS='0'
$env:HUB_RUN_LIVE_TESTS='0'
```

当前真实结果见 local_api_acceptance.md；缺配置或被跳过的功能仍标为未验证。

准备工作离线回归：371 passed / 22 skipped，58.88 秒；输出见 tests/artifacts/live_preparation_pytest.txt。22 项跳过包括新增业务 7 项、既有 M4 8 项、Planner 7 项。本轮没有发送真实 API 请求，尚无新的联网通过证据。
