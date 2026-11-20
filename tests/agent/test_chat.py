import unittest
from simulation_agent.chat import ChatController
from simulation_agent.orchestrator import ModelResponse, ToolCall
from simulation_agent.providers import ProviderConfig, ProviderError
from simulation_agent.tools import WorkspaceContext

PDB = f'ATOM  {1:5d}  CA  ALA A{1:4d}    {1.:8.3f}{2.:8.3f}{3.:8.3f}  1.00 20.00           C  '

class Provider:
    def __init__(self, config): self.n = 0
    def check_compatibility(self): pass
    def respond(self, **kwargs):
        self.n += 1
        if self.n == 1: return ModelResponse(calls=(ToolCall('1', 'inspect_structure', {}),))
        return ModelResponse(text='Structure inspected; this does not establish scientific validity.')

class ChatTests(unittest.TestCase):
    def setUp(self):
        self.config = ProviderConfig('custom', 'model', base_url='http://localhost:11434/v1')
        self.controller = ChatController(provider_factory=Provider)

    def test_session_returns_evidence_and_close_revokes_access(self):
        token = self.controller.start(self.config, WorkspaceContext(PDB))
        result = self.controller.turn(token, 'inspect')
        self.assertEqual(result['status'], 'complete')
        self.assertIn('atom_count', result['observations'][0]['content'])
        self.assertNotIn(PDB, str(result))
        self.controller.close(token)
        with self.assertRaises(ValueError): self.controller.turn(token, 'again')

    def test_failed_probe_does_not_create_session(self):
        class Bad(Provider):
            def check_compatibility(self): raise ProviderError('tool_use_unsupported', 'Unsupported.')
        controller = ChatController(provider_factory=Bad)
        with self.assertRaises(ProviderError): controller.start(self.config, WorkspaceContext(PDB))
        self.assertEqual(controller._sessions, {})

    def test_failed_turn_rolls_back_partial_messages(self):
        class BadTurn(Provider):
            def respond(self, **kwargs): raise ProviderError('connection_failed', 'Offline.')
        controller = ChatController(provider_factory=BadTurn)
        token = controller.start(self.config, WorkspaceContext(PDB))
        with self.assertRaises(ProviderError): controller.turn(token, 'inspect')
        self.assertEqual(controller._sessions[token].history.messages, [])

if __name__ == '__main__': unittest.main()
