"""Environment-only configuration. No implicit live-to-mock fallback."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mode: str = 'live'
    llm_base_url: str = ''
    llm_api_key: str = field(default='', repr=False)
    llm_model: str = ''
    llm_timeout: float = 30
    search_url: str = ''
    search_api_key: str = field(default='', repr=False)
    image_base_url: str = ''
    image_api_key: str = field(default='', repr=False)
    image_model: str = ''
    service_timeout: float = 60
    kb_path: Path | None = None

    def __post_init__(self):
        if self.mode not in ('live', 'mock'):
            raise ValueError('M4_MODE must be live or mock')
        for value in (self.llm_timeout, self.service_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Timeouts must be finite and positive')
        for value in (self.llm_base_url, self.search_url, self.image_base_url):
            if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
                raise ValueError('Configured service URLs must use http or https')

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd() / '.env', override=False)
        return cls(mode=os.getenv('M4_MODE', 'live'), llm_base_url=os.getenv('LLM_BASE_URL', ''),
            llm_api_key=os.getenv('LLM_API_KEY', ''), llm_model=os.getenv('LLM_MODEL', ''),
            llm_timeout=float(os.getenv('LLM_TIMEOUT_SECONDS', '30')),
            search_url=os.getenv('M4_SEARCH_URL', ''), search_api_key=os.getenv('M4_SEARCH_API_KEY', ''),
            image_base_url=os.getenv('M4_IMAGE_BASE_URL', ''), image_api_key=os.getenv('M4_IMAGE_API_KEY', ''),
            image_model=os.getenv('M4_IMAGE_MODEL', ''), service_timeout=float(os.getenv('M4_SERVICE_TIMEOUT_SECONDS', '60')),
            kb_path=Path(os.environ['M4_KB_PATH']) if os.getenv('M4_KB_PATH') else None)
