# 工作记录

## 2026-10-13 顶层 Planner 联网
- 按用户授权定位本机 DeepSeek 环境变量；初次组合枚举无输出，注册表属性展开报错，随后通过进程变量名称列表和存在性检查定位配置，没有展示凭证。
- 检查官方文档并调用 /models 确认可用模型；顶层配置适配使用 deepseek-flash，可通过环境变量覆盖，业务模块配置保持原样。
- 新增五项离线配置测试与一项真实多轮澄清测试；原“缺配置”测试同步清除 DeepSeek 变量，避免开发机凭证影响离线用例。
- 联网 7 passed in 14.46s；XML 与摘要记录八次模型请求均首次接受。额外实际 CLI 请求完成订单查询，退出码 0。
- 离线回归 302 passed / 15 skipped in 17.47s；业务执行全部 Mock。没有开启 M4/M3/M5 业务 API 验收。
- README、环境示例、顶层说明和 planner_api_connection.md 已同步。文档组合补丁曾因上下文不匹配原子失败，按实际文本重新应用成功。git diff --check 通过，仅既有行尾提示。未提交/推送。

## 2026-10-13 M3 / M7 清洁导入
- 检查上传源码、依赖和数据形状，保留原始包，排除环境/IDE/缓存/旧公共层；生成 docs/imports/m3_m7_source_manifest.json。
- M3 保留规划/执行分离，适配当前数据契约、可选上周同口径视图、结构化步骤和共享模型；本地计算模式与 live 模式显式区分。
- M7 导入真实图拓扑、State/reducer 和合规节点，改为真实挂起、显式决定、反思后新 token；实现同进程恢复、轨迹和回滚续跑。
- common/weekly_contract.py 和 refund_contract.py 同时供 Mock/真实模块使用；M2 Mock/M7 通过 common/order_data.py 复用订单事实。
- CLI 增加 --real-m3/--real-m7，验证与 M4/M5 同时替换；无新增 Executor/Planner 模块专属逻辑。
- 安装 LangGraph 时初次受沙箱网络限制，随后授权审核放行在主体 .venv 安装依赖；未复制上传包的环境。
- 首轮定向 48 passed，全量 295 passed / 14 skipped；补齐日志关联和回滚后续跑验证后最终 297 passed / 14 skipped（18.51 秒）。新增 50 项，业务联网测试未开启。
- 保存 tests/artifacts/m3_m7_pytest.txt 与 m3_m7_offline_demo.json。演示经营链 completed，退款平台报告 waiting_approval，同进程模块恢复 completed；报告明确平台尚无 resume。
- requirements-tested.txt、README、ICD、命名约定、顶层说明、集成文档已同步。原始源文件哈希未变，无提交/推送。

## 2026-10-12
- 完成空目录、需求来源及本轮边界确认。
- planning-with-files resolver 未发现既有计划，采用项目根目录计划文件。
- 开始契约与 Mock 实现。
- 完成公共契约、独立 Registry、七个 Mock、Validator、Executor、CLI 与四份演示计划。
- 添加契约、验证器、异常传播、动态自定义适配器、等待阻塞和 CLI 子进程测试。
- 虚拟环境安装成功：Python 3.14.5 / Pydantic 2.14.1 / jsonschema 4.26.0 / pytest 9.1.1。
- 首轮 pytest：64 passed，1 setup error，1 warning；已针对沙箱临时目录和参数化警告修正。
- 修正后 pytest：65 passed in 4.52s，无失败和警告；日志存入 tests/artifacts/pytest.txt。
- CLI 四场景实际退出码：operations=0、refund_waiting=3、failure=1、invalid_plan=2；完整报告保存。
- SHA-256 校验两份需求副本与用户源文件完全一致。
- 补齐 venv pip；冻结本次依赖快照 requirements-tested.txt。
- README、候选 ICD、第一阶段架构与完整交付报告完成。本阶段停止扩展。

