# M1 / M2 / M6 新版工程接入报告

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

2026-10-14；工程目录 `D:\模组\agent-hub`。父目录 `D:\模组` 还包含早期规划记录/辅助脚本，不能作为仓库根。此次保留已有 M3/M4/M5/M7、Planner 和全部未提交成果，未更改原 `D:\agent 项目` 中的交付文件。

## 来源与适配

来源 SHA-256 记录于 `docs/imports/m1_m2_m6_source_manifest.json`。M1.zip 只有 single_agent.py；M2.zip 只有 react_agent.py；M6 是单独的 M6_blackboard.py。三者引用的旧 common 或数据文件未随本次文件交付，不能直接覆盖新版公共层。

| 模块 | 已保留的架构 | 接入新版的必要变化 |
|---|---|---|
| M1 | 单模型调用、短期窗口记忆、简单工具调用 | 旧 chat/llm.chat 接口改为 invoke/TextModel.complete；按 PRD 的 FAQ 职责将订单/库存工具替换为 lookup_faq/get_service_policy；模型故障返回 failed，不把道歉当作成功 |
| M2 | 决策摘要 → Action → Observation → 目标检查的有界循环 | 将依赖缺失的 LangChain build_llm/create_agent 组装改为现有 TextModel JSON 动作协议；每轮只执行一个动作，避免外层有界但内层无限工具循环；未知订单、工具失败、轮次耗尽明确失败 |
| M6 | 私有黑板、Order/Behavior/Marketing/Insight 四个写入者、依赖协作、审计事件 | 原订阅仅打印通知，现订阅会入队并触发重算；读写/快照深复制；未收敛不导出成功；只输出现有消费者所需的平面经营视图 |

M2 旧例子中订单 2025101234 为 329.0 元，与新版共享事实 69900 分冲突，现统一使用 common/order_data.py，与真实 M7 和 Mock 相同。未将旧运单、旧金额或无时区 ETA 混入新版数据。

M6 原代码依赖未提供的 WEEKLY_SALES/USER_BEHAVIOR/CAMPAIGNS。现读取已存在的三类周样例（data/fixtures/m3），不修改其文件，也不覆盖逐笔订单表。现有源没有购买 UV、详情/加购人数、实际活动成本与归因成交额，故不能声称原丰富视图中的 ROI/加购瓶颈算法已完成验证。输出明确说明缺口，转换率直接沿用行为源，不用订单数/UV 重新编造。

## 当前实现和验证层级

- 已实现、已离线测试：三个统一 invoke、共享 Manifest、关联 ID、严格金额、M1 窗口记忆与会话隔离、M2 观察驱动循环与轮次限制、M6 订阅触发与私有状态隔离。
- 仅 Mock/注入响应验证：M1 模型问答和历史提示、M2 LLM 动作协议、七模块联合运行中的 M4 外部服务和 M5 模型生成。M2 local 是确定性决策；M6 是真实算法处理样例数据。
- 未在本轮调用或验证：M1/M2 真实 LLM 语义效果、业务真实订单/物流系统、搜索/生图服务、真实运营数据。此前 Planner 的 7 项 API 验证是历史证据，不能替代业务模块验收。
- 尚未实现：顶层计划审批恢复、跨进程会话持久化、真实退款支付；本轮不扩展这些功能。

## 文件与接口

新增模块：

```text
agents/
  single_agent.py   SingleAgent / ConversationMemory / FAQ tools
  react_agent.py    ReActAgent / evaluate_goal / order tools
  blackboard.py     Blackboard / four writers / controller / DataFusionModule
common/
  customer_contract.py   M1/M2 manifests
  fusion_contract.py     M6 manifest + shared fused_schema
```

三个模块都实现 `invoke(request: AgentRequest) -> AgentResult`。M1/M2 复用 `TextModel.complete(system: str, query: str) -> str`；M6 不需要模型。新增可选输入使 M1/M2 Manifest 版本为 1.1；M6 输出类型不变，保留 1.0。完整契约以 naming_convention.md 和 interface_contract.md 为准。

本轮修改现有代码：common/promotion_contract.py（共享融合 Schema）、common/llm.py 和 common/order_data.py（说明）、hub_platform/cli.py（--real-m1/2/6）、tests/mocks/agents.py（共享 Manifest）、tests/contract/test_naming_migration.py（版本断言）。Executor/Validator/Planner 无本轮改动。

新增测试：tests/unit/test_m1_single_agent.py、test_m2_react_agent.py、test_m6_blackboard.py；tests/integration/test_m1_m2_m6_platform.py。其他更新：.env.example、README.md、两份权威规范、docs/project_progress.md、本报告、来源清单、三份工程计划记录及测试产物。

## 运行与测试

以下命令在新版仓库根执行：

```powershell
.\.venv\Scripts\python.exe -m agents.single_agent '七天退货有什么条件？' --mode mock
.\.venv\Scripts\python.exe -m agents.react_agent --order-id 2025101234 --mode local
.\.venv\Scripts\python.exe -m agents.blackboard --week 2026-W41
$env:M2_MODE='local'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json --real-m2 --real-m7 --json
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m6 --real-m3 --json
.\.venv\Scripts\python.exe -m pytest -q
```

M1/M2 默认 live，通过 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL/LLM_TIMEOUT_SECONDS 配置公共适配器；不自动使用仅 Planner 的 DEEPSEEK 环境回退。MAX_REACT_ITERATIONS 默认 3；M6_DATA_DIR 可指定同结构数据目录。启动不自动降级为离线成功。上面的经营 CLI 保留 Mock M5，真实 M5 的离线链验证见集成测试/产物；真实 M5 CLI 会调用配置模型。

M1 同一实例内使用 payload.session_id 或平台 context.session_id 保持会话。独立 CLI 每次是新进程，重复传 session_id 不会恢复上次进程记忆。

## 验收证据

| 验证 | 结果 |
|---|---|
| 接入前基线 | 302 passed / 15 skipped，17.21 秒 |
| 本轮新增定向测试 | 65 passed，3.35 秒 |
| 最终全量回归 | 367 passed / 15 skipped，24.06 秒 |
| 七个真实架构注册/调用 | 全部通过 Executor，模型和服务使用明确的离线适配器 |
| M6 → M3 → M5 | 保持打乱的计划数组，按依赖顺序执行；1268430000 分通过 M3 进入 M5 |
| M2 → M7 | 49999/50000 分自动分支，50001/69900 分等待；等待下游阻塞，独立 FAQ 继续 |
| 失败路径 | 不存在订单/周次、工具异常、非法模型动作、轮次耗尽均失败并阻断下游 |

首轮集成测试出现一次测试输入错误：给真实 M4 的离线路由器使用了旧 Mock 的无前缀文本。改为其已有协议 `kb_qa: 优惠政策` 后通过，未更改 M4 路由逻辑或降低断言。

完整 pytest 输出：tests/artifacts/m1_m2_m6_pytest.txt。链路输出：tests/artifacts/m1_m2_m6_offline_demo.json（明确记录模式）。所有普通测试禁网，15 个 live 用例未显式启用而跳过。没有安装新增依赖，没有提交或推送本轮改动。
