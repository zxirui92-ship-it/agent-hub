"""Run M4 independently: python -m agents.router 'your request'."""
import argparse
from dataclasses import asdict
import json
import logging
import os
import sys
from uuid import uuid4

from agents.router.factory import create_agent
from agents.router.routing import RouteDecision
from common.contracts import AgentRequest
from common.errors import ErrorCode, ServiceError


def main(argv=None):
    parser = argparse.ArgumentParser(description='M4 Router + Skill (M4_MODE=mock for explicit offline tests)')
    parser.add_argument('query', nargs='?')
    parser.add_argument('--list-skills', action='store_true')
    parser.add_argument('--skill', help='Explicit Skill selection for independent testing; bypasses semantic routing')
    args = parser.parse_args(argv)
    try:
        agent = create_agent()
        logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO').upper(), format='%(message)s')
        if args.list_skills:
            print(json.dumps([asdict(s) for s in agent.skills.list_skills()], ensure_ascii=False, indent=2))
            return 0
        if not args.query:
            parser.error('query is required')
        if args.skill:
            class SelectedRouter:
                def select(self, query, skills):
                    return RouteDecision(args.skill, 'Explicit CLI selection; semantic routing bypassed')
            agent.router = SelectedRouter()
        request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
            trace_id=f'trace-{uuid4().hex[:16]}', capability_id=agent.manifest.capability_id, payload={'query': args.query})
        response = agent.invoke(request)
        print(response.model_dump_json(indent=2))
        return 0 if response.status == 'completed' else 1
    except (ValueError, ServiceError) as exc:
        code = exc.code if isinstance(exc, ServiceError) else ErrorCode.INVALID_INPUT
        print(json.dumps({'status': 'failed', 'error': {'code': code.value, 'message': str(exc),
            'retryable': exc.retryable if isinstance(exc, ServiceError) else False}}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
