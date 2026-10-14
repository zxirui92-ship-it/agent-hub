"""M5 · Multi-Agent 大促方案协同 的自动化测试。

来源：group_02 7bcc1c6，原有五个测试场景保留，仅迁移契约与日志捕获。
运行：python -m pytest tests/unit/test_m5_multi_agent.py -v
LLM 一律以 fake 注入，测试不依赖外部服务与网络，可离线复现。
"""

from __future__ import annotations

import json

import agents.multi_agent as m5
from agents.multi_agent import Aggregator, M5Orchestrator, invoke
from common.contracts import AgentRequest
STATUS_COMPLETED, STATUS_FAILED = "completed", "failed"
from common.errors import ErrorCode, ServiceError
INVALID_INPUT, TOOL_UNAVAILABLE = ErrorCode.INVALID_INPUT, ErrorCode.TOOL_UNAVAILABLE

ROLE_LABELS = ("产品", "运营", "数据", "客服")


class FakeLLM:
    """可预期的假模型：按角色标签返回不同内容，用于断言四角色产出确实有差异。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    def __call__(self, prompt: str, system: str | None = None, **kwargs) -> str:
        self.prompts.append(prompt)

        if self.fail:
            raise ServiceError(TOOL_UNAVAILABLE, "fake llm 不可用")

        # 角色 Agent 的 Prompt 以「你现在的身份：」开头
        if "你现在的身份：" in prompt:
            for label in ROLE_LABELS:
                if f"「{label}」" in prompt:
                    return (
                        f"建议：{label}侧围绕本次大促给出专属动作，聚焦{label}维度的落地安排。\n"
                        f"依据：基于上周环比数据与{label}侧现有资源测算。"
                    )
            return "建议：未识别角色。\n依据：无。"

        # 聚合阶段：返回带跨角色引用的统一方案正文
        return (
            "## 二、统一执行方案\n\n"
            "四方共识：以恢复转化率为核心约束，预算优先投向转化洼地。\n\n"
            "冲突消解：运营侧希望 30% 折扣，数据侧测算仅支持 20%，"
            "最终按数据侧口径执行 20% 折扣并保留 5% 弹性额度。\n\n"
            "统一时间线：预热（D-7）→ 爆发（D1）→ 返场（D2-D3）。\n"
        )


def _make_request(payload: dict) -> AgentRequest:
    return AgentRequest(
        request_id="req-000000000001",
        task_id="task-000000000001",
        capability_id=m5.M5_CAPABILITY_ID,
        payload=payload,
        trace_id="trace-0000000000000001",
    )


def test_invoke_all_roles_completed() -> None:
    """四个角色均产出实际内容，整体返回 completed。"""

    result = invoke(_make_request({"goal": "双十一大促"}), llm_fn=FakeLLM())

    assert result.status == STATUS_COMPLETED
    assert result.capability_id == m5.M5_CAPABILITY_ID
    assert result.trace_id == "trace-0000000000000001"
    assert result.error is None

    roles = result.data["roles"]
    assert [item["role"] for item in roles] == list(m5.ROLE_ORDER)

    # 四个角色必须各说各的，防止"只换了个角色名"的同构实现
    assert len({item["contribution"] for item in roles}) == 4
    assert all(item["contribution"] and item["rationale"] for item in roles)


def test_invoke_missing_goal_returns_invalid_input() -> None:
    """payload 缺 goal 时显式失败，不得静默返回空方案。"""

    result = invoke(_make_request({}), llm_fn=FakeLLM())

    assert result.status == STATUS_FAILED
    assert result.error is not None
    assert result.error.code == INVALID_INPUT
    assert result.error.retryable is False
    assert result.data == {}


def test_invoke_llm_unavailable_returns_failed() -> None:
    """LLM 不可用时归类为 TOOL_UNAVAILABLE 且可重试。"""

    result = invoke(_make_request({"goal": "双十一大促"}), llm_fn=FakeLLM(fail=True))

    assert result.status == STATUS_FAILED
    assert result.error is not None
    assert result.error.code == TOOL_UNAVAILABLE
    assert result.error.retryable is True


def test_aggregator_merge_output_not_concatenation() -> None:
    """汇总结果必须具备跨角色结构，而不是四段文本依次罗列。"""

    fake = FakeLLM()
    contributions = [
        {"role": role, "contribution": f"{label}侧主张", "rationale": "对应依据"}
        for role, label in zip(m5.ROLE_ORDER, ROLE_LABELS)
    ]

    plan = Aggregator().merge("双十一大促", contributions, llm_fn=fake)

    assert "四方主张与冲突消解" in plan
    assert "统一时间线" in plan
    for label in ROLE_LABELS:
        assert label in plan
    # 聚合只调用一次 LLM（不是每个角色各聚合一次再拼接）
    assert len(fake.prompts) == 1


def test_orchestrator_dispatch_logs_message_passing(caplog) -> None:
    """消息派发与回传各 4 条，构成 AC-M5-02 的可验证证据。"""

    caplog.set_level("INFO", logger="agent_hub.m5")
    orchestrator = M5Orchestrator(llm_fn=FakeLLM())
    orchestrator.dispatch(
        "双十一大促",
        {},
        {"trace_id": "trace-0000000000000001", "capability_id": m5.M5_CAPABILITY_ID},
    )

    records = [json.loads(record.message) for record in caplog.records]
    m5_records = [item for item in records if item.get("module") == "m5"]

    dispatched = [item for item in m5_records if item.get("status") == "running"]
    returned = [item for item in m5_records if item.get("status") == "completed"]

    assert len(dispatched) == 4
    assert len(returned) == 4
    assert {item["role"] for item in dispatched} == set(m5.ROLE_ORDER)
    assert all(item["capability_id"] == m5.M5_CAPABILITY_ID for item in m5_records)
    assert all(item["trace_id"] == "trace-0000000000000001" for item in m5_records)
