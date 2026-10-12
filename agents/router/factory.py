"""Composition root. Adding a Skill means implementing it and registering it here."""
from agents.router.agent import RouterAgent
from agents.router.config import Settings
from agents.router.registry import SkillRegistry
from agents.router.routing import ExplicitMockRouter, LlmRouter
from agents.router.skills.web_search import WebSearchSkill
from agents.router.skills.kb_qa import KbQaSkill
from agents.router.skills.code_gen import CodeGenSkill
from agents.router.skills.image_gen import ImageGenSkill
from common.llm import ChatModel


def create_agent(settings: Settings | None = None) -> RouterAgent:
    settings = settings or Settings.from_env()
    mock = settings.mode == 'mock'
    model = ChatModel(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout)
    registry = SkillRegistry()
    registry.register('web_search', 'Search the public web for current facts, news and external sources. 联网搜索最新信息。', WebSearchSkill(settings.search_api_key, settings.search_url, settings.service_timeout, mock=mock))
    registry.register('kb_qa', 'Answer company policy questions using local knowledge entries. 企业知识库、优惠政策、退款规则。', KbQaSkill(settings.kb_path))
    registry.register('code_gen', 'Generate source code from natural language requirements; never execute code. 按需求生成代码。', CodeGenSkill(model, mock=mock))
    registry.register('image_gen', 'Generate images, illustrations or visual designs from text descriptions. 根据描述生成图片。', ImageGenSkill(settings.image_base_url, settings.image_api_key, settings.image_model, settings.service_timeout, mock=mock))
    return RouterAgent(registry, ExplicitMockRouter() if mock else LlmRouter(model))
