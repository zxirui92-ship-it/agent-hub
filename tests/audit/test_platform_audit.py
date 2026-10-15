"""Offline platform and installed-wheel regression coverage from the audit."""
from copy import deepcopy
from pathlib import Path
import json
import os
import random
import subprocess
import sys
import zipfile
import warnings

import pytest

from common.contracts import StepState
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from hub_platform.validator import PlanValidator
from tests.mocks.agents import manifest, obj, result, failure
from common.errors import ErrorCode


class ArithmeticModule:
    def __init__(self):
        self.calls = []
        self.manifest = manifest('audit.arithmetic', 'Arithmetic', 'Offline graph oracle',
            obj(value={'type': 'integer'}, fail={'type': 'boolean'}), obj(value={'type': 'integer'}))

    def invoke(self, request):
        self.calls.append(deepcopy(request))
        if request.payload['fail']:
            return failure(request, ErrorCode.TOOL_UNAVAILABLE, 'Synthetic branch failure')
        return result(request, {'value': request.payload['value'] + 1})


@pytest.mark.parametrize('seed', [17, 92, 731, 1203])
@pytest.mark.parametrize('with_failure', [False, True])
def test_generated_maximum_dags_match_independent_oracle(seed, with_failure):
    """32-node shuffled DAGs, varied fan-in, independent failures and ancestry."""
    rng = random.Random(seed)
    module, registry = ArithmeticModule(), CapabilityRegistry()
    registry.register(module.manifest, module)
    expected, values, steps = {}, {}, []
    failing = {5, 13, 21} if with_failure else set()
    for number in range(1, 33):
        sid = f's{number}'
        candidates = list(range(1, number))
        deps = rng.sample(candidates, min(len(candidates), rng.randint(0, 3)))
        dep_ids = [f's{x}' for x in deps]
        source = rng.choice(dep_ids) if deps else None
        raw_value = {'ref': f'{source}.data.value'} if source else {'literal': number}
        steps.append({'step_id': sid, 'capability_id': 'audit.arithmetic', 'depends_on': dep_ids,
                      'inputs': {'value': raw_value, 'fail': {'literal': number in failing}}})
        if any(expected[d] in ('failed', 'skipped') for d in dep_ids):
            expected[sid] = 'skipped'
        elif number in failing:
            expected[sid] = 'failed'
        else:
            expected[sid] = 'completed'
            values[sid] = (values[source] if source else number) + 1
    rng.shuffle(steps)
    plan = {'plan_id': 'plan-20261014-001', 'goal': 'Generated offline dependency graph', 'steps': steps}
    original = deepcopy(plan)
    report = Executor(registry).execute(plan)
    assert plan == original
    assert {sid: record.status.value for sid, record in report.steps.items()} == expected
    assert len(module.calls) == sum(status != 'skipped' for status in expected.values())
    assert len({r.request_id for r in module.calls}) == len(module.calls)
    assert report.status == ('failed' if with_failure else 'completed')
    depended_on = {dep for step in steps for dep in step['depends_on']}
    assert report.final_results == {sid: {'value': values[sid]} for sid in expected
                                   if expected[sid] == 'completed' and sid not in depended_on}
    completed = set()
    for event in report.events:
        if event.status == StepState.RUNNING:
            assert set(report.steps[event.step_id].depends_on) <= completed
        if event.status == StepState.COMPLETED:
            completed.add(event.step_id)
    assert [e.sequence for e in report.events] == list(range(1, len(report.events) + 1))


def test_step_33_rejected_before_any_adapter_call():
    module, registry = ArithmeticModule(), CapabilityRegistry()
    registry.register(module.manifest, module)
    plan = {'plan_id': 'plan-20261014-002', 'goal': 'Bounded execution', 'steps': [
        {'step_id': f's{i}', 'capability_id': 'audit.arithmetic',
         'inputs': {'value': {'literal': i}, 'fail': {'literal': False}}} for i in range(1, 34)]}
    with pytest.raises(HubError) as error:
        Executor(registry).execute(plan)
    assert error.value.code == ErrorCode.EXECUTION_LIMIT
    assert module.calls == []


@pytest.mark.parametrize('field,value', [
    ('request_id', 'req-ffffffffffff'), ('task_id', 'task-ffffffffffff'),
    ('trace_id', 'trace-ffffffffffffffff'), ('capability_id', 'other.capability')])
