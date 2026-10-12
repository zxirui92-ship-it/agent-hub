# Agent Hub · 第一阶段编排底座

候选契约 + Capability Registry + 七个确定性 Mock + 计划校验 + 顺序拓扑执行 + CLI。
**当前公共契约是 v1.0 候选，尚未冻结。Mock 不是七种真实 Agent 架构的课程验收实现。**

需求来源：`docs/requirement.md` 是用户重写的 PRD，`docs/original_assignment.md` 是原始课程作业，均原样保留。
本轮范围以用户提供的第一阶段开发指令为准；本工程不调用 LLM、数据库、支付系统或联网工具。

## 运行（PowerShell，项目根目录）

已为当前工作目录创建 `.venv`，可以直接运行后面的测试与演示命令。
首次下载项目到其他环境时，使用 Python 3.10+：

```powershell
Set-Location 'D:\模组\agent-hub'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若受限环境导致 `venv` 的 `ensurepip` 失败，但 `.venv/Scripts/python.exe` 已生成，可用已有全局 pip 引导：

```powershell
python -m pip --python '.venv\Scripts\python.exe' install pip -r requirements.txt
```

Linux/macOS 对应解释器路径为 `.venv/bin/python`。无需激活虚拟环境，也无需任何 API Key。

```powershell
# 运行全部自动化测试
.\.venv\Scripts\python.exe -m pytest -q

# 列出七个能力及完整 Manifest
.\.venv\Scripts\python.exe -m hub_platform --list-capabilities

# 场景一：经营融合 → 周报 → 大促方案（计划文件特意打乱数组顺序）
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json

# 场景二：订单 → 退款，699 元进入等待审核
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/refund_waiting.json

# 订单不存在，退款跳过
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/failure.json

# 未注册能力，调用前拒绝
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/invalid_plan.json

# 完整结果、每步原始业务输出及轨迹；限制计划大小
.\.venv\Scripts\python.exe -m hub_platform tests/fixtures/operations.json --json --max-steps 32
```

CLI 退出码：`0` 完成，`1` 模块/执行失败，`2` 无效计划/输入文件/参数，`3` 等待人工审核。
等待返回 3 是明确的挂起信号，不表示模块失败；程序不会忙等或代替人工批准。

## 自定义结构化计划

保存以下内容为 JSON，再将文件路径传给 CLI。平台不会根据中文关键词选择链路。

```json
{
  "plan_id": "plan-20261012-005",
  "goal": "了解退货政策",
  "steps": [
    {
      "step_id": "s1",
      "capability_id": "m1.faq_chat",
      "inputs": {"question": {"literal": "如何退货？"}}
    }
  ]
}
```

输入仅接受 `{"literal": JSON值}` 或 `{"ref": "上游步骤.data.字段"}`，不可混用。
数组可以作为整体传递，不支持数组下标、表达式、代码或模板执行。

## 模块接入

`common` 不依赖平台；Registry / Validator / Executor 只依赖公共契约和注入的模块。
只有 CLI 这个演示组装入口导入 `tests.mocks`，发布核心包时不包含 Mock。
**Mock CLI 需从完整源码目录运行**，单独安装核心 wheel 不包含演示数据与测试包。

```python
from common.contracts import AgentRequest, AgentResult, CapabilityManifest
from hub_platform.registry import CapabilityRegistry
from hub_platform.executor import Executor

class MyAdapter:
    def invoke(self, request: AgentRequest) -> AgentResult:
        return AgentResult(
            request_id=request.request_id, task_id=request.task_id,
            trace_id=request.trace_id, capability_id=request.capability_id,
            status="completed", data={"answer": "真实模块的业务输出"},
        )

schema = {
    "type": "object", "properties": {"answer": {"type": "string"}},
    "required": ["answer"], "additionalProperties": False,
}
manifest = CapabilityManifest(
    capability_id="team.answer", version="1.0", name="回答能力",
    description="返回业务回答", owner="模块负责人",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    output_schema=schema, preconditions=[], side_effects="read_only",
    execution_mode="immediate", supports_resume=False,
)
registry = CapabilityRegistry()
registry.register(manifest, MyAdapter())
report = Executor(registry).execute({
    "plan_id": "plan-20261012-006", "goal": "调用新能力",
    "steps": [{"step_id": "s1", "capability_id": "team.answer"}],
})
assert report.final_results["s1"]["answer"] == "真实模块的业务输出"
```

替换现有能力：在新的注册表中为同一 `capability_id` 注册真实适配器和兼容 Manifest 即可。
重复注册会报错，不会悄悄覆盖已有模块。模块私有 Agent 控制流由各负责人维护。

## 工程与验收资料

- `common/contracts.py`：候选数据模型与 Protocol。
- `hub_platform/`：Registry、Schema 工具、Validator、Executor、CLI。
- `tests/mocks/`：七个可独立调用的确定性业务 Mock。
- `tests/fixtures/`：经营链、退款链、失败、无效计划。
- `tests/contract/`、`tests/integration/`：契约和平台测试。
- `docs/interface_contract.md`：字段定义、状态、错误和待评审决定。
- `docs/phase1_architecture.md`：本阶段依赖关系及执行语义。
- `docs/phase1_delivery.md`：完整交付清单、验证结果、风险和下一阶段建议。
- `tests/artifacts/`：本轮实际运行记录。

阶段 A 验证记录见 tests/artifacts/phase_a_pytest.txt。测试的临时目录限定为项目内 `.pytest_cache/tmp`，避免沙箱系统临时目录权限问题；pytest 会清理该专用测试临时目录。
`requirements-tested.txt` 保存本次测试实际依赖版本；Python 3.10+ 是项目目标，本轮实际验证环境为 Windows Python 3.14.5。

本轮未实现自然语言 Planner、真实 M1–M7、LangGraph 检查点、恢复、重试、超时、持久化、并发调度或前端。
重复执行同一计划会重新调用所有可运行步骤；它不是恢复操作，接入有真实副作用的模块前必须先评审恢复与幂等语义。
