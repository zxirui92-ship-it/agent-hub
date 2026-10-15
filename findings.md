# 需求审查与决策

## PRD补齐后的已知边界（2026-10-14）
- 同进程审批续跑已实现；跨进程持久化、并发审核和真实支付仍未实现，禁止把恢复解释成重新执行整单退款。
- 新资料首轮真实5项通过，M1/M3限定复验2项通过；最新离线460项通过/30项跳过。M5建议预算加总正确，但阶段/渠道预算可交叉，模型“冲突”措辞仍需业务评审；小样本不代表质量达标率。
- 41个缺物流订单按状态分为未付款5、已退款11、退款中6、已发货19；不能全部断言为业务数据错误，也不能直接假造运单。待办见data_quality_review.md。

## 2026-10-13 顶层 API 接通
- 本机进程已有 DEEPSEEK_API_KEY 与 DEEPSEEK_BASE_URL=https://api.deepseek.com，LLM_* 未配置，DEEPSEEK_MODEL 未配置。未输出或保存密钥。
- 认证 /models 返回 deepseek-flash 和 deepseek-v4-pro；选择前者执行顶层语义规划，复用 Chat Completions transport。
- configured_model 仅在通用 LLM_* 整组未配置时使用 DeepSeek；新增 HUB_PLANNER_MODEL 顶层覆盖，不修改业务模块环境。
- 联网七项全部通过（六个单轮 + 一个双轮），8 次模型调用均一次通过，未触发修正；预算、依赖绑定、缺参、unsupported、上下文续接正确。实际 CLI 也完成一次真实路由→M2 Mock 查询。
- 完整离线回归 302 passed / 15 skipped；本轮没有业务模块真实 API 调用。

## 2026-10-13 M3 / M7 整理发现
- 上传源码在 D:/agent 项目/M3、M7，主体在 D:/模组/agent-hub。M3 有 .venv/.idea，M7 只有四个 Python 文件；来源清单记录 19 个非环境文件，原始目录保持不变。
- M3 旧 common.contract/trace 放在 context 的做法与主体 envelope 不兼容；其嵌套 fused_data 也不匹配当前 M6。已统一四个关联字段，使用当前扁平经营视图，steps 改为可核对对象数组，业务版本 2.0。
- M3 同名 order_basic.json 实际为周汇总，不可覆盖 M2/M7 逐单数据。三个样例隔离保存；平台调用不会拿另一套样例补上周数据。营销样例保留但未接入扁平融合视图。
- M7 引用的 common/config/data_loader/policy 未随包提供。保留真实 LangGraph 图和规则，补模块私有适配，复用主体订单事实；本地样例策略明示阈值和反思次数。
- M7 原演示会自行假定人工批准、材料补齐并承诺到账，已改为明确等待/提交决定；不调用支付服务。真实 M7 supports_resume=true，Mock=false，二者共享业务 Schema 2.0。
- 上层依旧通用注册/校验/执行，CLI 只增加两个替换开关。模块内部恢复已验证，顶层计划恢复仍未实现。
- LangGraph 1.2.15 安装在主体 .venv，pip check 通过；最终 297 passed / 14 skipped，19 个源文件与 3 个隔离 fixture 哈希核对通过。

- 已阅读用户第一阶段指令、重写 PRD 和原始作业需求。
- 工作目录无代码、依赖、测试或 AGENTS.md；没有既有公共契约。
- PRD 中 platform/ 与标准库冲突，按用户指令使用 hub_platform/。
- PRD 的自然语言规划、真实七架构、LangGraph 恢复不是本阶段验收目标。
- PRD 附有转义字符，保留原文，不修改业务验收标准。
- 候选接口增加请求 trace_id、结果 task_id，等待原因显式表达；兼容影响写入 ICD。
- 不将文档中的八人协作理解为授权启动 AI 子代理。
- 静态校验覆盖引用类型与形状；值约束和可选字段存在性由运行时校验，已在 ICD 明示。
- JSON Schema 不支持引用/联合类型，注册时显式报错；没有静默接受不完整的 Schema。
- 65 项自动化测试通过，四个 CLI 场景结果和退出码符合预期，PRD/原始需求副本哈希一致。

## 2026-10-13 M5 接入发现
- group_02 最新提交仍为 7bcc1c66302a505ed3528456908ab5621c69c79b；已下载快照与远端 HEAD 一致。
- 上游 M5 引用自己的 common.llm/errors/ids/logging，不能覆盖本地 common；保留其角色、分派、汇总代码，迁移模块边界。
- 本地 Mock 的 report 和 roles 对象与上游 goal/report_markdown/roles 数组不同；需要共享 promotion Manifest，避免两套定义。
- 本地工作树初始干净。项目根历史计划已完成；resolver 无命名计划输出，沿用根计划追加本次阶段。

