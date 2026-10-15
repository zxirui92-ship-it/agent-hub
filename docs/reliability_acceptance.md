# 2026-10-15 可靠性整合验收

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

结论：可进入模拟项目的前端集成阶段。七个真实模块、自然语言规划、跨模块执行、知识/订单/经营资料读取及人工审核续跑均已有验收证据。浏览器所需的 HTTP 层尚未实现；现有 Python 会话入口及页面状态约定见 [前端接入说明](frontend_handoff.md)。这不是生产可用性 SLA，也不是对任意模型答案准确性的承诺。

## 版本与范围

- 基线 main：`d47e297`。
- 先将本地 group02 数据、PRD 补齐、平台审批恢复保存为 `d56ccdc`。
- 整合 Dots 分支 `fix/audit-hardening-20261015` 的 `dc33ccf`。
- 当前开发分支：`codex/reliability-integration-20261015`。本轮本地保存，不推送、不更新远端 main。
- 原始 group02 JSON/Excel 保持原字节及来源记录；数据为模拟资料，不调用支付或真实订单系统。

## 实际修正

1. **联合兼容**：保留审计修复和后续 group02/审批续跑两边成果；统一严格 JSON、ISO 周、整数分、安装包资源以及 HTTP/图片响应校验。Mock 和真实模块继续共用公共接口。
2. **来源枚举**：completed 可退款，pending_payment/refunding 不自动退款；watch 保留来源含义，仅 high_risk 强制人工审核。公共订单事实供 M2/M7 共用。
3. **物流不完整时仍可查订单**：M2 契约版本1.2。79个已知订单均可返回金额/状态；41条缺物流、19条物流矛盾明确返回 availability/warnings，运单为空，不编造正常物流。未知订单与损坏数据仍明确失败。
4. **审批可靠重试**：审核决定已提交、结果返回临时失败时，平台保留原续跑入口；只能重试原决定，不重复执行审批或上游订单查询。非重试故障保留失败传播。
5. **明确预算校验**：真实模型曾将10万元错误换为1000000分。现在程序精确换算明确人民币预算，单预算消费步骤执行前校验，不一致走现有一次计划修正。多预算分配不擅自猜测，仍由语义规划处理。
6. **计划 JSON**：真实双周计划曾缺逗号，Planner 已开启模型 JSON 模式，并继续保留 Schema 和业务校验，不以格式模式代替校验。
7. **方案基础数字**：内容检查发现 M5 自算客单价和日历错误。现在程序向四角色、汇总者和最终方案提供预算、ISO活动日历、精确客单价。group02 W41 为19154分/191.54元；2025-W42为10月13日至19日。正文明确标为模型建议。

