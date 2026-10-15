# 金额元迁移与 M4 稳定性修复验收（2026-10-15）

规范真源仍是 naming_convention.md 与 interface_contract.md；本文仅记录本次实现和验证。

## 金额

前端、公共 Schema、七个 Mock、真实模块、Planner、CLI 与维护中的 Fixture 已统一使用人民币元。页面输入/结果显示两位小数；接口使用 JSON number，尾随零不属于 JSON 数值语义。M2/M3/M5/M6/M7 Manifest 分别升级为 2.0/3.0/3.0/2.0/3.0。

退款阈值为 500.00 元；499.99/500.00 自动，500.01 等待，高风险仍需人工。去掉退款节点的 int 截断。Decimal 计算出的客单价按 ROUND_HALF_UP 保留两位，例如 2.01÷2=1.01；原始订单/退款输入超过两位小数则明确拒绝，不能替调用方改金额。订单事实与退款金额仍须相等。

group02 归档 JSON 保留分单位与原始字节；BusinessData.read 明确转换一次，向业务模块提供元。Excel 原本为元，审计也统一为元核对。14 个来源文件哈希全部一致，8 张 Excel 表的 2,593 个字段核对无差异。自定义数据加载器与 M6_DATA_DIR 须使用新元契约；不能把 BusinessData.read 返回值写回分单位归档。

## M4

初始回归复现了截图中的 CONTRACT_MISMATCH：模型输出合法 JSON 的 Markdown 包裹会被拒绝，而 M4 的 ChatModel 没启用 JSON mode。

现开启 JSON mode，兼容恰好一个完整 JSON 包裹，继续严格验证对象字段、类型、非空值和 Skill 注册范围。失败反馈具体校验错误，最多修复一次，合计两次模型尝试。只有校验通过才分发 Skill；搜索/生图等工具不会随格式修复重复执行。鉴权、余额、限流及网络错误不进入格式重试。第二次仍不合格就保留明确失败，不返回假成功。没有改造平台 Executor，也没有额外搭建 LangGraph。

浏览器检查另发现搜索摘要偶尔在真实来源已返回时自称不能联网。补充搜索专用证据提示，要求说明结果缺口、保留引用，不混称企业知识库、不编造网页全文。随后两次真实搜索复验通过。此为抽样验证，不宣称模型永不出错或已核实摘要中的每项事实。

错误信息显示路由或 Skill 阶段，格式重试耗尽时包含尝试次数；前端新增可展开复制的完整错误 JSON 与 request_id/trace_id，长文本换行，M4 不再截掉错误消息尾部。密钥仍脱敏。

## 验证与日志

| 范围 | 结果 |
|---|---|
| 最终全量 pytest | 1434 passed / 36 skipped，42.46 秒；36 项收费测试默认关闭 |
| 前端 Node 测试 | 13 passed |
| 新 wheel 独立离线启动 | 七个入口检查通过；另外三个打包资源测试通过 |
| M4 真实端到端 | 代码生成两次、搜索两次，4 passed |
| 元金额真实跨模块链 | 双周融合→周报→营销，订单→退款→审批续跑，2 passed |
| 搜索摘要提示修正后 | 搜索两次，2 passed |
| 浏览器 | 1099.00 元退款进入等待；截图同一句 Python 请求返回 live 代码；搜索返回服务商真实来源；控制台无错误 |

联网自动化共 25 次外部请求及 25 次响应，零传输错误。完整脱敏请求/响应在本地 `audit_artifacts/yuan-m4-live/`、`yuan-business-live/`、`yuan-search-recheck/` 的 http.jsonl；各目录 results.xml 含模块/计划执行报告。离线日志在 yuan-final.log/xml，前端在 yuan-frontend.log，来源核对在 yuan-source-audit.json。原始日志不上传远端，提交可分享摘要 tests/artifacts/yuan_m4_acceptance.json 及页面截图。

本轮没有重新付费测试生图、M1 多轮问答及所有语义场景；它们有全量离线回归，不冒充全量联网覆盖。M4 真实模型需支持 OpenAI-compatible JSON response_format；不同供应商需用自己的配置复验。

更新时前后端一起拉取、重启后端并刷新页面，新建会话，不能复用旧分单位计划。正常启动 `python -m web`；离线用 `python -m web --offline`。测试命令：

```powershell
python -m pytest -q
node --test tests/frontend/rendering.test.cjs
# 下列显式开启收费调用；密钥保存在本机环境变量中
$env:M4_RUN_LIVE_TESTS='1'
$env:HUB_LIVE_LOG_DIR='audit_artifacts/m4-recheck'
python -m pytest tests/live/test_m4_live.py -k reported_m4 --run-live
```
