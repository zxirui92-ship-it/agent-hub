# Agent Hub 第一阶段

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
