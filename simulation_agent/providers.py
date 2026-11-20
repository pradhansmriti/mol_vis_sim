"""Provider adapters and a mandatory, per-configuration tool-use probe."""
from dataclasses import dataclass, field
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .orchestrator import ModelResponse, ToolCall


class ProviderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url, headers, payload):
    request = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode(),
                                     headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ProviderError('authentication_failed', 'Provider rejected the credentials or access to the model.') from exc
        if exc.code == 429:
            raise ProviderError('rate_limited', 'Provider rate limit or quota reached. Try again later.') from exc
        raise ProviderError('provider_rejected', f'Provider rejected the request (HTTP {exc.code}). Check the endpoint, model, and tool support.') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError('connection_failed', 'Could not reach the configured provider endpoint.') from exc
    except (ValueError, UnicodeError) as exc:
        raise ProviderError('invalid_response', 'Provider returned invalid JSON.') from exc


@dataclass(frozen=True)
class ProviderConfig:
    kind: str
    model: str
    api_key: str = field(default='', repr=False)
    base_url: str = ''

    def __post_init__(self):
        if self.kind not in ('openai', 'openrouter', 'anthropic', 'custom'):
            raise ValueError('Unknown provider.')
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('A model name is required.')
        if self.kind != 'custom' and not self.api_key:
            raise ValueError('An API key is required for this provider.')
        url = self.endpoint
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment):
            raise ValueError('Provide a valid endpoint URL without credentials, query or fragment.')
        if parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote endpoints must use HTTPS.')
        if self.kind != 'custom' and self.base_url:
            raise ValueError('Custom endpoint URLs are supported only with the custom provider.')

    @property
    def endpoint(self):
        return {'openai': 'https://api.openai.com/v1', 'openrouter': 'https://openrouter.ai/api/v1',
                'anthropic': 'https://api.anthropic.com/v1', 'custom': self.base_url}.get(self.kind, '')


class ModelProvider:
    def __init__(self, config, transport=post_json):
        self.config, self.transport = config, transport
        self._verified_config = None

    def check_compatibility(self):
        """Probe a tool call AND tool-result follow-up; does not touch workspace data."""
        self._verified_config = None
        tool = {'name': 'probe', 'description': 'Return a test value.', 'input_schema': {
            'type': 'object', 'properties': {}, 'additionalProperties': False}}
        try:
            first = self._respond(system='Call the probe tool, then report its result.',
                                  messages=[{'role': 'user', 'content': 'Call probe.'}], tools=[tool])
            if len(first.calls) != 1 or first.calls[0].name != 'probe' or first.calls[0].arguments != {}:
                raise ProviderError('tool_use_unsupported', 'Model did not produce the required valid tool call.')
            call = first.calls[0]
            history = [{'role': 'user', 'content': 'Call probe.'},
                       {'role': 'assistant', 'content': first.text, 'tool_calls': [
                           {'id': call.id, 'name': call.name, 'arguments': call.arguments}]},
                       {'role': 'tool', 'tool_call_id': call.id, 'name': 'probe', 'content': 'PROBE_OK'}]
            second = self._respond(system='Call the probe tool, then report its result.', messages=history, tools=[tool])
            if second.calls or 'PROBE_OK' not in second.text:
                raise ProviderError('tool_result_unsupported', 'Model did not return the test tool result correctly.')
        except ProviderError:
            raise
        self._verified_config = self.config

    def respond(self, *, system, messages, tools):
        if self._verified_config is None or self._verified_config != self.config:
            raise ProviderError('compatibility_not_verified', 'Check model compatibility successfully before planning.')
        return self._respond(system=system, messages=messages, tools=tools)

    def _respond(self, *, system, messages, tools):
        try:
            if self.config.kind == 'anthropic':
                return self._anthropic(system, messages, tools)
            return self._openai(system, messages, tools)
        except (KeyError, TypeError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError('invalid_response', 'Provider returned an unsupported or malformed model response.') from exc

    def _openai(self, system, messages, tools):
        wire = [{'role': 'system', 'content': system}]
        for msg in messages:
            entry = {'role': msg['role'], 'content': msg['content']}
            if msg['role'] == 'assistant' and msg.get('tool_calls'):
                entry['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                    'name': c['name'], 'arguments': json.dumps(c['arguments'])}} for c in msg['tool_calls']]
            if msg['role'] == 'tool':
                entry['tool_call_id'] = msg['tool_call_id']
            wire.append(entry)
        payload = {'model': self.config.model, 'messages': wire, 'tools': [
            {'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                               'parameters': t['input_schema']}} for t in tools]}
        headers = {'Authorization': f'Bearer {self.config.api_key}'} if self.config.api_key else {}
        data = self.transport(self.config.endpoint.rstrip('/') + '/chat/completions', headers, payload)
        msg = data['choices'][0]['message']
        calls = tuple(ToolCall(c['id'], c['function']['name'], json.loads(c['function']['arguments']))
                      for c in (msg.get('tool_calls') or []))
        if any(not c.id or not isinstance(c.arguments, dict) for c in calls):
            raise ValueError('Invalid tool call')
        text = msg.get('content') or ''
        if not isinstance(text, str):
            raise ValueError('Invalid content')
        return ModelResponse(text, calls)

    def _anthropic(self, system, messages, tools):
        wire = []
        for msg in messages:
            if msg['role'] == 'assistant':
                content = ([{'type': 'text', 'text': msg['content']}] if msg['content'] else [])
                content += [{'type': 'tool_use', 'id': c['id'], 'name': c['name'], 'input': c['arguments']}
                            for c in msg.get('tool_calls', [])]
                wire.append({'role': 'assistant', 'content': content})
            elif msg['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': msg['tool_call_id'], 'content': msg['content']}
                if wire and wire[-1]['role'] == 'user' and isinstance(wire[-1]['content'], list):
                    wire[-1]['content'].append(block)
                else:
                    wire.append({'role': 'user', 'content': [block]})
            else:
                wire.append({'role': 'user', 'content': msg['content']})
        data = self.transport(self.config.endpoint + '/messages', {'x-api-key': self.config.api_key,
                              'anthropic-version': '2023-06-01'}, {'model': self.config.model,
                              'max_tokens': 1024, 'system': system, 'messages': wire, 'tools': tools})
        blocks = data['content']
        text = ''.join(b['text'] for b in blocks if b['type'] == 'text')
        calls = tuple(ToolCall(b['id'], b['name'], b['input']) for b in blocks if b['type'] == 'tool_use')
        if any(not c.id or not isinstance(c.arguments, dict) for c in calls):
            raise ValueError('Invalid tool call')
        return ModelResponse(text, calls)
