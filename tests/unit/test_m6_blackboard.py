from copy import deepcopy
from datetime import datetime
import json
import shutil
import pytest

from agents.blackboard import Blackboard, BlackboardController, DataFusionModule, WeeklySource, FIXTURES
from common.errors import ErrorCode, ServiceError
from tests.contract.test_contracts import request_for


def invoke(week='2026-W41', **kwargs):
    return DataFusionModule(**kwargs).invoke(request_for('m6.data_fusion', {'week': week}))


def test_three_sources_reactive_writers_and_complete_audit():
    result = invoke()
    assert result.status == 'completed'
    fused = result.data['fused_data']
    assert fused['revenue_amount'] == 12684300.0 and fused['conversion_rate'] == 0.0242
    assert '秋日焕新季' in fused['anomaly'] and '无法计算 ROI' in fused['anomaly']
    events = [json.loads(event) for event in result.data['update_events']]
    writes = [(i, e) for i, e in enumerate(events) if e['event'] == 'write']
    positions = {e['key']: i for i, e in writes}
    assert positions['orders'] < positions['marketing'] < positions['insight']
    assert positions['behavior'] < positions['insight']
    assert {e['author'] for _, e in writes} == {'order_agent', 'behavior_agent', 'marketing_agent', 'insight_agent'}
    assert {'read', 'process', 'write', 'react'} <= {e['event'] for e in events}
    assert all(datetime.fromisoformat(e['ts']).tzinfo for e in events)


def test_subscriptions_schedule_real_recomputation():
    controller = BlackboardController('2026-W41')
    controller.run()
    data = controller.board.read('behavior')
    data['conversion_rate'] = 0.05
    controller.board.write('behavior', data, 'test_update')
    controller.run()
    assert '5.00%' in controller.fused_data()['anomaly']
    assert controller.fused_data()['conversion_rate'] == 0.05


def test_board_copies_all_read_write_and_callback_boundaries():
    board = Blackboard()
    value = {'x': [1]}
    board.subscribe('a', lambda e: e.value['x'].append(100))
    board.write('a', value, 'a')
    value['x'].append(2)
    board.read('a')['x'].append(3)
    board.snapshot()['a']['x'].append(4)
    assert board.read('a') == {'x': [1]}


def test_calls_have_private_boards_and_no_stale_week():
    module = DataFusionModule()
    first = module.invoke(request_for('m6.data_fusion', {'week': '2026-W41'}))
    first.data['fused_data']['revenue_amount'] = 0.01
    second = module.invoke(request_for('m6.data_fusion', {'week': '2026-W40'}))
    assert second.data['fused_data']['revenue_amount'] == 11734650.0
    assert '未记录本周活动' in second.data['fused_data']['anomaly']


@pytest.mark.parametrize('week,code', [('2026-W42', ErrorCode.NOT_FOUND), ('2025-W53', ErrorCode.INVALID_INPUT),
                                     ('2026-W00', ErrorCode.INVALID_INPUT)])
def test_absent_and_invalid_weeks_fail(week, code):
    assert invoke(week).error.code == code


def test_unconverged_board_does_not_export_partial_success():
    result = invoke(max_rounds=1)
    assert result.error.code == ErrorCode.EXECUTION_LIMIT
    assert result.data == {}


def test_source_unavailable(tmp_path):
    assert invoke(source=WeeklySource(tmp_path)).error.code == ErrorCode.TOOL_UNAVAILABLE


@pytest.mark.parametrize('bad', [True, 123.001, -1])
def test_source_amounts_are_strict_integer_cents(tmp_path, bad):
    for file in FIXTURES.glob('*.json'):
        shutil.copyfile(file, tmp_path / file.name)
    path = tmp_path / 'order_basic.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['weeks']['2026-W41']['gmv_amount'] = bad
    path.write_text(json.dumps(data), encoding='utf-8')
    assert invoke(source=WeeklySource(tmp_path)).error.code == ErrorCode.CONTRACT_MISMATCH
