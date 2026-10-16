"""M6 private Blackboard, adapted from M6_blackboard.py.

Four cooperating writers communicate only through board entries. Subscriptions
enqueue dependent writers; a bounded controller drains the queue. The available
weekly sample data is explicit, with missing marketing performance disclosed.
"""
import argparse
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.resources import files
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from common.money import yuan_schema
from common.contracts import AgentRequest, AgentResult
from common.business_data import configured_data
from common.weekly_data import campaign_summary, insight_summary, fused_view
from common.errors import ErrorCode, ServiceError
from common.fusion_contract import fusion_manifest
from common.iso_week import week_start, shared_weeks
from common.json_data import strict_json_loads
from common.module_boundary import result_for, failure, correlation
from hub_platform.errors import HubError
from hub_platform.schema import validate_data

FIXTURES = files('common').joinpath('fixtures', 'm3')
FIELD_DEFINITIONS = [
    'week：ISO 周；输入必须显式指定。本地周汇总样例，非生产实时数据。',
    'revenue_amount：订单周汇总 gmv_amount，元（最多两位小数）；本视图沿用成交金额口径，不表示会计确认收入。',
    'order_count：订单周汇总订单量，整数单。',
    'conversion_rate：行为源已提供的 0–1 比率；缺少购买 UV，不能用订单量/UV 替代。',
    'anomaly：源记录异常与融合洞察、数据缺口；营销预算不是实际支出，不能据此计算 ROI。',
]


