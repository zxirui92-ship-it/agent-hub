# 七种 Agent 架构与平台边界

2026-10-14，按当前实现绘制。图中“模型”在离线测试中可注入显式替身；真实路径复用公共 TextModel。模块统一对外 `invoke(AgentRequest) -> AgentResult`。

## M1：Single Agent

```mermaid
flowchart LR
    U[咨询和 session_id] --> A[SingleAgent]
    A --> M[窗口会话记忆]
    A --> F[lookup_faq]
    A --> P[get_service_policy]
    F --> K[共享知识源]
    P --> K
    M --> L[单一 LLM]
    F --> L
    P --> L
    L --> R[回答并写入记忆]
```

对应 `agents/single_agent.py`。两个工具分别检索 FAQ/服务政策；明确指代的追问可以使用窗口内用户问题定位主题。无命中返回资料缺失证据，闲聊不因此失败；源文件错误仍明确失败。业务冲突保留来源和提示，不由模型裁定权威。

## M2：ReAct

```mermaid
flowchart TD
    Q[订单号与查询意图] --> D[LLM 决策摘要]
    D --> A[选择一个剩余工具]
    A --> O[query_order 或 query_logistics]
    O --> V[观察值与 Schema 校验]
    V --> G{订单和物流均齐全且一致?}
    G -->|是| R[返回事实和轨迹]
    G -->|否| N{达到轮次上限?}
    N -->|否| D
    N -->|是| E[EXECUTION_LIMIT]
    O -->|工具或资料错误| F[失败并保留已有观察]
```

对应 `agents/react_agent.py`。输出公开决策摘要、Action、Observation、停止原因；不暴露模型隐藏推理。订单号由程序固定，模型只能选择工具。仿真订单由公共数据源提供。

## M3：Plan & Execute

```mermaid
flowchart LR
    I[本周及可选上周视图] --> P[WeeklyReportPlanner]
    P --> S[编号动作计划]
    S --> E[WeeklyReportExecutor]
    E --> F[读取指标]
    F --> C[计算环比]
    C --> A[异常与证据限制]
    A --> R[Markdown 周报]
    R --> L[可选模型建议]
```

对应 `agents/plan_execute.py`。规划与执行有独立类；环比由代码计算，模型建议标注待验证。相邻上周必须通过统一输入传入；独立入口可用 `common/weekly_data.py` 读取同口径视图，不导入其他 Agent 私有实现。

## M4：Router + Skill

```mermaid
flowchart TD
    U[用户请求] --> R[语义 Router]
    C[Skill Registry 描述清单] --> R
    R --> D[Skill 名称和选择理由]
    D --> V[Registry 查询与调用]
    V --> W[web_search]
    V --> K[kb_qa]
    V --> G[code_gen]
    V --> I[image_gen]
    W --> O[统一结果]
    K --> O
    G --> O
    I --> O
    R -->|无匹配| F[明确失败]
```

对应 `agents/router/`。搜索与生图可接百炼；知识检索读取本地资料；代码生成不执行代码。新增 Skill 实现并注册即可，Router 没有按四个名称硬编码分发。

## M5：Multi-Agent

```mermaid
flowchart TD
    U[目标和约束及上游事实] --> O[Orchestrator]
    O --> P[产品 Agent]
    O --> B[运营 Agent]
    O --> D[数据 Agent]
    O --> S[客服 Agent]
    P --> M[带角色的消息与结果]
    B --> M
    D --> M
    S --> M
    M --> A[汇总与取舍]
    A --> R[大促综合方案和角色贡献]
```

对应 `agents/multi_agent.py`。四角色执行及汇总均有记录；事实来自显式输入，不读取其他模块私有状态。离线演示注入 FakeLLM，只验证协作结构，不代表营销质量已验收。

## M6：Blackboard

```mermaid
flowchart TD
    S[订单 行为 营销三类源] --> C[有界控制器]
    C --> O[订单写入者]
    C --> U[行为写入者]
    O --> B[私有 Blackboard]
    U --> B
    B -->|订单更新触发| M[营销处理者]
    M --> B
    B -->|订单 行为 营销齐全| I[洞察处理者]
    I --> B
    B --> R[融合视图 字段口径 更新事件]
```

对应 `agents/blackboard.py`。黑板仅属于一次 M6 调用；订阅触发队列，读/处理/写/响应事件可检查。计算函数可共享，但 Blackboard 和队列不共享给 M3。

## M7：LangGraph Workflow

```mermaid
flowchart TD
    S[Start] --> R[受理和统一订单快照]
    R --> C{订单状态 金额 风险}
    C -->|不可退款| F[结束并驳回]
    C -->|小额且非高风险| A[自动审批]
    C -->|大额或高风险| W[暂停并保存检查点]
    W --> H[显式人工审核决定]
    H -->|拒绝| F
    H -->|同意| V[合规校验]
    A --> V
    V -->|通过| E[结束并记录审批结果]
    V -->|不通过| T[反思和记录缺项]
    T --> L{未达上限且可人工复核?}
    L -->|是| W
    L -->|否| F
```

对应 `agents/workflow/`。金额阈值 50000 分；高风险小额必须核验材料。检查点支持同进程恢复、轨迹和流程状态回滚；不执行支付，也不宣称回滚可撤销真实打款。

## 平台补充：规划、执行与审批续跑

```mermaid
flowchart LR
    U[自然语言] --> P[Dynamic Planner]
    C[Capability Registry] --> P
    P --> V[Plan Validator]
    V --> E[依赖拓扑 Executor]
    E --> M[M1 到 M7 统一 invoke]
    M --> R[执行报告]
    R -->|waiting_approval| W[保存计划及步骤状态]
    H[显式 review 决定] --> W
    W --> X[可选 resume_approval 协议]
    X --> E
```

恢复时校验原关联 ID 与输出 Schema，只运行新就绪的 pending 步骤；已完成步骤不重跑，等待不是成功。没有 M7 名称特判。只支持同进程、串行调用；重启后的持久化恢复不属于本次实现。
