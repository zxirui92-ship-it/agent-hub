# 成员前端整合与真实服务验收（2026-10-15）

> 历史验收记录：2026-10-15 后金额公共接口已改为元（最多两位小数）。本文旧分单位的调用示例不再适用于当前版本；最新契约见 [interface_contract.md](interface_contract.md)。原始验收证据保留。

源仓库：`zxy258455/agent-hub`，基线 `4760d44`，包含此前 `8a300a5` 与 Dots 修复。本地目录 `D:/模组/agent-hub-frontend`，分支 `fix/frontend-live-defaults-20261015`。原 `D:/模组/agent-hub` 保留；本轮没有推送成员仓库。

## 已修复

1. **CI 数据哈希**：先复现 `test_provenance_and_original_files` 失败，再逐个验证。13 个 JSON 仅将 LF 恢复为 CRLF 后即与 provenance 清单原 SHA256 一致；Excel 本来就一致。恢复原字节，不修改业务内容或来源清单。已有 `.gitattributes` 的 `data/group02/* -text` 保证 Git 不再转换这些字节。
2. **默认真实服务**：`python -m web` 注册真实 Planner 与七模块；M1/M2/M3/M4 强制 live。缺文本配置拒绝启动，未配置搜索/生图明确失败。`--offline` 才使用七个 Mock，不存在静默降级。M6 的融合和 M7 的审批是真实业务实现，不需要为了称作“真实”额外调用模型；业务资料仍是模拟数据，退款不调用支付。
3. **前后端契约**：表单示例来自当前后端数据，退款订单 2025100004 的实际金额为109900分；M5一万元预算为1000000分。周报输入使用同源双周数据。支持搜索 source_url 和 images[].image_url/base64，代码只转义一次，模型建议不再归入“已核对基础数据”。
4. **状态与错误**：审核布尔值严格校验，坏 JSON 返回400，服务错误结构化；审核续跑更新原报告；M1显式显示失败；重置会话旋转 session_id，并丢弃直调等待任务。Web会话ID与业务上下文一致，客服直调和编排可以共享记忆。
5. **控制依赖**：浏览器实测发现模型把“审核结束后再回答”当成无依赖步骤。修正规划提示中的数据/控制依赖定义，增加真实模型用例；实际页面复验为先等待审核，客服步骤 pending。
6. **窄窗口**：低于900px时侧栏移到操作区下方，修复最终JSON撑宽页面；实际458px视口测得内容宽度同为458px。
7. **安装包**：wheel 包含 web Python代码与 HTML/JS/CSS，页面无需 Node 构建。Node仅用于前端回归测试。

## 自动化与真实验证

- 初次完整离线回归：1392 passed /31 skipped，62.87秒。跳过项全部是显式付费联网测试，不是失败测试。
- 最终完整离线回归：**1396 passed /32 skipped**，43.73秒；32项是已另行执行的付费用例（含新增控制依赖用例）。报告 `tests/artifacts/frontend_offline_final.xml`。
- 前端 JavaScript：6项通过；同样测试针对旧前端失败，验证新增断言能识别缺陷。
- 新增日志脱敏/嵌套JSON/原始响应保持/异常传播：4项通过。
- 最新 wheel：7项源码目录外独立入口检查通过，静态资源存在，pip check通过。
- 真实HTTP直调：M2正常订单、M6、M3双周周报、M5基于实际周报的方案、M4知识库和代码生成全部完成；未知订单明确 NOT_FOUND。完整报告 `tests/artifacts/frontend_live_http.json`。
- 真实浏览器：M1政策问答和昵称记忆；M4百炼联网搜索返回10条可点击来源；百炼 qwen-image-2.0 返回图片，浏览器确认1024×1024加载完成。初始浏览器截图保留在本地 audit_artifacts；最终界面截图为 `tests/artifacts/frontend_ready.jpg`。
- 真实浏览器退款：109900分进入人工等待，提交模拟审核后原报告更新；修正控制依赖后再次验证等待/续跑。浏览器完整会话报告保存在本地 `audit_artifacts/`。
- 用户随后明确开启全部联网测试。首轮全量 **1426 passed /1 failed /0 skipped**，391.56秒；32项联网用例中31项通过、1项失败。失败是 max_repairs=0 的经营链测试收到裸参数，模型未包 literal。补充参数正反例，保留严格断言，再运行全部受影响的12项规划/跨模块用例：**12 passed /0 skipped**，277.24秒。正常服务仍最多修正一次，未增加隐式重试或放宽Schema。两轮日志分别保存，不能把复测合并称作首轮全绿。

## 本机运行

```powershell
cd 'D:\模组\agent-hub-frontend'
.\.venv\Scripts\python.exe -m scripts.check_live_config
.\.venv\Scripts\python.exe -m web --port 8765
```

本机 `.env`（不提交）选择百炼 qwen-plus、group02资料与120秒文本超时。密钥在 Windows 用户环境；新设变量后需重新打开终端。成员可按 [配置映射说明](team_configuration.md) 对应自己的变量名。访问 `http://127.0.0.1:8765/`。

## 联网日志与复现

```powershell
$env:BUSINESS_RUN_LIVE_TESTS='1'
$env:HUB_RUN_LIVE_TESTS='1'
$env:M4_RUN_LIVE_TESTS='1'
$env:M4_MODE='live'
$env:HUB_LIVE_LOG_DIR='audit_artifacts/live-20261015'
python -m pytest --run-live -v --junitxml=audit_artifacts/live-20261015/full.xml -o junit_family=legacy 2>&1 | Tee-Object audit_artifacts/live-20261015/pytest.log
node --test tests/frontend/rendering.test.cjs
```

每轮使用新目录，保留首轮失败与后续复验。`pytest.log` 保存逐项状态和失败堆栈；`full.xml` 保存用例耗时、完整业务结果、执行轨迹和规划记录；`http.jsonl` 保存每次外部请求/原始响应、模型、超时和耗时，并以测试ID和call_id关联。不记录认证头，已知密钥及HTTP日志中的图片签名参数脱敏；响应正文不截断。普通离线测试不会调用服务。Planner语义用例中的业务执行仍用Mock，business/group02用例才同时调用真实业务模块，不能混淆。

日志目录被Git忽略，供本机debug，不自动上传。图片URL有有效期；日志记录成功不表示链接永久有效。未在本轮开始记录前发生的调用不能补造原始HTTP日志，已有业务报告和截图保留为对应证据。

## 边界

这是本机模拟项目验收，不是生产可用性或语义正确率承诺。会话、记忆和审批仅保留于当前进程，重启丢失；无跨进程恢复、身份认证、真实支付或流式输出。数据政策冲突仍以来源提示展示，模型自由文本需要人工核对。当前结果不能证明所有自然语言请求必然规划正确。

## 日志完整性核验

首轮 http.jsonl 包含32组测试开始/结束、64次请求和64次响应；首轮失败也保留完整模型响应。记录期间发现1行图片签名脱敏误删了嵌套JSON引号转义，已保存原日志为 http.before_json_escape_fix.jsonl，再仅恢复转义；修复明细在 log_repair.json。新增先失败后通过的回归，改为序列化前脱敏，逐行JSON解析通过。未删除失败结果。

复验目录为 `audit_artifacts/live-20261015-recheck`，12组测试、32次请求/响应，全部通过。两轮共96次外部调用完整记录；已知本机密钥扫描未发现泄漏。摘要 `tests/artifacts/frontend_live_summary.json`。这些是本轮测试执行日志；未把未来Web操作自动记录到此目录。