## 2026-10-13 M5 本地接入
- 开始检查上游来源和本地契约，远端版本未改变；本轮没有真实 API 调用。
- 导入 agents/multi_agent.py 及上游五个测试场景，记录来源 commit 7bcc1c6。
- 新增 common/promotion_contract.py，使真实 M5 和 Mock 共用 Manifest 2.0；迁移 operations fixture 和相关测试。
- 保留角色协作核心，统一请求/返回 ID、ErrorDetail、LLM 配置及 JSON 日志；增加独立 CLI 与平台 --real-m5 组装选项。
- 首轮定向测试 36 passed/1 failed，定位为测试对上游 Prompt 摘要格式的错误预期，修正数据内容断言。
- 最终全量回归 206 passed/8 skipped，10.86 秒；新增 37 项 M5 离线测试通过。
- 实际运行 FakeLLM 经营链，状态 completed，5 次模拟模型调用、0 外部 API 调用；证据存为 tests/artifacts/m5_offline_operations.json。
- README、ICD、命名草案、M5 迁移说明与结果记录已同步。未改 D:\agent 项目 的平台工程、未推送远端。

## 2026-10-13 顶层 Planner
- 开始设计并实施；基础工作树包含此前 M5 接口统一的未提交成果，保留这些文件。
- 完成 DynamicPlanner、PlannerDecision/PlanningResult、Conversation 和内存 SessionContext；复用原 Validator/Executor。
- CLI 增加自然语言、多轮和预览入口，保留 JSON 计划入口及真实 M4/M5 组装。
- 先运行 28 项 Planner/会话测试全部通过；补齐 CLI 后 41 项定向测试通过。
- 增加六道真实模型行为题，单独 HUB_RUN_LIVE_TESTS 标志；现有 M4 live 测试开启方式保持兼容。
- 全量回归：247 passed, 14 skipped in 35.48s。无本阶段测试失败；真实 LLM 配置缺失，未调用外部服务。
- 离线交互执行产物：needs_clarification → completed → completed → waiting_approval，4 次 scripted model 调用，记录于 tests/artifacts/planner_offline_demo.json。
- README、ICD、docs/top_level_planner.md、环境示例与测试记录已更新。仅本地修改，未提交/推送。

## 2026-10-14 M1/M2/M6
- 已核对源文件、恢复新版工程上下文；保留 M3/M5/M7/Planner 未提交成果。
- 基线 pytest：302 passed / 15 skipped，17.21 秒；本轮无真实 API 调用。
- 完成 agents/single_agent.py、react_agent.py、blackboard.py 与共享契约、CLI 插拔。
- 47 项首轮单测通过；新增集成首轮 17 passed / 1 failed（M4 离线路由样例前缀错误），修正测试后新增 65 passed。
- 全量 367 passed / 15 skipped，24.06 秒；无真实业务 API 调用。
- 离线产物：经营链 completed；69900 分退款链 waiting_approval。原始源码保留，来源 SHA-256 已保存。
- README、ICD、命名约定、项目进度和集成报告已同步；本轮未提交或推送。

## 2026-10-14 联网实测准备
- 新增不联网的配置检查、7 个 business_live 用例和独立开关；docs/live_acceptance.md 提供三批运行命令和验收边界。
- 配置检查：只有 Planner 的 DeepSeek 组完整；业务 LLM、搜索、生图缺项。未读取展示密钥值，未修改服务配置。
- 全量 pytest：371 passed / 22 skipped，58.88 秒；结果保存 tests/artifacts/live_preparation_pytest.txt。本轮真实 API 调用 0 次。
- 未提交/推送。业务 LLM 是否沿用 DeepSeek 的偏好尚待回复；实测入口已准备。
- 已确认新设置的 Windows User BAILIAN_API_KEY/BAILIAN_BASE_URL；旧进程需显式刷新变量。未存储或展示密钥。
- 首批真实结果：DeepSeek M1 1 passed（6.18 秒）；M2/M3/M5 4 passed（180.75 秒）。人工检查 M5 发现分/元误读，已修正角色与汇总输入的确定金额换算和完整事实，待经营链复验。
- 百炼模型列表查询成功，qwen-image-2.0、qwen-plus 均列出；生图按官方同步原生接口，复用同一北京业务空间域名。
- M4 live：7 passed / 1 skipped（未配置搜索），7.80 秒；包含真实 qwen-image-2.0 单图。千问 qwen-plus M1：1 passed，2.72 秒。
- 记录工程错误：首个定向测试命令误用不存在的 test_m4_skills.py，改为实际 test_m4_services.py；一次补丁上下文错误导致原子操作未生效，重新定位后成功。未修改或删除失败测试。
- 首轮全量回归 385 passed / 2 failed / 22 skipped：旧 M5 子进程缺配置测试只清空 LLM_*，新增 DeepSeek 回退后尝试使用继承配置（连接失败，未成功调用）。已清空新增来源密钥并让普通测试对子进程继承空凭证；保留缺配置断言，防止日后离线测试访问真实服务。
- 真实经营链通过，人工检查 M5 已使用 1,268,430,000 分 = 12,684,300.00 元并保留数据缺口；未把初次结构通过误报为内容无误。
- 初轮真实退款链失败：Planner 的 query 只要求金额/状态，M2 模型自行返回 finish。已在语义指令中明确完整契约、remaining_actions 与程序终止职责；没有兼容伪造 finish 成功。新增对应单测和 live 场景，金额场景+真实退款链复测 2 passed，6.87 秒。原失败 XML 保留。
- 本轮最终离线回归 388 passed / 23 skipped，23.68 秒。已保存 local_api_offline_pytest.txt 与 local_api_summary.json。
- 本机文本配置集中化，支持 DeepSeek 默认或百炼 qwen-plus；百炼原生同步生图 qwen-image-2.0 成功。各批 XML 保留原始失败与复验，报告明确搜索未配置、数据仍为 Fixture、图片未做视觉评分。
- M5 金额/事实问题、M2 金额查询提前 finish 及离线子进程继承凭证问题均有回归；核心调度不改。未提交/推送。

