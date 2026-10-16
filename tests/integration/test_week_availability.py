"""Keep the planner's week hints tied to the actual M6 data source."""
import json
from pathlib import Path

from agents.blackboard import DataFusionModule, WeeklySource
from common.business_data import BusinessData
from common.errors import ErrorCode
from hub_platform.planner import DynamicPlanner
from hub_platform.registry import CapabilityRegistry
from tests.contract.test_contracts import request_for
from tests.unit.test_planner import ScriptedModel


DATA = Path(__file__).resolve().parents[2] / 'data/group02'


def test_planner_receives_imported_weeks_instead_of_fixture_year():
    module = DataFusionModule(source=BusinessData(DATA))
    registry = CapabilityRegistry()
    registry.register(module.manifest, module)
    model = ScriptedModel({'status': 'needs_clarification', 'message': '请选择年份。'})
    DynamicPlanner(registry, model).plan('生成 W41 周报')
    system, query = model.calls[0]
    week = query['catalog'][0]['input_schema']['properties']['week']
    assert '2025-W40、2025-W41、2025-W42、2025-W43' in week['description']
    assert '2026-W41' not in system
    assert '年份' in week['description']


def test_wrong_year_error_lists_available_weeks_without_relabeling_data():
    module = DataFusionModule(source=BusinessData(DATA))
    result = module.invoke(request_for('m6.data_fusion', {'week': '2026-W41'}))
    assert result.status == 'failed' and result.error.code == ErrorCode.NOT_FOUND
    assert '2026-W41' in result.error.message
    assert '2025-W41' in result.error.message
    valid = module.invoke(request_for('m6.data_fusion', {'week': '2025-W41'}))
    assert valid.status == 'completed'
    assert valid.data['fused_data']['week'] == '2025-W41'
    assert valid.data['fused_data']['revenue_amount'] == 12680000.0


def test_week_hints_are_per_instance_and_only_include_shared_indexes(tmp_path):
    for name in ('weekly_sales', 'user_behavior_weekly', 'marketing_campaign_weekly'):
        data = json.loads((DATA / f'{name}.json').read_text(encoding='utf-8-sig'))
        if name == 'marketing_campaign_weekly':
            data.pop('2025-W41')
        (tmp_path / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')
    imported = DataFusionModule(source=BusinessData(tmp_path))
    fixture = DataFusionModule(source=WeeklySource())
    imported_hint = imported.manifest.input_schema['properties']['week']['description']
    assert '2025-W40、2025-W42、2025-W43' in imported_hint
    assert '2025-W41' not in imported_hint
    assert '2026-W40、2026-W41' in fixture.manifest.input_schema['properties']['week']['description']
    assert 'description' not in DataFusionModule.manifest.input_schema['properties']['week']
