# M3 / M7 本地整理与接入

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

实施日期：2026-10-13。主体工程为 `D:\模组\agent-hub`，输入目录为 `D:\agent 项目\M3`、`D:\agent 项目\M7`。原始目录保留，本次“清理”指选择有用内容导入主体，不删除用户上传包。

## 来源和文件取舍

原始包共记录 19 个非环境文件的大小和 SHA-256，见 [来源清单](imports/m3_m7_source_manifest.json)。没有来源提交号，不将本地上传内容冒称为某个远端提交。

| 输入内容 | 处理与目标位置 |
|---|---|
| M3/.venv、.idea、Python 缓存 | 不复制、不运行上传包的环境 |
| M3/agents/plan_execute.py | 适配至 agents/plan_execute.py；保留 PlanStep、WeeklyReportPlanner、WeeklyReportExecutor 分离设计，重写契约边界及数据映射 |
| M3/common、requirements.txt、.env.example | 不覆盖主体；复用主体 common、LLM、ID 和错误模型，只合并实际需要的配置 |
| M3/data/fixtures/*.json | 隔离在 data/fixtures/m3/；原始样例原样保留，避免同名 order_basic.json 覆盖订单事实 |
| M3/tests | 旧请求模型、Mock LLM 依赖不兼容，按原验收意图重写为 tests/unit/test_m3_plan_execute.py |
| M3/README、docs/architecture.md | 作为来源参考，当前使用说明整合至本文，不导入第二套入口文档 |
| M7/state.py | agents/workflow/state.py，保留全局状态、列表追加 reducer；节点名改为 snake_case |
| M7/nodes.py | agents/workflow/nodes.py，保留金额条件边、合规规则和反思回跳；移除虚构人工裁定和打款承诺 |
| M7/refund_graph.py | 拓扑提取至 agents/workflow/_graph_definition.py，当前契约门面放在 refund_graph.py |
| M7/__init__.py、缺失的 common/工具依赖 | 使用最小包入口；显示助手放在模块私有 formatting.py，订单源统一到 common/order_data.py |

M7 原包未附带所引用的订单加载器、配置和风控策略。本地适配明确采用样例策略：阈值 50000 分，连续三次合规不通过后驳回；没有声称已接入风控系统。订单快照在受理时固定。若测试注入的订单带 risk_level，会进入原风险校验规则，正式数据接入仍待后续。

## 与当前架构的关系

```text
顶层 Planner / Conversation
          ↓ ExecutionPlan
Registry → Validator → Executor（保持通用调度）
          ├─ M6 Mock → M3 Plan/Execute → M5 四角色
          ├─ M2 Mock → M7 LangGraph → completed / waiting_approval
          └─ M4 Router → Skills
```

只有 CLI 组装增加 `--real-m3`、`--real-m7`；默认仍注册七个 Mock。两种实现共享业务 Schema，M7 的 supports_resume 按实现如实声明。上层会话上下文仍由顶层持有，通过 plan.inputs 显式传递业务数据，不把模块检查点塞进顶层聊天历史。

M3/M7 业务版本升为 2.0，公共 AgentRequest/AgentResult envelope 不变。详细字段见 [ICD](interface_contract.md)。现有 operations/refund_waiting 计划原样可用：M3 接受既有 fused_data，M7 接受 order_id/refund_amount/reason；M3 的输出 steps 改为可核对的对象数组。

## M3 数据与模型边界

默认 `M3_MODE=local`：使用显式标准四步计划，实际读取入参、计算环比、整理异常和生成 Markdown。`M3_MODE=live`：使用共享 ChatModel 生成可执行动作序列和运营建议；API 失败或非法计划返回错误，没有隐式本地兜底。中间 compare/anomaly 可以交换，fetch 必须先执行，report 最后执行。

本次适配明确解决原代码的两项数据问题：不再用缺失数据补零，不把 M6 当前数据与另一套本地上周样例拼成环比。调用方有同口径历史时传 previous_fused_data；没有则报告缺口。转化率差值使用“百分点”，上周分母为零时说明变化率不适用，ISO 周跨年按真实日历计算。

独立 --week 入口读取 M3 样例，将 gmv_amount 映射为示例经营视图的 revenue_amount，仅供演示销售额口径；实际业务中 GMV/收入区别需要 M6 明确。当前扁平视图不含 UV、客单价、活动字段，因此不伪造这些字段或原包中的活动关联。marketing_campaign.json 留作后续 M6 接入参考，尚未参与本次平台链路。

```powershell
Set-Location 'D:\模组\agent-hub'
.\.venv\Scripts\python.exe -m agents.plan_execute --week 2026-W41 --mode local
$env:M3_MODE='local'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m3 --json
# 已配置 LLM 后才运行：
$env:M3_MODE='live'
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --real-m3 --real-m5 --json
```

## M7 等待与恢复

普通订单金额不超过 50000 分走自动审批，超过或 risk_level=high_risk 则停在 manual_review 前。来源省略 risk_level 时兼容样例默认 normal；显式提供时只接受 normal/watch/high_risk（watch 为观察标记，沿用金额审批规则），未知或格式错误值返回 CONTRACT_MISMATCH。自动审批不补造材料齐全的事实；高风险订单需明确人工决定及完整材料才能通过 R3。只有 paid/shipped/delivered/completed 状态可退款；canceled/refunded/not_found/pending_payment/refunding 直接驳回，未知或格式错误的来源状态返回 CONTRACT_MISMATCH。node_trace 只包含已经执行的节点，等待时不会虚构 manual_review 已完成。人工拒绝是 completed + data.approval_status=rejected；输入错误是 failed。

检查点和 token 只保存在当前模块实例的内存中。一次 CLI 退出后 token 失效；顶层 Conversation.review/Executor.resume 已支持显式恢复，并继续等待任务的就绪后继步骤。要演示恢复，应在同一 Python 进程保留 agent：

```python
from agents.workflow.refund_graph import RefundWorkflow
from common.contracts import AgentRequest

agent = RefundWorkflow()
request = AgentRequest(
    request_id='req-000000000001', task_id='task-000000000001',
    trace_id='trace-0000000000000001', capability_id='m7.refund_approval',
    payload={'order_id': '2025101234', 'refund_amount': 69900, 'reason': '退货'},
)
waiting = agent.invoke(request)
result = agent.submit_decision(
    waiting.continuation_token, approved=True,
    reviewer='本地测试审核人', material_complete=True,
)
assert result.status == 'completed'
assert result.data['approval_status'] == 'approved'
trace = agent.get_request_trace(request.request_id)
```

上例只演示样例订单审批，不调用支付接口。大额或高风险订单的 material_complete=False 会进入原合规反思路径，清空先前人工决定，返回新 token 等待再次审核；不能自动假定用户已补齐材料。若决定已经提交但读取或构造结果失败，原 token 保留，同一决定重试只读取已提交状态，不再次执行审核；尝试换用其他决定会失败。成功返回才消费旧 token，再次等待则发放新 token。低层 run/get_trace/rollback/resume 可用于检查点演示，rollback 从历史检查点分叉且不会重复追加 reducer 列表；低层 API 不负责更新平台报告，也不应与待恢复的模块级提交混用。

保留上游静态断点方案并依据官方 [检查点与恢复说明](https://docs.langchain.com/oss/python/langgraph/interrupts) 和 [历史分叉说明](https://docs.langchain.com/oss/python/langgraph/use-time-travel) 校对恢复与回滚 API；对应行为由本地测试验证。

## 验证与剩余事项

本轮离线测试覆盖真实计算、模型注入、缺失/错误输入、ID 与日志关联、Schema 一致性、四模块同时替换、顶层规划链路、50000 分边界、人工批准/拒绝、反思再等待、token 消费与请求隔离、回滚恢复、独立 CLI。

最终结果：**297 passed / 14 skipped，18.51 秒**，本轮新增 50 项测试。14 项为原有真实 API 测试，未开启。运行产物显示经营链 completed、退款链 waiting_approval、模块级提交决定后 completed。

依赖新增 LangGraph 1.2.15，装入主体自己的 .venv；没有复制上传包的虚拟环境。requirements-tested.txt 记录已验证环境，pip check 通过。最终测试结果和执行样例存于 tests/artifacts/m3_m7_*。

尚未完成：真实模型与搜索/图片 API 联网验收、M1/M2/M6 真实模块接入、实际业务数据与风控策略、平台统一审批恢复。当前完成的是源码与现有 Mock 集成环境接通。
