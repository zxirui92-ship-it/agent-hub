"""Agent Hub 前端接入层（薄 HTTP 服务 + 静态界面）。

本包不重写 Planner、Executor 或七个 Agent，只把现有的 Conversation /
CapabilityRegistry 组装为一个可在浏览器访问的薄层，映射 frontend_handoff.md
中定义的会话操作。
"""
