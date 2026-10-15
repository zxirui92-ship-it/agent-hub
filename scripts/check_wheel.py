"""Install a built wheel in isolation and exercise offline runtime entry points.

Usage: python scripts/check_wheel.py dist/agent_hub_foundation-*.whl
Uses the current interpreter's dependencies, but neither the source tree nor
its tests, data directory, or credentials. No index or API calls are allowed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve(strict=True)
    aliases = {key for key in os.environ if key.endswith('_ENV') and
               key.startswith(('LLM_', 'DEEPSEEK_', 'BAILIAN_', 'M4_', 'HUB_PLANNER_'))}
    credential_sources = {os.environ[key].strip() for key in aliases if key.endswith('API_KEY_ENV')}
    env = {key: value for key, value in os.environ.items()
           if not key.endswith('API_KEY') and key not in aliases | credential_sources}
    with tempfile.TemporaryDirectory(prefix='agent-hub-wheel-') as temp:
        root = Path(temp)
        target = root / 'installed'
        install = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
             '--target', str(target), str(wheel)], cwd=root, env=env,
            capture_output=True, text=True, timeout=120)
        if install.returncode:
            raise RuntimeError(install.stdout + install.stderr)
        env['PYTHONPATH'] = str(target)
        checks = [
            ('hub_platform.cli', ['--list-capabilities'], 0, None),
            ('hub_platform.cli', ['--list-capabilities', '--real-m1', '--real-m2',
                                  '--real-m3', '--real-m4', '--real-m5', '--real-m6', '--real-m7'], 0, None),
            ('agents.react_agent', ['--order-id', 'order-low', '--mode', 'local'], 0, 'completed'),
            ('agents.blackboard', ['--week', '2026-W41'], 0, 'completed'),
            ('agents.plan_execute', ['--week', '2026-W41', '--mode', 'local'], 0, 'completed'),
            ('agents.workflow.refund_graph', ['--order-id', 'order-low', '--refund-amount', '19900'], 0, 'completed'),
            ('agents.workflow.refund_graph', ['--order-id', '2025101234', '--refund-amount', '69900'], 0, 'waiting_approval'),
        ]
        for module, arguments, expected_exit, expected_status in checks:
            code = (
                "import socket; "
                "socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('offline')); "
                "import importlib; from pathlib import Path; "
                f"module=importlib.import_module({module!r}); "
                f"assert Path(module.__file__).resolve().is_relative_to(Path({str(target)!r})); "
                f"raise SystemExit(module.main({arguments!r}))"
            )
            run = subprocess.run([sys.executable, '-c', code], cwd=root, env=env,
                                 capture_output=True, text=True, timeout=60)
            if run.returncode != expected_exit:
                raise AssertionError(f'{module} {arguments}: {run.stdout}\n{run.stderr}')
            data = json.loads(run.stdout)
            if expected_status is None:
                assert len(data) == 7, data
            else:
                assert data['status'] == expected_status, data
            print(f'PASS {module} {arguments}')
    print('Installed wheel: all offline smoke checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
