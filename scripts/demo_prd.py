"""Offline classroom rehearsal. Explicit demo decisions never call a payment API."""
import argparse
import json
import os
from pathlib import Path

from agents.single_agent import SingleAgent
from agents.react_agent import ReActAgent
from agents.blackboard import DataFusionModule
from agents.plan_execute import WeeklyReportAgent
from agents.multi_agent import PromotionAgent
from agents.router.config import Settings
from agents.router.factory import create_agent
from agents.workflow.refund_graph import RefundWorkflow
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from tests.unit.test_m5_multi_agent import FakeLLM

ROOT=Path(__file__).resolve().parents[1]


def run_demo():
    # This is a fixture rehearsal, not the production default or semantic testing.
    os.environ['HUB_DATA_DIR']=str(ROOT/'data/group02')
    os.environ['M6_DATA_DIR']=''
    registry=CapabilityRegistry()
    modules=[SingleAgent(mode='mock'),ReActAgent(mode='local'),WeeklyReportAgent(mode='local'),
             create_agent(Settings(mode='mock')),PromotionAgent(FakeLLM()),DataFusionModule(),RefundWorkflow()]
    for module in modules:
        registry.register(module.manifest,module)
    executor=Executor(registry)
    knowledge=json.loads((ROOT/'examples/group02_knowledge.json').read_text(encoding='utf-8'))
    operations=json.loads((ROOT/'examples/group02_operations.json').read_text(encoding='utf-8'))
    operations['steps'].append({'step_id':'s4','capability_id':'m5.promotion_plan','depends_on':['s2'],
        'inputs':{'goal':{'literal':'课堂离线演示：根据周报制定大促方案'},'budget_amount':{'literal':1000000},
                  'fused_data':{'ref':'s1.data.fused_data'},'report_markdown':{'ref':'s2.data.report_markdown'}}})
    refund=json.loads((ROOT/'examples/group02_refund.json').read_text(encoding='utf-8'))
    refund['steps'][0]['inputs']['order_id']['literal']='2025100004'
    refund['steps'].append({'step_id':'s3','capability_id':'m1.faq_chat','depends_on':['s2'],
                           'inputs':{'question':{'literal':'退货条件'}}})
    reports={'knowledge':executor.execute(knowledge),'operations':executor.execute(operations)}
    waiting=executor.execute(refund)
    reports['approval_waiting']=waiting
    reports['approval_reflection']=executor.resume(waiting.task_id,'s2',
        {'approved':True,'reviewer':'课堂演示决定（模拟）','material_complete':False})
    reports['approval_completed']=executor.resume(waiting.task_id,'s2',
        {'approved':True,'reviewer':'课堂演示决定（模拟）','material_complete':True})
    workflow=modules[-1]
    thread_id='demo-rollback'
    workflow.run('2025100003','课堂回滚演示',refund_amount=12900,thread_id=thread_id)
    before=workflow.get_trace(thread_id)
    restored=workflow.rollback(thread_id,1)
    resumed=workflow.resume(thread_id)
    return {'mode':'offline_demo', 'notice':'真实架构代码、仿真资料；模型与审核决定为明确的演示替身，无真实支付。',
            'reports':{k:v.model_dump(mode='json') for k,v in reports.items()},
            'rollback':{'checkpoints_before':len(before),'rollback_log':restored['rollback_log'],
                        'final_status':resumed['approval_status']}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'tests/artifacts/prd_demo.json')
    args=parser.parse_args()
    data=run_demo()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name,report in data['reports'].items():
        print(f"{name}: {report['status']}")
    print('M2 Action / Observation:')
    for observation in data['reports']['approval_waiting']['steps']['s1']['result']['data']['observations']:
        print(observation)
    print('M7 回跳节点:',data['reports']['approval_reflection']['steps']['s2']['result']['data']['node_trace'])
    print('检查点回滚:',data['rollback'])
    print(f'完整演示证据：{args.output}')
    expected=['completed','completed','waiting_approval','waiting_approval','completed']
    return int([r['status'] for r in data['reports'].values()] != expected)


if __name__=='__main__':
    raise SystemExit(main())
