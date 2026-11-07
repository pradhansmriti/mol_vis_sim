"""Run with python3 -m molvis. Bound to loopback only."""
import argparse
import json
import os
import re
import signal
import csv
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .planning import create_plan
from .preparation import prepare, output_root
from .compatibility import check_compatibility
from .environment_storage import DOWNLOADS, environment_root
from .live_runs import start_run, read_run, cancel_run, shutdown

WEB = Path(__file__).resolve().parent.parent / 'web'


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, content, mime, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        live=re.fullmatch(r'/api/runs/([0-9a-f-]{36})(/measurements\.(?:jsonl|csv))?',self.path)
        if live:
            try: record=read_run(live[1])
            except (ValueError,FileNotFoundError):
                self.reply(404,b'Run not found','text/plain'); return
            if live[2] and live[2].endswith('.csv'):
                from .telemetry import FIELDS
                output=io.StringIO(); writer=csv.DictWriter(output,fieldnames=FIELDS);writer.writeheader();writer.writerows(record['samples'])
                self.reply(200,output.getvalue().encode(),'text/csv; charset=utf-8','measurements.csv')
            elif live[2]:
                content=''.join(json.dumps(row,allow_nan=False)+'\n' for row in record['samples']).encode()
                self.reply(200,content,'application/x-ndjson','measurements.jsonl')
            else: self.reply(200,json.dumps(record,allow_nan=False).encode(),'application/json')
            return
        artifact=re.fullmatch(r'/api/runs/([0-9a-f-]{36})/files/([A-Za-z0-9_.-]+)',self.path)
        if artifact:
            from .live_runs import ARTIFACTS, run_root
            identifier,name=artifact.groups()
            if name not in ARTIFACTS:
                self.reply(404,b'Not found','text/plain'); return
            try:
                read_run(identifier)
                content=(run_root()/identifier/'worker'/name).read_bytes()
            except (ValueError,FileNotFoundError):
                self.reply(404,b'Run artifact not available','text/plain'); return
            self.reply(200,content,'application/octet-stream' if name.endswith('.chk') else 'text/plain; charset=utf-8',name); return
        environment = re.fullmatch(r'/api/environments/([0-9a-f-]{36})/files/([A-Za-z0-9_.-]+)',self.path)
        if environment:
            identifier,filename=environment.groups()
            if filename not in DOWNLOADS:
                self.reply(404,b'Not found','text/plain'); return
            try:
                content=(environment_root()/identifier/filename).read_bytes()
            except OSError:
                self.reply(404,b'Environment file not found','text/plain'); return
            mime='application/zip' if filename.endswith('.zip') else 'application/json' if filename.endswith('.json') else 'text/plain; charset=utf-8'
            self.reply(200,content,mime,filename=filename); return
        download = re.fullmatch(r'/api/preparations/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/files/(prepared\.pdb|prepared\.psf|manifest\.json|preparation\.zip)', self.path)
        if download:
            preparation_id, filename = download.groups()
            try:
                content = (output_root() / preparation_id / filename).read_bytes()
            except OSError:
                self.reply(404, b'Preparation file not found', 'text/plain')
                return
            mime = {'preparation.zip': 'application/zip', 'manifest.json': 'application/json'}.get(filename, 'text/plain; charset=utf-8')
            self.reply(200, content, mime, filename=filename)
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        entry = files.get(self.path.split('?',1)[0])
        if not entry:
            self.reply(404, b'Not found', 'text/plain')
            return
        self.reply(200, (WEB / entry[0]).read_bytes(), entry[1])

    def do_POST(self):
        cancel=re.fullmatch(r'/api/runs/([0-9a-f-]{36})/cancel',self.path)
        if self.path not in ('/api/plan', '/api/prepare', '/api/compatibility','/api/readiness','/api/runs') and not cancel:
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
            if self.path=='/api/readiness': payload['test_dynamics']=True
            else: payload.pop('test_dynamics',None)
            actions = {'/api/prepare':prepare, '/api/plan':create_plan, '/api/compatibility':check_compatibility,'/api/readiness':check_compatibility,'/api/runs':start_run}
            result = cancel_run(cancel[1]) if cancel else actions[self.path](payload)
            self.reply(202 if self.path=='/api/runs' else 200, json.dumps(result, allow_nan=False).encode(), 'application/json')
        except (ValueError, TypeError, UnicodeError) as exc:
            self.reply(400, json.dumps({'error': str(exc)}).encode(), 'application/json')


def main():
    def stop(signum,frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--psfgen', help='Path to a standalone psfgen 2.x executable; overrides MOLVIS_PSFGEN.')
    args = parser.parse_args()
    if args.psfgen:
        os.environ['MOLVIS_PSFGEN'] = args.psfgen
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Workspace: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
