import json

import pytest

from common.errors import ErrorCode
from common.llm import ChatModel
from hub_platform.amounts import explicit_budget
from hub_platform.planner import DynamicPlanner, PlanningError
from tests.unit.test_planner import ScriptedModel, ready


@pytest.mark.parametrize('text,amount', [('预算10万元',10000000),('预算10000元',1000000),
    ('总预算为1.25万元',1250000),('预算：2,000.05元',200005),('预算不超过50000分',50000),
    ('预算10万\n补充：预算改为2万元',2000000),('预算10万\n补充：预算改成2万元',2000000),
    ('预算100元\n补充：下周开展',10000)])
def test_explicit_budget_units_and_latest_correction(text,amount):
    assert explicit_budget(text)['budget_amount'] == amount


@pytest.mark.parametrize('text',['预算未知','预算100','预算100美元','预算1元和预算2元',
                               '预算0.001元','预算十万元','预算10万美元','预算10万日元',
                               '预算10万元\n补充：改成2万元', '预算10万元\n补充：预算取消'])
def test_ambiguous_or_unsupported_amounts_are_not_guessed(text):
    assert explicit_budget(text) is None


def promotion(amount):
    return ready([{'step_id':'s1','capability_id':'m5.promotion_plan','inputs':{
        'goal':{'literal':'活动'},'budget_amount':{'literal':amount}}}])


def test_wrong_unit_is_repaired_before_execution(registry):
    model=ScriptedModel(promotion(1000000),promotion(10000000))
    result=DynamicPlanner(registry,model).plan('制定大促方案，预算10万元')
    assert result.plan.steps[0].inputs['budget_amount'].literal == 10000000
    assert [a.status for a in result.attempts] == ['invalid','accepted']
    assert model.calls[0][1]['monetary_facts']['budget_amount'] == 10000000


def test_wrong_unit_cannot_pass_without_repair_budget(registry):
    with pytest.raises(PlanningError) as exc:
        DynamicPlanner(registry,ScriptedModel(promotion(10000)),max_repairs=0).plan('大促预算10000元')
    assert exc.value.code == ErrorCode.INVALID_PLAN


def test_json_mode_is_explicit_and_does_not_change_free_text_calls():
    payloads=[]
    def transport(url,payload,key,timeout):
        payloads.append(payload)
        return {'choices':[{'message':{'content':'{}'}}]}
    ChatModel('https://example.invalid','test','test',transport=transport,json_mode=True).complete('JSON','test')
    ChatModel('https://example.invalid','test','test',transport=transport).complete('text','test')
    assert payloads[0]['response_format'] == {'type':'json_object'}
    assert 'response_format' not in payloads[1]
