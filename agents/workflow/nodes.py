"""M7 condition edges and compliance rules retained from the supplied graph."""
from __future__ import annotations
from typing import Any, Dict
from agents.workflow.state import NODE_AUTO_APPROVE, NODE_COMPLIANCE_CHECK, NODE_FINALIZE, NODE_MANUAL_REVIEW, NODE_RECEIVE, NODE_REFLECT, RefundState
import logging
from agents.workflow.formatting import ORDER_STATUS_LABELS, format_amount, label
logger = logging.getLogger('agents.workflow.nodes')
NON_REFUNDABLE_ORDER_STATUS = {'canceled', 'refunded', 'not_found'}
REFUNDABLE_ORDER_STATUS = {'paid', 'shipped', 'delivered'}
BRANCH_AUTO = 'auto'
BRANCH_MANUAL = 'manual'
BRANCH_REJECT = 'reject'

def route_by_amount(state: RefundState) -> str:
    status = state.get('order_status')
    if not isinstance(status, str) or status not in REFUNDABLE_ORDER_STATUS:
        return BRANCH_REJECT
    refund_amount = int(state.get('refund_amount', 0))
    threshold = int(state.get('auto_approve_amount') or 50000)
    return BRANCH_MANUAL if refund_amount > threshold or state.get('risk_level') == 'high_risk' else BRANCH_AUTO

def auto_approve_node(state: RefundState) -> Dict[str, Any]:
    # Approval is not evidence that return documents were supplied.
    return {'approval_status': 'approved', 'approval_mode': 'auto', 'reviewer': '智能客服自动审批', 'history': [f"[自动审批] 金额 {format_amount(state.get('refund_amount', 0))} ≤ 阈值，命中「小额快速退款」策略，免人工直接放行"], 'node_trace': [{'node_name': NODE_AUTO_APPROVE}]}

def route_after_review(state: RefundState) -> str:
    return 'rejected' if state.get('approval_status') == 'rejected' else 'continue'

def compliance_check_node(state: RefundState) -> Dict[str, Any]:
    threshold = int(state.get('auto_approve_amount') or 50000)
    refund_amount = int(state.get('refund_amount', 0))
    order_amount = int(state.get('order_amount', refund_amount))
    material_complete = bool(state.get('material_complete', False))
    risk_level = str(state.get('risk_level', 'normal'))
    approved = state.get('approval_status') == 'approved'
    failed = []
    notes = []
    if refund_amount <= threshold:
        notes.append(f'R1 金额阈值：✅ 通过（{format_amount(refund_amount, digits=0)} ≤ 阈值 {format_amount(threshold, digits=0)}）')
    elif approved and state.get('approval_mode') == 'manual':
        notes.append(f'R1 金额阈值：✅ 通过（{format_amount(refund_amount, digits=0)} > 阈值 {format_amount(threshold, digits=0)}，已取得人工审核通过结论）')
    else:
        failed.append('R1')
        notes.append(f'R1 金额阈值：❌ 超过阈值 {format_amount(threshold, digits=0)} 且未取得有效人工审核结论')
    order_status = str(state.get('order_status', ''))
    if order_status in REFUNDABLE_ORDER_STATUS:
        notes.append(f'R2 订单状态：✅ 通过（{label(ORDER_STATUS_LABELS, order_status)}）')
    else:
        failed.append('R2')
        notes.append(f'R2 订单状态：❌ 异常（{label(ORDER_STATUS_LABELS, order_status)}）')
    if risk_level == 'high_risk' and (not material_complete):
        failed.append('R3')
        notes.append('R3 薅羊毛风控：❌ 高风险用户未提供退货物流单号与质检凭证')
    elif risk_level == 'high_risk':
        notes.append('R3 薅羊毛风控：✅ 高风险用户已补充完整材料，通过复核')
    else:
        notes.append(f'R3 薅羊毛风控：✅ 通过（风险等级 {risk_level}）')
    if refund_amount > threshold and (not material_complete):
        failed.append('R4')
        notes.append('R4 材料完整性：❌ 大额退款缺少退货物流单号')
    else:
        notes.append('R4 材料完整性：✅ 通过')
    if refund_amount <= order_amount:
        notes.append(f'R5 毛利保护：✅ 通过（退款 {format_amount(refund_amount)} ≤ 实付 {format_amount(order_amount)}）')
    else:
        failed.append('R5')
        notes.append('R5 毛利保护：❌ 退款金额超过订单实付金额')
    passed = not failed
    return {'compliance_passed': passed, 'failed_rules': failed, 'compliance_notes': '\n'.join(notes), 'history': [f"[合规校验] {('✅ 全部规则通过' if passed else '❌ 未通过规则：' + '、'.join(failed))}"], 'node_trace': [{'node_name': NODE_COMPLIANCE_CHECK}]}

