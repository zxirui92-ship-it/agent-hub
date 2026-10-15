"""Tavily-compatible search, explicit offline sample, or explicit unconfigured error."""
import json

from agents.router.skills import query_text
from common.errors import ErrorCode, ServiceError
from common.http_client import parse_http_url, post_json


class WebSearchSkill:
    def __init__(self, api_key='', url='', timeout=30, *, mock=False, transport=post_json):
        self.api_key, self.url, self.timeout = api_key, url, timeout
        self.mock, self.transport = mock, transport

    def run(self, payload: dict) -> str:
        query = query_text(payload)
        if self.mock:
            return json.dumps({'mode': 'mock', 'query': query, 'results': [
                {'title': '离线搜索样例', 'source_url': 'https://example.com/', 'content': '固定测试结果，不是实时搜索。'}]}, ensure_ascii=False)
        if not self.api_key or not self.url:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Search service not_configured: set M4_SEARCH_API_KEY and M4_SEARCH_URL', retryable=False)
        response = self.transport(self.url, {'query': query, 'max_results': 5}, self.api_key, self.timeout)
        rows = response.get('results')
        if not isinstance(rows, list):
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Search response missing results array')
        results = []
        for row in rows:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('title', 'url', 'content')):
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Search result requires title/url/content strings')
            try:
                parse_http_url(row['url'])
            except ValueError as exc:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Search result has invalid source URL') from exc
            results.append({'title': row['title'], 'source_url': row['url'], 'content': row['content']})
        return json.dumps({'mode': 'live', 'query': query, 'results': results}, ensure_ascii=False)
