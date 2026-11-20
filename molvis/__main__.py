"""Run with python3 -m molvis. Bound to loopback only."""
import argparse
import json
import os
import re
import signal
import csv
import io
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .planning import create_plan
from .preparation import prepare, output_root
from .compatibility import check_compatibility
from .environment_storage import DOWNLOADS, environment_root
from .live_runs import start_run, resume_run, read_run, cancel_run, shutdown
from simulation_agent.chat import ChatController
from simulation_agent.providers import ProviderConfig, ProviderError
from simulation_agent.tools import WorkspaceContext

WEB = Path(__file__).resolve().parent.parent / 'web'
AGENT_SESSIONS = ChatController()
EXAMPLE_SETTINGS = dict(solvent_model='obc2', salt_molar=0.2, temperature_k=300,
                        timestep_fs=2, dynamics_steps=100)


def example_input():
    directory = os.environ.get('MOLVIS_EXAMPLE_DIR')
    if not directory:
        raise ValueError('The ubiquitin example is not configured. Start the server with --example-dir pointing to the prepared files; see the README guided example setup.')
    folder = Path(directory).expanduser()
    parameters = folder / 'par_all36m_prot.prm'
    try:
        def read_file(path):
            with path.open('rb') as file:
                content = file.read(5_000_001)
            if len(content) > 5_000_000:
                raise ValueError('A configured ubiquitin example file exceeds 5 MB.')
            return content.decode('utf-8')

        return dict(pdb=read_file(folder / 'prepared.pdb'), psf=read_file(folder / 'prepared.psf'),
                    parameters=[dict(name=parameters.name, text=read_file(parameters))],
                    settings=EXAMPLE_SETTINGS)
    except (OSError, UnicodeError) as exc:
        raise ValueError('The example folder must contain readable prepared.pdb, prepared.psf, and par_all36m_prot.prm files. See the README guided example setup.') from exc


class Handler(BaseHTTPRequestHandler):
    def error_reply(self, status, code, message):
        """Return a machine-readable error while preserving the UI's error field."""
        self.reply(status, json.dumps({'error': message, 'code': code}).encode(), 'application/json')

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
        if self.path == '/api/example':
            try:
                pair = example_input()
                result = dict(pdb=pair['pdb'], psf=pair['psf'], settings=pair['settings'])
                self.reply(200, json.dumps(result).encode(), 'application/json')
            except ValueError as exc:
                self.error_reply(404, 'example_unavailable', str(exc))
            return
        live=re.fullmatch(r'/api/runs/([0-9a-f-]{36})(/measurements\.(?:jsonl|csv))?',self.path)
        if live:
            try: record=read_run(live[1])
            except (ValueError,FileNotFoundError):
                self.error_reply(404, 'run_not_found', 'Run not found.'); return
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
        download = re.fullmatch(r'/api/preparations/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/files/(prepared\.pdb|prepared\.psf|protein\.pdb|manifest\.json|preparation\.zip)', self.path)
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
        agent_route = self.path in ('/api/agent/start', '/api/agent/turn', '/api/agent/close')
        cancel=re.fullmatch(r'/api/runs/([0-9a-f-]{36})/cancel',self.path)
        resume=re.fullmatch(r'/api/runs/([0-9a-f-]{36})/resume',self.path)
        if self.path not in ('/api/plan', '/api/prepare', '/api/compatibility','/api/readiness','/api/runs','/api/example/run') and not (cancel or resume or agent_route):
            self.error_reply(404, 'route_not_found', 'Not found.')
            return
        # Reject cross-site browser requests to this local service.
        origin = self.headers.get('Origin')
        if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
            self.error_reply(403, 'origin_rejected', 'Origin rejected.')
            return
        if agent_route and (origin != f'http://127.0.0.1:{self.server.server_port}' or
                            self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json'):
            self.error_reply(403, 'origin_rejected', 'Agent requests require the local workspace origin and JSON content.')
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 30_000_000:
                raise ValueError('Request must be between 1 byte and 30 MB.')
        except ValueError as exc:
            self.error_reply(400, 'invalid_request_size', str(exc))
            return
        try:
            # Python's JSON decoder accepts NaN and Infinity by default, although
            # those tokens are not JSON and cannot be safely persisted.
            def reject_constant(value):
                raise ValueError(f'Non-finite JSON value {value} is not allowed.')
            def finite_float(value):
                result = float(value)
                if not math.isfinite(result):
                    raise ValueError('JSON numbers must be finite.')
                return result
            payload = json.loads(self.rfile.read(size), parse_constant=reject_constant,
                                 parse_float=finite_float)
        except (ValueError, UnicodeError) as exc:
            self.error_reply(400, 'invalid_json', str(exc))
            return
        try:
            if not isinstance(payload, dict):
                raise ValueError('Request must be an object.')
            if self.path=='/api/readiness': payload['test_dynamics']=True
            else: payload.pop('test_dynamics',None)
            actions = {'/api/prepare':prepare, '/api/plan':create_plan, '/api/compatibility':check_compatibility,'/api/readiness':check_compatibility,'/api/runs':start_run}
            if resume:
                result = resume_run(resume[1], payload)
            elif cancel:
                result = cancel_run(cancel[1])
            elif self.path == '/api/example/run':
                result = start_run(example_input())
            elif self.path == '/api/agent/start':
                if set(payload) - {'provider', 'model', 'base_url', 'pdb', 'psf'}:
                    raise ValueError('Unsupported agent configuration field.')
                kind = payload.get('provider')
                env_names = {'openai': 'OPENAI_API_KEY', 'openrouter': 'OPENROUTER_API_KEY',
                             'anthropic': 'ANTHROPIC_API_KEY', 'custom': 'SIMULATION_AGENT_API_KEY'}
                if kind not in env_names:
                    raise ValueError('Choose a supported provider.')
                config = ProviderConfig(kind, payload.get('model', ''), os.environ.get(env_names[kind], ''), payload.get('base_url', ''))
                token = AGENT_SESSIONS.start(config, WorkspaceContext(payload.get('pdb', ''), payload.get('psf')))
                result = {'session': token, 'status': 'ready'}
            elif self.path == '/api/agent/turn':
                result = AGENT_SESSIONS.turn(payload.get('session'), payload.get('message'))
            elif self.path == '/api/agent/close':
                AGENT_SESSIONS.close(payload.get('session'))
                result = {'status': 'closed'}
            else:
                result = actions[self.path](payload)
            self.reply(202 if resume or self.path in ('/api/runs','/api/example/run') else 200, json.dumps(result, allow_nan=False).encode(), 'application/json')
        except (ValueError, TypeError, UnicodeError) as exc:
            self.error_reply(400, 'invalid_request', str(exc))
        except ProviderError as exc:
            self.error_reply(400, exc.code, str(exc))


def main():
    def stop(signum,frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--psfgen', help='Path to a standalone psfgen 2.x executable; overrides MOLVIS_PSFGEN.')
    parser.add_argument('--example-dir', help='Folder with the prepared ubiquitin pair and local CHARMM36m parameters.')
    parser.add_argument('--check-setup', action='store_true', help='Check local preparation, OpenMM and example configuration without starting the server.')
    args = parser.parse_args()
    if args.psfgen:
        os.environ['MOLVIS_PSFGEN'] = args.psfgen
    if args.example_dir:
        os.environ['MOLVIS_EXAMPLE_DIR'] = args.example_dir
    if args.check_setup:
        from .setup_check import setup_report
        for name, status, message in setup_report(example_input):
            print(f'{name}: {status} — {message}')
        return
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
