from copy import deepcopy

import pytest

from common.contracts import AgentRequest, StepState
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from tests.mocks.agents import manifest, obj, result


def test_operations_out_of_order_and_data_flow(registry, load_plan):
    plan = load_plan("operations")
    before = deepcopy(plan)
    report = Executor(registry).execute(plan, task_id="task-000000000001", trace_id="trace-0000000000000001")
    assert report.status == "completed" and plan == before
    assert [event.step_id for event in report.events if event.status == StepState.RUNNING] == ["s1", "s2", "s3"]
    assert report.steps["s2"].inputs["fused_data"] == report.steps["s1"].result.data["fused_data"]
    assert report.steps["s3"].inputs["report_markdown"] == report.steps["s2"].result.data["report_markdown"]
    assert report.steps["s3"].inputs["report_markdown"] in report.final_results["s3"]["plan_markdown"]
    assert all(e.trace_id == "trace-0000000000000001" and e.task_id == "task-000000000001" for e in report.events)
    assert [e.sequence for e in report.events] == list(range(1, len(report.events) + 1))


def test_waiting_preserved_without_fake_continuation(registry, load_plan):
    report = Executor(registry).execute(load_plan("refund_waiting"))
    assert report.status == "waiting_approval"
    assert report.steps["s1"].status == StepState.COMPLETED
    refund = report.steps["s2"]
    assert refund.status == StepState.WAITING_APPROVAL and refund.error is None
    assert refund.result.data["approval_status"] == "waiting_approval"
    assert refund.result.continuation_token is None
    assert report.final_results == {}


@pytest.mark.parametrize("amount,expected", [(49999, "completed"), (50000, "completed"), (50001, "waiting_approval")])
def test_refund_threshold(registry, amount, expected):
    plan = {"plan_id": "plan-20261012-001", "goal": "s2", "steps": [{"step_id": "s1", "capability_id": "m7.refund_approval",
            "inputs": {"order_id": {"literal": {49999: "order-below", 50000: "order-boundary", 50001: "order-above"}[amount]}, "refund_amount": {"literal": amount}, "reason": {"literal": "退货"}}}]}
    assert Executor(registry).execute(plan).status == expected


