"""Keep source-facing example copies aligned with distributable runtime data."""
from importlib.resources import files
from pathlib import Path

from hub_platform.demo_agents import create_mock_registry
from tests.mocks.agents import create_mock_registry as compatibility_registry


def test_demo_registry_is_the_same_runtime_implementation():
    assert compatibility_registry is create_mock_registry
    assert len(create_mock_registry().list_capabilities()) == 7


def test_documented_fixture_copies_match_packaged_resources():
    source = Path(__file__).resolve().parents[2] / 'data' / 'fixtures'
    packaged = files('common').joinpath('fixtures')
    for path in source.rglob('*.json'):
        resource = packaged.joinpath(*path.relative_to(source).parts)
        assert resource.read_bytes() == path.read_bytes(), str(path)
