"""Original M7 topology: amount branch, compliance and reflection loop."""
from typing import Any, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from agents.workflow.state import RefundState
from agents.workflow.nodes import (receive_node, auto_approve_node, manual_review_node, compliance_check_node, reflect_node, finalize_node, route_by_amount, route_after_review, route_compliance, route_reflection, BRANCH_AUTO, BRANCH_MANUAL, BRANCH_REJECT)

def build_refund_graph(checkpointer: Optional[Any]=None, interrupt_before: tuple=('manual_review',)):
    builder = StateGraph(RefundState)
    builder.add_node('receive', receive_node)
    builder.add_node('auto_approve', auto_approve_node)
    builder.add_node('manual_review', manual_review_node)
    builder.add_node('compliance_check', compliance_check_node)
    builder.add_node('reflect', reflect_node)
    builder.add_node('finalize', finalize_node)
    builder.add_edge(START, 'receive')
    builder.add_conditional_edges('receive', route_by_amount, {BRANCH_AUTO: 'auto_approve', BRANCH_MANUAL: 'manual_review', BRANCH_REJECT: 'finalize'})
    builder.add_edge('auto_approve', 'compliance_check')
    builder.add_conditional_edges('manual_review', route_after_review, {'continue': 'compliance_check', 'rejected': 'finalize'})
    builder.add_conditional_edges('compliance_check', route_compliance, {'pass': 'finalize', 'retry': 'reflect'})
    builder.add_conditional_edges('reflect', route_reflection, {'back': 'manual_review', 'reject': 'finalize'})
    builder.add_edge('finalize', END)
    return builder.compile(checkpointer=checkpointer or MemorySaver(), interrupt_before=list(interrupt_before))
