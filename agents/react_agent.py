"""M2 bounded decision/action/observation loop, adapted from M2.zip.

Uses the project's TextModel instead of a second LangChain model stack.
Live decisions use an LLM; local decisions are explicitly deterministic.
Both currently read the shared fixture order source, never a live OMS.
"""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from common.contracts import AgentRequest, AgentResult
from common.customer_contract import order_manifest, obj, TEXT
from common.errors import ErrorCode, ServiceError
from common.model_config import text_config
from common.llm import ChatModel, TextModel, json_object
from common.module_boundary import result_for, failure, correlation
from common.order_data import order_fact
from hub_platform.errors import HubError
from hub_platform.schema import validate_data

ORDER_FACT = obj(order_amount={'type': 'integer', 'minimum': 0}, order_status=TEXT, tracking_number=TEXT)


def query_order(order_id: str) -> dict:
    fact = order_fact(order_id)
    validate_data(fact, ORDER_FACT, ErrorCode.CONTRACT_MISMATCH)
    return {'order_id': order_id, **fact, 'source': 'local_fixture'}


def query_logistics(order_id: str) -> dict:
    fact = query_order(order_id)
    return {'order_id': order_id, 'tracking_number': fact['tracking_number'], 'source': 'local_fixture'}


def evaluate_goal(observations: list[dict], order_id: str) -> tuple[bool, str]:
    by_tool = {item['action']: item['result'] for item in observations}
    if not all(name in by_tool for name in ('query_order', 'query_logistics')):
        return False, '需要订单和物流两项可核对的观察'
    order, logistics = by_tool['query_order'], by_tool['query_logistics']
    if order['order_id'] != order_id or logistics['order_id'] != order_id:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, '工具返回其他订单', retryable=False)
    if order['tracking_number'] != logistics['tracking_number']:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, '订单与物流运单不一致', retryable=False)
    return True, 'goal_achieved'


class LocalDecisionModel:
    def complete(self, system, query):
        seen = {o['action'] for o in json.loads(query)['observations']}
        return json.dumps({'action': 'query_logistics' if 'query_order' in seen else 'query_order',
                           'decision_summary': '本地确定性演示：读取尚缺失的共享样例事实'})


class ReActAgent:
    manifest = order_manifest()

    def __init__(self, model: TextModel | None = None, *, mode=None, max_rounds=None, tools=None):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        self.mode = mode or ('live' if model is not None else os.getenv('M2_MODE', 'live'))
        if self.mode not in ('live', 'local') or (self.mode == 'local' and model is not None):
            raise ValueError('M2_MODE must be live or local; local does not accept a model')
        self.max_rounds = max_rounds if max_rounds is not None else int(os.getenv('MAX_REACT_ITERATIONS', '3'))
        if type(self.max_rounds) is not int or self.max_rounds < 1:
            raise ValueError('MAX_REACT_ITERATIONS must be a positive integer')
        config = text_config()
        self.model = model if model is not None else (LocalDecisionModel() if self.mode == 'local' else
            ChatModel(config.base_url, config.api_key, config.model, float(os.getenv('LLM_TIMEOUT_SECONDS') or '120')))
        self.tools = tools if tools is not None else {'query_order': query_order, 'query_logistics': query_logistics}

    def invoke(self, request: AgentRequest) -> AgentResult:
        actions, observations = [], []
        try:
            if request.capability_id != self.manifest.capability_id:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Wrong capability_id', retryable=False)
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            order_id = request.payload['order_id']
            for round_no in range(1, self.max_rounds + 1):
                remaining = [name for name in ('query_order', 'query_logistics')
                             if name not in {item['action'] for item in observations}]
                choice = json_object(self.model.complete(
                    '查询指定订单与物流。每轮根据观察选择一个工具：query_order 或 query_logistics。'
                    '模块契约要求订单和物流两项观察，即使 query 只关注金额，也须获取剩余观察。'
                    '仅从 remaining_actions 选择。结束条件由程序检查，禁止输出 finish、done 或其他动作。'
                    '只返回 JSON {"action":"工具名","decision_summary":"简短选择依据"}。'
                    '仅选择动作，不生成事实、不提供隐藏推理。order_id 由程序绑定，不可改写。',
                    json.dumps({'order_id': order_id, 'query': request.payload.get('query', '查询订单与物流'),
                                'observations': observations, 'remaining_actions': remaining}, ensure_ascii=False)))
                validate_data(choice, obj(action={'type': 'string', 'enum': ['query_order', 'query_logistics']},
                    decision_summary=TEXT), ErrorCode.CONTRACT_MISMATCH)
                action = choice['action']
                actions.append(action)
                if action not in self.tools:
                    raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'未配置工具：{action}', retryable=False)
                fact = self.tools[action](order_id)
                schema = obj(order_id=TEXT, source={'type': 'string', 'enum': ['local_fixture']},
                    **ORDER_FACT['properties']) if action == 'query_order' else obj(
                        order_id=TEXT, tracking_number=TEXT, source={'type': 'string', 'enum': ['local_fixture']})
                validate_data(fact, schema, ErrorCode.CONTRACT_MISMATCH)
                if fact['order_id'] != order_id:
                    raise ServiceError(ErrorCode.CONTRACT_MISMATCH, '工具返回其他订单', retryable=False)
                observation = {'round': round_no, **choice, 'result': fact, 'mode': self.mode}
                observations.append(observation)
                logging.getLogger('agent_hub.m2').info(json.dumps({**correlation(request),
                    'ts': datetime.now(timezone.utc).isoformat(), 'level': 'info',
                    'module': 'm2', 'event': 'observation', **observation}, ensure_ascii=False))
                complete, reason = evaluate_goal(observations, order_id)
                if complete:
                    order = next(o['result'] for o in reversed(observations) if o['action'] == 'query_order')
                    data = {'order_id': order_id, **{k: order[k] for k in ORDER_FACT['properties']},
                            'actions': actions, 'observations': [json.dumps(o, ensure_ascii=False) for o in observations],
                            'stop_reason': reason}
                    validate_data(data, self.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
                    return result_for(request, status='completed', data=data)
            raise ServiceError(ErrorCode.EXECUTION_LIMIT, f'M2 达到 {self.max_rounds} 轮仍未获得完整观察', retryable=False)
        except (ServiceError, HubError) as exc:
            result = failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception:
            logging.getLogger('agent_hub.m2').exception('M2 invocation failed')
            result = failure(request, ErrorCode.INTERNAL_ERROR, 'M2 内部执行失败')
        # Failed results preserve partial evidence, never a successful order-shaped result.
        result.data = {'actions': actions, 'observations': [json.dumps(o, ensure_ascii=False) for o in observations],
                       'stop_reason': result.error.code.value}
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='M2 bounded ReAct order query')
    parser.add_argument('--order-id', default='2025101234')
    parser.add_argument('--query', default='查询订单与物流')
    parser.add_argument('--mode', choices=['live', 'local'])
    parser.add_argument('--max-rounds', type=int)
    args = parser.parse_args(argv)
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
        trace_id=f'trace-{uuid4().hex[:16]}', capability_id='m2.order_tracking',
        payload={'order_id': args.order_id, 'query': args.query})
    try:
        agent = ReActAgent(mode=args.mode, max_rounds=args.max_rounds)
    except ValueError as exc:
        parser.error(str(exc))
    result = agent.invoke(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
