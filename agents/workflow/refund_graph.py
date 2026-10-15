"""M7 facade adapted to the current hub contracts, with in-process checkpoints.

Original topology/state/compliance rules: user-supplied M7 (郑江).
No payment service is called. Module resume does not resume a platform plan.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from agents.workflow._graph_definition import build_refund_graph
from agents.workflow.nodes import NON_REFUNDABLE_ORDER_STATUS, REFUNDABLE_ORDER_STATUS
from agents.workflow.state import new_state
from common.contracts import AgentRequest, AgentResult
from common.errors import ErrorCode, ServiceError
from common.module_boundary import result_for, failure
from common.order_data import order_fact
from common.refund_contract import refund_manifest
from hub_platform.errors import HubError
from hub_platform.schema import validate_data

CAPABILITY_ID = 'm7.refund_approval'
MANIFEST = refund_manifest(supports_resume=True)


class RefundWorkflow:
    manifest = MANIFEST

    def __init__(self, *, order_loader=order_fact):
        self.order_loader = order_loader
        self.checkpointer = MemorySaver()
        self.graph = build_refund_graph(self.checkpointer)
        self._pending: dict[str, tuple[AgentRequest, str]] = {}
        # A committed graph step must not run again if only its response failed.
        self._submitted: dict[str, tuple[bool, str, bool]] = {}
        self._resume_generations: dict[str, int] = {}
        self._requests: dict[str, str] = {}

    @staticmethod
    def _config(thread_id):
        return {'configurable': {'thread_id': thread_id}}

    def run(self, order_id: str, reason: str, *, refund_amount: int,
            thread_id: str | None = None) -> dict:
        """Independent local workflow entry; new runs need a fresh thread id."""
        thread_id = thread_id or f'workflow-{uuid4().hex}'
        config = self._config(thread_id)
        if self.graph.get_state(config).values:
            raise ServiceError(ErrorCode.INVALID_INPUT, 'thread_id 已存在，请通过 resume 恢复', retryable=False)
        fact = deepcopy(self.order_loader(order_id))
        if (not isinstance(fact, dict)
                or type(fact.get('order_amount')) is not int or fact['order_amount'] <= 0
                or not isinstance(fact.get('order_status'), str)
                or fact['order_status'] not in REFUNDABLE_ORDER_STATUS | NON_REFUNDABLE_ORDER_STATUS
                or not isinstance(fact.get('risk_level', 'normal'), str)
                or fact.get('risk_level', 'normal') not in {'normal', 'high_risk'}):
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, '订单来源金额、状态或风险等级不符合契约', retryable=False)
        if type(refund_amount) is not int or refund_amount <= 0 or refund_amount != fact['order_amount']:
            raise ServiceError(ErrorCode.INVALID_INPUT, '仅支持整单退款；refund_amount 必须等于订单事实 order_amount', retryable=False)
        state = new_state(order_id, reason, thread_id)
        state.update(order_snapshot=fact, max_reflection=3)
        self.graph.invoke(state, config)
        return dict(self.graph.get_state(config).values)

    def next_nodes(self, thread_id: str) -> list[str]:
        return list(self.graph.get_state(self._config(thread_id)).next)

    def get_trace(self, thread_id: str, limit: int = 50) -> list[dict]:
        from itertools import islice
        return [{'checkpoint_id': snap.config['configurable']['checkpoint_id'],
                 'step': (snap.metadata or {}).get('step'), 'next_node': list(snap.next),
                 'state': deepcopy(snap.values)}
                for snap in islice(self.graph.get_state_history(self._config(thread_id)), limit)]

    def get_request_trace(self, request_id: str) -> list[dict]:
        return self.get_trace(self._requests[request_id])

    def rollback(self, thread_id: str, steps_back: int = 1) -> dict:
        """Fork from a historical checkpoint, retaining reducer history once."""
        if type(steps_back) is not int or steps_back < 1:
            raise ValueError('steps_back 必须是正整数')
        history = list(self.graph.get_state_history(self._config(thread_id)))
        if steps_back >= len(history):
            raise ValueError('检查点不足')
        target = history[steps_back]
        self.graph.update_state(target.config, {
            'rollback_log': [f"回滚至 {target.config['configurable']['checkpoint_id']}"]})
        return dict(self.graph.get_state(self._config(thread_id)).values)

    def resume(self, thread_id: str, *, approved: bool | None = None, reviewer: str = '', material_complete: bool = False) -> dict:
        """Continue a checkpoint; the manual node always requires an explicit decision."""
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.next:
            raise ServiceError(ErrorCode.INVALID_INPUT, '当前没有可恢复的节点', retryable=False)
        if snapshot.next == ('manual_review',):
            approved, reviewer, material_complete = self._decision(approved, reviewer, material_complete)
            # Write as the preceding node so the pending manual node is not skipped.
            self.graph.update_state(config, {'human_decision': 'approved' if approved else 'rejected',
                'reviewer': reviewer.strip(), 'material_complete': material_complete})
        elif approved is not None:
            raise ServiceError(ErrorCode.INVALID_INPUT, '当前节点不接受人工审批决定', retryable=False)
        self.graph.invoke(None, config)
        # Record completion before reading the response snapshot: that read can fail
        # after the graph has already committed an approval or another review pause.
        self._resume_generations[thread_id] = self._resume_generations.get(thread_id, 0) + 1
        return dict(self.graph.get_state(config).values)

    @staticmethod
    def _decision(approved, reviewer, material_complete) -> tuple[bool, str, bool]:
        if type(approved) is not bool or type(material_complete) is not bool or not isinstance(reviewer, str) or not reviewer.strip():
            raise ServiceError(ErrorCode.INVALID_INPUT, '需提供布尔 approved/material_complete 和非空 reviewer', retryable=False)
        return approved, reviewer.strip(), material_complete

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

    def _result(self, request: AgentRequest, thread_id: str) -> AgentResult:
        state = self.graph.get_state(self._config(thread_id)).values
        waiting = bool(self.next_nodes(thread_id))
        data = {'request_id': 'refund-' + sha256(request.request_id.encode()).hexdigest()[:12],
                'approval_status': 'waiting_approval' if waiting else state['approval_status'],
                'node_trace': state['node_trace'],
                'state_view': {key: state[key] for key in ('order_id', 'order_amount', 'refund_amount')}}
        validate_data(data, self.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
        metadata = {}
        if waiting:
            token = f'cont-{uuid4().hex[:16]}'
            metadata = {'continuation_token': token,
                        'waiting_reason': state.get('reflection_notes') or (
                            '高风险订单，等待人工审核及完整退货材料。' if state.get('risk_level') == 'high_risk'
                            else '金额超过 50000 分，等待人工审核。')}
        return result_for(request, status='waiting_approval' if waiting else 'completed', data=data, **metadata)

    def _register_pending(self, request: AgentRequest, thread_id: str, result: AgentResult) -> None:
        # Publish a continuation only after the entire response was constructed.
        if result.continuation_token:
            self._pending[result.continuation_token] = (request.model_copy(deep=True), thread_id)

    def invoke(self, request: AgentRequest) -> AgentResult:
        if request.capability_id != CAPABILITY_ID:
            return failure(request, ErrorCode.CONTRACT_MISMATCH, 'Request capability_id does not match M7')
        try:
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            thread_id = f'workflow-{uuid4().hex}'
            self.run(**request.payload, thread_id=thread_id)
            self._requests[request.request_id] = thread_id
            result = self._result(request, thread_id)
            self._register_pending(request, thread_id, result)
            return result
        except (HubError, ServiceError) as exc:
            return failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception as exc:
            return failure(request, ErrorCode.INTERNAL_ERROR, f'M7 执行失败：{type(exc).__name__}')

    def submit_decision(self, continuation_token: str, *, approved: bool, reviewer: str,
                        material_complete: bool) -> AgentResult:
        """In-process module resume; tokens rotate after each successful response.

        Unknown/consumed tokens raise NOT_FOUND (no correlation is available).
        Known requests always return the original four correlation fields.
        Retrying a committed decision after response failure only rebuilds its result.
        """
        if continuation_token not in self._pending:
            raise ServiceError(ErrorCode.NOT_FOUND, '审批 token 不存在、已使用或进程已重启', retryable=False)
        request, thread_id = self._pending[continuation_token]
        try:
            decision = self._decision(approved, reviewer, material_complete)
            if continuation_token in self._submitted:
                if decision != self._submitted[continuation_token]:
                    raise ServiceError(ErrorCode.INVALID_INPUT, '审批决定已提交；请使用原决定重试获取结果', retryable=False)
            else:
                generation = self._resume_generations.get(thread_id, 0)
                try:
                    self.resume(thread_id, approved=approved, reviewer=reviewer, material_complete=material_complete)
                finally:
                    if self._resume_generations.get(thread_id, 0) != generation:
                        self._submitted[continuation_token] = decision
            result = self._result(request, thread_id)
            self._register_pending(request, thread_id, result)
        except (HubError, ServiceError) as exc:
            return failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception as exc:
            return failure(request, ErrorCode.INTERNAL_ERROR, f'M7 恢复失败：{type(exc).__name__}',
                           retryable=continuation_token in self._submitted)
        del self._pending[continuation_token]
        del self._submitted[continuation_token]
        return result


_default: RefundWorkflow | None = None


def _agent():
    global _default
    if _default is None:
        _default = RefundWorkflow()
    return _default


def invoke(request: AgentRequest) -> AgentResult:
    return _agent().invoke(request)


def submit_decision(continuation_token: str, **decision) -> AgentResult:
    return _agent().submit_decision(continuation_token, **decision)


def main(argv=None):
    parser = argparse.ArgumentParser(description='M7 独立本地退款审批图（不执行打款）')
    parser.add_argument('--order-id', default='order-low')
    parser.add_argument('--refund-amount', type=int, default=19900)
    parser.add_argument('--reason', default='商品退货')
    parser.add_argument('--manifest', action='store_true')
    args = parser.parse_args(argv)
    if args.manifest:
        print(MANIFEST.model_dump_json(indent=2))
        return 0
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
        trace_id=f'trace-{uuid4().hex[:16]}', capability_id=CAPABILITY_ID,
        payload={'order_id': args.order_id, 'refund_amount': args.refund_amount, 'reason': args.reason})
    result = invoke(request)
    print(result.model_dump_json(indent=2))
    return 1 if result.status == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
