import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agents.single_agent import SingleAgent
from agents.workflow.refund_graph import RefundWorkflow
from common.contracts import AgentResult, CapabilityManifest
from common.errors import ErrorCode, ServiceError
from hub_platform.cli import chat_loop
from hub_platform.conversation import Conversation
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.planner import DynamicPlanner
from hub_platform.registry import CapabilityRegistry
from tests.contract.test_contracts import request_for
from tests.integration.test_m1_m2_m6_platform import all_real_registry
from tests.integration.test_m3_m7_platform import replacement_registry
from tests.unit.test_planner import ScriptedModel, ready

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def group02(monkeypatch):
    monkeypatch.setenv('HUB_DATA_DIR', str(ROOT/'data/group02'))
    monkeypatch.setenv('M6_DATA_DIR', '')


class AnswerModel:
    def __init__(self):
        self.calls = []

    def complete(self, system, query):
        self.calls.append(json.loads(query))
        return '测试模型回答；事实以提供的来源为准。'


def faq(agent, question, session='sess-000000000001'):
    return agent.invoke(request_for('m1.faq_chat', {'question':question, 'session_id':session}))


def test_m1_two_tools_followup_chitchat_and_unrelated_question(group02, caplog):
    caplog.set_level('INFO', logger='agent_hub.m1')
    model = AnswerModel()
    agent = SingleAgent(model)
    for question in ['保修政策', '那具体要什么条件？', '你好', '量子引力场方程']:
        assert faq(agent, question).status == 'completed'
    assert len(model.calls[1]['history']) == 2
    for call in model.calls:
        assert set(call['tool_results']) == {'lookup_faq','get_service_policy'}
    followup = json.loads(model.calls[1]['tool_results']['get_service_policy'])
    assert followup['status'] == 'found' and '保修政策' in followup['retrieval_query']
    assert followup['warnings'] and followup['sources']
    for call in model.calls[2:]:
        assert all(json.loads(v)['status'] == 'not_found' for v in call['tool_results'].values())
    assert any(set(json.loads(r.message).get('actions',[])) == {'lookup_faq','get_service_policy'} for r in caplog.records)
    assert faq(agent, '那具体要什么条件？', 'sess-000000000002').status == 'completed'
    assert not model.calls[-1]['history']
    assert all(json.loads(v)['status']=='not_found' for v in model.calls[-1]['tool_results'].values())


def test_m1_file_error_is_not_swallowed_as_retrieval_miss(group02, monkeypatch, tmp_path):
    monkeypatch.setenv('HUB_DATA_DIR', str(tmp_path))
    model = AnswerModel()
    result = faq(SingleAgent(model), '你好')
    assert result.status == 'failed' and result.error.code == ErrorCode.TOOL_UNAVAILABLE
    assert not model.calls


def test_m3_no_agent_dependency_and_platform_compares_adjacent_weeks(group02):
    tree = ast.parse((ROOT/'agents/plan_execute.py').read_text(encoding='utf-8'))
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or '').startswith('agents.') for n in ast.walk(tree))
    plan = json.loads((ROOT/'examples/group02_operations.json').read_text())
    report = Executor(all_real_registry()).execute(plan)
    assert report.status == 'completed'
    inputs = report.steps['s2'].inputs
    assert inputs['previous_fused_data']['week'] == '2025-W40'
    text = report.steps['s2'].result.data['report_markdown']
    expected = (1268000000-1392000000)/1392000000
    assert f'{expected:+.2%}' in text and '无法重新计算环比' not in text
    assert '498000/287000/118000/71400' in text and '2025-W40' in text


def approval_plan(load_plan):
    plan = load_plan('refund_waiting')
    plan['steps'] += [
        {'step_id':'s3','capability_id':'m1.faq_chat','depends_on':['s2'], 'inputs':{'question':{'literal':'退货条件'}}},
        {'step_id':'s4','capability_id':'m1.faq_chat','inputs':{'question':{'literal':'发票'}}}]
    return plan


def decision(**overrides):
    return {'approved':True,'reviewer':'测试审核员','material_complete':True, **overrides}


