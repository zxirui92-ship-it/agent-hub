"""Composition root. Adding a Skill means implementing it and registering it here."""
from agents.router.agent import RouterAgent
from agents.router.config import Settings
from agents.router.registry import SkillRegistry
from agents.router.routing import ExplicitMockRouter, LlmRouter
from agents.router.skills.web_search import WebSearchSkill
from agents.router.skills.kb_qa import KbQaSkill
from agents.router.skills.code_gen import CodeGenSkill
from agents.router.skills.image_gen import ImageGenSkill
from agents.router.skills.bailian_image import BailianImageSkill
from agents.router.skills.bailian_search import BailianSearchSkill
from common.llm import ChatModel
from agents.router.image_brief import ImagePromptWriter, PromptedImageSkill


def create_agent(settings: Settings | None = None) -> RouterAgent:
    settings = settings or Settings.from_env()
    mock = settings.mode == 'mock'
    model = ChatModel(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout, json_mode=True)
    registry = SkillRegistry()
    search = (BailianSearchSkill(settings.search_url, settings.search_api_key, settings.search_model,
              settings.service_timeout, mock=mock) if settings.search_provider == 'bailian' else
              WebSearchSkill(settings.search_api_key, settings.search_url, settings.service_timeout, mock=mock))
    registry.register('web_search', 'Search the public web for current facts, news and external sources. 联网搜索最新信息。', search)
    registry.register('kb_qa', 'Answer company policy questions using local knowledge entries. 企业知识库、优惠政策、退款规则。', KbQaSkill(settings.kb_path))
    registry.register('code_gen', 'Generate requested source code; never execute it. 按明确要求生成源代码；海报成图和营销文案不是代码任务。', CodeGenSkill(model, mock=mock))
    image_type = BailianImageSkill if settings.image_provider == 'bailian' else ImageGenSkill
    provider = image_type(settings.image_base_url, settings.image_api_key, settings.image_model, settings.image_timeout, mock=mock)
    registry.register('image_gen', 'Generate images, posters, illustrations or visual designs from text descriptions. 先撰写视觉提示词，再生成真实图片。',
                      PromptedImageSkill(ImagePromptWriter(model, mock=mock), provider))
    return RouterAgent(registry, ExplicitMockRouter() if mock else LlmRouter(model))
