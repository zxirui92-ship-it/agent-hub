# PRD 验收对照与本轮交付

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

2026-10-14。对照 `requirement.md`、`original_assignment.md` 及现有公共契约。本文件是实现和证据索引，不是新的接口规范，也不代替组员对政策、架构选型或答辩材料的最终确认。

## 已完成的工程补齐

| PRD / 作业验收点 | 当前实现 | 证据 |
|---|---|---|
| AC-M1-01/02/03 多轮、双工具、独立入口 | FAQ/政策分别检索；明确追问可利用窗口上下文；闲聊和无命中不直接失败，文件故障仍失败 | test_prd_completion.py 的M1两项；group02_live 的昵称、问候与政策冲突 |
| AC-M2-01～05 工具循环、异常、轮次和轨迹 | 有界ReAct保留公开决策摘要、Action/Observation/终止；事实由共享源校验 | test_m2_react_agent.py、test_group02_data.py；真实正常/冲突订单两例 |
| AC-M3-01～04 计划/执行、环比、报告 | 两周平台示例、相邻周校验与代码环比；模型获得两周完整依据；共享计算移至common，无M6私有导入 | test_m3_plan_execute.py、test_prd_completion.py；真实双周报告 |
| AC-M4-01～03 四Skill、注册扩展、兜底 | 四Skill保留，group_02知识来源与冲突可见，第5Skill测试保留 | test_m4_router.py、test_m4_services.py、test_m4_platform.py；真实语义知识路由 |
| AC-M5-01～03 四角色、消息、综合方案 | 原四角色实现和汇总保留，消费新资料周报与预算 | test_m5_multi_agent.py、test_m5_platform.py；真实双周→周报→方案链 |
| AC-M6-01～04 多源黑板和依赖响应 | 四写入/处理角色，私有黑板、订阅队列、完整事件；共用纯计算不改变控制流 | test_m6_blackboard.py、test_group02_data.py |
| AC-M7-01～05 分支、人工恢复、回跳、检查点 | 模块原有能力保留；新增通用审批扩展，平台可续跑；高风险小额不走自动审批 | test_m7_workflow.py、test_prd_completion.py；prd_demo.json的等待/反思/完成/回滚 |
| PC-01～04 动态组合与显式绑定 | 真实Planner按注册能力生成本周/上周两次融合，再生成周报与方案；无模块名称分支 | test_planner.py、test_conversation.py；prd_group02_live.xml 的生成计划 |
| PC-05/06 失败隔离与等待 | 失败阻断依赖，独立分支继续；等待报告保存；显式审核后只运行就绪pending步骤 | test_executor.py、test_prd_completion.py；通用非M7插件、双等待分支、错误关联/Schema测试 |
| PC-07 / NFR-01 独立运行 | README原有七模块命令保留，新增资料示例与统一离线演练 | 原独立CLI回归；scripts.demo_prd实际执行 |
| NFR-02 模块低耦合 | M3不再导入BlackboardController；common.weekly_data只含计算和源读取 | AST依赖检查；两周视图一致性测试 |
| T-04 / T-07 重点演示 | M2两轮轨迹，M7材料不足反思、续跑与检查点回滚均已重放 | prd_demo_console.txt、prd_demo.json |
| 交付：七张架构图 | 新增docs/architecture.md，另附平台审批续跑图 | 源码对应说明与Mermaid文本；课堂演示前由组员预览 |
| 交付：测试与演示脚本 | 测试文件、XML、真实回答和7分30秒演练提纲齐备 | docs/demo_script.md；实际课堂演示/录屏仍需小组完成 |

测试文件位于tests/unit、tests/integration或tests/live相应目录。统一接口仍为invoke；可选审批扩展以interface_contract.md为准，不通过重新invoke假装恢复。

## 测试与内容核查

最终离线回归 **460 passed / 30 skipped，20.32秒**，见 `tests/artifacts/prd_offline.xml`。本轮从438项基线上新增22项M1、M3、平台恢复及演示测试；所有原有合理测试保留。最初有一项旧断言把工具输出与M4输出逐字相等，新增检索状态后改为验证同源事实和双工具；没有删除该用例。

真实模型使用本机 `deepseek-flash`，共两批：首轮 **5 passed，206.42秒**；修正后的限定复验 **2 passed，36.08秒**。合计7次用例执行，覆盖6个不同用例；不是7个独立场景，也不代表总体准确率。新付费用例均受 `--run-live` 与 `BUSINESS_RUN_LIVE_TESTS=1` 双开关约束。

- M1：复验自然问候，保留昵称海风，引用F019/SP007并明确保修冲突；未自行选定年限。
- M2：2025100003返回12900分和已签收；2025101234因源资料冲突失败，未伪造成功。
- M4：真实语义路由选择kb_qa，读取导入资料；未重复调用联网搜索和生图，二者已有历史实测记录。
- M3：W41成交1268000000分，销售额环比-8.91%、订单量-7.28%、转化率变化-0.31个百分点。复验模型可引用W40和W41完整漏斗，明确观察与假设。
- M5：四角色综合方案保留金额单位、10000元总预算和4000/4500/1500元阶段分配，资源和目标标为待确认/假设。但将阶段与渠道预算描述成冲突的措辞不够严谨，二者可交叉分配；方案仍需业务人员评审。

首轮真实经营链约190.68秒，不能据此承诺10秒响应。记录了各用例耗时、规划尝试次数和注入模型调用数；后者不包括工厂创建的M4、Planner及M5调用，不能当作总调用数。精确token用量和费用未记录。原始XML与内容核查摘要分别为 `prd_group02_live.xml`、`prd_group02_live_followup.xml`、`prd_acceptance_summary.json`。首轮XML存在pytest xunit2/record_property兼容警告，但属性内容已读取核对；后续采用legacy格式。

## 数据验收与团队待办

原始13份JSON和Excel已经完整保存并核对；实际模块使用FAQ、政策、订单、物流、退款及周汇总。用户、日报、行为、活动明细尚未提供任意查询接口，PRD当前核心场景不要求全表开放查询。来源仍为仿真资料，不是生产连接。

资料负责人需确认物流缺失/时间冲突、R0001以及保修/发票口径，具体清单见data_quality_review.md。代码和测试不能代替这些业务决定。新资料示例使用2025年周次；旧2026年Fixture示例不能混入。

仍需团队完成：确认接口候选与模块负责人验收；确认M2公开决策摘要的答辩口径；评审营销内容；按demo_script.md进行实际课堂演示或录屏；需要共享本轮代码时再提交/推送。PRD中的旧待决策表保留历史状态，并未擅自替团队签字冻结。

## 本次未扩建的范围

审批恢复只保证同一进程、相同Executor/模块实例的串行调用。没有跨进程持久化、并发审批服务、审核员身份认证、生产订单接口或真实退款支付。没有新增前端、数据库服务器或完整RAG。微服务、队列、复杂权限系统不属于本次验收必要项。

## 主要修改

- M1及共享KnowledgeBase：双工具、检索缺失证据、指代追问、闲聊提示；M4保持直接检索未命中失败。
- common.weekly_data / M3 / M6：共享纯计算；双周报告保留完整依据；examples/group02_operations.json新增上周融合步骤。
- common.contracts / M7：新增ApprovalDecision和ApprovalResumable；保留原模块恢复入口。
- Executor / Conversation / CLI：保存等待任务，显式审核、校验、拓扑续跑、审核事件、历史任务选择与reset清理；没有M7专用分支。
- 新增离线/联网测试、演练脚本、七架构图、PRD映射、资料待确认表与报告；同步README、命名规范、ICD和1014开发进度。