JSON 模式依据：[百炼结构化输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)、[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。

## 离线与安装验证

环境：Windows，本机 Python3.14.5。最终代码完整回归：**1368 passed / 31 skipped，38.03秒**。跳过的31项均为默认关闭的真实 API 测试，不是删除失败用例。

- 安装 wheel 后在源码目录外运行：**7项通过**，覆盖能力列表、七真实模块注册及 M2/M3/M6/M7 离线入口。
- compileall 通过；pip check 报告无依赖破损。
- 34个知识条目逐条检索、79个订单查询、79个订单退款处理均有离线覆盖。退款“处理通过”包括明确拒绝/等待，并不表示所有订单都获批准；R0001来源矛盾仍显式拒绝。
- PRD 演练含知识、经营、审批等待、材料不足回跳、补齐后完成及检查点回滚。
- 新增第五个 Skill、自定义可恢复模块、失败/等待传播、输出 Schema、拓扑执行及数据深复制等原有测试保留。

最终 wheel SHA256：`2ae20e4adebf83fc28f007b6bd45635eeafd8cbecbe7a73dc069ade6561234f4`。GitHub Actions 已有 Python3.10/3.12配置，本轮没有推送触发远端 CI，不能将它报告为已通过。

## 真实联网结果

本机显式使用百炼 `qwen-plus`，搜索为百炼原生联网搜索，图片为 `qwen-image-2.0`；密钥只从本机环境读取。DeepSeek模型列表可访问，但文本生成超时/失败，保留探针证据，未以 Mock 冒充服务恢复。

| 批次 | 结果 | 证据 |
| --- | --- | --- |
| 千问首次业务/资料验收 | 11通过、2失败，235.08秒 | `tests/artifacts/reliability_live_qwen.xml` |
| 修复预算/JSON后，失败场景复验及余下真实测试 | 20通过，288.10秒 | `tests/artifacts/reliability_live_followup.xml` |
| 修复M5客单价/日历后，双周经营链再次复验 | 1通过，118.67秒 | `tests/artifacts/reliability_live_facts.xml` |

三批合计覆盖**31个不同的真实测试场景**，每个都有通过记录；不是声称一次运行31项全绿，也不是把首次失败抹去。最后一次代码变化集中于M5事实计算，相关离线完整回归和真实双周链均重新通过。

实测覆盖：

- M1问候、记忆、多轮政策与冲突来源回答；M2正常订单、未知订单、仅问金额及物流冲突。
- M3双周漏斗和环比；M6融合→M3周报→M5四角色方案，两种数据集及预算。
- M4四种意图、无法执行的意图、真实联网搜索、知识检索、代码生成、图片服务调用、Executor统一调用搜索。
- 平台语义规划、缺参数澄清、多轮补充、M2→M7等待→模拟明确审批→M1下游继续；上游订单步骤只执行一次。

内容检查：搜索Python文档返回10条真实服务来源，包括docs.python.org；另一“官方百炼文档”查询主要返回阿里云社区文章，相关性不等于官方性。代码生成返回实际函数文本，未执行生成代码。生图返回服务签名URL，未做视觉质量评分或永久存储，链接可能过期。

## 已知边界与仍待处理事项

- **模型自由文本并非全部已校验**：最后方案的基础客单价、日期和预算正确，但正文仍出现将UV下降叙述为“472000→444000估算值”等不可靠推演，与输入的本周UV472000不一致。M5适合作为策划草稿；顶部程序核对事实与模型建议必须分开展示，不能宣布所有正文事实正确。没有通过另加审查Agent掩盖这一边界。
- **资料冲突保留**：41条缺物流、19条物流时间冲突、R0001退款事实矛盾和部分知识政策差异没有改写源记录制造成功。查询会披露；退款对矛盾事实拒绝。团队可后续修订模拟资料。
- **服务与耗时**：本轮两条经营链约99～119秒。页面需要明确等待状态，避免重复提交。外部限流/欠费/网络故障会返回错误；没有压力测试或长期可用率数据。
- **运行状态在内存**：同一会话请求需串行；重启不恢复会话和审核。本轮未实现跨进程持久化、HTTP API、流式进度、前端、真实支付。
- **检索覆盖的含义**：34条逐条检索通过不等于每种改写问法都命中，也不等于未提供资料的问题可以凭空回答。

上述边界不阻止课程模拟项目的前端集成；下一步是薄 HTTP 会话适配、结果/来源展示、审批表单和错误/加载状态，不需要重写七模块或执行器。

## 复现

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir dist
$env:AUDIT_WHEEL=(Resolve-Path dist/agent_hub_foundation-0.1.0-py3-none-any.whl).Path
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/check_wheel.py $env:AUDIT_WHEEL
```

真实测试会产生模型费用，需本机环境配置及显式开关：

```powershell
$env:LLM_PROVIDER='bailian'
$env:BAILIAN_TEXT_MODEL='qwen-plus'
$env:M4_MODE='live'
$env:BUSINESS_RUN_LIVE_TESTS='1'
$env:M4_RUN_LIVE_TESTS='1'
$env:HUB_RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/live --run-live -q
```

新终端应继承已设置的BAILIAN_API_KEY/BAILIAN_BASE_URL；不要把密钥写入测试或文档。本机 `.env`（忽略追踪）另设 `HUB_DATA_DIR=data/group02`。测试分别隔离旧Fixture与新资料，不把同ID不同数据源静默混用。

完整变更清单可用 `git diff --name-status d47e297 HEAD` 查看；当前阶段验收证据统一放在 `tests/artifacts/reliability_*`，早期失败记录也保留。
