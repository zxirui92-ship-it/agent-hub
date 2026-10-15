# 离线审计修复说明

日期：2026-10-15。基线：`d47e2976d3b62a9217c93b6d6194341a8c01e7fc`。

本次处理原离线审计的 16 组发现。原有测试、原审计断言及新增边界控制共同验证，不启用真实 API、模型收费或退款执行。

## 修复映射

| 发现 | 修复与回归 |
| --- | --- |
| F01 | 共享 HTTP transport 使用独立同来源重定向策略，跨主机/端口/协议及 HTTPS 降级均在后续请求前拒绝；同来源正常行为保留。 |
| F02 | 会话依据每步 waiting_approval 状态阻止重新规划，即使总体报告为 failed；保留原错误、报告、关联 ID，显式 new/reset 不变。 |
| F03 | 高风险退款无论金额多少均等待人工审批，自动审批不再合成材料完整的事实。 |
| F04 | JSON 边界拒绝 NaN/Infinity/指数溢出；共享 Schema 拒绝非有限数值，非法源数据按契约错误终止。 |
| F05 | M5 最终聚合显式接收目标活动周和历史经营期间，避免角色文本未复述目标周时丢失上下文。 |
| F06 | M3/M5/M6 共用真实 ISO 日历周校验；目标周与历史周可以不同，无效年/第53周在模型调用前拒绝。 |
| F07 | plan_id 序号最少三位、超过999继续扩展，不取模或按日期重置；唯一性仍限定同一 Planner 实例。 |
| F08 | HTTP 协议/截断异常统一为已净化、可重试 TOOL_UNAVAILABLE，不回显提供方异常载荷。 |
| F09 | 搜索/图片 URL 的解析失败统一为 CONTRACT_MISMATCH。 |
| F10 | 金额展示统一采用整数商余数，不经 float，超出 IEEE754 精确整数范围仍保持分位一致。 |
| D01 | 确定性演示适配器移至可分发 hub_platform.demo_agents；测试保留兼容导入，平台 CLI 不再依赖 tests 包。 |
| D02 | 订单与周汇总数据随 common/fixtures 打包，以 importlib.resources 定位；源码示例副本有一致性回归。 |
| H01 | M7 验证订单状态；paid/shipped/delivered 可退款，已取消/已退款等明确驳回，未知或畸形事实 fail closed。 |
| H02 | 决定已提交但读取或构造结果失败时保留 token；同一决定重试读取检查点，不重复执行审核。成功响应后消费旧 token，再次等待则轮换。 |
| H03 | 资源 URL 拒绝 userinfo，包括空用户名；不把提供方 URL 中的凭据带回结果。 |
| H04 | base64 必须具有支持的 PNG/JPEG/WebP 签名和结构边界；拒绝文本、HTML、截断及错误格式。 |

## 验证入口

```bash
python -m pip install -r requirements.txt
python -m pip wheel . --no-deps --wheel-dir dist
AUDIT_WHEEL="$(find "$PWD/dist" -name '*.whl' -print -quit)" python -m pytest -q
python scripts/check_wheel.py dist/*.whl
python -m compileall -q agents common hub_platform scripts
python -m pip check
```

GitHub Actions 的 `Offline regression and wheel` 在 Python 3.10/3.12 上运行上述检查。pytest 默认阻止网络连接并清空业务 API Key；24 个真实服务用例继续显式跳过。完整 suite 需提供新构建的 AUDIT_WHEEL，避免将 wheel 验证误算为通过。

## 本地最终验证

- Python 3.12：1093 passed、0 failed、24 skipped；跳过项全部为未启用的真实服务测试。
- 原审计五文件及后续扩展断言全部通过，包括新构建 wheel 的三项隔离回归。
- 源码外实际安装 wheel 后，平台能力清单（默认和七模块替换）以及 M2/M3/M6/M7 离线入口共7项 smoke 全部通过。
- compileall、pip check、git diff --check 通过；独立代码复核没有遗留的已确认问题。
- detect-secrets 1.5.0 使用 --no-verify 扫描完整待提交树，41个候选经复核均为源码来源哈希、合成测试凭据或图片测试字节，未发现真实密钥。未进行在线凭据验证。

## 保留的边界

- M7 仍为本地同进程示例，无真实支付执行、用户身份授权或持久化 token；并发提交、进程崩溃和分布式事务恢复不在本次验证范围。
- 顶层会话仅防止待审批任务被意外重放，不提供完整审核恢复入口；模块级恢复继续使用 M7 token。
- 图片检测验证类型签名和结构边界，不是完整像素解码，也不代表图像内容安全或生成质量验收；URL 图片不下载。
- 同来源重定向沿用标准库方法语义，跨来源即使无害也会明确失败；不会悄悄把认证移到另一服务。
- 真实模型、订单数据库、外部搜索/生图响应与生产网络未运行。本次结果不能替代这些环境的端到端验收。
- 没有修改 main、创建 PR、部署或提交凭据/虚拟环境/缓存。新增分支包含完整 Git 树及修复，不重复提交未变更文件。
