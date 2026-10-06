"""Loopback web UI. All media work is delegated to bounded background workers."""
import json
import secrets
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Project, create_project
from . import repair, media


class Application:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.projects = {}
        self.active = None
        self.thread = None
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.worker_error = None
        self.worker_mode = None

    def libraries(self):
        items = []
        for p in self.root.iterdir():
            if not p.is_dir() or p.is_symlink():
                continue
            try:
                uuid.UUID(p.name)
                data = json.loads((p / 'project.json').read_text())
                items.append({'id': p.name, 'name': data['name'], 'created': data['created']})
            except (ValueError, OSError, KeyError):
                continue
        return sorted(items, key=lambda d: d['created'], reverse=True)

    def open(self, ident):
        try:
            ident = str(uuid.UUID(ident))
        except (ValueError, AttributeError):
            raise ValueError('Invalid library ID')
        if not (self.root / ident / 'project.json').is_file():
            raise ValueError('Library not found')
        self.stop()
        if ident not in self.projects:
            self.projects[ident] = Project(self.root / ident)
        self.active = self.projects[ident]
        self.active.refresh_environment()
        return self.state()

    def stop(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise ValueError('Checkpoint still saving; wait before switching or closing')
        self.thread = None
        self.worker_mode = None

    def start(self):
        if not self.active:
            raise ValueError('Open or create a library first')
        if self.thread and self.thread.is_alive():
            raise ValueError('A scan is already running')
        if not self.active.latest_job():
            self.active.new_job()
        self.cancel = threading.Event()
        project, cancel = self.active, self.cancel
        self.worker_error = None
        def work():
            try:
                project.run(cancel, workers=2)
            except Exception as e:
                self.worker_error = str(e)
        self.worker_mode = 'scan'
        self.thread = threading.Thread(target=work, name='audit-job', daemon=True)
        self.thread.start()

    def start_repairs(self, ids=None, resume=False):
        if not self.active:
            raise ValueError('Open a library first')
        if self.thread and self.thread.is_alive():
            raise ValueError('Stop the current job before repairing')
        job = self.active.latest_job()
        if not job or job['state'] in {'running','abandoned'}:
            raise ValueError('Pause or finish the scan before repairing completed files')
        self.cancel = threading.Event()
        project, cancel = self.active, self.cancel
        self.worker_error = None
        self.worker_mode = 'repair'
        def work():
            try:
                repair.work(project, cancel, ids, resume)
            except media.Cancelled:
                pass
            except Exception as e:
                self.worker_error = str(e)
        self.thread = threading.Thread(target=work, name='repair-job', daemon=True)
        self.thread.start()

    def state(self, params=None):
        params = params or {}
        if not self.active:
            return {'project': None, 'libraries': self.libraries(), 'worker_active': False, 'worker_error': self.worker_error}
        r = self.active.snapshot(search=params.get('search', ''), status=params.get('status', ''), kind=params.get('kind', ''), offset=int(params.get('offset', 0)), job_id=params.get('job'))
        r.update(libraries=self.libraries(), worker_active=bool(self.thread and self.thread.is_alive()), worker_error=self.worker_error, worker_mode=self.worker_mode)
        r['repairs'] = repair.history(self.active, r['job']['id'] if r['job'] else None, limit=100)
        r['repair_counts'] = repair.counts(self.active,r['job']['id']) if r['job'] else {}
        return r


def make_server(app, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, status=200, mime='application/json'):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=True).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') or mime == 'application/json' else ''))
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', f"default-src 'self'; script-src 'nonce-{app.token}'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self, token=True):
            host = f'127.0.0.1:{self.server.server_address[1]}'
            if self.headers.get('Host') != host:
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                return False
            return not token or secrets.compare_digest(self.headers.get('X-Auditor-Token', ''), app.token)

        def do_GET(self):
            u = urlparse(self.path)
            if not self.allowed(token=u.path not in {'/', '/assets/mic-riot-music-works.png'}):
                return self.send({'error': 'Local session authorization required'}, 403)
            try:
                if u.path == '/':
                    html = (Path(__file__).parent / 'ui.html').read_text().replace('__TOKEN__', app.token)
                    return self.send(html.encode(), mime='text/html')
                if u.path == '/assets/mic-riot-music-works.png':
                    return self.send((Path(__file__).parent / 'assets' / 'mic-riot-music-works.png').read_bytes(), mime='image/png')
                if u.path == '/api/state':
                    params = {k: v[0] for k, v in parse_qs(u.query).items()}
                    return self.send(app.state(params))
                if u.path == '/api/repair-plan':
                    if not app.active:
                        raise ValueError('Open a library first')
                    return self.send(repair.plan(app.active, parse_qs(u.query)['id'][0]))
                if u.path == '/api/file':
                    if not app.active:
                        raise ValueError('Open a library first')
                    return self.send(app.active.file_detail(parse_qs(u.query)['id'][0]))
                if u.path.startswith('/api/report/'):
                    if not app.active:
                        raise ValueError('Open a library first')
                    name = u.path.removeprefix('/api/report/')
                    if name not in {'audit.json', 'audit.csv', 'repairs.json', 'errors.log'}:
                        raise ValueError('Unknown report')
                    jid = app.active.get_job(parse_qs(u.query).get('job', [None])[0])['id']
                    target = app.active.path / 'REPORTS' / jid / name
                    return self.send(target.read_bytes(), mime='application/octet-stream')
                return self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError, KeyError, TypeError) as e:
                self.send({'error': str(e)}, 400)

        def do_POST(self):
            if not self.allowed():
                return self.send({'error': 'Local session token and same origin required'}, 403)
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 <= size <= 65536:
                    raise ValueError('Request too large')
                d = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(d, dict):
                    raise ValueError('Expected JSON object')
                with app.lock:
                    path = urlparse(self.path).path
                    if path == '/api/projects':
                        p = create_project(app.root, d['name'])
                        return self.send(app.open(p.name))
                    if path == '/api/open':
                        return self.send(app.open(d['id']))
                    if path == '/api/choose-folder':
                        if sys.platform != 'darwin':
                            raise ValueError('Enter a source path on this operating system')
                        p = subprocess.run(['osascript', '-e', 'POSIX path of (choose folder with prompt "Choose a read-only music source")'], capture_output=True, text=True, timeout=120)
                        if p.returncode:
                            return self.send({'cancelled': True})
                        return self.send({'path': p.stdout.strip()})
                    if path == '/api/shutdown':
                        app.stop()
                        response = self.send({'saved': True})
                        self.wfile.flush()
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                        return response
                    if not app.active:
                        raise ValueError('Open or create a library first')
                    if path == '/api/config':
                        if app.thread and app.thread.is_alive():
                            raise ValueError('Stop the scan before changing sources/settings')
                        j = app.active.latest_job()
                        if j and j['state'] not in {'complete', 'abandoned'}:
                            raise ValueError('Resume the saved scan; use New Full Scan to change its sources')
                        app.active.config(sources=d.get('sources'), naming=d.get('naming'))
                    elif path == '/api/scan':
                        if app.thread and app.thread.is_alive():
                            raise ValueError('Stop the current job before starting another scan')
                        j = app.active.latest_job()
                        if not j or j['state'] in {'complete', 'abandoned'}:
                            app.active.new_job(incremental=True)
                        app.start()
                    elif path == '/api/resume':
                        app.start()
                    elif path in {'/api/pause', '/api/stop'}:
                        app.stop()
                    elif path == '/api/full-scan':
                        app.stop()
                        j = app.active.latest_job()
                        if d.get('confirm') != (j['id'] if j else 'new'):
                            raise ValueError('Confirm the exact scan before starting a full inventory')
                        app.active.abandon()
                        app.active.new_job()
                        app.start()
                    elif path == '/api/open-fixed':
                        if sys.platform != 'darwin':
                            raise ValueError('Open the project FIXED directory on this operating system')
                        subprocess.Popen(['open', str(app.active.path / 'FIXED')])
                    elif path == '/api/repair':
                        ids = d.get('ids')
                        if ids is not None and (not isinstance(ids,list) or len(ids)>100):
                            raise ValueError('Choose up to 100 files or repair all eligible files')
                        app.start_repairs(ids, resume=bool(d.get('resume')))
                    elif path == '/api/export':
                        report = app.active.export(job_id=d.get('job'))
                        return self.send({'project_id': app.active.manifest['id'], 'path': str(report), 'files': ['audit.json', 'audit.csv', 'repairs.json', 'errors.log']})
                    elif path == '/api/shutdown':
                        app.stop()
                        response = self.send({'saved': True})
                        self.wfile.flush()
                        threading.Thread(target=self.server.shutdown, daemon=True).start()
                        return response
                    else:
                        return self.send({'error': 'Not found'}, 404)
                    return self.send(app.state())
            except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
                self.send({'error': str(e)}, 400)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
