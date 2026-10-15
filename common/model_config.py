"""Resolve local text-model settings without copying credentials into files."""
from dataclasses import dataclass, field
from common.config_env import TEXT_SETTINGS, resolve_env


@dataclass(frozen=True)
class TextConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    source: str


def text_config(env=None):
    env = resolve_env(env, TEXT_SETTINGS)
    values = [env.get(key, '').strip() for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL')]
    if any(values):
        return TextConfig(*values, 'LLM_*')
    provider = env.get('LLM_PROVIDER', 'deepseek').strip() or 'deepseek'
    if provider == 'bailian':
        return TextConfig(env.get('BAILIAN_BASE_URL', '').strip(), env.get('BAILIAN_API_KEY', '').strip(),
                          env.get('BAILIAN_TEXT_MODEL', '').strip() or 'qwen-plus', 'BAILIAN_*')
    if provider != 'deepseek':
        raise ValueError('LLM_PROVIDER must be deepseek or bailian')
    return TextConfig(env.get('DEEPSEEK_BASE_URL', '').strip(), env.get('DEEPSEEK_API_KEY', '').strip(),
                      env.get('DEEPSEEK_MODEL', '').strip() or 'deepseek-flash', 'DEEPSEEK_*')