class WeeklySource:
    def __init__(self, path=None):
        self.path = FIXTURES if path is None else Path(path)

    def available_weeks(self):
        try:
            indexes = [strict_json_loads((self.path / f'{name}.json').read_text(encoding='utf-8-sig'))['weeks']
                       for name in ('order_basic', 'user_behavior')]
            if not all(isinstance(index, dict) for index in indexes):
                raise ValueError('Invalid week indexes')
            return shared_weeks(*indexes)
        except OSError as exc:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'M6 无法读取周汇总样例') from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M6 周汇总源结构不完整', retryable=False) from exc

    def load(self, week):
        try:
            week_start(week)
        except ValueError as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, 'week 不是有效 ISO 周', retryable=False) from exc
        try:
            documents = {name: strict_json_loads((self.path / f'{name}.json').read_text(encoding='utf-8-sig'))
                         for name in ('order_basic', 'user_behavior', 'marketing_campaign')}
        except OSError as exc:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'M6 无法读取周汇总样例') from exc
        except ValueError as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M6 数据源不是有效 JSON', retryable=False) from exc
        try:
            orders = documents['order_basic']['weeks']
            behavior = documents['user_behavior']['weeks']
            campaigns = documents['marketing_campaign']['campaigns']
            if not isinstance(orders, dict) or not isinstance(behavior, dict) or not isinstance(campaigns, list):
                raise TypeError('Invalid source collections')
            if week not in orders or week not in behavior:
                available = '、'.join(shared_weeks(orders, behavior)) or '无'
                raise ServiceError(ErrorCode.NOT_FOUND,
                    f'M6 周次 {week} 缺少订单或行为样例；当前数据源可用周次：{available}。请核对年份。', retryable=False)
            order, funnel = orders[week], behavior[week]
            money = yuan_schema()
            validate_data(order, {'type': 'object', 'required': ['gmv_amount', 'order_count', 'refund_rate'],
                'properties': {'gmv_amount': money, 'order_count': {'type': 'integer', 'minimum': 0},
                               'refund_rate': {'type': 'number', 'minimum': 0, 'maximum': 1}}}, ErrorCode.CONTRACT_MISMATCH)
            validate_data(funnel, {'type': 'object', 'required': ['conversion_rate'],
                'properties': {'conversion_rate': {'type': 'number', 'minimum': 0, 'maximum': 1}}}, ErrorCode.CONTRACT_MISMATCH)
            for campaign in campaigns:
                validate_data(campaign, {'type': 'object', 'required': ['week', 'name', 'budget_amount'],
                    'properties': {'week': {'type': 'string'}, 'name': {'type': 'string', 'minLength': 1},
                                   'budget_amount': money}}, ErrorCode.CONTRACT_MISMATCH)
            anomalies = order.get('anomalies', [])
            if not isinstance(anomalies, list) or any(not isinstance(a, dict) or
                    not isinstance(a.get('reason'), str) for a in anomalies):
                raise TypeError('Invalid anomalies')
            return deepcopy({'orders': {**order, 'week': week}, 'behavior': funnel,
                             'campaigns': [c for c in campaigns if c['week'] == week]})
        except (KeyError, TypeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M6 周汇总源结构不完整', retryable=False) from exc


@dataclass
class BlackboardEntry:
    key: str
    value: object
    author: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Blackboard:
    def __init__(self):
        self._store = {}
        self._subscribers = {}
        self.update_events = []

    def record(self, event, key, author):
        self.update_events.append({'ts': datetime.now(timezone.utc).isoformat(),
                                   'event': event, 'key': key, 'author': author})

    def read(self, key, default=None, *, author='reader'):
        self.record('read', key, author)
        entry = self._store.get(key)
        return deepcopy(entry.value if entry else default)

    def write(self, key, value, author):
        entry = BlackboardEntry(key, deepcopy(value), author)
        self._store[key] = entry
        self.update_events.append({'ts': entry.ts, 'event': 'write', 'key': key, 'author': author})
        for callback in self._subscribers.get(key, []):
            callback(deepcopy(entry))

    def subscribe(self, key, callback):
        self._subscribers.setdefault(key, []).append(callback)

    def exists(self, key):
        return key in self._store

    def snapshot(self):
        return {key: deepcopy(entry.value) for key, entry in self._store.items()}


class BlackboardAgent:
    reads = ()

    def __init__(self, board, source):
        self.board, self.source = board, deepcopy(source)

    def run(self):
        if not all(self.board.exists(key) for key in self.reads):
            return
        data = {key: self.board.read(key, author=self.name) for key in self.reads}
        self.board.record('process', self.writes, self.name)
        self.board.write(self.writes, self.process(data), self.name)

    def process(self, data):
        raise NotImplementedError


class OrderAgent(BlackboardAgent):
    name, writes = 'order_agent', 'orders'

    def process(self, data):
        return self.source['orders']


class BehaviorAgent(BlackboardAgent):
    name, writes = 'behavior_agent', 'behavior'

    def process(self, data):
        return self.source['behavior']


class MarketingAgent(BlackboardAgent):
    name, writes, reads = 'marketing_agent', 'marketing', ('orders',)

    def process(self, data):
        return campaign_summary(data['orders'], self.source['campaigns'])


class InsightAgent(BlackboardAgent):
    name, writes, reads = 'insight_agent', 'insight', ('orders', 'behavior', 'marketing')

    def process(self, data):
        return insight_summary(data['orders'], data['behavior'], data['marketing'])


class BlackboardController:
    TARGET_KEYS = {'orders', 'behavior', 'marketing', 'insight'}

    def __init__(self, week, source=None, max_rounds=4):
        if type(max_rounds) is not int or max_rounds < 1:
            raise ValueError('max_rounds must be a positive integer')
        self.week, self.max_rounds = week, max_rounds
        snapshot = (source if source is not None else WeeklySource()).load(week)
        self.board = Blackboard()
        self.agents = [cls(self.board, snapshot) for cls in (OrderAgent, BehaviorAgent, MarketingAgent, InsightAgent)]
        self._pending = deque()
        for agent in self.agents:
            for key in agent.reads:
                self.board.subscribe(key, lambda entry, agent=agent: self._react(agent, entry))
            if not agent.reads:
                self._enqueue(agent)

    def _enqueue(self, agent):
        if agent not in self._pending:
            self._pending.append(agent)

    def _react(self, agent, entry):
        self.board.record('react', entry.key, agent.name)
        self._enqueue(agent)

    def run(self):
        for _ in range(self.max_rounds):
            for _ in range(len(self._pending)):
                self._pending.popleft().run()
            if not self._pending and self.TARGET_KEYS.issubset(self.board.snapshot()):
                return self.board.snapshot()
            if not self._pending:
                break
        raise ServiceError(ErrorCode.EXECUTION_LIMIT, 'M6 黑板未在最大轮次内完成融合', retryable=False)

    def fused_data(self):
        snap = self.board.snapshot()
        if not self.TARGET_KEYS.issubset(snap):
            raise ServiceError(ErrorCode.EXECUTION_LIMIT, 'M6 黑板缺少必要数据区', retryable=False)
        return fused_view(self.week, snap['orders'], snap['behavior'], snap['insight'])


class DataFusionModule:
    manifest = fusion_manifest()

    def __init__(self, source=None, *, max_rounds=4):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        self.source = source if source is not None else (WeeklySource(os.getenv('M6_DATA_DIR')) if os.getenv('M6_DATA_DIR') else configured_data() or WeeklySource())
        self.max_rounds = max_rounds

        # Advertise this instance's source through the existing registry catalog.
        # Source failures still surface at invoke(), rather than breaking startup.
        self.manifest = type(self).manifest.model_copy(deep=True)
        if callable(getattr(self.source, 'available_weeks', None)):
            try:
                weeks = self.source.available_weeks()
            except ServiceError:
                weeks = None
            if weeks is not None:
                field = self.manifest.input_schema['properties']['week']
                field['description'] = ('当前数据源可用周次：' + ('、'.join(weeks) or '无') +
                    '。必须核对年份；仅给周号时可匹配唯一可用周次，有歧义则澄清。'
                    '明确指定的年份或相对日期不得替换成其他年份。')

    def invoke(self, request: AgentRequest) -> AgentResult:
        try:
            if request.capability_id != self.manifest.capability_id:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Wrong capability_id', retryable=False)
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            controller = BlackboardController(request.payload['week'], self.source, self.max_rounds)
            controller.run()
            data = {'fused_data': controller.fused_data(), 'field_definitions': deepcopy(getattr(self.source, 'field_definitions', FIELD_DEFINITIONS)),
                    'update_events': [json.dumps(e, ensure_ascii=False) for e in controller.board.update_events]}
            validate_data(data, self.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
            for event in controller.board.update_events:
                logging.getLogger('agent_hub.m6').info(json.dumps({**correlation(request), 'level': 'info', 'module': 'm6', **event}))
            return result_for(request, status='completed', data=data)
        except (ServiceError, HubError) as exc:
            return failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception:
            logging.getLogger('agent_hub.m6').exception('M6 invocation failed')
            return failure(request, ErrorCode.INTERNAL_ERROR, 'M6 内部执行失败')


def main(argv=None):
    parser = argparse.ArgumentParser(description='M6 private blackboard sample data fusion')
    parser.add_argument('--week', default='2026-W41')
    args = parser.parse_args(argv)
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
        trace_id=f'trace-{uuid4().hex[:16]}', capability_id='m6.data_fusion', payload={'week': args.week})
    result = DataFusionModule().invoke(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
