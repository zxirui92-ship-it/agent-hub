# Agent Hub 第一阶段

## 2026-10-15 可靠性整合与前端准备
用户授权整合审计分支并验证全部模拟业务功能；本轮不实现前端、不推送远端。
1. 保存本机成果并合入 dc33ccf：complete（检查点 d56ccdc，分支 codex/reliability-integration-20261015）。
2. 修复枚举、审批恢复及资料常见场景：complete（34知识、79查询、79退款、恢复幂等和真实演练通过）。
3. 全量离线、安装包、七模块与真实 API 验收：in_progress（千问替换不可用DeepSeek，显式配置）。
4. 前端调用说明、可用范围和最终检查点：pending。
resolver 无命名计划，按脚本约定继续使用根目录 legacy 计划。
错误记录：7个合并冲突待逐项解决；首次计划补丁因错误的 findings 标题未完整执行，改用准确上下文。

## 2026-10-13 顶层 Planner 真实 API 接通（完成）
用户决定业务模块联网留到全部集成后；本轮仅顶层语义规划调用本机已有 API，其余执行使用 Mock。
1. 查找配置与连接适配：complete
2. 六项真实语义题及多轮澄清验证：complete
3. 离线回归与使用记录：complete
已发现 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL；只记录变量名称和配置存在性，不复制/打印密钥。复用当前 ChatModel，不更改各业务模块的服务配置。

结果：认证 /models 成功，选用返回列表中的 deepseek-flash。联网 7 passed / 14.46 秒，8 次模型请求均首次通过；真实 CLI 追加一次请求，完成 M2 Mock 查询。离线 302 passed / 15 skipped，17.47 秒。业务模块 API 调用数为零。记录在 docs/planner_api_connection.md 和 tests/artifacts/planner_api_*。

## 2026-10-13 M3 / M7 清理与集成（完成）
目标：从 D:/agent 项目/M3、M7 提取业务源码，保留原始目录，适配当前主体契约并可替换 Mock。
1. 源码、依赖和接口盘点：complete
2. 清洁导入、模块内适配和共享业务 Schema：complete
3. CLI 插拔、图工作流与集成测试：complete
4. 完整回归、来源清单与使用文档：complete
决策：不复制 .venv/.idea、旧 common、旧依赖全集；M3 周汇总 fixture 单独存放，不能覆盖 M2/M7 的订单事实表。保留当前融合数据入参，真实审批停在人工节点。当前平台只负责首次 invoke，模块级恢复能力单独验证，不扩展全平台持久化。

最终验证：297 passed / 14 skipped，18.51 秒；本轮新增 50 项测试。M6 Mock→M3→M5（FakeLLM）完成，M2 Mock→M7 等待，模块同进程批准后完成。原始 19 个文件哈希未变，三个隔离数据文件与原始一致。pip check 和 git diff --check 通过（Git 仅提示行尾转换）。未调用真实业务 API，未提交或推送。

## 目标
实现候选契约、注册表、七个确定性 Mock、计划验证、顺序执行、CLI 与自动化测试；不扩展真实 Agent / LLM Planner。

## 阶段
1. 需求和空目录审查：complete
2. 公共契约、Registry、Mock：complete
3. Validator、Executor、CLI：complete
4. pytest 和 CLI 验证：complete
5. 文档与交付报告：complete

## 决策
- PRD 原样复制；原始作业为课程需求基线，粘贴指令决定本轮范围。
- 暂用同步 invoke；不提供 resume，waiting 下游保持 pending，独立分支继续。
- JSON Schema 使用明确的可组合子集，注册时拒绝不支持的关键字；运行前后校验数据。
- 本工作目录为空且非 Git 仓库，不创建虚假历史或推送。

## 错误记录
- PowerShell profile 的 conda 启动报错：后续命令 login=false。
- 全局 Python 缺少 pytest：建立项目虚拟环境安装依赖。
- venv ensurepip 失败：使用全局 pip --python 指向项目 venv 安装。
- 沙箱网络限制导致首次 pip 失败：授权审核通过后依赖已安装。
- 首轮测试 64 passed / 1 setup error：Windows 沙箱临时目录不可写，pytest 临时根改为项目内 .pytest_cache/tmp。
- pytest 的 zip 参数化弃用警告：改为 list(zip(...))。

## 2026-10-13 M5 本地接口统一
目标：导入 group_02 的 M5，保留四角色协作，统一到本地公共契约，并验证可替换 Mock；不执行外部 API、不推送。
1. 上游来源与接口差异核对：complete
2. M5 公共业务 Schema、真实模块与 Mock 统一：complete
3. 固定计划接入、独立入口及离线回归：complete
4. 接口迁移与交付文档：complete
决策：保留本地 common 契约与 LLM transport；M5 使用 goal + 可选 report_markdown/week/budget_amount/fused_data，roles 数组；变更 M5 版本为 2.0，旧 report 入参显式拒绝，更新本地 fixture。