def test_low_value_order_refund_completes(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"][0]["inputs"]["order_id"]["literal"] = "order-low"
    report = Executor(registry).execute(plan)
    assert report.final_results["s2"]["approval_status"] == "approved"


def add_followup(plan):
    plan["steps"].extend([
        {"step_id": "s3", "capability_id": "m1.faq_chat", "depends_on": ["s2"], "inputs": {"question": {"literal": "退货"}}},
        {"step_id": "s4", "capability_id": "m1.faq_chat", "depends_on": ["s3"], "inputs": {"question": {"literal": "退货"}}},
        {"step_id": "s5", "capability_id": "m4.capability_gateway", "inputs": {"query": {"literal": "促销"}}},
    ])


def test_waiting_blocks_descendants_but_independent_branch_runs(registry, load_plan):
    plan = load_plan("refund_waiting")
    add_followup(plan)
    report = Executor(registry).execute(plan)
    assert report.steps["s3"].status == report.steps["s4"].status == StepState.PENDING
    assert report.steps["s5"].status == StepState.COMPLETED
    assert set(report.final_results) == {"s5"}
    assert not any(e.status == StepState.RUNNING and e.step_id in ("s3", "s4") for e in report.events)


@pytest.mark.parametrize("order_id,code", [("MISSING", "NOT_FOUND"), ("unavailable", "TOOL_UNAVAILABLE")])
def test_failure_skips_transitive_dependencies(registry, load_plan, order_id, code):
    plan = load_plan("failure")
    plan["steps"][0]["inputs"]["order_id"]["literal"] = order_id
    add_followup(plan)
    report = Executor(registry).execute(plan, trace_id="trace-0000000000000001", task_id="task-000000000001")
    assert report.status == "failed" and report.steps["s1"].error.code == code
    for key in ("s2", "s3", "s4"):
        assert report.steps[key].status == StepState.SKIPPED
        assert report.steps[key].result is None
        assert report.steps[key].error.code == "DEPENDENCY_FAILED"
        assert report.steps[key].error.trace_id == "trace-0000000000000001"
    assert report.steps["s5"].status == StepState.COMPLETED


class CustomAdapter:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    def invoke(self, request: AgentRequest):
        self.calls.append(request)
        return self.behavior(request)


def custom_setup(behavior):
    registry = CapabilityRegistry()
    adapter = CustomAdapter(behavior)
    spec = manifest("partner.echo", "自定义", "可替换适配器", obj(value={"type": "integer"}), obj(value={"type": "integer"}))
    registry.register(spec, adapter)
    plan = {"plan_id": "plan-20261012-001", "goal": "dynamic capability", "steps": [{"step_id": "s1", "capability_id": "partner.echo", "inputs": {"value": {"literal": 7}}}]}
    return registry, adapter, plan


def test_new_adapter_diamond_graph_nested_data_and_isolation():
    def behavior(req):
        original = req.payload["value"]
        req.payload["value"] = -99
        req.context["tags"].append("private")
        return result(req, {"value": original + 1})
    registry, adapter, plan = custom_setup(behavior)
    for key, deps, reference in [("s2", ["s1"], "s1"), ("s3", ["s1"], "s1"), ("s4", ["s2", "s3"], "s3")]:
        plan["steps"].insert(0, {"step_id": key, "capability_id": "partner.echo", "depends_on": deps,
                                "inputs": {"value": {"ref": f"{reference}.data.value"}}})
    context = {"tags": []}
    report = Executor(registry).execute(plan, context=context)
    assert len(adapter.calls) == 4 and report.status == "completed"
    assert report.final_results == {"s4": {"value": 10}}
    assert report.steps["s1"].inputs == {"value": 7}
    assert context == {"tags": []}
    assert all(req.context["tags"] == ["private"] for req in adapter.calls)


@pytest.mark.parametrize("behavior,code", [
    (lambda req: {"value": 7}, "CONTRACT_MISMATCH"),
    (lambda req: result(req, {"value": "wrong"}), "CONTRACT_MISMATCH"),
    (lambda req: result(req, {}), "CONTRACT_MISMATCH"),
    (lambda req: result(req, {"value": 7}).model_copy(update={"trace_id": "other"}), "CONTRACT_MISMATCH"),
    (lambda req: result(req, {"value": 7}, status="waiting_approval", waiting_reason="waiting"), "CONTRACT_MISMATCH"),
])
def test_adapter_contract_errors_are_visible(behavior, code):
    registry, adapter, plan = custom_setup(behavior)
    report = Executor(registry).execute(plan)
    assert report.status == "failed" and report.steps["s1"].error.code == code
    assert len(adapter.calls) == 1 and not report.final_results


def test_unexpected_adapter_exception_is_visible_without_retry():
    def crash(req):
        raise RuntimeError("simulated crash")
    registry, adapter, plan = custom_setup(crash)
    report = Executor(registry).execute(plan)
    assert report.steps["s1"].error.code == "INTERNAL_ERROR"
    assert report.steps["s1"].error.message == "RuntimeError: simulated crash"
    assert len(adapter.calls) == 1


def test_invalid_plan_has_no_calls():
    registry, adapter, plan = custom_setup(lambda req: result(req, {"value": 1}))
    plan["steps"].append({"step_id": "s6", "capability_id": "missing"})
    with pytest.raises(HubError):
        Executor(registry).execute(plan)
    assert adapter.calls == []


def test_runtime_value_constraints_checked_before_downstream():
    registry, adapter, plan = custom_setup(lambda req: result(req, {"value": 0}))
    spec = manifest("positive", "正数", "只接受正数", obj(value={"type": "integer", "minimum": 1}), obj(value={"type": "integer"}))
    downstream = CustomAdapter(lambda req: result(req, {"value": 1}))
    registry.register(spec, downstream)
    plan["steps"].append({"step_id": "s2", "capability_id": "positive", "depends_on": ["s1"], "inputs": {"value": {"ref": "s1.data.value"}}})
    report = Executor(registry).execute(plan)
    assert report.steps["s2"].error.code == "INVALID_INPUT" and downstream.calls == []


def test_missing_optional_runtime_field_is_diagnosed():
    registry = CapabilityRegistry()
    spec = manifest("optional", "可选字段", "用于缺失引用测试", obj(), obj(value={"type": "integer"}))
    spec.output_schema["required"] = []
    registry.register(spec, CustomAdapter(lambda req: result(req, {})))
    target = manifest("target", "目标", "接收可选字段", obj(value={"type": "integer"}), obj(value={"type": "integer"}))
    registry.register(target, CustomAdapter(lambda req: result(req, req.payload)))
    plan = {"plan_id": "plan-20261012-001", "goal": "missing runtime reference", "steps": [
        {"step_id": "s1", "capability_id": "optional"},
        {"step_id": "s2", "capability_id": "target", "depends_on": ["s1"], "inputs": {"value": {"ref": "s1.data.value"}}},
    ]}
    report = Executor(registry).execute(plan)
    assert report.steps["s1"].status == StepState.COMPLETED
    assert report.steps["s2"].error.code == "INVALID_REFERENCE"
