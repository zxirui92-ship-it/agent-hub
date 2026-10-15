# group_02 业务资料接入记录（2026-10-14）

> 本文保留首次资料接入的438项测试记录。同日后续已补齐M1双工具/闲聊、M3双周与平台同进程审批续跑，最新460项回归和真实模型抽样见 [PRD验收记录](prd_acceptance.md)。下文“未实现/未联网”是首次接入阶段范围，后续状态以该记录和ICD为准。

已将 Gitee 仓库 `baisumartin/0727-rag_-agent` 的 `group_02` 分支接入 Agent Hub。固定源提交为 `7f70950d6cfea4cab0f8a8b996e176d5eee55ae2`。这是星潮电商的**仿真业务资料包**，由 JSON 和 Excel 组成，没有需要启动的数据库服务器，也不是生产订单系统。

## 来源与文件

源仓库独立下载在 `D:\模组\imports\0727-rag_-agent`；平台使用 `data/group02/` 中的副本。13 个原始 JSON 和原始 Excel 保持字节不变，`source_manifest.json` 记录路径、提交及逐文件 SHA256；同时保存源仓库许可证。`integration_notes.json` 为本项目新增的冲突说明，不冒充源文件。

| 资料 | 数量 | 当前用途 |
|---|---:|---|
| FAQ / 服务政策 | 24 / 10 | M1 与 M4 共用检索 |
| 订单 / 物流 | 79 / 38 | M2 查询；M7 使用同源订单金额 |
| 退款申请 / 退款策略 | 20 / 1 | 历史一致性核对、风险等级及审批阈值 |
| 周销售 / 周行为 / 周活动 | 4 周 / 4 周 / 每周 3 活动 | M6 融合；M3/M5 消费统一输出 |
| 用户 / 日报 / 行为 / 活动明细 | 40 / 60 / 80 / 12 | 保留原始资料，当前不伪装成已接通的查询功能 |

周数据范围为 **2025-W40 至 2025-W43**，不是 2026 年。原始 Excel 的 8 张业务表共 353 行、2,593 个字段值，与 JSON 按主键及明确转换规则核对。Excel 金额为元，原始 JSON 金额仍为整数分，保留来源字节及哈希；BusinessData 读取后显式除以 100 转成元，公共接口使用元。Excel 无时区时间按源 JSON 的 +08:00 核对；运行时订单、物流及退款时间必须带时区。

## 数据选择和模块边界

在项目根 `.env` 设置 `HUB_DATA_DIR=data/group02`；当前本机已经配置，文件不进入 Git。相对路径以仓库根为基准。设为空可回到旧演示资料；选定目录缺文件、缺记录或存在冲突时明确失败，不回退拼接旧订单。默认七个 Mock 仍使用原有确定性 Fixture，使用真实模块需要 `--real-m*`。

- M1：共享 FAQ/政策检索，保留会话和模型适配器。模型提示要求引用来源并披露冲突。离线 `mock` 输出带标记；语义回答质量尚未在新资料上联网评测。
- M4 `kb_qa`：直接返回命中原文、条目 ID、源文件与政策生效日期；命中已知冲突时同时列出相关条目和提示。检索是轻量关键词方式，未引入完整 RAG。`M4_KB_PATH` 可显式覆盖 M4 的知识源，此时不再保证与 M1 共用资料。
- M2：读取订单与物流，订单 `已签收` 映射为 `delivered`，保留工具来源标记 `imported_simulation`；不向模型发送姓名、电话和地址。M2 1.2 在缺物流或时间/状态冲突时返回已核实订单事实、空运单和明确 warnings，不伪造物流。
- M6：使用独立周汇总。成交金额取 `gmv_amount` 元（最多两位小数），转化率为 **下单人数 / UV**。可展示完整漏斗和活动成交额/成本，后者不是利润 ROI。显式 `M6_DATA_DIR` 仍优先使用旧周数据结构，做本次演示请清空它。
- M3：平台输入契约不变，消费 M6 的 `fused_data`；独立 `--week` 入口也能读取选定的 group_02 源。M5 通过现有经营链消费报告和融合数据，无须直接读取数据库。
- M7：共享订单金额，核对相关退款历史的客户、金额和申请时间。源历史审批状态不会自动执行。阈值固定 500.00元，本数据源最多反思 2 次；高风险客户即使小额也转人工，未付款、已退款、退款中或取消订单不能自动通过。不执行退款打款。

公共 Agent Schema、Registry、Validator 和 Executor 没有新增模块专用分支。

## 已知源数据问题

