import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def cli(*args):
    return subprocess.run([sys.executable, "-m", "hub_platform", *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", check=False)


@pytest.mark.parametrize("fixture,exit_code,status", [
    ("operations", 0, "completed"), ("refund_waiting", 3, "waiting_approval"),
    ("failure", 1, "failed"), ("invalid_plan", 2, None),
])
def test_cli_scenarios(fixture, exit_code, status):
    run = cli(str(ROOT / "tests" / "fixtures" / f"{fixture}.json"), "--json")
    assert run.returncode == exit_code, run.stderr
    data = json.loads(run.stdout)
    assert data["trace_id"] and data["task_id"]
    if status:
        assert data["status"] == status
    else:
        assert data["code"] == "UNKNOWN_CAPABILITY"


def test_cli_human_report_and_capabilities():
    run = cli("tests/fixtures/refund_waiting.json")
    assert run.returncode == 3
    assert all(value in run.stdout for value in ["计划 ID", "依赖", "状态", "输入", "输出", "原因", "执行轨迹", "最终结果"])
    run = cli("--list-capabilities")
    assert run.returncode == 0 and len(json.loads(run.stdout)) == 7


def test_cli_bad_file_and_limits(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{bad json", encoding="utf-8")
    for source in (str(path), str(tmp_path / "missing.json")):
        run = cli(source, "--json")
        assert run.returncode == 2 and json.loads(run.stdout)["code"] == "INVALID_PLAN_FILE"
    run = cli("tests/fixtures/operations.json", "--max-steps", "2", "--json")
    assert run.returncode == 2 and json.loads(run.stdout)["code"] == "EXECUTION_LIMIT"


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity', '1e9999'])
def test_cli_rejects_non_json_numeric_values_before_execution(tmp_path, constant):
    path = tmp_path / 'nonfinite.json'
    path.write_text('{"unexpected": ' + constant + '}', encoding='utf-8')
    run = cli(str(path), '--json')
    assert run.returncode == 2
    assert json.loads(run.stdout)['code'] == 'INVALID_PLAN_FILE'
