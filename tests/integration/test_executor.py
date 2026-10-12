from copy import deepcopy

import pytest

from common.contracts import AgentRequest, StepStatus
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from tests.mocks.agents import manifest, obj, result


def test_operations_out_of_order_and_data_flow(registry, load_plan):
    plan = load_plan("operations")
    before = deepcopy(plan)
    report = Executor(registry).execute(plan, task_id="task", trace_id="trace")
    assert report.status == "completed" and plan == before
    assert [event.step_id for event in report.events if event.status == StepStatus.RUNNING] == ["fusion", "report", "promotion"]
    assert report.steps["report"].inputs["fused_data"] == report.steps["fusion"].result.data["fused_data"]
    assert report.steps["promotion"].inputs["report"] == report.steps["report"].result.data["report_markdown"]
    assert report.final_results["promotion"]["source_report"] == report.steps["promotion"].inputs["report"]
    assert all(e.trace_id == "trace" and e.task_id == "task" for e in report.events)
    assert [e.sequence for e in report.events] == list(range(1, len(report.events) + 1))


def test_waiting_preserved_without_fake_continuation(registry, load_plan):
    report = Executor(registry).execute(load_plan("refund_waiting"))
    assert report.status == "waiting_approval"
    assert report.steps["order"].status == StepStatus.COMPLETED
    refund = report.steps["refund"]
    assert refund.status == StepStatus.WAITING_APPROVAL and refund.error is None
    assert refund.result.data["decision"] == "pending_review"
    assert refund.result.continuation_token is None
    assert report.final_results == {}


@pytest.mark.parametrize("amount,expected", [(499, "completed"), (500, "completed"), (500.01, "waiting_approval")])
def test_refund_threshold(registry, amount, expected):
    plan = {"plan_id": "threshold", "goal": "refund", "steps": [{"step_id": "r", "capability_id": "m7.refund_approval",
            "inputs": {"order_id": {"literal": "ORDER-LOW"}, "amount": {"literal": amount}, "reason": {"literal": "退货"}}}]}
    assert Executor(registry).execute(plan).status == expected


