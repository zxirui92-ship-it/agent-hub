"""Independent Skills share run(self, payload: dict) -> str."""
from common.errors import ErrorCode, ServiceError

SKILL_CATEGORIES = ('web_search', 'kb_qa', 'code_gen', 'image_gen')


def query_text(payload: dict) -> str:
    query = payload.get('query')
    if not isinstance(query, str) or not query.strip():
        raise ServiceError(ErrorCode.INVALID_INPUT, 'Skill requires a nonempty query')
    return query
