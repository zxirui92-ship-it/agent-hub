# 顶层 Planner API 接入记录

日期：2026-10-13。用户决定等所有模块完成集成后再进行业务 API 联网；本轮仅顶层语义路由接 API，业务执行使用七个 Mock。

## 配置与实现

- 从当前进程环境找到 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL；未打印、复制或落盘密钥。
- 地址为 https://api.deepseek.com。通过认证 GET /models 验证连接，返回 deepseek-flash、deepseek-v4-pro；本轮使用 deepseek-flash。
- hub_platform/planner.py 的 configured_model 先使用已有 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 配置组；三项均为空时使用 DeepSeek 环境变量。部分通用配置不会借用另一组凭证。
- DEEPSEEK_MODEL 可选，默认 deepseek-flash；HUB_PLANNER_MODEL 可仅覆盖顶层模型。复用已有 ChatModel 和 120 秒可配置超时，不增加 SDK、自动服务降级或业务层路由分支。
- 不修改或注入业务模块 LLM_* 环境变量。默认 CLI 中 M1–M7 仍为 Mock。

API 协议校对依据：[DeepSeek 官方调用说明](https://api-docs.deepseek.com/)、[模型列表接口](https://api-docs.deepseek.com/api/list-models/)。模型选择以本轮认证接口实际返回为准。

## 联网结果

七项真实 Planner 测试 **7 passed，14.46 秒**；六个单轮案例与一个双轮案例，共八次模型请求，全部首次通过校验，没有触发修正。每个 ready 计划都经过现有 Validator，并交给 Mock Executor 验证数据绑定。

| 案例 | 验证结果 |
|---|---|
| 查询订单物流 | ready → M2，Mock 执行完成 |
| 融合经营数据、周报、大促方案 | ready → M6→M3→M5；预算 10 万元映射为 10000000 分 |
| 查询订单后申请整单退款 | ready → M2→M7；金额引用订单输出，执行后等待审批 |
| 编写加法函数 | ready → M4；内部业务结果仍为 Mock |
| 缺少订单号 | needs_clarification，不执行模块 |
| 亲自到用户家浇花 | unsupported，不执行模块 |
| 两轮补充订单号 | 澄清后完成查询，沿用同一 task_id/trace_id |

完整计划和 Mock 执行报告保存在 tests/artifacts/planner_api_live.xml；控制台测试结果保存在 planner_api_live_pytest.txt。记录仅含合成测试问题、公开计划及样例执行结果，不保存 API 密钥或隐藏推理。

摘要见 planner_api_live_summary.json；额外真实 CLI 调用返回 completed、退出码 0，选择 M2 Mock，输出见 planner_api_cli.json。本轮合计九次顶层模型请求，业务模块 API 请求为零。离线全量回归：**302 passed / 15 skipped，17.47 秒**。

这是一轮小规模功能实测，不代表所有表达的路由准确率已验收。业务模块联网、真实知识库/业务数据及顶层审批恢复保持原阶段边界。

## 本机使用

```powershell
Set-Location 'D:\模组\agent-hub'
.\.venv\Scripts\python.exe -m hub_platform --goal '查询订单2025101234的物流状态' --json
.\.venv\Scripts\python.exe -m hub_platform --chat
# 只查看模型生成的计划
.\.venv\Scripts\python.exe -m hub_platform --goal '融合2026年第41周经营数据并生成周报' --plan-only
```

以上命令不加 --real-m*，保持只有顶层联网。环境变量需要被运行终端继承；若另一个终端刚设置变量，需打开新的终端/进程。

需要再次主动执行联网测试时：

```powershell
$env:HUB_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live/test_planner_live.py --run-live -v
```

普通 pytest 不联网；必须同时提供上述标志与 --run-live 才运行真实模型测试。
