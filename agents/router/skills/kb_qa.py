"""Small lexical knowledge lookup with grounded extracts. No RAG framework or LLM."""
import json
from agents.router.skills import query_text
from common.knowledge import KnowledgeBase


class KbQaSkill(KnowledgeBase):
    def run(self, payload: dict) -> str:
        return json.dumps(self.search(query_text(payload)), ensure_ascii=False)
