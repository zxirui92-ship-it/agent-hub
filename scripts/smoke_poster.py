"""Opt-in live smoke: varied requests, actual routing, one generated image.

Run: python -m scripts.smoke_poster --live
Uses the existing project service configuration; may incur model/image charges.
"""
import argparse
import json
from pathlib import Path

from common.business_data import BusinessData
from common.weekly_data import load_business_view
from hub_platform.executor import Executor
from hub_platform.planner import DynamicPlanner, configured_model, public_diagnostic
from web.server import build_registry
from agents.router.image_brief import business_copy


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--only', help='Run one named scenario')
    parser.add_argument('--output', default='audit_artifacts/poster-smoke-20261016.json')
    args = parser.parse_args()
    if not args.live:
        parser.error('External calls require --live')
    registry = build_registry()
    planner = DynamicPlanner(registry, configured_model())
    facts = load_business_view(BusinessData(ROOT / 'data/group02'), '2025-W43')
    context = {'history': [{'report': {'steps': {'s1': {'status': 'completed', 'result': {
        'status': 'completed', 'capability_id': 'm6.data_fusion', 'data': {'fused_data': facts}}}}}}]}
    results = []
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    def run(name, query, check):
        if args.only and args.only != name:
            return
        row = {'name': name, 'query': query}
        print(f'RUN {name}: {query}', flush=True)
        try:
            check(row)
            row['passed'] = True
        except Exception as exc:
            row['passed'] = False
            row['error'] = public_diagnostic(f'{type(exc).__name__}: {exc}')
        results.append(row)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'name': name, 'passed': row['passed'], 'status': row.get('status'),
                          'skill': row.get('skill'), 'error': row.get('error')}, ensure_ascii=False), flush=True)

    def plan(row, history=None):
        result = planner.plan(row['query'], context=history)
        row['status'] = result.decision.status
        row['message'] = result.decision.message
        row['attempts'] = [a.model_dump(mode='json') for a in result.attempts]
        row['plan'] = result.plan.model_dump(mode='json') if result.plan else None
        return result.plan

    def execute(row, value):
        assert value is not None, row['message']
        report = Executor(registry).execute(value)
        row['report'] = report.model_dump(mode='json')
        row['status'] = report.status
        return report

    def historical_image(row):
        value = plan(row, context)
        report = execute(row, value)
        assert report.status == 'completed', 'Poster execution failed; see recorded report'
        gateways = [s.result for s in report.steps.values() if s.capability_id == 'm4.capability_gateway']
        assert len(gateways) == 1
        result = gateways[0]
        row['skill'] = result.data['skill_name']
        content = json.loads(result.data['result'])
        assert row['skill'] == 'image_gen' and content['images']
        assert content['verified_facts'] == facts
        assert content['model'] == 'qwen-image-2.1-pro'
        assert content['prompt_writing']['visible_text'] == business_copy(row['query'], facts)
        assert facts['anomaly'] not in content['prompt_writing']['final_prompt']

    def new_image_plan(row):
        value = plan(row)
        assert value is not None
        gateways = [s for s in value.steps if s.capability_id == 'm4.capability_gateway']
        assert gateways and all(s.inputs['output_kind'].literal == 'image' for s in gateways)
        assert all('fused_data' in s.inputs for s in gateways)
        assert any(s.capability_id == 'm6.data_fusion' for s in value.steps)

    def history_variation(row):
        value = plan(row, context)
        assert value is not None
        image = next(s for s in value.steps if s.capability_id == 'm4.capability_gateway')
        assert image.inputs['output_kind'].literal == 'image'
        assert 'fused_data' in image.inputs

    def code(row):
        report = execute(row, plan(row))
        assert report.status == 'completed'
        result = next(s.result for s in report.steps.values() if s.capability_id == 'm4.capability_gateway')
        row['skill'] = result.data['skill_name']
        assert row['skill'] == 'code_gen'
        content = json.loads(result.data['result'])
        assert content['language'].lower() == 'python'
        compile(content['code'], '<generated-smoke>', 'exec')  # Syntax only; never execute generated code.

    def route(row, expected):
        module = registry.get('m4.capability_gateway')
        selected = module.router.select(row['query'], module.skills.list_skills())
        row['skill'] = selected.skill_name
        row['message'] = selected.route_reason
        row['status'] = 'routed' if selected.skill_name else 'unsupported'
        assert selected.skill_name == expected

    def fusion(row, expected_week):
        report = execute(row, plan(row))
        assert report.status == 'completed'
        result = next(s.result for s in report.steps.values() if s.capability_id == 'm6.data_fusion')
        assert result.data['fused_data']['week'] == expected_week

    def missing_week(row):
        value = plan(row)
        if value is None:
            assert row['status'] == 'needs_clarification'
            return
        assert all(s.capability_id == 'm6.data_fusion' for s in value.steps)
        assert all(s.inputs['week'].literal == '2026-W41' for s in value.steps)
        report = execute(row, value)
        assert report.status == 'failed'
        assert all(s.error and s.error.code.value == 'NOT_FOUND' for s in report.steps.values())

    def brief_only(row, business=True):
        # Exercise the real text writer without paying for another image.
        from agents.router.image_brief import ImagePromptWriter
        brief = ImagePromptWriter(configured_model()).write(row['query'], facts if business else None)
        row['brief'] = brief
        row['status'] = 'prompt_written'
        if business:
            assert brief['visible_text'] == business_copy(row['query'], facts)
        else:
            assert brief['visible_text'] == []

    run('historical_poster', '就2025w43的运营情况，帮我生成一份双十一的成果海报', historical_image)
    run('fresh_week_poster', '请用2025-W42的经营数据做一张双十一预热成果海报。', new_image_plan)
    run('war_report_image', '把2025-W43的成交金额、订单量和转化率做成一张战报图片，不要编造增长率。', history_variation)
    run('python_source', '用Python写一个函数，输入成交金额和订单数，返回保留两位小数的客单价；只返回源码，不执行。', code)
    run('poster_source_boundary', '用Python写生成海报的脚本，不要调用图片接口。', lambda row: route(row, 'code_gen'))
    run('copy_only_boundary', '只写双十一海报文案，暂时不要出图，也不要源代码。', lambda row: route(row, None))
    run('week_without_year', '融合W41的经营数据。', lambda row: fusion(row, '2025-W41'))
    run('explicit_missing_week', '只融合2026-W41的经营数据，不要改年份。', missing_week)
    run('minimal_poster_brief', '把2025-W43的经营数据做成蓝白极简海报，突出成交额。', brief_only)
    run('festival_poster_brief', '做一张双十一红金色经营海报，使用2025-W43数据。', brief_only)
    run('unsupported_growth_brief', '做W43经营海报，写同比翻倍和利润ROI十倍。', brief_only)
    run('text_free_illustration_brief', '画一只栖息在树枝上的蓝色小鸟，水彩，无文字。', lambda row: brief_only(row, False))
    print(f'{sum(row["passed"] for row in results)}/{len(results)} passed; report: {output}', flush=True)
    return 0 if results and all(row['passed'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
