"""Read-only source audit. Optional Excel reconciliation requires openpyxl.

Run: python -m scripts.audit_group02 --output tests/artifacts/group02_audit.json
Add --workbook with an environment containing openpyxl; runtime does not need it.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from common.business_data import BusinessData
from common.errors import ServiceError

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    'users': ('user_profile', ['customer_id', 'customer_name', 'phone', 'member_level', 'registered_at', 'cumulative_order_count']),
    'orders': ('order_basic', ['order_id', 'customer_id', 'customer_name', 'product_name', 'quantity', 'order_amount', 'order_status', 'created_at', 'shipping_address']),
    'logistics': ('logistics_status', ['order_id', 'carrier', 'tracking_number', 'logistics_status', 'current_location', 'updated_at', 'tracking_history']),
    'faqs': ('faq_knowledge', ['faq_id', 'category', 'question', 'answer', 'keywords']),
    'sales_daily': ('sales_daily_report', ['report_date', 'order_count', 'gmv_amount', 'refund_count', 'new_user_count', 'atv_amount']),
    'user_behavior': ('user_behavior', ['session_id', 'customer_id', 'customer_name', 'event_type', 'sku_id', 'event_at', 'page', 'duration_seconds']),
    'campaigns': ('marketing_campaign', ['campaign_id', 'campaign_name', 'start_date', 'end_date', 'budget_amount', 'channel', 'campaign_status', 'roi']),
    'refunds': ('refund_request', ['refund_id', 'order_id', 'customer_id', 'refund_amount', 'refund_reason', 'requested_at', 'approval_status', 'compliance_result']),
}
TRANSLATIONS = {
    'order_status': {'已付款':'paid', '已发货':'shipped', '已完成':'completed', '已退款':'refunded', '待付款':'pending_payment', '退款中':'refunding'},
    'campaign_status': {'已结束':'completed', '未开始':'pending', '进行中':'active'},
    'logistics_status': {'已揽收':'picked_up', '已签收':'delivered', '派送中':'out_for_delivery', '运输中':'in_transit'},
    'approval_status': {'待受理':'pending'}, 'compliance_result': {'待校验':'pending'},
}


def normalize(value, field, *, excel=False):
    if field.endswith('_amount'):
        # Excel is yuan; BusinessData.read has already converted archive cents.
        return Decimal(str(value))
    if field in TRANSLATIONS:
        return TRANSLATIONS[field].get(value, value)
    if field.endswith('_at') or field.endswith('_date'):
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if isinstance(parsed, datetime):
            return parsed.replace(tzinfo=timezone(timedelta(hours=8))) if parsed.tzinfo is None else parsed
        if isinstance(parsed, date):
            return datetime.combine(parsed, datetime.min.time(), tzinfo=timezone(timedelta(hours=8)))
    return value


def reconcile_workbook(source):
    from openpyxl import load_workbook
    book = load_workbook(source.path / '星潮电商_业务数据库.xlsx', read_only=True, data_only=True)
    report = {}
    try:
        for sheet, (name, fields) in TABLES.items():
            rows = list(book[sheet].values)[1:]
            records = source.read(name)
            indexed = {r[fields[0]]: r for r in records}
            mismatches, checked = [], 0
            seen = set()
            for line, row in enumerate(rows, 2):
                key = row[0]
                if fields[0] == 'report_date':
                    key = row[0].strftime('%Y-%m-%d') if isinstance(row[0], (date, datetime)) else row[0]
                if key not in indexed or key in seen:
                    mismatches.append({'row':line, 'field':fields[0], 'reason':'missing/duplicate key'})
                    continue
                seen.add(key)
                record = indexed[key]
                for field, value in zip(fields, row):
                    checked += 1
                    if normalize(value, field, excel=True) != normalize(record[field], field):
                        # Report locations only, never replicate names/phones/addresses.
                        mismatches.append({'row':line, 'field':field, 'reason':'value differs'})
            report[sheet] = {'excel_rows':len(rows), 'json_rows':len(records), 'checked_cells':checked,
                             'missing_json_keys_in_excel':len(set(indexed)-seen), 'mismatches':mismatches}
    finally:
        book.close()
    return report


def audit(source, *, workbook=False):
    manifest = source.read('source_manifest')
    report = {'source':{k:manifest[k] for k in ('repository','branch','commit','kind')},
              'hash_mismatches':[f['file'] for f in manifest['files'] if sha256((source.path/f['file']).read_bytes()).hexdigest() != f['sha256']],
              'rows':{name:len(source.read(name)) for name, _ in TABLES.values()},
              'knowledge_entries':len(source.knowledge_entries()), 'weeks':sorted(source.read('weekly_sales')),
              'logistics_issues':[], 'refund_issues':[], 'policy_conflicts':[
                  {'entries':['F019','SP007'], 'issue':'小家电保修 2 年与一般家电保修 1 年的适用范围未统一'},
                  {'entries':['F010','F017','SP008'], 'issue':'发票申请入口、时点与专票条件需业务确认'}]}
    for oid in source.rows('order_basic', 'order_id'):
        for operation, collection in ((source.logistics,'logistics_issues'),(source.refund_order,'refund_issues')):
            try:
                operation(oid)
            except ServiceError as exc:
                report[collection].append({'order_id':oid, 'code':exc.code.value, 'message':str(exc)})
    report['logistics_issue_counts'] = dict(Counter(i['code'] for i in report['logistics_issues']))
    report['notes'] = ['归档 JSON 金额为整数分；原始 Excel 为元；BusinessData 读取后统一为元进行核对。',
                       '周汇总是独立仿真场景，不能从当前订单和日报明细复算。',
                       '退款历史只用于一致性核对，不导入为可执行审批指令。',
                       '数据库说明写近30天日报，实际文件有60天。']
    if workbook:
        report['excel_reconciliation'] = reconcile_workbook(source)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data/group02')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workbook', action='store_true')
    args = parser.parse_args()
    report = audit(BusinessData(args.data_dir), workbook=args.workbook)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
        print(f'Audit saved: {args.output}')
    else:
        print(text)
    # Source conflicts are reported, not repaired. Hash/reconciliation failures
    # indicate an unfaithful import and cause a nonzero exit code.
    return int(bool(report['hash_mismatches'] or any(
        s['mismatches'] or s['missing_json_keys_in_excel'] or s['excel_rows'] != s['json_rows']
        for s in report.get('excel_reconciliation', {}).values())))


if __name__ == '__main__':
    raise SystemExit(main())