本阶段测试记录：首轮 M5 定向测试 36 passed / 1 failed；测试错误地要求多行周报原文出现在上游已有的压平摘要 Prompt 中。边界传参断言已通过，修正模型输入断言为核对实际周次和异常事实，保留上游摘要逻辑。

最终验证：206 passed, 8 skipped in 10.86s；8 项均为原有 M4 live 测试。离线经营链产物已保存；git diff --check 无空白错误（仅 Windows 行尾提示）。未执行真实模型调用，未提交或推送。

## 2026-10-13 顶层语义路由与会话上下文
目标：自然语言 + 顶层会话历史 → Registry 驱动的动态计划 → 现有校验与执行；先保证可用，避免额外安全/审批体系。
1. 设计 Planner 输出与会话边界：complete
2. 实现 Planner、内存上下文和自然语言/交互 CLI：complete
3. 单能力、复合任务、澄清、修正、M4/M5 替换测试：complete
4. 文档、离线演示记录与全量回归：complete
决策：识别与规划合并为一次模型调用；ready/needs_clarification/unsupported 三种模型结果；使用现有 ExecutionPlan 和 Validator。默认最多修正一次非法输出，不重复执行失败业务。会话先保存在进程内，不增加数据库或自动摘要。沿用现有 LLM 配置，暂不增加限流、审批 Agent、额外防护层。

验证：新增定向测试 41 passed；全量 247 passed / 14 skipped，35.48 秒。未出现本阶段测试失败。14 个 live 用例因未显式开启而跳过，且本地三项 LLM 配置均未设置；不能宣称语义准确率实测通过。已保存 scripted planner 离线交互产物，文档说明实际调用方式与内存会话边界。

## 2026-10-14 M1/M2/M6 接入新版工程
用户授权：将 D:\agent 项目 提供的 M1.zip、M2.zip、M6_blackboard.py 接入 D:\模组\agent-hub。保留此前全部未提交成果。
1. 来源、契约及基线核对：complete（302 passed / 15 skipped）
2. 迁移三个模块、共享 Manifest、数据源与 CLI：complete
3. 架构单测、七模块替换、经营/退款链回归：complete
4. 来源记录、启动说明、限制与验收报告：complete
决策：不覆盖 common；M1 保留单模型与窗口记忆，工具按 FAQ 职责调整；M2 保留有界观察驱动 ReAct，使用共享 TextModel 和订单事实；M6 保留私有黑板和订阅响应，输出既有平面经营视图，缺失营销实绩明确披露。默认测试禁网，不调用真实业务 API。
- 首轮新增单测：47 passed。集成测试：17 passed / 1 failed，原因是旧 Mock M4 样例未含真实 M4 离线路由器要求的 skill 前缀；修正七模块测试输入为 kb_qa: 优惠政策，未改 M4 实现或降低断言。
- 迁移、共享契约及 CLI：complete；新增定向测试 65 passed，3.35 秒。
- 七架构替换及全量回归：complete；367 passed / 15 skipped，24.06 秒。真实业务 API 本轮未调用。
- 来源记录与启动/验收说明：complete；产物 tests/artifacts/m1_m2_m6_pytest.txt 与 m1_m2_m6_offline_demo.json。

## 2026-10-14 联网实测准备
目标：补齐业务模块与真实编排链的显式 live 验收入口；只准备和离线验证，不因 pytest 默认运行产生付费调用。
1. 配置与现有入口核对：complete。仅 DEEPSEEK_BASE_URL/API_KEY 已设置；业务 LLM、搜索、生图缺配置（未输出值）。
2. 无网络配置检查、M1/M2/M3/M5 与经营/退款 live 测试：complete。
3. 离线验证测试开关与使用文档：complete。371 passed / 22 skipped，58.88 秒。
业务模型是否沿用 DeepSeek 的偏好已询问，准备工作继续，不修改密钥或自动启用服务。

## 2026-10-14 本机模型配置及真实 API 验收
用户授权开始真实 API 测试并使用本机配置；生图变量前缀 BAILIAN（用户补存后已读取并完成实测）。
1. 文本模块统一复用本机 DeepSeek / 显式 LLM 配置：complete（含百炼千问可选配置）。
2. 百炼接口适配与隔离测试：complete（实际生成一张，返回真实 URL）。
3. 分批联网、记录失败并修复、全量离线回归：complete。388 passed / 23 skipped；实测分批记录见 docs/local_api_acceptance.md。
不输出或写入密钥；不改原始用户交付文件；不自动推送。

## 2026-10-14 国内联网搜索接入
用户授权自行配置国内服务；复用百炼北京业务空间和环境变量，不复制密钥。
1. 核实官方搜索协议与配置：complete。使用原生 text-generation、强制搜索和来源返回。
2. Skill、配置及离线回归：complete。基线 388/23；最新 409 passed / 24 skipped。
3. 实际联网验证来源及 M4 平台调用、记录结果：complete。初次 403；用户充值后 2 passed，来源各 10 条。检索相关性不等同系统验收。
不修改 Executor 或知识库检索，不自动推送。

