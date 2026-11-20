import unittest

from simulation_agent.orchestrator import Agent, Session
from simulation_agent.providers import ModelProvider, ProviderConfig, ProviderError


def openai_call():
    return {'choices': [{'message': {'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function',
        'function': {'name': 'probe', 'arguments': '{}'}}]}}]}


def openai_done():
    return {'choices': [{'message': {'content': 'PROBE_OK'}}]}


class ProviderTests(unittest.TestCase):
    def test_successful_probe_and_tool_result_encoding(self):
        responses = iter([openai_call(), openai_done(), openai_done()])
        sent = []
        def transport(url, headers, body):
            sent.append((url, headers, body))
            return next(responses)
        provider = ModelProvider(ProviderConfig('openrouter', 'test', 'secret'), transport)
        provider.check_compatibility()
        self.assertEqual(sent[1][2]['messages'][-1]['tool_call_id'], 'c1')
        self.assertEqual(provider.respond(system='s', messages=[], tools=[]).text, 'PROBE_OK')
        self.assertNotIn('secret', repr(provider.config))

    def test_block_before_and_after_failed_check(self):
        provider = ModelProvider(ProviderConfig('custom', 'test', base_url='http://localhost:11434/v1'),
                                 lambda *args: openai_done())
        for action in (lambda: provider.respond(system='', messages=[], tools=[]), provider.check_compatibility,
                       lambda: provider.respond(system='', messages=[], tools=[])):
            with self.assertRaises(ProviderError):
                action()
        with self.assertRaises(ProviderError):
            Agent(provider, None).turn(Session(), 'hello')

    def test_second_stage_failure_revokes_previous_success(self):
        replies = iter([openai_call(), openai_done(), openai_call(), {'choices': [{'message': {'content': 'wrong'}}]}])
        provider = ModelProvider(ProviderConfig('openai', 'test', 'key'), lambda *args: next(replies))
        provider.check_compatibility()
        with self.assertRaises(ProviderError) as error:
            provider.check_compatibility()
        self.assertEqual(error.exception.code, 'tool_result_unsupported')
        with self.assertRaises(ProviderError):
            provider.respond(system='', messages=[], tools=[])

    def test_changed_configuration_requires_new_check(self):
        replies = iter([openai_call(), openai_done()])
        provider = ModelProvider(ProviderConfig('openai', 'first', 'key'), lambda *args: next(replies))
        provider.check_compatibility()
        provider.config = ProviderConfig('openai', 'second', 'key')
        with self.assertRaises(ProviderError) as error:
            provider.respond(system='', messages=[], tools=[])
        self.assertEqual(error.exception.code, 'compatibility_not_verified')

    def test_anthropic_round_trip(self):
        replies = iter([{'content': [{'type': 'tool_use', 'id': 't1', 'name': 'probe', 'input': {}}]},
                        {'content': [{'type': 'text', 'text': 'PROBE_OK'}]}])
        sent = []
        def transport(url, headers, body):
            sent.append(body)
            return next(replies)
        provider = ModelProvider(ProviderConfig('anthropic', 'test', 'key'), transport)
        provider.check_compatibility()
        self.assertEqual(sent[1]['messages'][-1]['content'][0]['tool_use_id'], 't1')

    def test_invalid_response_and_endpoint_fail_closed(self):
        with self.assertRaises(ValueError):
            ProviderConfig('custom', 'test', base_url='http://example.com/v1')
        with self.assertRaises(ValueError):
            ProviderConfig('custom', 'test', base_url='https://user:password@example.com')
        provider = ModelProvider(ProviderConfig('openai', 'test', 'key'), lambda *args: {})
        with self.assertRaises(ProviderError) as error:
            provider.check_compatibility()
        self.assertEqual(error.exception.code, 'invalid_response')

if __name__ == '__main__':
    unittest.main()
