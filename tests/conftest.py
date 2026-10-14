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
    for item in items:
        flag = ('BUSINESS_RUN_LIVE_TESTS' if 'business_live' in item.keywords else
                'HUB_RUN_LIVE_TESTS' if 'planner_live' in item.keywords else 'M4_RUN_LIVE_TESTS')
        enabled = config.getoption('--run-live') and os.getenv(flag) == '1'
        if 'live' in item.keywords and not enabled:
            item.add_marker(pytest.mark.skip(reason=f'Live API tests require --run-live and {flag}=1'))


def redact_report(text):
    for name, value in os.environ.items():
        if name.endswith('API_KEY') and value:
            text = text.replace(value, '[redacted]')
    return text


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # Pytest includes function arguments even without --showlocals. Protect both
    # terminal tracebacks and JUnit artifacts, including chained HTTP exceptions.
    if report.failed:
        report.longrepr = redact_report(str(report.longrepr))
    report.sections = [(name, redact_report(text)) for name, text in report.sections]
    report.user_properties = [(name, redact_report(value) if isinstance(value, str) else value)
                              for name, value in report.user_properties]


@pytest.fixture(autouse=True)
def offline_network_guard(request, monkeypatch):
    if 'live' not in request.keywords:
        # Child CLI processes inherit these empty keys too; socket monkeypatches
        # alone do not protect subprocesses from the user's local credentials.
        for name in ('LLM_API_KEY', 'DEEPSEEK_API_KEY', 'BAILIAN_API_KEY',
                     'M4_IMAGE_API_KEY', 'M4_SEARCH_API_KEY'):
            monkeypatch.setenv(name, '')
        def blocked(*args, **kwargs):
            raise AssertionError('Network is disabled in ordinary tests')
        monkeypatch.setattr(socket.socket, 'connect', blocked)