- M5 业务契约 2.0 已确定：goal 必填；report_markdown、week、budget_amount、fused_data 可选；roles 为 product/operation/data/service 四项数组。旧 report/source_report 迁移方式记录在 ICD。
- 保留上游 200 字符背景摘要及角色格式解析兜底；不宣称真实模型效果已验收。
- 导入 M5 通过现有 Registry/Validator/Executor；平台核心调度未改，只增加 CLI 组装选择 --real-m5。

## 顶层 Planner
- 用户授权自主规划并实现；后续明确要求先可用、宽松工程边界，不急于增加超时等护栏。
- 复用 Registry、PlanValidator、Executor、ChatModel；M4/M5 已有更改保留，不回退。
- 采用一个模型决策协议同时表达可执行计划、缺参澄清、不支持；模型不直接调用模块。
- 会话上下文由顶层持有，业务数据通过计划 inputs 显式传递，模块 context 只带会话标识。

- 当前 `.env`/环境内 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 均未配置（仅检查存在性，没有输出凭证）。所以只验证离线结构与执行链路，真实模型行为题集留待配置后运行。
- 新增 --goal/--chat/--plan-only；--chat 保留内存历史与澄清，可通过 /new、/reset、/context、/exit 操作。
- 当前任务需要澄清时保持 task_id/trace_id；后续任务读取真实历史报告，不共享模块私有对象。
- 新 Planner 不含业务模块名分支，Registry 动态增加能力不需修改 Planner；默认真实 LLM 规划搭配 Mock 业务执行。

## 2026-10-14 M1/M2/M6 来源差异
- M1.zip 仅 single_agent.py，M2.zip 仅 react_agent.py；M6 独立文件，缺失各自 common 依赖和数据。
- M1 旧工具查订单/库存与当前 FAQ 模块职责不符，改 lookup_faq/get_service_policy；模型错误必须返回 failed。
- M2 旧 329 元订单与平台 69900 分冲突，统一 common.order_data；不自动降级为离线成功，真实模型与本地演示显式分开。
- M6 未附原 mock_data。现有 data/fixtures/m3 是周汇总样例，含 GMV、行为转化率和活动预算，缺少实际投放成本/归因 GMV/购买 UV，不可据此计算 ROI 或以订单量除 UV 伪造转化率。保留字段来源与缺口。
- 基线 302 passed / 15 skipped，17.21 秒。未更改 Executor/Validator/Planner。
- M1/M2 新增可选 session_id/query，共享 Manifest 1.1；M6 平面 Schema 和字符串列表保持 1.0，M3/M5 从同一 fused_schema 读取。
- M6 订阅原实现只有日志，新实现真正调度依赖写入者；M2 模型动作协议使用已有 TextModel，无新增 LangChain 供应商框架。
- 最终 367 passed / 15 skipped；全部七架构可替换注册，未改 Executor/Validator/Planner。

## 2026-10-14 联网准备
- 现有顶层 DeepSeek 配置可用于 Planner；业务 LLM/search/image 缺配置，检查仅输出字段是否存在。
- 新增 scripts/check_live_config.py 和 7 项 business_live 用例（M1/M2/M3/M5 与两条真实链）。BUSINESS_RUN_LIVE_TESTS 与 --run-live 双重显式开关，独立于 M4 和 Planner。
- 新增四项离线配置检查测试，不输出凭证、不联网。业务数据依然是明确的本地 Fixture；模型联网不等于生产数据接入。

## 本机 API 验收结论
- 用户授权后真实调用：M1/M2/M3/M5、M4 路由与代码、百炼单图，以及经营/退款两条真实模型链。
- 本机新 BAILIAN_* 用户变量需刷新旧进程；只在工具进程载入，不保存密钥。文本共享配置优先整组 LLM_*，否则按 LLM_PROVIDER 选择已有本机服务。
- 当前抽样通过不等于普遍语义准确率。初次 M5 测试暴露分/元误读，初次退款链暴露 M2 premature finish；均修复复验，原始证据保留。

## 2026-10-14 国内搜索协议
- 当前实测：首次普通文本与搜索均 AccessDenied.Unpurchased；用户说明欠费并充值后原生搜索恢复。不能仅据该错误码断定用户从未开通过服务。
- 搜索来源是真实接口元数据；模型摘要仍可能偏题，官方文档查询只返回社区文章。记录连接/契约通过与相关性评估的区别。
- 官方 https://help.aliyun.com/zh/model-studio/web-search：qwen-plus 支持北京地域搜索；原生 text-generation 返回 output.search_info.search_results。
- 参数 enable_search、forced_search、enable_source；OpenAI Chat Completions 兼容路径不返回来源，故选择原生端点。
- 来源通常只有标题、URL、index，无原文片段；不把模型回答填成网页原文。不返回来源的响应不能伪装联网成功。

