"""Environment-only configuration. No implicit live-to-mock fallback."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from common.model_config import text_config
from common.config_env import resolve_env


def search_source(env):
    """Choose one credential group; never mix an override with another provider."""
    explicit = any(env.get(key, '').strip() for key in ('M4_SEARCH_URL', 'M4_SEARCH_API_KEY', 'M4_SEARCH_MODEL'))
    provider = env.get('M4_SEARCH_PROVIDER', '').strip() or ('bailian' if not explicit and
        any(env.get(key, '').strip() for key in ('BAILIAN_API_KEY', 'BAILIAN_BASE_URL')) else 'tavily')
    if provider not in ('bailian', 'tavily'):
        raise ValueError('M4_SEARCH_PROVIDER must be bailian or tavily')
    return provider, 'BAILIAN_*' if provider == 'bailian' and not explicit else 'M4_SEARCH_*'


@dataclass(frozen=True)
class Settings:
    mode: str = 'live'
    llm_base_url: str = ''
    llm_api_key: str = field(default='', repr=False)
    llm_model: str = ''
    llm_timeout: float = 30
    search_url: str = ''
    search_api_key: str = field(default='', repr=False)
    search_provider: str = 'tavily'
    search_model: str = 'qwen-plus'
    image_base_url: str = ''
    image_api_key: str = field(default='', repr=False)
    image_model: str = ''
    image_provider: str = 'openai'
    image_timeout: float = 180
    service_timeout: float = 60
    kb_path: Path | None = None

    def __post_init__(self):
        if self.mode not in ('live', 'mock'):
            raise ValueError('M4_MODE must be live or mock')
        if self.image_provider not in ('openai', 'bailian'):
            raise ValueError('M4_IMAGE_PROVIDER must be openai or bailian')
        if self.search_provider not in ('bailian', 'tavily'):
            raise ValueError('M4_SEARCH_PROVIDER must be bailian or tavily')
        for value in (self.llm_timeout, self.service_timeout, self.image_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Timeouts must be finite and positive')
        for value in (self.llm_base_url, self.search_url, self.image_base_url):
            if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
                raise ValueError('Configured service URLs must use http or https')

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd() / '.env', override=False)
        env = resolve_env()
        config = text_config(env)
        search_provider, source = search_source(env)
        search_bailian = source == 'BAILIAN_*'
        explicit_image = any(env.get(key, '').strip() for key in ('M4_IMAGE_BASE_URL', 'M4_IMAGE_API_KEY', 'M4_IMAGE_MODEL'))
        provider = env.get('M4_IMAGE_PROVIDER') or ('bailian' if not explicit_image and
            any(env.get(key, '').strip() for key in ('BAILIAN_API_KEY', 'BAILIAN_BASE_URL')) else 'openai')
        use_bailian = provider == 'bailian' and not explicit_image
        return cls(mode=env.get('M4_MODE', 'live'), llm_base_url=config.base_url,
            llm_api_key=config.api_key, llm_model=config.model,
            llm_timeout=float(env.get('LLM_TIMEOUT_SECONDS', '30')),
            search_url=env.get('BAILIAN_BASE_URL' if search_bailian else 'M4_SEARCH_URL', '').strip(),
            search_api_key=env.get('BAILIAN_API_KEY' if search_bailian else 'M4_SEARCH_API_KEY', '').strip(),
            search_provider=search_provider,
            search_model=env.get('BAILIAN_SEARCH_MODEL' if search_bailian else 'M4_SEARCH_MODEL', '').strip() or 'qwen-plus',
            image_base_url=env.get('BAILIAN_BASE_URL', '') if use_bailian else env.get('M4_IMAGE_BASE_URL', ''),
            image_api_key=env.get('BAILIAN_API_KEY', '') if use_bailian else env.get('M4_IMAGE_API_KEY', ''),
            image_model=(env.get('BAILIAN_IMAGE_MODEL') or 'qwen-image-2.0') if use_bailian else env.get('M4_IMAGE_MODEL', ''),
            image_provider=provider, image_timeout=float(env.get('M4_IMAGE_TIMEOUT_SECONDS') or '180'),
            service_timeout=float(env.get('M4_SERVICE_TIMEOUT_SECONDS', '60')),
            kb_path=Path(env['M4_KB_PATH']) if env.get('M4_KB_PATH') else None)
