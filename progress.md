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