@pytest.mark.parametrize('approved', [True,False])
def test_resume_preserves_ids_completed_steps_and_explicit_business_rejection(load_plan, approved):
    registry = replacement_registry(RefundWorkflow())
    counts = {}
    for manifest in registry.list_capabilities():
        agent = registry.get(manifest.capability_id)
        original = agent.invoke
        def counted(request, original=original):
            counts[request.capability_id] = counts.get(request.capability_id,0)+1
            return original(request)
        agent.invoke = counted
    executor = Executor(registry)
    first = executor.execute(approval_plan(load_plan))
    assert first.status == 'waiting_approval' and first.steps['s4'].status == 'completed'
    request_id = first.steps['s2'].request_id
    # Returned reports are snapshots, not writable executor state.
    first.steps['s1'].result.data['order_amount'] = -1
    final = executor.resume(first.task_id,'s2',decision(approved=approved))
    assert final.status == 'completed' and final.steps['s3'].status == 'completed'
    assert final.task_id == first.task_id and final.trace_id == first.trace_id
    assert final.steps['s2'].request_id == request_id
    assert final.steps['s1'].result.data['order_amount'] == 69900
    assert final.steps['s2'].result.data['approval_status'] == ('approved' if approved else 'rejected')
    assert counts == {'m2.order_tracking':1,'m7.refund_approval':1,'m1.faq_chat':2}
    assert any('reviewer=测试审核员' in e.reason for e in final.events)
    assert [e.sequence for e in final.events] == list(range(1,len(final.events)+1))
    with pytest.raises(HubError) as exc:
        executor.resume(first.task_id,'s2',decision())
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_reflection_rotates_token_then_resumes_only_pending_work(load_plan):
    executor = Executor(replacement_registry(RefundWorkflow()))
    first = executor.execute(approval_plan(load_plan))
    second = executor.resume(first.task_id,'s2',decision(material_complete=False))
    assert second.status == 'waiting_approval' and second.steps['s3'].status == 'pending'
    assert first.steps['s2'].result.continuation_token != second.steps['s2'].result.continuation_token
    assert 'reflect' in [n['node_name'] for n in second.steps['s2'].result.data['node_trace']]
    final = executor.resume(first.task_id,'s2',decision())
    assert final.status == 'completed'
    assert sum(e.step_id=='s1' and e.status=='running' for e in final.events) == 1


@pytest.mark.parametrize('bad', [decision(approved='yes'), decision(reviewer=' '), decision(material_complete=1), {}])
def test_invalid_decision_does_not_consume_waiting_task(load_plan,bad):
    executor = Executor(replacement_registry(RefundWorkflow()))
    first = executor.execute(approval_plan(load_plan))
    with pytest.raises(HubError) as exc:
        executor.resume(first.task_id,'s2',bad)
    assert exc.value.code == ErrorCode.INVALID_INPUT
    assert executor.resume(first.task_id,'s2',decision()).status == 'completed'


def test_unknown_step_task_and_mock_without_resume(load_plan,registry):
    executor = Executor(registry)
    first = executor.execute(approval_plan(load_plan))
    for tid,sid,code in [(first.task_id,'s1',ErrorCode.INVALID_INPUT),
                         ('task-000000000999','s2',ErrorCode.NOT_FOUND),
                         (first.task_id,'s2',ErrorCode.TOOL_UNAVAILABLE)]:
        with pytest.raises(HubError) as exc:
            executor.resume(tid,sid,decision())
        assert exc.value.code == code
    with pytest.raises(HubError):
        executor.execute(approval_plan(load_plan),task_id=first.task_id)


class CustomApproval:
    """A non-M7 plugin proves Executor continuation has no module branches."""
    manifest = CapabilityManifest(capability_id='custom.review', version='1.0',name='测试审核',description='测试',
        input_schema={'type':'object','additionalProperties':False,'properties':{},'required':[]},
        output_schema={'type':'object','additionalProperties':False,'required':['value'],'properties':{'value':{'type':'integer'}}},
        preconditions=[],side_effects='requires_approval',execution_mode='may_wait',supports_resume=True,owner='test')
    def __init__(self, behavior='ok'):
        self.behavior = behavior

    def invoke(self, request):
        self.request = request
        return AgentResult(**{k:getattr(request,k) for k in ('request_id','task_id','trace_id','capability_id')},
            status='waiting_approval',data={'value':1},waiting_reason='测试',continuation_token='cont-0000000000000001')

    def resume_approval(self, token, decision):
        if self.behavior=='reject_call':
            raise ServiceError(ErrorCode.INVALID_INPUT,'测试拒绝调用',retryable=False)
        if self.behavior=='exception':
            raise RuntimeError('tool crashed')
        result = AgentResult(**{k:getattr(self.request,k) for k in ('request_id','task_id','trace_id','capability_id')},status='completed',data={'value':2})
        if self.behavior=='wrong_id': result.request_id='req-000000000999'
        if self.behavior=='wrong_schema': result.data={'value':'wrong'}
        return result


@pytest.mark.parametrize('behavior,expected', [('ok','completed'),('wrong_id','failed'),('wrong_schema','failed'),('exception','failed')])
def test_generic_plugin_resume_validates_result_and_does_not_fake_success(behavior,expected):
    registry = CapabilityRegistry()
    module = CustomApproval(behavior)
    registry.register(module.manifest,module)
    executor = Executor(registry)
    plan={'plan_id':'plan-20261014-099','goal':'test','steps':[
        {'step_id':'s1','capability_id':'custom.review','inputs':{}},
        {'step_id':'s2','capability_id':'custom.review','depends_on':['s1'],'inputs':{}}]}
    first = executor.execute(plan)
    report = executor.resume(first.task_id,'s1',decision())
    if expected=='completed':
        assert report.steps['s1'].status=='completed' and report.steps['s2'].status=='waiting_approval'
        assert executor.resume(first.task_id,'s2',decision()).status=='completed'
    else:
        assert report.status=='failed' and report.steps['s2'].status=='skipped'


