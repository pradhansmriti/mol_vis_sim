"""Test agent HTTP contracts without a listening socket or model provider."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from molvis.__main__ import Handler
from simulation_agent.providers import ProviderError

class AgentApiTests(unittest.TestCase):
    def request(self, path, payload, headers=None):
        body = json.dumps(payload).encode()
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/json',
                           'Origin': 'http://127.0.0.1:8765', **(headers or {})}
        handler.server = SimpleNamespace(server_port=8765)
        handler.rfile = io.BytesIO(body)
        responses = []
        handler.reply = lambda status, data, mime, filename=None: responses.append((status, json.loads(data)))
        handler.do_POST()
        return responses[0]

    def test_start_passes_environment_key_and_returns_session(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'private-key'}), patch('molvis.__main__.AGENT_SESSIONS') as sessions:
            sessions.start.return_value = 'session-token'
            status, result = self.request('/api/agent/start', {'provider':'openai', 'model':'example', 'pdb':'pdb'})
            self.assertEqual((status, result['status']), (200, 'ready'))
            config, context = sessions.start.call_args.args
            self.assertEqual(config.api_key, 'private-key')
            self.assertNotIn('private-key', str(result))
            self.assertEqual(context.pdb, 'pdb')

    def test_failed_probe_reports_error_and_no_session(self):
        with patch('molvis.__main__.AGENT_SESSIONS') as sessions:
            sessions.start.side_effect = ProviderError('tool_use_unsupported', 'Tool use unsupported.')
            status, result = self.request('/api/agent/start', {'provider':'custom', 'model':'example',
                'base_url':'http://localhost:1234/v1', 'pdb':'pdb'})
            self.assertEqual((status, result['code']), (400, 'tool_use_unsupported'))
            self.assertNotIn('session', result)

    def test_agent_requires_local_origin_and_json(self):
        for headers in ({'Origin':'https://example.com'}, {'Origin':''}, {'Content-Type':'text/plain'}):
            with self.subTest(headers=headers):
                status, result = self.request('/api/agent/turn', {}, headers)
                self.assertEqual((status, result['code']), (403, 'origin_rejected'))

    def test_credentials_rejected_in_request(self):
        status, result = self.request('/api/agent/start', {'api_key':'secret'})
        self.assertEqual((status, result['code']), (400, 'invalid_request'))
        self.assertNotIn('secret', str(result))

if __name__ == '__main__': unittest.main()
