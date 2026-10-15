"""Shared lexical retrieval for M1 and M4; answers retain source identifiers."""
import json
from pathlib import Path
import re

from common.business_data import configured_data
from common.errors import ErrorCode, ServiceError


class KnowledgeBase:
    def __init__(self, path=None, *, data=None):
        self.data = data if data is not None else (configured_data() if path is None else None)
        self.path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / 'agents/router/skills/knowledge_sample.json'
        self.sample = path is None

    def search(self, query, *, source_file=None):
        query = query.casefold()
        if self.data is not None:
            entries = self.data.knowledge_entries()
        else:
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
        words = set(re.findall(r'[a-z0-9]{3,}', query))
        for entry in entries:
            if source_file is not None and entry.get('source_file') != source_file:
                continue
            score = sum(1 for keyword in set(entry['keywords']) if keyword.casefold() in query)
            score += len(words & set(re.findall(r'[a-z0-9]{3,}', (entry['title']+' '+entry['content']).casefold())))
            if entry['title'].casefold() in query:
                score += 100
            if score:
                ranked.append((score, entry))
        if not ranked:
            raise ServiceError(ErrorCode.NOT_FOUND, 'No matching knowledge entry; no answer invented')
        hits = [entry for _, entry in sorted(ranked, key=lambda item: -item[0])[:3]]
        imported = self.data is not None
        warnings = []
        if imported:
            hit_ids = {e['entry_id'] for e in hits}
            for conflict in self.data.knowledge_conflicts():
                if hit_ids.intersection(conflict['entry_ids']):
                    warnings.append(conflict['message'])
                    for entry in entries:
                        if entry['entry_id'] in conflict['entry_ids'] and entry['entry_id'] not in hit_ids:
                            hits.append(entry)
                            hit_ids.add(entry['entry_id'])
        result = {'mode': 'local', 'source_kind': self.data.source_kind if imported else
                ('bundled_sample' if self.sample else 'configured_knowledge'),
                'answer': '\n'.join((f"【{e['entry_id']} {e['title']}】" if imported else '') + e['content'] for e in hits),
                'sources': [{k: e[k] for k in ('entry_id', 'title', 'source_file', 'effective_date') if k in e} for e in hits]}
        if warnings:
            result['warnings'] = warnings
            result['answer'] += '\n' + '\n'.join(warnings)
        return result
