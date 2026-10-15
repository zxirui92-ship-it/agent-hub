"""Read the group_02 simulation dataset without merging it with legacy fixtures.

JSON amounts already use integer cents. The Excel workbook is an original source
for inspection, not a runtime dependency. Invalid joins fail instead of guessing.
"""
from copy import deepcopy
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from common.errors import ErrorCode, ServiceError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'imported_simulation'
STATUS_MAP = {'已签收': 'delivered'}
STATUSES = {'pending_payment', 'paid', 'shipped', 'delivered', 'completed', 'refunding', 'refunded', 'canceled'}


def require(condition, message):
    if not condition:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, message, retryable=False)


def integer(value, field):
    require(type(value) is int and value >= 0, f'{field} 必须为非负整数（金额单位为分）')
    return value


def timestamp(value, field):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed
    except (TypeError, ValueError) as exc:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, f'{field} 必须为带时区的 ISO 8601', retryable=False) from exc


def configured_data():
    load_dotenv(ROOT / '.env', override=False)
    path = os.getenv('HUB_DATA_DIR', '').strip()
    return BusinessData(Path(path) if Path(path).is_absolute() else ROOT / path) if path else None


class BusinessData:
    source_kind = SOURCE
    field_definitions = [
        'source：group_02 星潮电商仿真业务库；非生产业务系统。',
        'week：ISO 周，使用 weekly_sales/user_behavior_weekly/marketing_campaign_weekly 的独立周样例。',
        'revenue_amount：weekly_sales.gmv_amount，整数分；不表示会计确认收入。',
        'order_count：周汇总订单数；不由演示订单明细推算。',
        'conversion_rate：user_behavior_weekly.order_uv / uv，0–1 比率；不是订单数 / UV。',
        'anomaly：来源限制、漏斗与活动成交额/成本；后者不是利润 ROI，不与日报/明细强行对账。',
    ]

    def __init__(self, path):
        self.path = Path(path)

    def read(self, name):
        try:
            return json.loads((self.path / f'{name}.json').read_text(encoding='utf-8-sig'))
        except OSError as exc:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'业务资料不可读取：{name}', retryable=False) from exc
        except (ValueError, UnicodeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, f'业务资料不是有效 JSON：{name}', retryable=False) from exc

    def rows(self, name, key):
        data = self.read(name)
        require(isinstance(data, list), f'{name} 必须为数组')
        result = {}
        for row in data:
            require(isinstance(row, dict) and isinstance(row.get(key), str) and bool(row[key].strip()),
                    f'{name} 缺少有效 {key}')
            require(row[key] not in result, f'{name} 重复主键：{row[key]}')
            result[row[key]] = row
        return result

    def order(self, order_id):
        row = self.rows('order_basic', 'order_id').get(order_id)
        if row is None:
            raise ServiceError(ErrorCode.NOT_FOUND, f'仿真业务库订单不存在：{order_id}', retryable=False)
        amount = integer(row.get('order_amount'), 'order_amount')
        require(isinstance(row.get('order_status'), str), '订单状态必须为字符串')
        status = STATUS_MAP.get(row.get('order_status'), row.get('order_status'))
        require(status in STATUSES, f'订单 {order_id} 的状态不受支持')
        require(isinstance(row.get('customer_id'), str) and bool(row['customer_id']), '订单缺少 customer_id')
        timestamp(row.get('created_at'), 'created_at')
        return {'order_amount': amount, 'order_status': status, 'customer_id': row['customer_id'],
                'product_name': row.get('product_name', ''), 'created_at': row['created_at'], 'source_kind': SOURCE}

    def logistics(self, order_id):
        order = self.order(order_id)
        row = self.rows('logistics_status', 'order_id').get(order_id)
        if row is None:
            raise ServiceError(ErrorCode.NOT_FOUND, f'订单 {order_id} 缺少物流记录，不能生成运单', retryable=False)
        for field in ('tracking_number', 'logistics_status', 'carrier', 'current_location', 'tracking_history'):
            require(isinstance(row.get(field), str) and bool(row[field].strip()), f'物流缺少 {field}')
        require(timestamp(row.get('updated_at'), 'updated_at') >= timestamp(order['created_at'], 'created_at'),
                f'订单 {order_id} 的物流更新时间早于下单时间')
        require(order['order_status'] not in ('pending_payment', 'paid', 'canceled'),
                f'订单 {order_id} 的状态与已存在物流记录冲突')
        return deepcopy(row)

    def refund_policy(self):
        policy = self.read('refund_compliance_policy')
        require(isinstance(policy, dict), '退款策略必须为对象')
        require(type(policy.get('auto_approve_amount')) is int and policy['auto_approve_amount'] == 50000,
                '退款阈值必须与公共契约一致：50000 分')
        require(type(policy.get('max_reflection')) is int and 1 <= policy['max_reflection'] <= 10,
                'max_reflection 必须为 1–10 的整数')
        risks = policy.get('risk_users')
        require(isinstance(risks, dict), 'risk_users 必须为对象')
        for customer, risk in risks.items():
            require(isinstance(customer, str) and isinstance(risk, dict) and
                    risk.get('risk_level') in ('normal', 'watch', 'high_risk'), '风险记录无效')
        return policy

    def refund_order(self, order_id):
        fact = self.order(order_id)
        # Imported requests are evidence, not approval commands. This platform
        # supports whole-order refunds only; mismatches must be resolved upstream.
        for row in self.rows('refund_request', 'refund_id').values():
            if row.get('order_id') != order_id:
                continue
            amount = integer(row.get('refund_amount'), 'refund_amount')
            require(row.get('customer_id') == fact['customer_id'], f'退款 {row["refund_id"]} 与订单客户不一致')
            require(amount == fact['order_amount'], f'退款 {row["refund_id"]} 与整单实付金额不一致')
            require(timestamp(row.get('requested_at'), 'requested_at') >= timestamp(fact['created_at'], 'created_at'),
                    f'退款 {row["refund_id"]} 的申请时间早于下单时间')
        policy = self.refund_policy()
        risk = policy['risk_users'].get(fact['customer_id'], {})
        return {**fact, 'risk_level': risk.get('risk_level', 'normal'), 'risk_note': risk.get('note', '')}

    def knowledge_entries(self):
        faqs = self.rows('faq_knowledge', 'faq_id')
        policies = self.rows('service_policy', 'policy_id')
        entries, vocabulary = [], set()
        for key, row in faqs.items():
            require(all(isinstance(row.get(k), str) and row[k].strip() for k in ('question', 'answer', 'keywords')),
                    f'FAQ {key} 缺少问题、答案或关键词')
            keywords = [k.strip() for k in re.split('[,，]', row['keywords']) if k.strip()]
            vocabulary.update(keywords)
            entries.append({'entry_id': key, 'title': row['question'], 'content': row['answer'],
                            'keywords': keywords, 'source_file': 'faq_knowledge.json'})
        for key, row in policies.items():
            require(all(isinstance(row.get(k), str) and row[k].strip() for k in ('title', 'content', 'effective_date')),
                    f'政策 {key} 字段不完整')
            try:
                date.fromisoformat(row['effective_date'])
            except ValueError as exc:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, f'政策 {key} 生效日期无效', retryable=False) from exc
            text = row['title'] + row['content']
            keywords = sorted(k for k in vocabulary if k in text)
            keywords += [row['title']] + [row['title'][i:i+2] for i in range(len(row['title'])-1)]
            entries.append({'entry_id': key, 'title': row['title'], 'content': row['content'],
                            'keywords': keywords, 'source_file': 'service_policy.json', 'effective_date': row['effective_date']})
        return entries

    def load(self, week):
        """M6 source boundary, keeping the independent weekly dataset explicit."""
        try:
            if not re.fullmatch(r'\d{4}-W\d{2}', week):
                raise ValueError('week 格式无效')
            date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
        except (TypeError, ValueError) as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, 'week 不是有效 ISO 周', retryable=False) from exc
        datasets = [self.read(name) for name in ('weekly_sales', 'user_behavior_weekly', 'marketing_campaign_weekly')]
        require(all(isinstance(d, dict) for d in datasets), '周数据必须按 ISO 周索引')
        if any(week not in d for d in datasets):
            raise ServiceError(ErrorCode.NOT_FOUND, f'仿真业务库缺少完整周次：{week}', retryable=False)
        sales, behavior, campaigns = [d[week] for d in datasets]
        require(isinstance(sales, dict) and isinstance(behavior, dict) and isinstance(campaigns, list), '周数据结构错误')
        require(sales.get('week') == behavior.get('week') == week, '周索引与记录 week 不一致')
        for key in ('gmv_amount', 'order_count', 'ad_cost_amount', 'new_customer_count'):
            integer(sales.get(key), key)
        rate = sales.get('refund_rate')
        require(type(rate) in (int, float) and math.isfinite(rate) and 0 <= rate <= 1, '退款率必须为 0–1')
        for key in ('uv', 'detail_uv', 'cart_uv', 'order_uv'):
            integer(behavior.get(key), key)
        require(behavior['uv'] > 0 and behavior['uv'] >= behavior['detail_uv'] >= behavior['cart_uv'] >= behavior['order_uv'],
                '周漏斗人数必须有效且逐层不增加，UV 不可为零')
        for item in campaigns:
            require(isinstance(item, dict) and isinstance(item.get('name'), str) and bool(item['name'].strip()), '周活动缺少名称')
            integer(item.get('gmv_amount'), 'campaign.gmv_amount')
            integer(item.get('cost_amount'), 'campaign.cost_amount')
        return deepcopy({'orders': sales, 'behavior': {**behavior, 'conversion_rate': behavior['order_uv']/behavior['uv']},
                         'campaigns': campaigns})

    def knowledge_conflicts(self):
        # Derived notes are separate from the unmodified original source files.
        if not (self.path / 'integration_notes.json').exists():
            return []
        notes = self.read('integration_notes')
        require(isinstance(notes, dict) and isinstance(notes.get('knowledge_conflicts'), list), '知识冲突说明格式无效')
        conflicts = notes['knowledge_conflicts']
        for item in conflicts:
            require(isinstance(item, dict) and isinstance(item.get('entry_ids'), list) and
                    all(isinstance(k, str) for k in item['entry_ids']) and
                    isinstance(item.get('message'), str), '知识冲突说明字段无效')
        return conflicts