def test_low_value_order_refund_completes(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"][0]["inputs"]["order_id"]["literal"] = "ORDER-LOW"
    report = Executor(registry).execute(plan)
    assert report.final_results["refund"]["decision"] == "approved"


def add_followup(plan):
    plan["steps"].extend([
        {"step_id": "followup", "capability_id": "m1.faq", "depends_on": ["refund"], "inputs": {"question": {"literal": "退货"}}},
        {"step_id": "later", "capability_id": "m1.faq", "depends_on": ["followup"], "inputs": {"question": {"literal": "退货"}}},
        {"step_id": "independent", "capability_id": "m4.capability_gateway", "inputs": {"query": {"literal": "促销"}}},
    ])


def test_waiting_blocks_descendants_but_independent_branch_runs(registry, load_plan):
    plan = load_plan("refund_waiting")
    add_followup(plan)
    report = Executor(registry).execute(plan)
    assert report.steps["followup"].status == report.steps["later"].status == StepStatus.PENDING
    assert report.steps["independent"].status == StepStatus.COMPLETED
    assert set(report.final_results) == {"independent"}
    assert not any(e.status == StepStatus.RUNNING and e.step_id in ("followup", "later") for e in report.events)


@pytest.mark.parametrize("order_id,code", [("MISSING", "NOT_FOUND"), ("unavailable", "TOOL_UNAVAILABLE")])
def test_failure_skips_transitive_dependencies(registry, load_plan, order_id, code):
    plan = load_plan("failure")
    plan["steps"][0]["inputs"]["order_id"]["literal"] = order_id
    add_followup(plan)
    report = Executor(registry).execute(plan, trace_id="trace", task_id="task")
    assert report.status == "failed" and report.steps["order"].error.code == code
    for key in ("refund", "followup", "later"):
        assert report.steps[key].status == StepStatus.SKIPPED
        assert report.steps[key].result is None
        assert report.steps[key].error.code == "DEPENDENCY_FAILED"
        assert report.steps[key].error.trace_id == "trace"
    assert report.steps["independent"].status == StepStatus.COMPLETED


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
    plan = {"plan_id": "custom", "goal": "dynamic capability", "steps": [{"step_id": "a", "capability_id": "partner.echo", "inputs": {"value": {"literal": 7}}}]}
    return registry, adapter, plan


def test_new_adapter_diamond_graph_nested_data_and_isolation():
    def behavior(req):
        original = req.payload["value"]
        req.payload["value"] = -99
        req.context["tags"].append("private")
        return result(req, {"value": original + 1})
    registry, adapter, plan = custom_setup(behavior)
    for key, deps, reference in [("b", ["a"], "a"), ("c", ["a"], "a"), ("d", ["b", "c"], "c")]:
        plan["steps"].insert(0, {"step_id": key, "capability_id": "partner.echo", "depends_on": deps,
                                "inputs": {"value": {"ref": f"{reference}.data.value"}}})
    context = {"tags": []}
    report = Executor(registry).execute(plan, context=context)
    assert len(adapter.calls) == 4 and report.status == "completed"
    assert report.final_results == {"d": {"value": 10}}
    assert report.steps["a"].inputs == {"value": 7}
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
    assert report.status == "failed" and report.steps["a"].error.code == code
    assert len(adapter.calls) == 1 and not report.final_results


def test_unexpected_adapter_exception_is_visible_without_retry():
    def crash(req):
        raise RuntimeError("simulated crash")
    registry, adapter, plan = custom_setup(crash)
    report = Executor(registry).execute(plan)
    assert report.steps["a"].error.code == "INTERNAL_ERROR"
    assert report.steps["a"].error.message == "RuntimeError: simulated crash"
    assert len(adapter.calls) == 1


def test_invalid_plan_has_no_calls():
    registry, adapter, plan = custom_setup(lambda req: result(req, {"value": 1}))
    plan["steps"].append({"step_id": "bad", "capability_id": "missing"})
    with pytest.raises(HubError):
        Executor(registry).execute(plan)
    assert adapter.calls == []


def test_runtime_value_constraints_checked_before_downstream():
    registry, adapter, plan = custom_setup(lambda req: result(req, {"value": 0}))
    spec = manifest("positive", "正数", "只接受正数", obj(value={"type": "integer", "minimum": 1}), obj(value={"type": "integer"}))
    downstream = CustomAdapter(lambda req: result(req, {"value": 1}))
    registry.register(spec, downstream)
    plan["steps"].append({"step_id": "b", "capability_id": "positive", "depends_on": ["a"], "inputs": {"value": {"ref": "a.data.value"}}})
    report = Executor(registry).execute(plan)
    assert report.steps["b"].error.code == "INVALID_INPUT" and downstream.calls == []


def test_missing_optional_runtime_field_is_diagnosed():
    registry = CapabilityRegistry()
    spec = manifest("optional", "可选字段", "用于缺失引用测试", obj(), obj(value={"type": "integer"}))
    spec.output_schema["required"] = []
    registry.register(spec, CustomAdapter(lambda req: result(req, {})))
    target = manifest("target", "目标", "接收可选字段", obj(value={"type": "integer"}), obj(value={"type": "integer"}))
    registry.register(target, CustomAdapter(lambda req: result(req, req.payload)))
    plan = {"plan_id": "optional", "goal": "missing runtime reference", "steps": [
        {"step_id": "a", "capability_id": "optional"},
        {"step_id": "b", "capability_id": "target", "depends_on": ["a"], "inputs": {"value": {"ref": "a.data.value"}}},
    ]}
    report = Executor(registry).execute(plan)
    assert report.steps["a"].status == StepStatus.COMPLETED
    assert report.steps["b"].error.code == "INVALID_REFERENCE"