## 2026-10-14 国内搜索接入
- 用户确认欠费并充值后，原协议复测 2 passed，17.14 秒；两次搜索各返回 10 条服务端来源。平台链无需修改 Executor。Python 查询命中官方文档；百炼官方文档查询只有社区文章，报告披露相关性限制。
- 全量 409 passed / 24 skipped，37.13 秒。新增 live 用例默认关闭，未重复调用生图/其他业务模型。保存成功与脱敏失败两份 XML、离线 XML，完成配置和文档，不提交/推送。
- 新增百炼原生搜索、整组配置选择与来源验证；定向离线测试 74 passed，6.90 秒。
- 首次 live 1 passed / 2 failed：语义路由正确，但 qwen-plus 原生搜索 HTTP 403，脱敏诊断码 AccessDenied.Unpurchased。继续定位模型与搜索权限。
- pytest 默认回溯展开 HTTP 函数密钥参数；立即脱敏已存 XML，并加入报告 hook 和回归测试，避免控制台/JUnit 再次暴露。未复制密钥到配置文件。

## 2026-10-14 全量推送主分支
- 用户明确授权将全部成果推送远端并直接更新 main。
- 检查 155 个候选文件，未发现当前真实 API Key、令牌或私钥；保留测试和已脱敏失败证据，.env 与 .venv 继续忽略。
- GitHub 直连失败，使用 Windows 已配置代理 127.0.0.1:7897 成功 fetch；随后提交全部模块、Planner、国内搜索、测试及文档。
- 开发提交 ecd1481aee4c80d67478d58f6ec679cf462f2684 已成功推送 origin/main；独立 ls-remote 核对一致，工作区干净。远端此前是 5295f39，按正常快进直接更新主分支。
- 暂存检查发现两份失败 XML 中的回溯尾部空白，清理空白后 diff --check 通过；未更改测试结果或异常证据。最新测试仍为 409 passed / 24 skipped。

## 2026-10-14 group_02 业务资料接入

