"""Offline presence check. Never print credentials or contact a service."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from common.model_config import text_config
from common.config_env import MAPPED_SETTINGS, resolve_env
from agents.router.config import search_source

GROUPS = {
    'business_llm': ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'),
    'search': ('M4_SEARCH_URL', 'M4_SEARCH_API_KEY'),
    'image': ('M4_IMAGE_BASE_URL', 'M4_IMAGE_API_KEY', 'M4_IMAGE_MODEL'),
}


def check_config(env):
    mapped = [name for name in MAPPED_SETTINGS if env.get(name + '_ENV', '').strip()]
    env = resolve_env(env)
    def group(names):
        missing = [name for name in names if not env.get(name, '').strip()]
        return {'configured': not missing, 'missing': missing}
    result = {name: group(keys) for name, keys in GROUPS.items()}
    search_provider, source = search_source(env)
    names = ('BAILIAN_BASE_URL', 'BAILIAN_API_KEY') if source == 'BAILIAN_*' else GROUPS['search']
    result['search'] = {**group(names), 'source': source, 'provider': search_provider}
    config = text_config(env)
    source_fields = {'LLM_*': ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'),
                     'DEEPSEEK_*': ('DEEPSEEK_BASE_URL', 'DEEPSEEK_API_KEY'),
                     'BAILIAN_*': ('BAILIAN_BASE_URL', 'BAILIAN_API_KEY')}
    result['business_llm'] = {**group(source_fields[config.source]), 'source': config.source}
    if any(env.get(key, '').strip() for key in GROUPS['business_llm']):
        names = ('LLM_BASE_URL', 'LLM_API_KEY',
                 'HUB_PLANNER_MODEL' if env.get('HUB_PLANNER_MODEL', '').strip() else 'LLM_MODEL')
        result['planner'] = {**group(names), 'source': 'LLM_*'}
    else:
        result['planner'] = dict(result['business_llm'])
    explicit_image = any(env.get(key, '').strip() for key in GROUPS['image'])
    provider = env.get('M4_IMAGE_PROVIDER') or ('bailian' if not explicit_image and
        any(env.get(key, '').strip() for key in ('BAILIAN_API_KEY', 'BAILIAN_BASE_URL')) else 'openai')
    if provider == 'bailian' and not explicit_image:
        result['image'] = {**group(('BAILIAN_BASE_URL', 'BAILIAN_API_KEY')), 'source': 'BAILIAN_*'}
    else:
        result['image']['source'] = 'M4_IMAGE_*'
    return {'network_called': False, 'note': 'Presence only; endpoint compatibility and credentials are unverified.',
            'mapped_settings': mapped,
            'services': result}


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    try:
        result = check_config(os.environ)
    except ValueError as exc:
        print(json.dumps({'network_called': False, 'configuration_error': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(group['configured'] for group in result['services'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
