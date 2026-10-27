"""Run with python3 -m molvis. Bound to loopback only."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .planning import create_plan
from .preparation import prepare

WEB = Path(__file__).resolve().parent.parent / 'web'


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, content, mime):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        entry = files.get(self.path)
        if not entry:
            self.reply(404, b'Not found', 'text/plain')
            return
        self.reply(200, (WEB / entry[0]).read_bytes(), entry[1])

    def do_POST(self):
        if self.path not in ('/api/plan', '/api/prepare'):
            self.reply(404, b'Not found', 'text/plain')
            return
        # Reject cross-site browser requests to this local service.
        origin = self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self.reply(403, b'Origin rejected', 'text/plain')
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 30_000_000:
                raise ValueError('Request must be between 1 byte and 30 MB.')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('Request must be an object.')
            result = prepare(payload) if self.path == '/api/prepare' else create_plan(payload)
            self.reply(200, json.dumps(result, allow_nan=False).encode(), 'application/json')
        except (ValueError, TypeError, UnicodeError) as exc:
            self.reply(400, json.dumps({'error': str(exc)}).encode(), 'application/json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Workspace: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
