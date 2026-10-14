"""M7 state and append reducers, adapted from the supplied module."""
from __future__ import annotations
import operator
from typing import Annotated, Any, Dict, List, TypedDict
from agents.workflow.formatting import format_amount
NODE_RECEIVE = 'receive'
NODE_AUTO_APPROVE = 'auto_approve'
NODE_MANUAL_REVIEW = 'manual_review'
NODE_COMPLIANCE_CHECK = 'compliance_check'
NODE_REFLECT = 'reflect'
NODE_FINALIZE = 'finalize'

class RefundState(TypedDict, total=False):
    order_snapshot: Dict[str, Any]
    max_reflection: int
    order_id: str
    reason: str
    thread_id: str
    customer_id: str
    customer_name: str
    refund_amount: int
    order_amount: int
    product_name: str
    order_status: str
    risk_level: str
    risk_note: str
    auto_approve_amount: int
    amount_branch: str
    requires_manual: bool
    human_decision: str
    approval_status: str
    approval_mode: str
    reviewer: str
    material_complete: bool
    compliance_passed: bool
    compliance_notes: str
    failed_rules: List[str]
    reflection_count: int
    reflection_notes: str
    decision: str
    decision_detail: str
    history: Annotated[List[str], operator.add]
    node_trace: Annotated[List[Dict[str, str]], operator.add]
    rollback_log: Annotated[List[str], operator.add]

def new_state(order_id: str, reason: str, thread_id: str) -> RefundState:
    return RefundState(order_id=order_id, reason=reason, thread_id=thread_id, refund_amount=0, order_amount=0, auto_approve_amount=50000, amount_branch='', reflection_count=0, compliance_passed=False, material_complete=False, requires_manual=False, human_decision='', approval_status='pending', approval_mode='', decision='pending', history=[f'[受理] 收到退款申请：订单 {order_id}，原因「{reason}」'], node_trace=[], rollback_log=[])

def summarize(state: Dict[str, Any]) -> str:
    return f"订单={state.get('order_id')} 金额={format_amount(state.get('refund_amount', 0))} 阈值={format_amount(state.get('auto_approve_amount', 0))} 分支={state.get('amount_branch') or '—'} 审核={state.get('approval_status')} 合规={('通过' if state.get('compliance_passed') else '未通过')} 反思次数={state.get('reflection_count')} 决策={state.get('decision') or 'pending'}"
