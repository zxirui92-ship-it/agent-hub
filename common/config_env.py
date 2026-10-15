"""Explicit local variable-name aliases; no environment mutation or secret files."""
import os
import re


TEXT_SETTINGS = (
    'LLM_PROVIDER', 'LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL',
    'DEEPSEEK_BASE_URL', 'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL',
    'BAILIAN_BASE_URL', 'BAILIAN_API_KEY', 'BAILIAN_TEXT_MODEL',
)
SKILL_SETTINGS = (
    'M4_SEARCH_PROVIDER', 'M4_SEARCH_URL', 'M4_SEARCH_API_KEY', 'M4_SEARCH_MODEL',
    'BAILIAN_SEARCH_MODEL', 'M4_IMAGE_PROVIDER', 'M4_IMAGE_BASE_URL',
    'M4_IMAGE_API_KEY', 'M4_IMAGE_MODEL', 'BAILIAN_IMAGE_MODEL',
)
MAPPED_SETTINGS = TEXT_SETTINGS + SKILL_SETTINGS + ('HUB_PLANNER_MODEL',)
KEY_SETTINGS = tuple(name for name in MAPPED_SETTINGS if name.endswith('API_KEY'))
_VARIABLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def resolve_env(env=None, names=MAPPED_SETTINGS):
    """NAME_ENV=EXISTING_VAR overrides NAME, reading one level from the input.

    An explicit missing alias is a configuration error, never permission to use
    another account/provider. Empty NAME_ENV leaves the existing behavior intact.
    """
    source = os.environ if env is None else env
    result = dict(source)
    for name in names:
        result.pop(name + '_ENV', None)
        alias = source.get(name + '_ENV', '').strip()
        if not alias:
            continue
        if _VARIABLE.fullmatch(alias) is None:
            raise ValueError(f'{name}_ENV must contain an environment variable name, not a value')
        value = source.get(alias, '').strip()
        if not value:
            raise ValueError(f'{name}_ENV points to an unset or empty environment variable')
        result[name] = value
    return result


def secret_values(env=None):
    """Include arbitrary credential aliases in existing error/report redaction."""
    source = os.environ if env is None else env
    values = {value for name, value in source.items() if name.endswith('API_KEY') and value}
    for name in KEY_SETTINGS:
        alias = source.get(name + '_ENV', '').strip()
        if _VARIABLE.fullmatch(alias) and source.get(alias):
            values.add(source[alias])
    return values | {value.strip() for value in values if value.strip()}
