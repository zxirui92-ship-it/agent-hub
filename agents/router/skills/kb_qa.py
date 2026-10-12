"""Small lexical knowledge lookup with grounded extracts. No RAG framework or LLM."""
import json
from pathlib import Path
import re

from agents.router.skills import query_text
from common.errors import ErrorCode, ServiceError


class KbQaSkill:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).with_name('knowledge_sample.json')
        self.sample = path is None

    def run(self, payload: dict) -> str:
        query = query_text(payload).casefold()
        try:
            entries = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Knowledge file unavailable or invalid JSON', retryable=False) from exc
        if not isinstance(entries, list) or any(not isinstance(e, dict) or
                not all(isinstance(e.get(k), str) and e[k].strip() for k in ('entry_id', 'title', 'content')) or
                not isinstance(e.get('keywords'), list) or not e['keywords'] or
                not all(isinstance(k, str) and k.strip() for k in e['keywords']) for e in entries):
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Knowledge entries require entry_id/title/content and nonempty keywords')
        ranked = []
        for entry in entries:
            score = sum(1 for keyword in entry['keywords'] if keyword.casefold() in query)
            # Latin word matching also permits useful lookup in user supplied entries.
            words = set(re.findall(r'[a-z0-9]{3,}', query))
            score += len(words & set(re.findall(r'[a-z0-9]{3,}', (entry['title']+' '+entry['content']).casefold())))
            if score:
                ranked.append((score, entry))
        if not ranked:
            raise ServiceError(ErrorCode.NOT_FOUND, 'No matching knowledge entry; no answer invented')
        hits = [entry for _, entry in sorted(ranked, key=lambda item: -item[0])[:3]]
        return json.dumps({'mode': 'local', 'source_kind': 'bundled_sample' if self.sample else 'configured_knowledge',
                           'answer': '\n'.join(entry['content'] for entry in hits),
                           'sources': [{'entry_id': e['entry_id'], 'title': e['title']} for e in hits]}, ensure_ascii=False)