1. 41 个订单缺少物流；另 19 个订单物流更新时间早于下单时间，严格物流数据读取仍报错；M2 查询将这两类业务情况整理为 unavailable/inconsistent 与提示，保留订单金额和状态。原始记录保留，不补造。
2. `2025101234` 在本源中是 2397.00元，不能与旧 Fixture 的 699.00元混用。退款 `R0001` 的客户和金额均与该订单不符，申请时间也早于下单；当前模块在首个不一致处失败。
3. F019 与 SP007 的小家电保修年限存在口径差异；F010/F017/SP008 的发票入口、时点和条件需业务确认。检索提示冲突，不替团队指定政策优先级。
4. 周汇总、日报与订单明细是不同粒度的仿真场景，不强行相加对账；活动成本与周广告费用也不宣称是同一统计范围。原 workbook 说明写“近30天”，实际日报为 60 天。

这些问题不妨碍一致数据的演示，但尚不能把资料包认定为经过业务验收的正式知识库。

## 离线运行

在仓库根执行以下 PowerShell 命令；不会调用付费 API：

```powershell
$env:HUB_DATA_DIR='data/group02'
$env:M6_DATA_DIR=''
$env:M4_KB_PATH=''
$env:M1_MODE='mock'
$env:M2_MODE='local'
$env:M3_MODE='local'
$env:M4_MODE='mock'

.\.venv\Scripts\python.exe -m hub_platform examples/group02_knowledge.json --real-m1 --real-m4 --json
.\.venv\Scripts\python.exe -m hub_platform examples/group02_operations.json --real-m6 --real-m3 --json
.\.venv\Scripts\python.exe -m hub_platform examples/group02_refund.json --real-m2 --real-m7 --json

# 独立模块：
.\.venv\Scripts\python.exe -m agents.router '保修' --skill kb_qa
.\.venv\Scripts\python.exe -m agents.react_agent --mode local --order-id 2025100003
.\.venv\Scripts\python.exe -m agents.blackboard --week 2025-W41
.\.venv\Scripts\python.exe -m agents.plan_execute --mode local --week 2025-W41

# 原始资料完整性和问题清单（无需 openpyxl）：
.\.venv\Scripts\python.exe -m scripts.audit_group02
.\.venv\Scripts\python.exe -m pytest tests/integration/test_group02_data.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

退款示例使用 `2025100003`，金额 129.00元，审批通过但不打款；改用 `2025100004` 后应为 1099.00元、等待人工审核（CLI 退出码 3）。使用 `2025101234` 查询应失败，可验证下游阻断。经营示例刻意将 `s2` 放在 `s1` 前，仍由依赖拓扑排序执行。

审计可加 `--workbook --output 路径` 重做 Excel 核对，需要运行该命令的 Python 环境具有 `openpyxl`，不是平台运行依赖。本机已使用现有工具附带库完成核对，结果保存在 `tests/artifacts/group02_audit.json`。

## 验收范围

最终全量回归：**438 passed / 24 skipped，19.98 秒**，其中新增 group_02 测试 29 项；原有 409 项合理测试全部保留并通过。三个新增平台 CLI 示例均实际执行成功，证据见 `tests/artifacts/group02_cli.json`。原始资料哈希全部一致，Excel 核对差异为 0。工作区成果尚未提交或推送远端。

测试覆盖来源哈希、金额类型、中文状态、订单与退款矛盾、无记录、周转化计算、深复制、数据源隔离、政策冲突提示、高风险小额转人工、审批恢复、三模块经营链与两模块退款链。新集成测试使用真实模块代码和导入文件，模型部分为显式本地/Mock 适配器。全量回归 XML 见 `tests/artifacts/group02_offline.xml`。

本次未调用付费模型、搜索或生图 API；未验证新资料上的真实模型语义准确率。未新增 SQL 服务、资料编辑后台、生产业务连接、平台级审批恢复或真实支付。后续应先由组员确认上述源资料问题，再对新资料开展模型内容验收。

## 修改位置

- 新增 `common/business_data.py`、`common/knowledge.py`：共享数据校验、事实读取和知识检索。
- 接入 `agents/single_agent.py`、`agents/react_agent.py`、`agents/blackboard.py`、`agents/plan_execute.py`、`agents/router/skills/kb_qa.py`、`agents/workflow/refund_graph.py`；修正 `agents/workflow/nodes.py` 风险及订单状态分流。
- 新增 `data/group02/` 原始资料、来源清单和冲突说明；`.env.example` 说明选择方式，本机 `.env` 单独启用该目录。
- 新增 `scripts/audit_group02.py`、`tests/integration/test_group02_data.py`；`tests/conftest.py` 在收集与执行阶段隔离本机数据配置。
- 新增 `examples/group02_knowledge.json`、`examples/group02_operations.json`、`examples/group02_refund.json`，以及 `tests/artifacts/group02_audit.json`、`group02_offline.xml`、`group02_cli.json`。
- 更新 README、现有接口契约、本文、1014 开发进度及规划/发现/进度记录。未复制外部 Agent 代码覆盖当前工程。
