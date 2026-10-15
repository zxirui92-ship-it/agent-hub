# 前端接入说明（2026-10-15）

已接入成员提供的 `web/` HTTP 服务和前端页面，复用 Conversation、Planner、Executor 与七个 Agent。Web 默认使用真实服务，只有显式 `--offline` 才使用 Mock。跨进程会话持久化尚未实现。最新验收见 [前端验收记录](frontend_acceptance.md)，此前业务验收见 reliability_acceptance.md。

## 本机启动

小组成员变量名不一致时，使用 [本机变量映射说明](team_configuration.md) 和 `.env.team.example`；只映射名称，不复制或共享密钥。先运行 `python -m scripts.check_live_config` 做不联网的配置检查。

在仓库根运行。密钥仅从本机环境读取；本机 `.env` 已显式选择 `LLM_PROVIDER=bailian`、`BAILIAN_TEXT_MODEL=qwen-plus`、`HUB_DATA_DIR=data/group02`。所有文本模块共用千问；搜索、生图共用百炼配置，图片模型独立。DeepSeek 本轮文本请求超时，因此不作为本机验收默认服务；没有自动降级到 Mock。

```powershell
python -m pip install -r requirements.txt
python -m scripts.check_live_config
python -m web
# 访问 http://127.0.0.1:8000/；更换端口使用 --port 8765
# 无网络排练使用 python -m web --offline
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

HTTP 层已实现以下接口；字段以 `web/server.py` 为准。不同会话隔离，同一会话请求串行。耗时调用在请求线程执行；页面显示加载状态，无 token 流式推送。

| 方法与路径 | 请求/响应 |
| --- | --- |
| GET /api/health | mode 和已注册能力数量 |
| GET /api/capabilities | mode、Manifest 清单、当前数据对应的 examples |
| POST /api/session | 返回 session_id |
| GET /api/context?session_id=... | 会话快照 |
| POST /api/chat /api/plan | session_id、text；执行或仅预览 |
| POST /api/invoke | session_id、capability_id、payload；返回 ExecutionReport |
| POST /api/review /api/invoke/review | session_id、task_id、step_id、approved、reviewer、material_complete |
| POST /api/new | session_id；保留历史，开始新任务 |
| POST /api/reset | session_id；清空会话及直调等待任务，返回新 session_id，前端必须替换旧 ID |

审批布尔字段必须是 JSON true/false，字符串 "false" 会拒绝。无效输入返回 400，会话不存在返回 404；业务失败也可能以 200 返回 failed 报告，前端必须读取业务状态。运行时异常返回结构化错误。模型配置缺失时启动失败，不自动回退 Mock。示例按 `HUB_DATA_DIR` 选择资料，不能把旧样例订单金额与 group02 混用。

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
