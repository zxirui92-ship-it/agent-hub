# 需求审查与决策

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
