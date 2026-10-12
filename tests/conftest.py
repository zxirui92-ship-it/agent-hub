import json
from pathlib import Path

import pytest

from tests.mocks.agents import create_mock_registry

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def registry():
    return create_mock_registry()


@pytest.fixture
def load_plan():
    def load(name):
        return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return load