## 2026-10-14 全量提交并更新远端 main
用户明确授权全量推送并直接更新主分支，覆盖此前“不自动推送”的限制。
1. 检查工作区、测试证据、密钥及远端状态：complete。155 个候选文件扫描未发现凭证；最近回归 409 passed / 24 skipped。
2. 全量提交并推送 main：complete。105 个文件，9707 行新增、80 行删除；开发提交 ecd1481 已推送。GitHub 直连失败，使用系统现有代理完成。
3. 核对本地与远端提交及工作区：complete。ls-remote 确认 main = ecd1481aee4c80d67478d58f6ec679cf462f2684，本地工作区干净；本记录随后作为文档提交同步。

## 2026-10-14 Gitee 数据库接入
用户指定 https://gitee.com/baisumartin/0727-rag_-agent.git，要求检查数据库部分、拉取并接入整体平台。
1. 拉取独立源仓库、核实数据库和数据内容及兼容边界：complete。用户确认 group_02，固定提交 7f70950d6cfea4cab0f8a8b996e176d5eee55ae2。
2. 最小数据接入、相关模块配置和一致性校验：complete。HUB_DATA_DIR 选择源 JSON，M1/M4 共用知识、M2/M7 共用订单，M6 周数据供 M3/M5 消费；Mock 保留原基线。
3. 资料完整性、模块集成测试、全量回归和交付文档：complete。源是 JSON/Excel，无需数据库服务初始化。438 passed / 24 skipped；三条 CLI 示例成功；8 张 Excel 业务表 2593 字段值核对一致。详见 docs/group02_data_integration.md。
保留未提交的 1014开发进度.md；本轮不自动推送，不导入外部密钥，不执行未经检查的初始化脚本。
环境记录：默认 shell 创建失败（setup refresh）；提权工具执行恢复可用。网页读取 Gitee 失败，改用 Git 拉取。

## 2026-10-14 PRD 验收补齐（用户授权继续完成）
1. M1 双工具/闲聊/上下文检索，M3 共享数据边界及平台双周示例：complete。包括两周完整模型依据与闲聊复验。
2. 公共可选审批恢复协议、Executor/Conversation/CLI 同进程续跑及异常回归：complete。真实M7和自定义测试插件均通过，旧步骤不重跑。
3. 数据问题清单、七张架构图、需求测试映射、8分钟演示与进度更新：complete。演练脚本实际执行，资料政策决定和实际录屏留给团队。
4. 全量离线回归、新资料真实模型抽样、记录内容与边界：complete。460 passed /30 skipped；首轮真实5 passed，限定复验2 passed；报告明确内容限制。
业务政策冲突保留待业务确认，不自行统一来源或伪造缺失物流；不增加生产数据库/支付/前端，不自动推送。

## 2026-10-15 Dots整合与可靠性验收
用户授权拉取、整合修复并测试，以进入前端开发；不推送远端。
1. 保存原有工作并整合Dots审计分支：complete。d56ccdc保存本地成果，合入dc33ccf。
2. 修复来源状态、订单可查询性、审批重试及回归：complete。
3. 本机真实联网、内容检查及针对性修复：complete。31个不同live场景均有通过记录；预算/JSON失败修复后复验，M5日期及客单价再次修复并实测。
4. 完整离线、安装包和前端交付说明：complete。1368 passed/31 skipped；7项wheel检查通过；docs/reliability_acceptance.md与docs/frontend_handoff.md。
结论：可进入模拟项目的前端集成。M5自由文本仍会推演错误，报告明确实例；未声明任意回答无误。HTTP、跨进程持久化、实际支付和前端未实现。

## 2026-10-15 小组本机配置适配
用户选择各自在本地运行后端、首次映射变量名。
1. 统一标准字段_ENV读取本机任意变量名：complete。文本/Planner/搜索/图片均支持，不修改模块接口或系统环境。
2. 模板、离线检查、映射错误与脱敏：complete。新增.env.team.example及docs/team_configuration.md。
3. 验证：complete。1376项全量离线通过，3项包内测试补跑通过，安装后7项检查通过；真实本机配置改名诊断成功，无API费用。
4. 随团队交接同步远端main：complete（8a300a5，已核对远端）。

## 2026-10-15 成员前端整合与真实服务默认值
工作目录D:/模组/agent-hub-frontend；源zxy258455/agent-hub，基线4760d44，包含8a300a5及两个前端提交。原项目保持不变。
1. 阅读新增前后端、建立数据哈希与默认Mock复现：complete。
2. 修复原始文件字节、真实服务默认值及必要前后端连接问题：complete。
3. 离线完整回归、真实本机API/浏览器端到端验证：complete。首轮联网1426通过1失败，修复后受影响12项全部通过；日志保留。
4. 启动说明、验收记录及本地开发提交：complete。此次未授权向成员仓库推送。
约束：保留Dots修复；真实服务失败不得隐式返回Mock；密钥只读本机环境。截图给出的换行根因先验证，不能仅改清单哈希掩盖问题。
错误记录：首次计划补丁包含不匹配的findings上下文，原子操作未应用；拆分后重试。