def test_valid_but_wrong_result_correlation_never_reaches_dependents(field, value):
    module, registry = ArithmeticModule(), CapabilityRegistry()
    normal_invoke = module.invoke
    def altered(req):
        return normal_invoke(req).model_copy(update={field: value})
    module.invoke = altered
    registry.register(module.manifest, module)
    plan = {'plan_id': 'plan-20261014-003', 'goal': 'Correlation boundary', 'steps': [
        {'step_id': 's1', 'capability_id': 'audit.arithmetic',
         'inputs': {'value': {'literal': 1}, 'fail': {'literal': False}}},
        {'step_id': 's2', 'capability_id': 'audit.arithmetic', 'depends_on': ['s1'],
         'inputs': {'value': {'ref': 's1.data.value'}, 'fail': {'literal': False}}}]}
    report = Executor(registry).execute(plan)
    assert report.steps['s1'].error.code == ErrorCode.CONTRACT_MISMATCH
    assert report.steps['s2'].status == StepState.SKIPPED
    assert len(module.calls) == 1 and report.final_results == {}


def test_registry_snapshots_original_manifest_before_later_mutation():
    module, registry = ArithmeticModule(), CapabilityRegistry()
    registry.register(module.manifest, module)
    module.manifest.input_schema['properties']['value']['type'] = 'string'
    module.manifest.name = 'changed after registration'
    registered = registry.get_manifest('audit.arithmetic')
    assert registered.input_schema['properties']['value']['type'] == 'integer'
    assert registered.name == 'Arithmetic'


@pytest.mark.parametrize('bad_data', [None, [], {'value': object()}, {'value': True}])
def test_adapter_mutated_output_is_contained_as_contract_failure(bad_data):
    module, registry = ArithmeticModule(), CapabilityRegistry()
    module.invoke = lambda req: result(req, {'value': 1}).model_copy(update={'data': bad_data})
    registry.register(module.manifest, module)
    plan = {'plan_id': 'plan-20261014-004', 'goal': 'Malformed plugin output', 'steps': [
        {'step_id': 's1', 'capability_id': 'audit.arithmetic',
         'inputs': {'value': {'literal': 1}, 'fail': {'literal': False}}}]}
    with warnings.catch_warnings(record=True):
        report = Executor(registry).execute(plan)
    assert report.status == 'failed'
    assert report.steps['s1'].error.code == ErrorCode.CONTRACT_MISMATCH


@pytest.fixture(scope='module')
def wheel_root(tmp_path_factory):
    wheel_path = os.getenv('AUDIT_WHEEL')
    if not wheel_path:
        candidates = list((Path(__file__).resolve().parents[2] / 'audit_artifacts' / 'wheels').glob('*.whl'))
        if not candidates:
            pytest.skip('Packaging probe requires AUDIT_WHEEL pointing at the built project wheel')
        wheel_path = str(candidates[0])
    root = tmp_path_factory.mktemp('wheel_isolation')
    with zipfile.ZipFile(wheel_path) as archive:
        archive.extractall(root)
    return root


def wheel_command(wheel_root, code):
    env = {k: v for k, v in os.environ.items() if not k.endswith('API_KEY')}
    env['PYTHONPATH'] = str(wheel_root)
    code = "import socket; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('offline'));" + code
    return subprocess.run([sys.executable, '-c', code], cwd=wheel_root, env=env,
                          text=True, capture_output=True, timeout=30)


def test_installed_wheel_platform_cli_lists_all_seven_capabilities(wheel_root):
    probe = wheel_command(wheel_root, "from hub_platform.cli import main; raise SystemExit(main(['--list-capabilities']))")
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert len(json.loads(probe.stdout)) == 7


@pytest.mark.parametrize('module,args', [('agents.blackboard', "['--week','2026-W41']"),
    ('agents.react_agent', "['--order-id','order-low','--mode','local']")])
def test_installed_wheel_preserves_documented_offline_sample_data(wheel_root, module, args):
    probe = wheel_command(wheel_root, f"from {module} import main; raise SystemExit(main({args}))")
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert json.loads(probe.stdout)['status'] == 'completed'
