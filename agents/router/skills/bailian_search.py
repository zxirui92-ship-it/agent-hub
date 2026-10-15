"""Bailian native public web search. Sources come only from provider metadata."""
import json
from urllib.parse import urlsplit, urlunsplit

from agents.router.skills import query_text
from agents.router.skills.web_search import WebSearchSkill
from common.errors import ErrorCode, ServiceError
from common.http_client import post_json


def search_url(base_url):
    parts = urlsplit(base_url)
    endpoint = '/api/v1/services/aigc/text-generation/generation'
    if (parts.scheme not in ('https', 'http') or not parts.netloc or parts.query or parts.fragment
            or parts.username or parts.password
            or parts.path.rstrip('/') not in ('', '/compatible-mode/v1', '/api/v1', endpoint)):
        raise ValueError('Bailian search URL must be an origin, compatible-mode/v1, api/v1 or native text endpoint')
    return urlunsplit((parts.scheme, parts.netloc, endpoint, '', ''))


class BailianSearchSkill:
    def __init__(self, base_url='', api_key='', model='qwen-plus', timeout=60, *, mock=False, transport=post_json):
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.timeout, self.mock, self.transport = timeout, mock, transport

    def run(self, payload: dict) -> str:
        query = query_text(payload)
        if self.mock:
            return WebSearchSkill(mock=True).run(payload)
        if not all((self.base_url, self.api_key, self.model)):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE,
                'Bailian search service not_configured: set BAILIAN_BASE_URL and BAILIAN_API_KEY '
                '(or the complete M4_SEARCH_URL/API_KEY group)', retryable=False)
        try:
            url = search_url(self.base_url)
        except ValueError as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, str(exc), retryable=False) from exc
        response = self.transport(url, {'model': self.model,
            'input': {'messages': [
                {'role': 'system', 'content':
                 '你是公开网页搜索助手。本次请求已启用服务商联网搜索。请根据本次搜索提供的证据回答，'
                 '保留来源引用，不要把公开网页称为企业知识库。已获得检索证据时不要声称无法联网。'
                 '如果结果不足以回答或没有找到指定官方文档，明确说明未找到直接证据；'
                 '不得编造网址、来源或声称已阅读未提供的网页全文。'},
                {'role': 'user', 'content': query}]},
            'parameters': {'result_format': 'message', 'enable_search': True,
                'search_options': {'forced_search': True, 'enable_source': True,
                                   'enable_citation': True, 'citation_format': '[ref_<number>]'}}},
            self.api_key, self.timeout)
        if response.get('code'):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Bailian search returned a provider error', retryable=False)
        try:
            output = response['output']
            answer = output['choices'][0]['message']['content']
            rows = output['search_info']['search_results']
            if not isinstance(answer, str) or not answer.strip() or not isinstance(rows, list):
                raise ValueError('Invalid answer or sources')
            results = []
            for row in rows:
                title, resource = row['title'], row['url']
                if not isinstance(title, str) or not title.strip() or not isinstance(resource, str):
                    raise ValueError('Invalid source')
                parsed = urlsplit(resource)
                if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
                    raise ValueError('Invalid source URL')
                # DashScope supplies source metadata, not verbatim page text.
                item = {'title': title, 'source_url': resource, 'content': ''}
                if 'index' in row:
                    if type(row['index']) is not int or row['index'] < 1:
                        raise ValueError('Invalid citation index')
                    item['index'] = row['index']
                results.append(item)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH,
                'Bailian search response missing valid answer or source metadata', retryable=False) from exc
        if not results:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE,
                'Bailian search returned no sources; online search could not be verified', retryable=False)
        return json.dumps({'mode': 'live', 'provider': 'bailian', 'model': self.model,
            'query': query, 'answer': answer, 'results': results, 'source_content_available': False}, ensure_ascii=False)
