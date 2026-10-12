import json
from pathlib import Path

import pytest
import os
import socket

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


def pytest_addoption(parser):
    parser.addoption('--run-live', action='store_true', default=False, help='Allow explicitly marked paid API tests')


def pytest_sessionstart(session):
    # pytest's explicit nested basetemp needs its parent even on a fresh checkout.
    (session.config.rootpath / '.pytest_cache').mkdir(exist_ok=True)


def pytest_collection_modifyitems(config, items):
    enabled = config.getoption('--run-live') and os.getenv('M4_RUN_LIVE_TESTS') == '1'
    for item in items:
        if 'live' in item.keywords and not enabled:
            item.add_marker(pytest.mark.skip(reason='Live API tests require --run-live and M4_RUN_LIVE_TESTS=1'))


@pytest.fixture(autouse=True)
def offline_network_guard(request, monkeypatch):
    if 'live' not in request.keywords:
        def blocked(*args, **kwargs):
            raise AssertionError('Network is disabled in ordinary tests')
        monkeypatch.setattr(socket.socket, 'connect', blocked)