## 2026-10-14 Gitee 数据库来源
- 源仓库独立克隆到 D:\模组\imports\0727-rag_-agent，默认 master 提交 71fd7e8e02db11bdb68bc80dec0e4c88d2dfab2d。
- master 只有 README、依赖、批改报告和样例图片，没有数据库代码；README 说明小组/个人分支分别提交，正在列出远端分支定位来源。
- 根许可证为 MulanPSL2；导入来源需保留来源版本与许可证。
- group-item 分支虽然有 database.py，但 README/模型表明它是 Flask 课堂签到系统（学生/考勤/报告），与当前电商 Agent Hub 无关；不据此导入。已向用户询问目标分支，同时继续检查六个小组分支。
- 用户确认 group_02。该分支的 agent-hub/data 是“星潮电商·智能运营中枢 仿真业务库”，不是生产 MySQL/SQLite 服务。JSON 金额已为分，Excel 为元，不能再次乘 100。
- 24 FAQ、10 政策、79 订单、38 物流、20 退款、40 用户、60 日销售、80 行行为、12 活动，另有 4 周销售/行为/活动汇总；没有重复订单主键。
- 首条 R0001 与订单 2025101234 的 customer_id、金额均冲突；订单事实 239700 分（旧平台同 ID 是 69900 分，必须显式切换数据集）。41 个订单无物流；14 个订单状态为“已签收”，需明确映射 delivered。
- Excel 的说明行称“近 30 天销售”，实际 60 天。周汇总是独立样例，不能冒充由订单明细/日报汇总生成；营销周记录有 cost_amount/gmv_amount，可计算成交额/成本，但不能称利润 ROI。
## group_02 接入验收补充

- 最终438项离线测试通过，24项联网测试跳过；29项新增测试包含同源事实、冲突、风险审批与跨模块链路。
- Excel/JSON已按主键核对8张对应业务表、2593字段值，单位及状态翻译后无差异；业务记录自身的问题仍保留并单独报告。
- 周汇总使用2025-W40～W43；新数据订单2025101234金额239700分，不能回退到旧Fixture的69900分。演示可用2025100003（12900分）或2025100004（109900分）。
- 资料详细口径、已知问题、启动方式和文件清单见 docs/group02_data_integration.md；源仍是仿真资料，未进行新资料上的真实模型内容验收。

## 2026-10-15 可靠性整合进行中
- 已保存 d56ccdc 并合入审计 dc33ccf；保留 group02 和平台恢复。统一 completed/watch/pending_payment/refunding 处理。
- 首轮联合回归 1140 passed、1 failed、33 skipped：唯一失败为新旧 Fixture 行尾不同；新增 .gitattributes 固定 LF，原始导入资料保留字节。
- M2 区分订单存在与物流可用性，不伪造运单；M7 已提交审批的响应失败可从平台保留 token 重试。新增全79订单查询和全79退款场景验收。
- 两次多文件补丁因错误上下文整体未应用，已拆分为准确补丁。

- 联合全量1303 passed、1 failed、30 skipped：M2版本号测试需从1.1同步1.2，已修正。全34知识条目与79订单/79退款专项均通过。
- DeepSeek真实文本请求超时；停止批量验收后单独复现30秒超时。只读models在直连/代理均可用，极短文本对比DeepSeek仍超时/不可用，而百炼qwen-plus成功。按既有授权显式将本地.env的LLM_PROVIDER设为bailian，无密钥复制、不引入运行时自动降级。
- 一次定向测试误引用不存在的tests/unit/test_executor.py，改为实际文件集合后220 passed。

- 千问首批真实11 passed、2 failed（235.08秒）：10万元预算被Planner换算为1000000分；另一双周计划JSON缺逗号。没有放松断言。添加显式预算Decimal换算、单预算消费节点校验（错误进入现有repair），Planner采用官方JSON输出模式；64项定向测试通过。
- JSON模式依据：https://help.aliyun.com/en/model-studio/qwen-structured-output 和 https://api-docs.deepseek.com/guides/json_mode/。格式模式不代替Schema/业务金额校验。
- 此前最终离线1339 passed/30 skipped、wheel 7项通过；增加金额修复和新退款live验收后需再次全量。

## 2026-10-15 最终结论
- 1368离线通过、31live默认跳过、7项wheel检查通过；实际31个不同live场景分批均有成功记录，修复后的M5双周链额外复验通过。
- 程序精确提供M5客单价191.54元和2025-W42日期10月13日至19日，解决此前十倍金额和周日历错误；模型自由文本的其他推演不能认定全部正确（仍有UV估算偏差），已如实记录。
- 可进入前端集成；当前提供Python会话/审批入口，尚无HTTP服务。会话/审批保存在内存，经营链约100秒。详见docs/reliability_acceptance.md与docs/frontend_handoff.md。