def test_conversation_and_review_cli_do_not_replan(load_plan,monkeypatch,capsys):
    model=ScriptedModel(ready(approval_plan(load_plan)['steps']))
    chat=Conversation(DynamicPlanner(replacement_registry(RefundWorkflow()),model))
    first=chat.submit('查订单并退款')
    assert chat.submit('我同意').status=='waiting_approval'
    inputs=iter(['/review {"step_id":"s2","approved":true,"reviewer":"审核员","material_complete":false}',
                 '/review {"step_id":"s2","approved":true,"reviewer":"审核员","material_complete":true}', '/exit'])
    monkeypatch.setattr('builtins.input',lambda:next(inputs))
    assert chat_loop(chat,as_json=True)==0
    rows=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r['status'] for r in rows]==['waiting_approval','completed']
    assert all(r['task_id']==first.task_id for r in rows) and len(model.calls)==1


def test_history_review_and_reset_have_explicit_lifecycle(load_plan):
    model=ScriptedModel(ready(approval_plan(load_plan)['steps']))
    chat=Conversation(DynamicPlanner(replacement_registry(RefundWorkflow()),model))
    first=chat.submit('查订单并退款')
    chat.new_task()
    assert chat.review('s2',decision(),task_id=first.task_id).status=='completed'
    assert chat.context.history[0].report.status=='completed'
    chat.reset()
    with pytest.raises(HubError): chat.review('s2',decision(),task_id=first.task_id)


def test_multiple_waiting_branches_resume_independently(load_plan):
    plan=approval_plan(load_plan)
    plan['steps'].append({'step_id':'s5','capability_id':'m7.refund_approval',
        'inputs':{'order_id':{'literal':'2025101234'},'refund_amount':{'literal':69900},'reason':{'literal':'另一分支'}}})
    executor=Executor(replacement_registry(RefundWorkflow()))
    first=executor.execute(plan)
    second=executor.resume(first.task_id,'s2',decision())
    assert second.status=='waiting_approval' and second.steps['s3'].status=='completed'
    assert second.steps['s5'].result==first.steps['s5'].result
    final=executor.resume(first.task_id,'s5',decision(approved=False))
    assert final.status=='completed' and final.steps['s5'].result.data['approval_status']=='rejected'
    assert sum(e.step_id=='s3' and e.status=='running' for e in final.events)==1


def test_plugin_rejects_call_without_losing_checkpoint():
    registry=CapabilityRegistry()
    module=CustomApproval('reject_call')
    registry.register(module.manifest,module)
    executor=Executor(registry)
    first=executor.execute({'plan_id':'plan-20261014-098','goal':'test','steps':[
        {'step_id':'s1','capability_id':'custom.review','inputs':{}}]})
    with pytest.raises(HubError) as exc:
        executor.resume(first.task_id,'s1',decision())
    assert exc.value.code==ErrorCode.INVALID_INPUT
    module.behavior='ok'
    assert executor.resume(first.task_id,'s1',decision()).status=='completed'


def test_m7_internal_resume_failure_blocks_dependents(load_plan,monkeypatch):
    from common.module_boundary import failure
    module=RefundWorkflow()
    executor=Executor(replacement_registry(module))
    first=executor.execute(approval_plan(load_plan))
    def failed_resume(token, **kwargs):
        request,_=module._pending[token]
        return failure(request,ErrorCode.INTERNAL_ERROR,'测试恢复执行错误')
    monkeypatch.setattr(module,'submit_decision',failed_resume)
    result=executor.resume(first.task_id,'s2',decision())
    assert result.status=='failed' and result.steps['s3'].status=='skipped'
    assert result.steps['s2'].error.code==ErrorCode.INTERNAL_ERROR


def test_demo_script_exercises_reflection_and_rollback():
    from scripts.demo_prd import run_demo
    result=run_demo()
    assert result['mode']=='offline_demo'
    assert result['reports']['approval_completed']['status']=='completed'
    assert result['rollback']['rollback_log']


def test_bad_review_cli_does_not_invoke_planner_or_destroy_waiting_task(load_plan,monkeypatch,capsys):
    model=ScriptedModel(ready(approval_plan(load_plan)['steps']))
    chat=Conversation(DynamicPlanner(replacement_registry(RefundWorkflow()),model))
    first=chat.submit('退款')
    inputs=iter(['/review nope','/review []','/review {"step_id":[]}', '/exit'])
    monkeypatch.setattr('builtins.input',lambda:next(inputs))
    chat_loop(chat,as_json=True)
    assert all(json.loads(line)['status']=='failed' for line in capsys.readouterr().out.splitlines())
    assert chat.context.active_task.report==first.report and len(model.calls)==1
    assert chat.review('s2',decision()).status=='completed'
