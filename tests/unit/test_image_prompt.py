import json
import pytest
from agents.router.image_brief import ImagePromptWriter, PromptedImageSkill, business_copy
from common.errors import ServiceError
from tests.integration.test_poster_handoff import FACTS, GOAL


class WriterModel:
    model = 'test-writer'

    def __init__(self, corrupt=False):
        self.corrupt = corrupt

    def complete(self, system, query):
        request = json.loads(query)
        if 'original_request' in request:
            request = json.loads(request['original_request'])
        return json.dumps({'art_direction': '深红背景，香槟金流线，标题置顶，中央大数字，底部两张指标卡。清晰无衬线字体，充足留白。',
            'visible_text': ['4.12亿元'] if self.corrupt else request['required_copy'] or []})


def test_business_prompt_separates_design_from_verified_copy():
    calls = []
    class Image:
        def run(self, payload):
            calls.append(payload)
            return json.dumps({'images': [{'image_url': 'https://example.test/poster.png'}]})
    result = json.loads(PromptedImageSkill(ImagePromptWriter(WriterModel()), Image()).run(
        {'query': GOAL, 'fused_data': FACTS}))
    prompt = calls[0]['query']
    assert '1,512万元' in prompt and '75,300单' in prompt and '14.26%' in prompt
    assert '2025-10-20' in prompt and '2025-10-26' in prompt
    assert FACTS['anomaly'] not in prompt
    assert '不得捏造' not in prompt and '来源及限制' not in prompt
    assert result['prompt_writing']['visible_text'] == business_copy(GOAL, FACTS)
    assert result['prompt_writing']['final_prompt'] == prompt


def test_fabricated_copy_stops_before_paid_image_call():
    class NeverImage:
        def run(self, payload):
            pytest.fail('Invalid copy must not reach image provider')
    with pytest.raises(ServiceError, match='提示词撰写'):
        PromptedImageSkill(ImagePromptWriter(WriterModel(True)), NeverImage()).run(
            {'query': GOAL, 'fused_data': FACTS})


def test_illustration_does_not_inherit_business_poster_text():
    brief = ImagePromptWriter(WriterModel()).write('画一只蓝色小鸟，无文字')
    assert brief['visible_text'] == []
    assert '万元' not in brief['final_prompt'] and '2025' not in brief['final_prompt']
