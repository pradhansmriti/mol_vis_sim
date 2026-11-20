"""Exercise HTTP handler error contracts without binding a local socket."""
import io
import json
import unittest
from types import SimpleNamespace

from molvis.__main__ import Handler


class ErrorContractTests(unittest.TestCase):
    def request(self, method, path, body=b'', headers=None):
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {'Content-Length': str(len(body)), **(headers or {})}
        handler.server = SimpleNamespace(server_port=8765)
        handler.rfile = io.BytesIO(body)
        replies = []
        handler.reply = lambda status, content, mime, filename=None: replies.append((status, json.loads(content), mime))
        getattr(handler, 'do_' + method)()
        self.assertEqual(len(replies), 1)
        return replies[0]

    def test_strict_json(self):
        for body in (b'{', b'{"x": NaN}', b'{"x": Infinity}', b'{"x": 1e999}', b'\xff'):
            with self.subTest(body=body):
                status, result, mime = self.request('POST', '/api/plan', body)
                self.assertEqual((status, result['code'], mime), (400, 'invalid_json', 'application/json'))
                self.assertTrue(result['error'])

    def test_request_errors_are_structured(self):
        for body, headers, code, status in (
            (b'', {}, 'invalid_request_size', 400),
            (b'[]', {}, 'invalid_request', 400),
            (b'{}', {'Origin': 'https://example.com'}, 'origin_rejected', 403),
        ):
            with self.subTest(code=code):
                actual, result, _ = self.request('POST', '/api/plan', body, headers)
                self.assertEqual((actual, result['code']), (status, code))
                self.assertTrue(result['error'])

    def test_missing_run_is_structured(self):
        status, result, _ = self.request('GET', '/api/runs/00000000-0000-0000-0000-000000000000')
        self.assertEqual((status, result['code']), (404, 'run_not_found'))
        self.assertTrue(result['error'])


if __name__ == '__main__':
    unittest.main()
