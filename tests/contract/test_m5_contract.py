import json

import pytest

from agents.multi_agent import M5_MANIFEST, PromotionAgent, invoke
from common.errors import ErrorCode, ServiceError
from common.promotion_contract import promotion_manifest
from hub_platform.schema import validate_data
from tests.contract.test_contracts import request_for
from tests.mocks.agents import PromotionPlanMock
from tests.unit.test_m5_multi_agent import FakeLLM


CAPABILITY = 'm5.promotion_plan'


def test_real_and_mock_share_manifest_and_result_contract():
    fake = FakeLLM()
    request = request_for(CAPABILITY, {'goal': '双十一大促', 'budget_amount': 1000.0})
    # Context metadata must not override the platform's authoritative ID.
    request.context['trace_id'] = 'old-upstream-trace'
    before = request.model_dump()
    for module in (PromotionAgent(fake), PromotionPlanMock()):
        assert module.manifest == promotion_manifest() == M5_MANIFEST
        response = module.invoke(request)
        assert response.status == 'completed'
        assert response.model_dump(include={'request_id', 'task_id', 'trace_id', 'capability_id'}) == {
            key: getattr(request, key) for key in ('request_id', 'task_id', 'trace_id', 'capability_id')}
        validate_data(response.data, module.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
        assert [role['role'] for role in response.data['roles']] == ['product', 'operation', 'data', 'service']
    assert len(fake.prompts) == 5
    assert request.model_dump() == before


@pytest.mark.parametrize('payload', [
    {}, {'report': 'old report'}, {'goal': 'x', 'report': 'old report'},
    {'goal': ''}, {'goal': '  '}, {'goal': 12}, {'goal': 'x', 'extra': True},
    {'goal': 'x', 'budget_amount': -0.01}, {'goal': 'x', 'budget_amount': 1.001},
    {'goal': 'x', 'budget_amount': True}, {'goal': 'x', 'budget_amount': '100'},
    {'goal': 'x', 'week': '2026-W54'}, {'goal': 'x', 'report_markdown': None},
    {'goal': 'x', 'week': '2025-W53'}, {'goal': 'x', 'week': '0000-W01'},
    {'goal': 'x', 'fused_data': {}},
])
def test_invalid_payload_rejected_by_both_without_model_call(payload):
    fake = FakeLLM()
    for module in (PromotionAgent(fake), PromotionPlanMock()):
        request = request_for(CAPABILITY, payload)
        response = module.invoke(request)
        assert response.status == 'failed'
        assert response.error.code == ErrorCode.INVALID_INPUT
        assert response.error.request_id == request.request_id
        assert response.error.task_id == request.task_id
        assert response.error.trace_id == request.trace_id
        assert not response.error.retryable
    assert fake.prompts == []


def test_wrong_capability_is_rejected_before_model_call():
    fake = FakeLLM()
    request = request_for('m4.capability_gateway', {'goal': 'x'})
    for module in (PromotionAgent(fake), PromotionPlanMock()):
        response = module.invoke(request)
        assert response.error.code == ErrorCode.CONTRACT_MISMATCH
        assert response.capability_id == request.capability_id
    assert fake.prompts == []


@pytest.mark.parametrize('fail_at', [1, 3, 5])
def test_role_and_aggregation_failure_stop_calls_and_preserve_retryability(fail_at):
    calls = []
    def model(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == fail_at:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'HTTP 401', retryable=False)
        return '建议：有效动作\n依据：样例数据'
    response = invoke(request_for(CAPABILITY, {'goal': '大促'}), llm_fn=model)
    assert response.status == 'failed' and response.error.code == ErrorCode.TOOL_UNAVAILABLE
    assert response.data == {} and not response.error.retryable
    assert len(calls) == fail_at


@pytest.mark.parametrize('bad_output', ['', '  ', {'text': 'not a string'}])
@pytest.mark.parametrize('fail_at', [1, 5])
def test_empty_or_non_text_model_output_never_claims_completion(bad_output, fail_at):
    calls = []
    def model(prompt, **kwargs):
        calls.append(prompt)
        return bad_output if len(calls) == fail_at else '建议：有效动作\n依据：样例数据'
    response = invoke(request_for(CAPABILITY, {'goal': '大促'}), llm_fn=model)
    assert response.error.code == ErrorCode.CONTRACT_MISMATCH
    assert len(calls) == fail_at


def test_unexpected_failure_is_correlated_and_redacted(monkeypatch, caplog):
    monkeypatch.setenv('LLM_API_KEY', 'test-secret-m5')
    def model(*args, **kwargs):
        raise RuntimeError('test-secret-m5 failed')
    response = invoke(request_for(CAPABILITY, {'goal': '大促'}), llm_fn=model)
    assert response.error.code == ErrorCode.INTERNAL_ERROR
    assert 'RuntimeError' in response.error.message
    assert 'test-secret-m5' not in response.model_dump_json() + caplog.text
    event = json.loads(caplog.records[-1].message)
    assert event['status'] == 'failed' and event['trace_id'] == response.trace_id
