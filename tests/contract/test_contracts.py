import pytest
from pydantic import ValidationError

from common.contracts import AgentModule, AgentRequest, AgentResult, ExecutionPlan
from hub_platform.errors import HubError
from hub_platform.schema import validate_data
from tests.mocks.agents import MOCK_TYPES, DataFusionMock, OrderTrackingMock, result

SAMPLES = [
    {"question": "如何退货？"},
    {"order_id": "2025101234"},
    {"fused_data": {"week": "2026-W41", "revenue_amount": 12000000, "order_count": 800,
                    "conversion_rate": 0.032, "anomaly": "转化下降"}},
    {"query": "优惠政策"},
    {"goal": "制定下周大促方案", "report_markdown": "第 41 周转化下降，建议试投"},
    {"week": "2026-W41"},
    {"order_id": "order-low", "refund_amount": 19900, "reason": "退货"},
]


def request_for(capability, payload):
    return AgentRequest(request_id="req-000000000001", task_id="task-000000000001", trace_id="trace-0000000000000001",
                        capability_id=capability, payload=payload)


@pytest.mark.parametrize("mock_type,payload", list(zip(MOCK_TYPES, SAMPLES)))
def test_seven_mocks_registered_independently_callable_and_deterministic(registry, mock_type, payload):
    capability = mock_type.manifest.capability_id
    module = registry.get(capability)
    assert isinstance(module, AgentModule)
    assert len(registry.list_capabilities()) == 7
    manifest = registry.get_manifest(capability)
    validate_data(payload, manifest.input_schema, "INVALID_INPUT")
    request = request_for(capability, payload)
    first = module.invoke(request)
    assert first == mock_type().invoke(request)
    assert first.status == "completed"
    assert first.data
    assert first.trace_id == "trace-0000000000000001" and first.task_id == "task-000000000001"
    validate_data(first.data, manifest.output_schema, "CONTRACT_MISMATCH")


def test_duplicate_and_unknown_capabilities(registry):
    with pytest.raises(HubError, match="Already registered") as exc:
        registry.register(OrderTrackingMock.manifest, OrderTrackingMock())
    assert exc.value.code == "DUPLICATE_CAPABILITY"
    for lookup in (registry.get, registry.get_manifest):
        with pytest.raises(HubError) as exc:
            lookup("missing")
        assert exc.value.code == "UNKNOWN_CAPABILITY"


def test_manifest_is_snapshot(registry):
    returned = registry.get_manifest("m6.data_fusion")
    returned.input_schema["properties"].clear()
    registry.list_capabilities()[0].name = "modified"
    assert registry.get_manifest("m6.data_fusion").input_schema["properties"]
    assert registry.list_capabilities()[0].name != "modified"


@pytest.mark.parametrize("change", [
    {"status": "failed"},
    {"status": "waiting_approval"},
    {"waiting_reason": "unexpected"},
    {"continuation_token": "fake"},
])
def test_invalid_result_lifecycle_rejected(change):
    values = result(request_for("sample", {}), {}).model_dump()
    with pytest.raises(ValidationError):
        AgentResult.model_validate({**values, **change})


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {}, "additionalProperties": True},
    {"type": "object", "$ref": "https://example.com/remote.json", "additionalProperties": False},
    {"type": "object", "required": ["missing"], "additionalProperties": False},
    {"type": "object", "properties": {"x": {"type": ["string", "null"]}}, "additionalProperties": False},
    {"type": "object", "properties": {"x": True}, "additionalProperties": False},
])
def test_unsupported_manifest_schema_fails_explicitly(registry, schema):
    manifest = DataFusionMock.manifest.model_copy(deep=True, update={"capability_id": "custom"})
    manifest.input_schema = schema
    with pytest.raises(HubError):
        registry.register(manifest, DataFusionMock())


def test_schema_generation_and_round_trip(load_plan):
    raw = load_plan("operations")
    plan = ExecutionPlan.model_validate(raw)
    assert ExecutionPlan.model_validate_json(plan.model_dump_json()) == plan
    assert "steps" in ExecutionPlan.model_json_schema()["properties"]