def route_compliance(state: RefundState) -> str:
    return 'pass' if state.get('compliance_passed') else 'retry'

def route_reflection(state: RefundState) -> str:
    count = int(state.get('reflection_count', 0))
    max_reflection = int(state.get('max_reflection', 3))
    if count < max_reflection and state.get('requires_manual'):
        return 'back'
    return 'reject'
def receive_node(state: RefundState) -> Dict[str, Any]:
    """Use the validated order snapshot; every node sees the same facts."""
    order = state['order_snapshot']
    amount = order['order_amount']
    threshold = state['auto_approve_amount']
    manual = amount > threshold or order.get('risk_level') == 'high_risk'
    return {
        'order_amount': amount, 'refund_amount': amount, 'order_status': order['order_status'],
        'customer_id': order.get('customer_id', ''), 'customer_name': order.get('customer_name', ''),
        'product_name': order.get('product_name', ''),
        'risk_level': order.get('risk_level', 'normal'), 'risk_note': order.get('risk_note', ''),
        'amount_branch': BRANCH_MANUAL if manual else BRANCH_AUTO, 'requires_manual': manual,
        'history': [f"[受理] 订单 {state['order_id']}，整单退款 {amount} 分；订单来源为本地样例"],
        'node_trace': [{'node_name': NODE_RECEIVE}],
    }


def manual_review_node(state: RefundState) -> Dict[str, Any]:
    """Only consume an explicit decision; there is no simulated approver."""
    decision = state.get('human_decision')
    if decision not in ('approved', 'rejected'):
        raise ValueError('人工审核尚未提交决定')
    return {'approval_status': decision, 'approval_mode': 'manual',
            'reviewer': state['reviewer'], 'material_complete': state.get('material_complete', False),
            'history': [f"[人工审核] {state['reviewer']}：{decision}"],
            'node_trace': [{'node_name': NODE_MANUAL_REVIEW}]}


def reflect_node(state: RefundState) -> Dict[str, Any]:
    count = state.get('reflection_count', 0) + 1
    failed = state.get('failed_rules', [])
    note = f"未通过规则：{'、'.join(failed)}；请核对订单状态及退货材料后重新审核。"
    return {'reflection_count': count, 'reflection_notes': note,
            'approval_status': 'pending', 'human_decision': '', 'reviewer': '',
            'history': [f'[反思 {count}] {note}'], 'node_trace': [{'node_name': NODE_REFLECT}]}


def finalize_node(state: RefundState) -> Dict[str, Any]:
    rejected = state.get('approval_status') == 'rejected'
    passed = state.get('compliance_passed', False) and not rejected
    status = 'approved' if passed else 'rejected'
    decision = ('manual_approved' if state.get('requires_manual') else 'auto_approved') if passed else 'rejected'
    detail = '审批通过；当前只运行本地流程，未执行退款打款。' if passed else '审批驳回或订单不符合退款条件；未执行打款。'
    return {'decision': decision, 'approval_status': status, 'decision_detail': detail,
            'history': [f'[结束] {detail}'], 'node_trace': [{'node_name': NODE_FINALIZE}]}
