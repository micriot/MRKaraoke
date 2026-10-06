import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

try:
    from auditor.server import Application, make_server
except ImportError:
    Application = make_server = None


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Application, 'Local HTTP application missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Application(Path(self.tmp.name) / 'projects')
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.addCleanup(self.close)

    def close(self):
        self.app.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, token=True, origin=None):
        headers = {}
        if token:
            headers['X-Auditor-Token'] = self.app.token
        if origin:
            headers['Origin'] = origin
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=body, headers=headers)
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())

    def test_create_switch_and_snapshot(self):
        _, a = self.request('/api/projects', {'name': 'A'})
        self.request('/api/projects', {'name': 'B'})
        self.request('/api/open', {'id': a['project']['id']})
        _, snap = self.request('/api/state')
        self.assertEqual(snap['project']['name'], 'A')
        self.assertEqual(snap['counts']['discovered'], 0)

    def test_mutations_require_token_and_same_origin(self):
        for token, origin in [(False, None), (True, 'https://malicious.example')]:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.request('/api/projects', {'name': 'Denied'}, token, origin)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()

    def test_no_path_traversal_project_open(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.request('/api/open', {'id': '../../outside'})
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()

    def test_scan_request_during_repair_does_not_create_job(self):
        from unittest.mock import Mock
        _,created=self.request('/api/projects',{'name':'Busy'})
        p=self.app.active
        src=Path(self.tmp.name)/'song.wav';src.write_bytes(b'RIFFbad')
        p.config(sources=[{'path':str(src),'kind':'break'}]);old=p.new_job()
        with p.db() as db:db.execute("UPDATE jobs SET state='complete' WHERE id=?",(old,))
        self.app.thread=Mock();self.app.thread.is_alive.return_value=True
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/scan',{})
            caught.exception.close()
            self.assertEqual(p.latest_job()['id'],old)
        finally:self.app.thread=None
    def test_shutdown_responds_without_open_library(self):
        status,answer=self.request('/api/shutdown',{})
        self.assertEqual(status,200)
        self.assertTrue(answer['saved'])

if __name__ == '__main__':
    unittest.main()
