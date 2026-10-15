"""Calendar-aware ISO week values shared by business contracts."""
from datetime import date
import re


ISO_WEEK_PATTERN = r'^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$'


def week_start(week: str) -> date:
    """Return the Monday of an existing, canonically formatted ISO week."""
    if not isinstance(week, str) or re.fullmatch(ISO_WEEK_PATTERN, week) is None:
        raise ValueError('week 不是有效 ISO 周')
    year, number = week.split('-W')
    try:
        return date.fromisocalendar(int(year), int(number), 1)
    except ValueError as exc:
        raise ValueError('week 不是有效 ISO 周') from exc


def week_schema() -> dict:
    return {'type': 'string', 'pattern': ISO_WEEK_PATTERN, 'format': 'iso-week'}
