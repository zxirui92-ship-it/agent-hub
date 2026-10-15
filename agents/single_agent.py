"""M1 single model + window memory + two FAQ tools, adapted from M1.zip."""
import argparse
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from common.contracts import AgentRequest, AgentResult
from common.customer_contract import faq_manifest, SESSION
from common.errors import ErrorCode, ServiceError
from common.model_config import text_config
from common.llm import ChatModel, TextModel
from common.business_data import configured_data
from common.knowledge import KnowledgeBase
from common.module_boundary import result_for, failure, correlation
from hub_platform.errors import HubError
from hub_platform.schema import validate_data


def lookup_faq(question: str) -> str:
    """Local sample FAQ; no claim of querying a production service."""
    if any(word in question for word in ('退', '换', '售后')):
        return '样例 FAQ：符合条件的商品支持七天无理由退货，特殊商品以售后政策为准。'
    if '发票' in question:
        return '样例 FAQ：开票需提供订单和抬头，请通过订单售后入口申请。'
    return '样例 FAQ 未找到匹配条目；请补充服务问题，不编造订单信息。'


def get_service_policy() -> str:
    return '样例服务政策：退换货须满足商品完好等条件；具体资格由售后审核，不承诺退款已执行。'


class ConversationMemory:
    def __init__(self, window_size: int = 6):
        if type(window_size) is not int or window_size < 1:
            raise ValueError('window_size must be a positive integer')
        self.window_size = window_size
        self._history = defaultdict(lambda: deque(maxlen=window_size))

    def add(self, session_id: str, role: str, content: str):
        self._history[session_id].append({'role': role, 'content': content})

    def window(self, session_id: str):
        return deepcopy(list(self._history.get(session_id, ())))


class LocalFAQModel:
    """Explicit mock answer for a no-network demo; not semantic model validation."""
    def complete(self, system, query):
        data = json.loads(query)
        return 'Mock 回答（离线演示）：' + '；'.join(data['tool_results'].values())


class SingleAgent:
    manifest = faq_manifest()

    def __init__(self, model: TextModel | None = None, *, memory=None, mode=None, knowledge=None):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        self.mode = mode or ('live' if model is not None else os.getenv('M1_MODE', 'live'))
        if self.mode not in ('live', 'mock') or (self.mode == 'mock' and model is not None):
            raise ValueError('M1_MODE must be live or mock; mock does not accept a model')
        config = text_config()
        self.model = model if model is not None else (LocalFAQModel() if self.mode == 'mock' else
            ChatModel(config.base_url, config.api_key, config.model, float(os.getenv('LLM_TIMEOUT_SECONDS') or '120')))
        self.memory = memory if memory is not None else ConversationMemory()
        data = configured_data()
        self.knowledge = knowledge if knowledge is not None else (KnowledgeBase(data=data) if data is not None else None)

    def _knowledge_tool(self, question, history, source_file):
        """A retrieval miss is evidence of absence, not a failed conversation.

        Only explicit follow-ups may use prior user turns to resolve a topic.
        File/schema/service errors still propagate to the module boundary.
        """
        query = question
        if re.match(r'^(那|这|它|上述|刚才|具体|还需要)', question) and history:
            query = '\n'.join(m['content'] for m in history if m['role'] == 'user') + '\n' + question
        try:
            evidence = self.knowledge.search(query, source_file=source_file)
            evidence.update(status='found', retrieval_query=query)
        except ServiceError as exc:
            if exc.code != ErrorCode.NOT_FOUND:
                raise
            evidence = {'status':'not_found', 'answer':'本工具未检索到相关条目；不能据此编造业务政策。',
                        'sources':[], 'retrieval_query':query}
        return json.dumps(evidence, ensure_ascii=False)

    def invoke(self, request: AgentRequest) -> AgentResult:
        try:
            if request.capability_id != self.manifest.capability_id:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Wrong capability_id', retryable=False)
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            # Explicit payload takes precedence over the platform conversation context.
            session_id = request.payload.get('session_id') or request.context.get('session_id') or f'sess-{uuid4().hex[:12]}'
            validate_data(session_id, SESSION, ErrorCode.INVALID_INPUT)
            question = request.payload['question']
            history = self.memory.window(session_id)
            if self.knowledge:
                tool_results = {
                    'lookup_faq': self._knowledge_tool(question, history, 'faq_knowledge.json'),
                    'get_service_policy': self._knowledge_tool(question, history, 'service_policy.json'),
                }
            else:
                tool_results = {'lookup_faq': lookup_faq(question)}
            if self.knowledge is None and any(word in question for word in ('政策', '售后', '退', '换', '规则', '条件')):
                tool_results['get_service_policy'] = get_service_policy()
            logging.getLogger('agent_hub.m1').info(json.dumps({**correlation(request),
                'ts': datetime.now(timezone.utc).isoformat(), 'level': 'info',
                'module': 'm1', 'event': 'tool_calls', 'actions': list(tool_results),
                'mode': self.mode}, ensure_ascii=False))
            answer = self.model.complete(
                '你是 FAQ 客服。依据提供的工具事实和会话历史简短回答；条目是样例，缺失信息明确说明。'
                '引用条目 ID；若 FAQ 与政策冲突，列出差异并提示需要业务确认，不自行选择权威。'
                '工具 not_found 表示缺少相关资料；普通闲聊和会话记忆问题仍应正常回应。'
                '普通问候只自然回应，不主动提及工具、检索、not_found 或无关业务规则。'
                '历史检索仅用于用户明确的指代追问，不将历史话题套到无关问题。'
                '不查询实时订单、不承诺执行退款。', json.dumps({
                    'history': self.memory.window(session_id), 'question': question,
                    'tool_results': tool_results}, ensure_ascii=False))
            data = {'answer': answer, 'session_id': session_id}
            validate_data(data, self.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
            self.memory.add(session_id, 'user', question)
            self.memory.add(session_id, 'assistant', answer)
            return result_for(request, status='completed', data=data)
        except (ServiceError, HubError) as exc:
            return failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception:
            logging.getLogger('agent_hub.m1').exception('M1 invocation failed')
            return failure(request, ErrorCode.INTERNAL_ERROR, 'M1 内部执行失败')


def main(argv=None):
    parser = argparse.ArgumentParser(description='M1 FAQ single agent')
    parser.add_argument('question')
    parser.add_argument('--session-id')
    parser.add_argument('--mode', choices=['live', 'mock'])
    args = parser.parse_args(argv)
    payload = {'question': args.question}
    if args.session_id:
        payload['session_id'] = args.session_id
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
        trace_id=f'trace-{uuid4().hex[:16]}', capability_id='m1.faq_chat', payload=payload)
    result = SingleAgent(mode=args.mode).invoke(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
