# 前端接入说明（2026-10-15）

本轮整理的是可复用的 Python 业务入口，尚未实现 HTTP 服务、前端页面或跨进程会话持久化。浏览器接入时，在这些入口外增加薄 HTTP 层即可，不要重写 Planner、Executor 或七个 Agent。验收结果见 reliability_acceptance.md。

## 本机启动

在仓库根运行。密钥仅从本机环境读取；本机 `.env` 已显式选择 `LLM_PROVIDER=bailian`、`BAILIAN_TEXT_MODEL=qwen-plus`、`HUB_DATA_DIR=data/group02`。所有文本模块共用千问；搜索、生图共用百炼配置，图片模型独立。DeepSeek 本轮文本请求超时，因此不作为本机验收默认服务；没有自动降级到 Mock。

```powershell
$env:M3_MODE='live'
.\.venv\Scripts\python.exe -m hub_platform --chat --json --real-m1 --real-m2 --real-m3 --real-m4 --real-m5 --real-m6 --real-m7
```

默认 CLI 不带 `--real-m*` 时使用七个 Mock，不应把这种输出当作实际模型演示。全部真实模块清单可以用 `--list-capabilities` 加上述七个开关查看，无模型费用。

## 后端会话入口

以下组装与现有 CLI 相同。每个前端会话保留一个 Conversation；不要每条消息重新创建，否则会丢失记忆和等待审批的状态。

```python
from agents.single_agent import SingleAgent
from agents.react_agent import ReActAgent
from agents.plan_execute import WeeklyReportAgent
from agents.router.factory import create_agent
from agents.multi_agent import PromotionAgent
from agents.blackboard import DataFusionModule
from agents.workflow.refund_graph import RefundWorkflow
from hub_platform.registry import CapabilityRegistry
from hub_platform.planner import DynamicPlanner, configured_model
from hub_platform.conversation import Conversation

registry = CapabilityRegistry()
for module in (SingleAgent(), ReActAgent(), WeeklyReportAgent(mode='live'),
               create_agent(), PromotionAgent(), DataFusionModule(), RefundWorkflow()):
    registry.register(module.manifest, module)
chat = Conversation(DynamicPlanner(registry, configured_model()))

result = chat.submit('查询订单2025100004，再按实际订单金额申请整单退款，原因是买错了。')
response_json = result.model_dump(mode='json')
# 查看 response_json 中实际等待的 step_id，然后提交明确决定：
# chat.review(step_id, {'approved': True, 'reviewer': '演示审核员', 'material_complete': True})
```

现有同步方法对应前端操作：

| 操作 | Python 入口 | 说明 |
| --- | --- | --- |
| 能力列表 | registry.list_capabilities() | 七种能力及输入输出 Schema |
| 发送消息 | chat.submit(text) | 自然语言规划并执行 |
| 仅预览计划 | chat.submit(text, execute=False) | ready 表示计划就绪，未执行 |
| 审批 | chat.review(step_id, decision, task_id=...) | 原任务续跑，保持 task/request/trace ID |
| 当前与历史状态 | chat.context.model_dump(mode='json') | 深复制快照，不可作为恢复指令 |
| 新任务 | chat.new_task() | 保留历史及旧任务审核入口 |
| 重置 | chat.reset() | 清空会话并丢弃平台恢复入口 |

HTTP 路径和状态码尚未定义，不要直接假设 `/api/chat` 等地址存在。建议在下一阶段将上述方法一一映射，保持错误体和报告原样。不同会话隔离；同一会话请求串行，防止发送消息和审批同时操作状态。耗时模型调用放到服务工作线程，前端显示加载状态；本版没有流式 token 或进度推送接口。

## 页面必须区分的状态

| status | 页面行为 |
| --- | --- |
| needs_clarification | 展示 message，继续在同一会话补充参数 |
| ready | 展示预览计划，不能显示“业务执行完成” |
| unsupported | 展示当前能力范围说明 |
| completed | 展示各步骤结果、最终结果及来源 |
| waiting_approval | 展示原因和审核表单，下游尚未运行 |
| failed | 展示结构化错误，同时保留已完成和等待步骤 |

总体 failed 可能同时存在 waiting_approval 步骤，应继续展示它的审核入口。`final_results` 仅有已完成的叶子结果；完整中间结果、审批结果、观察轨迹在 `report.steps`。不能只展示 `message`（它通常是执行状态说明）。

M2 输出金额为整数分，显示时除以100但不要回写浮点金额。`tracking_number=''` 搭配 `logistics_availability=unavailable/inconsistent` 表示物流未核实；展示 warnings，不能显示“物流正常”。只有 available 才展示有效运单。未知订单仍为 NOT_FOUND。

M4 的 `data.result` 是字符串，四个内置 Skill 返回 JSON 文本：前端可尝试解析，但应保留普通字符串回退以支持新增 Skill。web_search 展示真实来源链接；kb_qa 展示来源条目与冲突提示；code_gen 只展示代码，不执行；image_gen 展示服务返回的 URL/base64。服务未配置或失败不显示生成成功。

M7 `AgentResult.status=completed` 不代表批准，必须继续读取 `data.approval_status` 的 approved/rejected。自然语言“同意”不会执行审核。不要通过重新发送原任务模拟恢复；使用 review 并保留原 task_id。可重试错误说明入口仍可恢复；已提交决定的重试必须使用原决定，不能换一个决定覆盖它。

M5 方案顶部“已核对的基础数据”由程序计算，包含预算、活动日历及客单价；其余角色意见和方案正文属于模型建议，不能标成已执行的业务事实。本次真实经营链约需 100 秒，页面应保持等待状态并避免用户重复提交；不能用固定几秒的前端超时截断它。

## 演示场景

- 客服：“小家电保修几年？请说明不同条目差异。”（资料有冲突，应如实说明）
- 订单：“查询订单2025100003的物流。”（正常）；2025101234 显示物流时间冲突及真实金额239700分。
- 经营：“分别融合2025-W41和2025-W40数据，生成W41环比周报，再制定下周预算10000元的大促方案。”
- 退款：“查询订单2025100004并申请整单退款。”（109900分，人工审核；材料不足可演示回跳）
- 四种 Skill：联网搜索、查询内部知识库、生成加法函数、生成小鸟图片。
- 缺订单号应澄清；未知订单应明确不存在；无法执行的现实动作应明确不支持。

无网络排练：`python -m scripts.demo_prd`，明确使用模型替身，不代替联网验收。服务重启后会话和审批不能恢复；资料为模拟记录，审批不调用支付接口。前端开发当前不需要引入数据库、队列或额外 Agent。
