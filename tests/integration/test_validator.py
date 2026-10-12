from copy import deepcopy

import pytest

from hub_platform.errors import HubError
from hub_platform.validator import PlanValidator


def check_bad(registry, plan, code, max_steps=32):
    with pytest.raises(HubError) as exc:
        PlanValidator(registry, max_steps).validate(plan)
    assert exc.value.code == code


def test_unknown_capability(registry, load_plan):
    check_bad(registry, load_plan("invalid_plan"), "UNKNOWN_CAPABILITY")


def test_duplicate_step(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"].append(deepcopy(plan["steps"][0]))
    check_bad(registry, plan, "DUPLICATE_STEP")


@pytest.mark.parametrize("dependency,code", [("missing", "INVALID_DEPENDENCY"), ("refund", "CYCLIC_DEPENDENCY")])
def test_bad_dependencies(registry, load_plan, dependency, code):
    plan = load_plan("refund_waiting")
    plan["steps"][0]["depends_on"] = [dependency]
    check_bad(registry, plan, code)


def test_duplicate_dependency(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"][1]["depends_on"] = ["order", "order"]
    check_bad(registry, plan, "INVALID_DEPENDENCY")


@pytest.mark.parametrize("ref,code", [
    ("order.data.missing", "INVALID_REFERENCE"),
    ("order.data.amount.value", "INVALID_REFERENCE"),
    ("missing.data.amount", "INVALID_REFERENCE"),
    ("refund.data.amount", "INVALID_REFERENCE"),
    ("order.data.order_id", "CONTRACT_MISMATCH"),
    ("order.data.__class__", "INVALID_REFERENCE"),
    ("__import__('os')", "INVALID_PLAN"),
])
def test_bad_output_bindings(registry, load_plan, ref, code):
    plan = load_plan("refund_waiting")
    plan["steps"][1]["inputs"]["amount"] = {"ref": ref}
    check_bad(registry, plan, code)


def test_existing_but_non_upstream_reference(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"][1]["depends_on"] = []
    check_bad(registry, plan, "INVALID_REFERENCE")


@pytest.mark.parametrize("binding,code", [
    ({"literal": "699"}, "INVALID_INPUT"),
    ({"literal": -1}, "INVALID_INPUT"),
    ({"literal": True}, "INVALID_INPUT"),
    ({"literal": 10, "ref": "order.data.amount"}, "INVALID_PLAN"),
    ({"expression": "1+1"}, "INVALID_PLAN"),
])
def test_invalid_literal_or_binding(registry, load_plan, binding, code):
    plan = load_plan("refund_waiting")
    plan["steps"][1]["inputs"]["amount"] = binding
    check_bad(registry, plan, code)


def test_missing_and_extra_input(registry, load_plan):
    plan = load_plan("refund_waiting")
    del plan["steps"][0]["inputs"]["order_id"]
    check_bad(registry, plan, "INVALID_INPUT")
    plan["steps"][0]["inputs"]["oops"] = {"literal": 1}
    check_bad(registry, plan, "INVALID_INPUT")


def test_step_limit_and_schema(registry, load_plan):
    check_bad(registry, load_plan("operations"), "EXECUTION_LIMIT", max_steps=2)
    assert PlanValidator(registry, 3).validate(load_plan("operations"))
    for raw in ({}, {"plan_id": "empty", "goal": "empty", "steps": []}, None, []):
        check_bad(registry, raw, "INVALID_PLAN")
    with pytest.raises(ValueError):
        PlanValidator(registry, 0)


def test_self_cycle(registry, load_plan):
    plan = load_plan("refund_waiting")
    plan["steps"][0]["depends_on"] = ["order"]
    check_bad(registry, plan, "CYCLIC_DEPENDENCY")
