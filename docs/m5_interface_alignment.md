# M5 本地接口统一与接入记录

日期：2026-10-13。目标目录：`D:\模组\agent-hub`。

M5 已导入，真实模块与 Mock 可在同一份计划中替换。此交付为本地修改；没有推送、合并远端或调用真实模型 API。

## 来源与保留范围

- 仓库：<https://gitee.com/baisumartin/0727-rag_-agent>，分支 `group_02`。
- 核实远端提交：`7bcc1c66302a505ed3528456908ab5621c69c79b`。
- 导入文件：`agent-hub/agents/multi_agent.py`、`agent-hub/tests/test_m5_multi_agent.py`。
- 原作者：程炜。保留四角色的职责和 Prompt、确定性目标拆分、同步分派及 Aggregator 的对照表与 LLM 汇总流程。
- 未复制上游 common 包；使用本地已有公共请求、结果、错误和 LLM transport。原五个测试场景保留，调整公共类型及日志捕获方式。

## 接口裁决

公共 envelope 仍使用本地 `common/contracts.py`，M5 业务 Manifest 统一为 `common/promotion_contract.py`，版本 `2.0`。这是本地候选迁移，团队远端未冻结。

| 位置 | 迁移前 | 迁移后 |
|---|---|---|
| M5 Mock 输入 | report 必填 | goal 必填；可选 report_markdown/week/budget_amount/fused_data |
| M5 输出 roles | Mock 为对象，真实模块为数组 | 统一为四项数组，每项 role/contribution/rationale |
| source_report | Mock 私有输出 | 移除；平台 StepRecord.inputs 保留原始输入 |
| 请求 trace_id | 上游从 context 读取并兜底生成 | 使用本地请求顶层 trace_id，完整透传 |
| 返回 task_id | 上游未定义 | 原样回传；error 同步 request_id/task_id/trace_id |
| 错误 | 上游 AgentError | 本地 ErrorDetail/ErrorCode，保留 retryable |
| Manifest | 上游普通 dict、开放对象 | 本地 CapabilityManifest，显式内联 Schema、禁止额外字段 |
| LLM | 上游默认模型/端点及 SDK | 复用本地 ChatModel，显式配置 LLM_*，单次尝试 |
| 日志 | 上游 print JSON | 标准 logging，独立 CLI 写 stderr，stdout 为结果 JSON |

`budget_amount` 严格为非负整数分，拒绝浮点和布尔值。`fused_data` 遵守现有 M6 经营视图 Schema。旧 report 计划明确报 INVALID_INPUT，不通过隐式猜测补 goal。

统一过程中增加了直接调用入参/出参校验，拒绝空模型输出；角色输出格式不符合“建议/依据”两行时，仍保留上游“全文作为贡献、依据可空”的兜底。上游对周报/融合数据摘要的 200 字符截断规则保留，模型质量与长上下文策略属于后续实测范围。

## 接入与运行

默认平台仍注册七个 Mock。`--real-m5` 将 M5 替换为 PromotionAgent，可与 `--real-m4` 组合；其余模块保持原选择。Registry、Validator、Executor 核心代码未改。

```powershell
Set-Location 'D:\模组\agent-hub'
# 无模型调用：查看契约、离线测试
.\.venv\Scripts\python.exe -m agents.multi_agent --manifest
.\.venv\Scripts\python.exe -m pytest tests/unit/test_m5_multi_agent.py tests/contract/test_m5_contract.py tests/integration/test_m5_platform.py -q

# 有模型调用：先配置 .env 的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
.\.venv\Scripts\python.exe -m agents.multi_agent '制定下周大促方案' --week 2026-W41 --budget-amount 10000000
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m5 --json
```

M5 成功路径调用模型五次（四角色 + 汇总）。M5_TIMEOUT_SECONDS 优先于 LLM_TIMEOUT_SECONDS，二者缺省时为 120 秒；无自动重试。M4_MODE 不控制 M5。没有模型配置时明确失败，没有内置假成功路径。

## 验证结果

使用本项目 `.venv` 执行全量回归：**206 passed, 8 skipped in 10.86s**。8 个跳过项为既有 M4 真实 API 测试，本轮未启动。

- 保留并迁移原 M5 五项测试；新增 32 个参数展开后的契约/集成用例，共新增 37 个通过项。
- 验证 Mock 与真实模块 Manifest 完全一致；同一 operations 计划执行 M6 Mock → M3 Mock → 真实 M5（FakeLLM 注入），检查周报、融合数据、角色输出及关联日志。
- 验证非法入参在模型调用前拒绝，保留错误码和 retryable，模型空输出不伪报成功。
- 验证 M5 失败导致依赖下游 skipped，独立分支继续；M4/M5 可在同一个 Registry 中执行。
- 验证模块方式和直接文件方式启动、Manifest 查询以及缺少服务配置时的失败退出码。
- 全量回归包含现有 Mock、M4、校验器和 CLI 场景，Validator/Executor 未改。

运行证据：`tests/artifacts/m5_interface_pytest.txt`、`tests/artifacts/m5_offline_operations.json`。旧 `tests/artifacts/operations.json` 等保留为迁移前历史记录。

首轮定向测试有一项失败：测试期望多行周报原文出现在已压平的 Prompt 中。模块接收的原始周报断言已通过；修正为检查模型收到实际周次和异常事实后，全量回归通过。

尚未验证真实 LLM 输出质量、联网可用性、端到端耗时和成本；尚未实现顶部自然语言 Planner。后续可先配置模型独立验收 M5，再通过 `--real-m5` 执行固定计划。
