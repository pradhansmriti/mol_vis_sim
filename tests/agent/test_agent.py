import io
import json
import unittest
from unittest.mock import patch
from molvis.planning import create_plan
from simulation_agent.orchestrator import Agent, ModelResponse, Session, ToolCall
from simulation_agent.tools import PlanningTools, WorkspaceClient, WorkspaceContext, WorkspaceError

PDB = f'ATOM  {1:5d}  CA  ALA A{1:4d}    {1.:8.3f}{2.:8.3f}{3.:8.3f}  1.00 20.00           C  '

class FakeProvider:
    def __init__(self, responses): self.responses, self.seen = iter(responses), []
    def respond(self, **kwargs):
        self.seen.append(kwargs)
        return next(self.responses)

class LocalPlanningClient:
    def plan(self, context, settings):
        return create_plan({'pdb': context.pdb, 'settings': settings, 'check_compatibility': False})

class AgentTests(unittest.TestCase):
    def setUp(self): self.tools = PlanningTools(LocalPlanningClient(), WorkspaceContext(PDB))

    def test_plan_loop_exposes_evidence_and_no_atom_payload(self):
        provider = FakeProvider([ModelResponse(calls=(ToolCall('1', 'propose_workflow', {'settings': {'temperature_k': 310, 'solvent_model': 'charmm_tip3p'}}),)), ModelResponse(text='Plan proposed; compatibility remains unchecked.')])
        session = Session()
        result = Agent(provider, self.tools).turn(session, 'Plan at 310 K in water')
        observation = json.loads(session.messages[2]['content'])
        self.assertEqual(result.status, 'complete')
        self.assertEqual(observation['data']['settings']['temperature_k'], 310)
        self.assertEqual(observation['data']['compatibility']['status'], 'not_checked')
        self.assertFalse(observation['data']['settings']['add_ions'])
        self.assertNotIn('atoms', observation['data']['structure'])
        self.assertEqual(provider.seen[1]['messages'][2]['role'], 'tool')

    def test_rejects_unapproved_tools_and_arguments_without_client(self):
        class NoCalls:
            def plan(self, *args): raise AssertionError('client called')
        tools = PlanningTools(NoCalls(), WorkspaceContext(PDB))
        for name, arguments in [('run_shell', {}), ('inspect_structure', {'pdb': 'x'}),
                                ('propose_workflow', {'settings': {'add_ions': True}}),
                                ('propose_workflow', {'settings': {'temperature_k': float('nan')}})]:
            with self.subTest(name=name, arguments=arguments):
                self.assertEqual(tools.call(name, arguments).status, 'error')

    def test_call_limit_prevents_extra_calls(self):
        class CountTools:
            def __init__(self): self.count = 0
            def call(self, *args):
                from simulation_agent.tools import ToolResult
                self.count += 1
                return ToolResult('ok', {})
        tools = CountTools()
        provider = FakeProvider([ModelResponse(calls=(ToolCall('1', 'inspect_structure', {}),)),
                                 ModelResponse(calls=(ToolCall('2', 'inspect_structure', {}),))])
        result = Agent(provider, tools, max_tool_calls=1).turn(Session(), 'inspect')
        self.assertEqual((result.status, tools.count), ('limit_reached', 1))

    def test_workspace_adapter_fixed_request_and_real_plan_contract(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def fake_open(request, timeout):
            self.assertEqual(request.full_url, 'http://127.0.0.1:8765/api/plan')
            payload = json.loads(request.data)
            self.assertFalse(payload['check_compatibility'])
            return Response(json.dumps(create_plan(payload)).encode())
        with patch('simulation_agent.tools.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = fake_open
            result = PlanningTools(WorkspaceClient(), WorkspaceContext(PDB)).call('inspect_structure', {})
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.data['structure']['atom_count'], 1)

    def test_unavailable_workspace_is_structured(self):
        from urllib.error import URLError
        with patch('simulation_agent.tools.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = URLError('offline')
            result = PlanningTools(WorkspaceClient(), WorkspaceContext(PDB)).call('inspect_structure', {})
        self.assertEqual(result.data['code'], 'workspace_unavailable')

    def test_workspace_error_code_reaches_agent(self):
        from urllib.error import HTTPError
        error = HTTPError('http://127.0.0.1:8765/api/plan', 400, 'Bad Request', {},
                          io.BytesIO(b'{"code":"invalid_request","error":"Invalid settings."}'))
        with patch('simulation_agent.tools.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = error
            result = PlanningTools(WorkspaceClient(), WorkspaceContext(PDB)).call('inspect_structure', {})
        self.assertEqual(result.data['code'], 'invalid_request')
        self.assertEqual(result.data['message'], 'Invalid settings.')

if __name__ == '__main__': unittest.main()