- 用户确认分支实际为 group_02；固定源提交 7f70950d6cfea4cab0f8a8b996e176d5eee55ae2。13 JSON 与 1 Excel 原样保存，附哈希清单及源许可证；没有运行外部初始化脚本，没有覆盖现有 Agent 代码。
- 共享数据源已接入 M1/M4、M2/M7 与 M6；M3 独立入口和 M6→M3→M5 现有平台链可消费新数据。真实模块显式使用 HUB_DATA_DIR；Mocks 保留基线。
- 发现 41 个订单缺物流、19 个物流时间冲突，以及 R0001 客户/金额/时间矛盾；相关调用失败，未修改源数据制造通过。保修及发票冲突附检索提示，待业务负责人确认。
- 修复高风险小额退款走自动审批的问题；未付款/退款中订单不能自动退款。源策略阈值50000分、最大反思2次，真实支付未实现。
- 首次大补丁因同一文件 delete/add 重复目标未执行，改为 update 后完成。首次回归 407 passed / 2 failed / 24 skipped，原因是测试收集时实例提前读取 .env；在收集阶段隔离数据配置后 434/24，补充冲突提示及退款一致性测试后最终 438 passed / 24 skipped（19.98秒）。未删除旧测试。
- Excel 初次核对的物流状态差异为中英文翻译；明确映射后 8 张表、353 行、2593 字段值全部一致，源哈希差异为0。使用现有 bundled openpyxl 只读核对，未改依赖。
- 工具曾因自动审批工作区额度不足停止，未绕过审批；用户要求断点继续后恢复。最终三条离线平台 CLI 示例通过，已保存 audit/json/xml 证据。
- 已补 docs/group02_data_integration.md、README、接口契约与1014开发进度。不调用付费API，不提交或推送远端。

## 2026-10-14 PRD 验收补齐

- 对照发现M1新资料路径仅一个工具且未命中中断闲聊；修复为FAQ/政策两个真实只读检索入口，未命中是显式证据，源故障仍失败；指代追问使用窗口上下文。
- M3/M6共用计算移至common.weekly_data，M3不导入M6私有控制器；平台示例加入W40和W41，报告保留上周完整视图。
- 新增公共ApprovalDecision/ApprovalResumable及M7适配，Executor同进程保存等待任务、复用输入绑定/输出校验/失败传播后续跑；Conversation.review与/review JSON可审核当前或历史任务。无模块名称特判，不接受自然语言自动同意，不重复invoke前序步骤。
- 新增22项离线测试覆盖双工具/会话、两周、审批同意拒绝/材料回跳、错误输入不消费token、多等待分支、非M7插件、错误Schema/关联ID/内部失败、历史/reset和演示。
- 初次回归437/1/24：旧同源检索断言没有考虑新增状态字段，改为保留同源事实验证并新增双工具要求。新测试最初4项失败为测试插件漏写additionalProperties=false，修正测试Schema后46项定向通过。一次空文档补丁上下文无匹配，未改动文件，随后使用准确上下文完成。
- 真实首轮5 passed（206.42秒）：DeepSeek问候/记忆/政策、M2正常与源冲突、M4知识路由、真实动态双周→报告→M5链。人工核查发现问候泄露检索术语、报告模型未获得完整上周漏斗，针对性修正后M1/M3限定复验2 passed（36.08秒）。未重复生图/搜索，无密钥输出。
- 最终460 passed /30 skipped（20.32秒），原有测试保留。七模块离线脚本重放成功：等待→reflect→补齐→下游完成，另演示检查点回滚。完整产物在tests/artifacts/prd_*。
- 已补七架构图、PRD映射、7分30秒演示提纲、数据待确认清单；更新规范/ICD/README/进度。模型建议仍需业务评审；数据口径、录屏和团队冻结不是代码可代签的事项。本轮未提交、未推送。

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

## 2026-10-15 最终验收
- 预算/JSON修复后真实20 passed（288.10秒），覆盖四Skill、语义Planner、双周经营及审批后继续。加首次已成功11项，共31个不同live场景都有通过记录。
- 人工检查仍发现M5自算客单价十倍错误、周日期错位；新增程序计算的客单价与ISO日历，传递至四角色和汇总，并在输出顶部显示。168项定向回归通过；真实双周链再测1 passed（118.67秒），日期/客单价在正文也正确。
- 最终完整离线1368 passed/31 skipped（38.03秒），wheel外部安装7项通过，compileall/pip check通过。默认跳过只限显式live测试。
- M5自由文本仍有UV估算等错误；作为草稿展示，已在验收报告明确，不将接口成功当成所有内容可信。搜索实际来源、图片真实服务URL、金额/日期及审批状态均已检查。
- 重建曾因使用--no-build-isolation而缺setuptools失败；改用项目标准隔离构建后成功。一次rg在Windows使用文件通配符失败，改按实际路径读取。文档补丁一次上下文不完整未应用，重新准确定位后成功。
- 已补可靠性验收和前端接入说明；准备保存合并提交，不推送。最后文件清单可通过与d47e297比较获取。
