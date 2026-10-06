"""Per-customer durable queues, checkpoints and bounded scan workers."""
import csv
import fcntl
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from pathlib import Path

from . import media

VERSION = 'audit-0.1.0-2'
APP_ROOT = Path(__file__).resolve().parents[1]


def dumps(obj):
    return json.dumps(obj, ensure_ascii=True, separators=(',', ':'))


def create_project(root, name):
    name = str(name).strip()
    if not name or len(name) > 120:
        raise ValueError('Library name must contain 1–120 characters')
    path = Path(root).resolve() / str(uuid.uuid4())
    path.mkdir(parents=True)
    for folder in ('ORIGINALS', 'WORKING', 'FIXED', 'NEEDS_REVIEW', 'FAILED', 'DUPLICATES', 'REPORTS'):
        (path / folder).mkdir()
    # ORIGINALS is a logical label; originals remain in the selected source.
    (path / 'project.json').write_text(dumps({'id': path.name, 'name': name, 'created': time.time(), 'mode': 'INDEPENDENT AUDIT AND COPY REPAIR', 'sources': [], 'naming': 'disc-artist-title'}))
    Project(path)
    return path


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.manifest = json.loads((self.path / 'project.json').read_text())
        self.db_path = self.path / 'library.sqlite'
        self.refresh_environment()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, state TEXT NOT NULL, started REAL NOT NULL,
              checkpoint REAL NOT NULL, sources TEXT NOT NULL, current_folder TEXT,
              current_file TEXT, error TEXT, discovery_complete INTEGER DEFAULT 0,
              enumerations INTEGER DEFAULT 0, cache_hits INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS directories(
              job TEXT, path TEXT, kind TEXT, state TEXT DEFAULT 'pending', error TEXT,
              mtime_ns INTEGER, PRIMARY KEY(job,path));
            CREATE TABLE IF NOT EXISTS files(
              id INTEGER PRIMARY KEY, job TEXT NOT NULL, path TEXT NOT NULL, kind TEXT,
              size INTEGER, mtime_ns INTEGER, state TEXT DEFAULT 'pending',
              sha256 TEXT, stages TEXT DEFAULT '{}', outcome TEXT DEFAULT 'PENDING',
              error TEXT, retries INTEGER DEFAULT 0, updated REAL,
              UNIQUE(job,path));
            CREATE INDEX IF NOT EXISTS file_queue ON files(job,state,id);
            CREATE INDEX IF NOT EXISTS file_outcome ON files(job,outcome,id);
            CREATE INDEX IF NOT EXISTS directory_queue ON directories(job,state);
            CREATE TABLE IF NOT EXISTS cache(
              digest TEXT, stage TEXT, version TEXT, value TEXT,
              PRIMARY KEY(digest,stage,version));
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, job TEXT, time REAL, file INTEGER,
              message TEXT);
            ''')
            # Remove retired integration evidence without repeating media analysis.
            db.execute("UPDATE files SET stages=json_remove(stages,'$.singws','$._environment.singws_source','$._environment.singws_format','$._environment.singws_known') WHERE json_type(stages,'$.singws') IS NOT NULL")
            db.execute("UPDATE files SET outcome=CASE WHEN EXISTS(SELECT 1 FROM json_each(files.stages) WHERE json_extract(value,'$.status')='FAIL') THEN 'FAILED' WHEN EXISTS(SELECT 1 FROM json_each(files.stages) WHERE json_extract(value,'$.status') IN ('WARNING','UNKNOWN')) THEN 'NEEDS_REVIEW' ELSE 'AUDIT_PASS' END WHERE state IN ('complete','failed') AND error IS NULL")
            if 'mtime_ns' not in {r['name'] for r in db.execute('PRAGMA table_info(directories)')}:
                db.execute('ALTER TABLE directories ADD COLUMN mtime_ns INTEGER')

    def refresh_environment(self):
        tools = [(x, str(media.shutil.which(x)), self._tool_stat(x)) for x in ('ffmpeg', 'ffprobe')]
        self.cache_version = hashlib.sha256(dumps([VERSION, tools]).encode()).hexdigest()

    @staticmethod
    def _tool_stat(name):
        p = media.shutil.which(name)
        if not p:
            return None
        s = Path(p).stat()
        return (s.st_size, s.st_mtime_ns)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def config(self, sources=None, naming=None):
        data = json.loads((self.path / 'project.json').read_text())
        if sources is not None:
            data['sources'] = self.validate_sources(sources)
        if naming is not None:
            if naming not in {'disc-artist-title', 'disc-title-artist', 'artist-title-disc', 'title-artist-disc', 'artist-title', 'title-artist'}:
                raise ValueError('Unsupported naming layout')
            data['naming'] = naming
        tmp = self.path / 'project.json.tmp'
        with open(tmp, 'w') as f:
            f.write(dumps(data))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path / 'project.json')
        self.manifest = data

    def validate_sources(self, sources):
        if not isinstance(sources, list) or not sources or len(sources) > 100:
            raise ValueError('Select 1–100 source folders/files')
        out = []
        storage = self.path.parent
        for item in sources:
            raw = Path(item['path']).expanduser()
            if raw.is_symlink():
                raise ValueError('Select the real source, not a symbolic link')
            p = raw.resolve()
            if not p.exists():
                raise ValueError(f'Source is unavailable: {p}')
            if p == storage or storage in p.parents or p in storage.parents or p == APP_ROOT or APP_ROOT in p.parents or p in APP_ROOT.parents:
                raise ValueError('Sources must not overlap app or project storage')
            kind = item.get('kind', 'karaoke')
            if kind not in {'karaoke', 'break'}:
                raise ValueError('Choose Karaoke or Break Music')
            # Reject conflicting nested kind assignments; preserve clear ownership.
            for old in out:
                q = Path(old['path'])
                if (p == q or p in q.parents or q in p.parents) and kind != old['kind']:
                    raise ValueError('Overlapping sources cannot have different library types')
            if any(Path(o['path']) == p or Path(o['path']) in p.parents for o in out):
                continue
            out = [o for o in out if p not in Path(o['path']).parents]
            out.append({'path': str(p), 'kind': kind})
        return out

    def latest_job(self):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs ORDER BY started DESC LIMIT 1').fetchone()
        return dict(row) if row else None

    def get_job(self, ident=None):
        if not ident:
            return self.latest_job()
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Scan job not found in this project')
        return dict(row)

    def new_job(self, sources=None, incremental=False):
        job = self.latest_job()
        if job and job['state'] not in {'complete', 'abandoned'}:
            raise ValueError('An unfinished scan exists. Resume it or explicitly abandon it first.')
        roots = self.validate_sources(sources or self.manifest['sources'])
        self.config(sources=roots)
        jid = str(uuid.uuid4())
        now = time.time()
        with self.db() as db:
            db.execute('INSERT INTO jobs(id,state,started,checkpoint,sources) VALUES(?,?,?,?,?)', (jid, 'paused', now, now, dumps(roots)))
            for root in roots:
                db.execute('INSERT INTO directories(job,path,kind) VALUES(?,?,?)', (jid, root['path'], root['kind']))
            if incremental and job:
                # Copy evidence transactionally; cheap directory-stat tasks decide
                # which folders actually require new enumeration in the worker.
                for root in roots:
                    prefix = root['path'].rstrip('/') + '/'
                    match = '(path=? OR substr(path,1,?)=?) AND kind=?'
                    args = [root['path'], len(prefix), prefix, root['kind']]
                    db.execute('INSERT OR REPLACE INTO directories(job,path,kind,state,error,mtime_ns) SELECT ?,path,kind,\'check\',NULL,mtime_ns FROM directories WHERE job=? AND ' + match, [jid, job['id']] + args)
                    db.execute('INSERT OR IGNORE INTO files(job,path,kind,size,mtime_ns,state,sha256,stages,outcome,error,retries,updated) SELECT ?,path,kind,size,mtime_ns,state,sha256,stages,outcome,error,retries,updated FROM files WHERE job=? AND ' + match, [jid, job['id']] + args)
            db.execute('INSERT INTO events(job,time,message) VALUES(?,?,?)', (jid, now, 'Independent scan queue created; originals protected'))
        return jid

    def abandon(self):
        job = self.latest_job()
        if job:
            with self.db() as db:
                db.execute("UPDATE jobs SET state='abandoned',checkpoint=? WHERE id=?", (time.time(), job['id']))

    def directory_states(self):
        j = self.latest_job()
        if not j:
            return {}
        with self.db() as db:
            return {r['path']: r['state'] for r in db.execute('SELECT path,state FROM directories WHERE job=?', (j['id'],))}

    def _enqueue_file(self, db, jid, path, kind, metadata=None):
        try:
            s = metadata if metadata is not None else path.stat()
        except OSError as e:
            db.execute('INSERT OR IGNORE INTO files(job,path,kind,state,outcome,error,updated) VALUES(?,?,?,?,?,?,?)', (jid, str(path), kind, 'failed', 'FAILED', str(e), time.time()))
            return
        db.execute('INSERT OR IGNORE INTO files(job,path,kind,size,mtime_ns,updated) VALUES(?,?,?,?,?,?)', (jid, str(path), kind, s.st_size, s.st_mtime_ns, time.time()))

    def discover_step(self, cancel):
        """Enumerate one pending folder; flush at 64 entries or one second."""
        j = self.latest_job()
        if not j:
            return False
        jid = j['id']
        with self.db() as db:
            d = db.execute("SELECT * FROM directories WHERE job=? AND state IN ('pending','check') ORDER BY rowid LIMIT 1", (jid,)).fetchone()
            if not d:
                db.execute('UPDATE jobs SET discovery_complete=1,checkpoint=? WHERE id=?', (time.time(), jid))
                return False
            db.execute("UPDATE directories SET state='running',error=NULL WHERE job=? AND path=?", (jid, d['path']))
            db.execute('UPDATE jobs SET current_folder=?,checkpoint=? WHERE id=?', (d['path'], time.time(), jid))
        p = Path(d['path'])
        try:
            media.check_cancel(cancel)
            if d['state'] == 'check' and p.stat().st_mtime_ns == d['mtime_ns']:
                with self.db() as db:
                    db.execute("UPDATE directories SET state='complete' WHERE job=? AND path=?", (jid, str(p)))
                return True
            with self.db() as db:
                db.execute('UPDATE jobs SET enumerations=enumerations+1 WHERE id=?', (jid,))
            if p.is_file():
                with self.db() as db:
                    self._enqueue_file(db, jid, p, d['kind'])
            else:
                # scandir is streaming: no giant in-memory list or master inventory restart.
                batch = []
                checkpoint = time.monotonic()
                with os.scandir(p) as it:
                    for entry in it:
                        media.check_cancel(cancel)
                        if entry.name.startswith('.') or entry.name == '__MACOSX':
                            continue
                        if entry.is_symlink():
                            continue
                        child = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            batch.append(('dir', child, None))
                        elif entry.is_file(follow_symlinks=False):
                            # Probe headers of unrecognized extensions too; CDG cannot
                            # be reliably identified without its filename/context.
                            known = child.suffix.lower() in media.EXTENSIONS
                            if not known:
                                try:
                                    known = media.signature(child)['format'] not in {'unknown', 'empty'}
                                except OSError:
                                    known = False
                            if known:
                                batch.append(('file', child, entry.stat(follow_symlinks=False)))
                        if len(batch) >= 64 or time.monotonic() - checkpoint >= 1:
                            self._flush_discovery(jid, d['kind'], batch)
                            batch = []
                            checkpoint = time.monotonic()
                    self._flush_discovery(jid, d['kind'], batch)
            with self.db() as db:
                db.execute("UPDATE directories SET state='complete',mtime_ns=? WHERE job=? AND path=?", (p.stat().st_mtime_ns, jid, str(p)))
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (time.time(), jid))
            return True
        except media.Cancelled:
            with self.db() as db:
                db.execute("UPDATE directories SET state='pending' WHERE job=? AND path=?", (jid, str(p)))
            raise
        except OSError as e:
            if isinstance(e, FileNotFoundError) and self._online_root_for(p, jid):
                with self.db() as db:
                    db.execute("UPDATE directories SET state='skipped',error='Folder removed from an online source' WHERE job=? AND path=?", (jid, str(p)))
                return True
            with self.db() as db:
                db.execute("UPDATE directories SET state='pending',error=? WHERE job=? AND path=?", (str(e), jid, str(p)))
                db.execute("UPDATE jobs SET state='blocked',error=?,checkpoint=? WHERE id=?", (f'Reconnect or grant access to source: {p}: {e}', time.time(), jid))
            raise SourceUnavailable(str(e))

    def _flush_discovery(self, jid, kind, batch):
        with self.db() as db:
            for item in batch:
                typ, path = item[:2]
                metadata = item[2] if len(item) > 2 else None
                if typ == 'dir':
                    db.execute('INSERT OR IGNORE INTO directories(job,path,kind) VALUES(?,?,?)', (jid, str(path), kind))
                else:
                    self._enqueue_file(db, jid, path, kind, metadata)
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (time.time(), jid))

    def _stage(self, fid, name, fn, digest=None, cacheable=False):
        detail = self.file_detail(fid)
        stages = detail['stages']
        if name in stages:
            return stages[name]
        value = None
        hit = False
        if digest and cacheable:
            with self.db() as db:
                row = db.execute('SELECT value FROM cache WHERE digest=? AND stage=? AND version=?', (digest, name, self.cache_version)).fetchone()
                if row:
                    value = json.loads(row['value'])
                    hit = True
        if value is None:
            value = fn()
        s = Path(detail['path']).stat()
        if (s.st_size, s.st_mtime_ns) != (detail['size'], detail['mtime_ns']):
            raise ChangedDuringAudit('Source changed before stage checkpoint; retry required')
        # Only this worker writes this file; re-read current stages for clarity.
        with self.db() as db:
            stages = json.loads(db.execute('SELECT stages FROM files WHERE id=?', (fid,)).fetchone()['stages'])
            stages[name] = value
            db.execute('UPDATE files SET stages=?,updated=? WHERE id=?', (dumps(stages), time.time(), fid))
            db.execute('UPDATE jobs SET checkpoint=?,cache_hits=cache_hits+? WHERE id=?', (time.time(), int(hit), detail['job']))
            if digest and cacheable and value.get('status') in {'PASS', 'FAIL', 'WARNING'}:
                db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)', (digest, name, self.cache_version, dumps(value)))
        return value

    def audit_file(self, fid, cancel):
        row = self.file_detail(fid)
        path = Path(row['path'])
        jid = row['job']
        try:
            media.check_cancel(cancel)
            s = path.stat()
            if (s.st_size, s.st_mtime_ns) != (row['size'], row['mtime_ns']):
                with self.db() as db:
                    db.execute("UPDATE files SET size=?,mtime_ns=?,sha256=NULL,stages='{}',retries=retries+1 WHERE id=?", (s.st_size, s.st_mtime_ns, fid))
                row = self.file_detail(fid)
            digest = row['sha256']
            if not digest:
                digest = media.hash_file(path, cancel)
                after = path.stat()
                if (after.st_size, after.st_mtime_ns) != (s.st_size, s.st_mtime_ns):
                    raise ChangedDuringAudit('Source changed while hashing; retry required')
                with self.db() as db:
                    db.execute('UPDATE files SET sha256=?,updated=? WHERE id=?', (digest, time.time(), fid))
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (time.time(), jid))
            self._stage(fid, '_environment', lambda: self.environment())
            sig = self._stage(fid, 'signature', lambda: media.signature(path))
            info = self._stage(fid, 'filename', lambda: media.filename(path, row['kind'], self.manifest['naming']))
            is_zip = sig.get('format') == 'zip' or path.suffix.lower() == '.zip'
            arc = self._stage(fid, 'zip', lambda: media.archive(path, cancel), digest, True) if is_zip else None
            pair = self._stage(fid, 'pair', lambda: media.pair(path, is_zip, arc) if row['kind'] == 'karaoke' else media.result('PASS', 'Break music has no CDG requirement'))
            audio_path = media.companion(path) if path.suffix.lower() == '.cdg' else path
            audio_name = arc.get('mp3', [None])[0] if arc and len(arc.get('mp3', [])) == 1 else None
            cdg_name = arc.get('cdg', [None])[0] if arc and len(arc.get('cdg', [])) == 1 else None
            working = self.path / 'WORKING'

            def audio_check():
                if is_zip and (not audio_name or arc['status'] not in {'PASS', 'WARNING'}):
                    return media.result('UNKNOWN', 'Archive audio component unavailable')
                if not audio_path:
                    return media.result('FAIL', 'MISSING MP3')
                with media.component(path if is_zip else audio_path, audio_name if is_zip else None, working, cancel) as p:
                    return media.audio(p, cancel)

            # Companion bytes have a separate digest; CDG hash must not cache MP3 decode.
            audio_digest = digest
            companion_evidence = None
            if audio_path and audio_path != path:
                def hash_companion():
                    before = audio_path.stat()
                    h = media.hash_file(audio_path, cancel)
                    after = audio_path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ChangedDuringAudit('Companion changed while hashing')
                    return {'path': str(audio_path), 'sha256': h, 'size': after.st_size, 'mtime_ns': after.st_mtime_ns}
                companion_evidence = self._stage(fid, '_companion', hash_companion)
                audio_digest = companion_evidence['sha256']
                original_audio_check = audio_check
                def audio_check():
                    value = original_audio_check()
                    now = audio_path.stat()
                    if (now.st_size, now.st_mtime_ns) != (companion_evidence['size'], companion_evidence['mtime_ns']):
                        raise ChangedDuringAudit('Companion changed during audio decode')
                    return value
            aud = self._stage(fid, 'audio', audio_check, audio_digest, True)
            if path.suffix.lower() == '.cdg' or is_zip:
                def cdg_check():
                    if is_zip and (not cdg_name or arc['status'] not in {'PASS', 'WARNING'}):
                        return media.result('UNKNOWN', 'Archive CDG component unavailable')
                    with media.component(path, cdg_name if is_zip else None, working, cancel) as p:
                        return media.cdg(p, cancel)
                graphics = self._stage(fid, 'cdg', cdg_check, digest, True)
                if graphics.get('duration') and aud.get('duration'):
                    self._stage(fid, 'duration_relationship', lambda: media.result('WARNING' if abs(graphics['duration'] - aud['duration']) > 10 else 'PASS', 'Duration comparison only; synchronization UNKNOWN', audio_seconds=aud['duration'], cdg_seconds=graphics['duration']))
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (s.st_size, s.st_mtime_ns):
                raise ChangedDuringAudit('Source changed during analysis; retry required')
            if companion_evidence:
                now = audio_path.stat()
                if (now.st_size, now.st_mtime_ns) != (companion_evidence['size'], companion_evidence['mtime_ns']):
                    raise ChangedDuringAudit('Companion changed during analysis; retry required')
            statuses = [x['status'] for x in self.file_detail(fid)['stages'].values() if isinstance(x, dict) and 'status' in x]
            outcome = 'FAILED' if 'FAIL' in statuses else 'NEEDS_REVIEW' if any(x in statuses for x in ('WARNING', 'UNKNOWN')) else 'AUDIT_PASS'
            with self.db() as db:
                db.execute('UPDATE files SET state=?,outcome=?,error=NULL,updated=? WHERE id=?', ('failed' if outcome == 'FAILED' else 'complete', outcome, time.time(), fid))
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (time.time(), jid))
        except media.Cancelled:
            with self.db() as db:
                db.execute("UPDATE files SET state='pending',updated=? WHERE id=?", (time.time(), fid))
            raise
        except ChangedDuringAudit as e:
            with self.db() as db:
                db.execute("UPDATE files SET state='pending',sha256=NULL,stages='{}',error=?,retries=retries+1 WHERE id=?", (str(e), fid))
            raise SourceUnavailable(str(e))
        except OSError as e:
            with self.db() as db:
                db.execute("UPDATE files SET state='pending',error=?,retries=retries+1 WHERE id=?", (str(e), fid))
            raise SourceUnavailable(f'Source disappeared: {path}')
        except Exception as e:
            with self.db() as db:
                db.execute("UPDATE files SET state='failed',outcome='FAILED',error=?,updated=? WHERE id=?", (str(e), time.time(), fid))
                db.execute('INSERT INTO events(job,time,file,message) VALUES(?,?,?,?)', (jid, time.time(), fid, str(e)))

    def environment(self):
        return {'analysis': self.cache_version, 'naming': self.manifest['naming']}

    def _refresh_pending(self, jid, cancel=None):
        """Resume reconciles discovered files, never traverses completed folders."""
        cancel = cancel or threading.Event()
        media.check_cancel(cancel)
        last = 0
        while True:
            with self.db() as db:
                rows = db.execute('SELECT id,path,size,mtime_ns,stages,state,sha256 FROM files WHERE job=? AND id>? ORDER BY id LIMIT 128', (jid, last)).fetchall()
            if not rows:
                break
            for row in rows:
                media.check_cancel(cancel)
                self._reconcile_file(row, jid)
                last = row['id']
            with self.db() as db:
                db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (time.time(), jid))

    def _reconcile_file(self, row, jid):
            p = Path(row['path'])
            try:
                s = p.stat()
            except FileNotFoundError:
                if not self._online_root_for(p, jid):
                    raise SourceUnavailable(f'Reconnect source containing {p}')
                with self.db() as db:
                    db.execute("UPDATE files SET state='skipped',outcome='NEEDS_REVIEW',error='Previously discovered file is missing; evidence retained',updated=? WHERE id=?", (time.time(), row['id']))
                return
            except OSError as e:
                raise SourceUnavailable(f'Reconnect or grant access to {p}: {e}')
            stages = json.loads(row['stages'])
            changed = (s.st_size, s.st_mtime_ns) != (row['size'], row['mtime_ns'])
            old_env = stages.get('_environment', {})
            new_env = self.environment()
            version_changed = bool(stages) and old_env.get('analysis') != new_env['analysis']
            config_changed = bool(stages) and old_env != new_env
            pair_changed = False
            pair = stages.get('pair', {})
            if p.suffix.lower() in {'.mp3', '.cdg'}:
                c = media.companion(p)
                pair_changed = bool(c) != bool(pair.get('companion'))
                if c and pair.get('companion'):
                    cs = c.stat()
                    pair_changed = pair_changed or (cs.st_size, cs.st_mtime_ns) != (pair.get('size'), pair.get('mtime_ns'))
            if changed or pair_changed or version_changed or config_changed or row['state'] == 'skipped':
                drop = {'_environment'}
                if pair_changed:
                    drop.update({'pair', 'duration_relationship'})
                    if p.suffix.lower() == '.cdg':
                        drop.update({'audio', '_companion'})
                if config_changed:
                    if old_env.get('naming') != new_env['naming']:
                        drop.add('filename')
                keep = {} if changed or version_changed else {k: v for k, v in stages.items() if k not in drop}
                with self.db() as db:
                    db.execute("UPDATE files SET state='pending',outcome='PENDING',size=?,mtime_ns=?,sha256=?,stages=?,error=NULL WHERE id=?", (s.st_size, s.st_mtime_ns, None if changed else row['sha256'], dumps(keep), row['id']))

    def _online_root_for(self, path, jid):
        with self.db() as db:
            sources = json.loads(db.execute('SELECT sources FROM jobs WHERE id=?', (jid,)).fetchone()['sources'])
        for item in sources:
            root = Path(item['path'])
            if root in path.parents and root.is_dir():
                # Merely exists is insufficient for a inaccessible/disconnected drive.
                with os.scandir(root):
                    return True
        return False

    def run(self, cancel, workers=2):
        with open(self.path / '.worker.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('This project already has an active scan worker')
            j = self.latest_job()
            if not j or j['state'] == 'abandoned':
                return
            jid = j['id']
            try:
                if cancel.is_set():
                    return
                for src in json.loads(j['sources']):
                    if not Path(src['path']).exists():
                        raise SourceUnavailable(f'Reconnect source: {src["path"]}')
                with self.db() as db:
                    db.execute("UPDATE directories SET state='pending' WHERE job=? AND state='running'", (jid,))
                    db.execute("UPDATE files SET state='pending' WHERE job=? AND state='running'", (jid,))
                    db.execute("UPDATE jobs SET state='running',error=NULL,checkpoint=? WHERE id=?", (time.time(), jid))
                self.refresh_environment()
                self._refresh_pending(jid, cancel)
                while not cancel.is_set() and self.discover_step(cancel):
                    pass
                if cancel.is_set():
                    return
                worker_count = max(1, min(int(workers), 4))
                with ThreadPoolExecutor(max_workers=worker_count) as pool:
                    active = set()
                    while not cancel.is_set():
                        # Refill as soon as any worker finishes, without waiting for
                        # the slowest file in a batch. Each claimed file stays durable.
                        slots = worker_count - len(active)
                        if slots:
                            with self.db() as db:
                                pending = db.execute("SELECT id,path FROM files WHERE job=? AND state='pending' ORDER BY id LIMIT ?", (jid, slots)).fetchall()
                                for f in pending:
                                    db.execute("UPDATE files SET state='running' WHERE id=?", (f['id'],))
                                if pending:
                                    db.execute('UPDATE jobs SET current_file=?,checkpoint=? WHERE id=?', (pending[0]['path'], time.time(), jid))
                            active.update(pool.submit(self.audit_file, f['id'], cancel) for f in pending)
                        if not active:
                            break
                        done, active = wait(active, timeout=.1, return_when=FIRST_COMPLETED)
                        for future in done:
                            try:
                                future.result()
                            except SourceUnavailable:
                                cancel.set()
                                raise
                if not cancel.is_set():
                    with self.db() as db:
                        db.execute("UPDATE jobs SET state='complete',current_file=NULL,current_folder=NULL,checkpoint=? WHERE id=?", (time.time(), jid))
            except media.Cancelled:
                pass
            except (SourceUnavailable, OSError) as e:
                with self.db() as db:
                    db.execute("UPDATE jobs SET state='blocked',error=?,checkpoint=? WHERE id=?", (str(e), time.time(), jid))
            finally:
                with self.db() as db:
                    db.execute("UPDATE files SET state='pending' WHERE job=? AND state='running'", (jid,))
                    db.execute("UPDATE directories SET state='pending' WHERE job=? AND state='running'", (jid,))
                    db.execute("UPDATE jobs SET state=CASE WHEN state IN ('complete','blocked') THEN state ELSE 'paused' END,checkpoint=? WHERE id=?", (time.time(), jid))

    def snapshot(self, search='', status='', kind='', offset=0, limit=50, job_id=None):
        job = self.get_job(job_id)
        counts = {'discovered': 0, 'processed': 0, 'pending': 0, 'failed': 0, 'skipped': 0, 'needs_review': 0, 'audit_pass': 0}
        rows = []
        total = 0
        if job:
            with self.db() as db:
                for r in db.execute('SELECT state,outcome,count(*) AS n FROM files WHERE job=? GROUP BY state,outcome', (job['id'],)):
                    counts['discovered'] += r['n']
                    if r['state'] in {'complete', 'failed', 'skipped'}:
                        counts['processed'] += r['n']
                    else:
                        counts['pending'] += r['n']
                    if r['state'] == 'failed':
                        counts['failed'] += r['n']
                    if r['state'] == 'skipped':
                        counts['skipped'] += r['n']
                    if r['outcome'] == 'NEEDS_REVIEW':
                        counts['needs_review'] += r['n']
                    if r['outcome'] == 'AUDIT_PASS':
                        counts['audit_pass'] += r['n']
                clauses, params = ['job=?'], [job['id']]
                if search:
                    clauses.append("path LIKE ? ESCAPE '\\'")
                    params.append('%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
                if status == 'PROBLEMS':
                    clauses.append("outcome IN ('NEEDS_REVIEW','FAILED')")
                elif status:
                    clauses.append('outcome=?')
                    params.append(status)
                if kind:
                    clauses.append('kind=?')
                    params.append(kind)
                where = ' AND '.join(clauses)
                total = db.execute('SELECT count(*) FROM files WHERE ' + where, params).fetchone()[0]
                rows = [dict(r) for r in db.execute('SELECT id,path,kind,size,state,outcome,updated,sha256,error,stages FROM files WHERE ' + where + ' ORDER BY id LIMIT ? OFFSET ?', params + [min(100, max(1, int(limit))), max(0, int(offset))])]
                for r in rows:
                    r['stages'] = {k: v for k, v in json.loads(r['stages']).items() if k != 'singws'}
        with self.db() as db:
            history = [dict(r) for r in db.execute('SELECT id,state,started FROM jobs ORDER BY started DESC LIMIT 100')]
        return {'project': self.manifest, 'job': job, 'latest_job': self.latest_job(), 'history': history, 'counts': counts, 'files': rows, 'filtered_total': total}

    def file_detail(self, fid):
        with self.db() as db:
            row = db.execute('SELECT * FROM files WHERE id=?', (int(fid),)).fetchone()
        if not row:
            raise ValueError('File record not found in this project')
        d = dict(row)
        d['stages'] = {k: v for k, v in json.loads(d['stages']).items() if k != 'singws'}
        d['project_id'] = self.manifest['id']
        return d

    def export(self, job_id=None):
        job = self.get_job(job_id)
        if not job:
            raise ValueError('Scan a source before exporting')
        report_dir = self.path / 'REPORTS' / job['id']
        report_dir.mkdir(exist_ok=True)
        with self.db() as db:
            rows = db.execute('SELECT * FROM files WHERE job=? ORDER BY id', (job['id'],)).fetchall()
        records = []
        for row in rows:
            d = dict(row)
            d['stages'] = {k: v for k, v in json.loads(d['stages']).items() if k != 'singws'}
            records.append(d)
        audit = {'project': self.manifest, 'job': job, 'summary': self.snapshot(job_id=job['id'])['counts'], 'mode': 'INDEPENDENT AUDIT AND COPY REPAIR', 'ready_validation': 'INCOMPLETE — no playback/render/sync tests in v0.2', 'files': records}
        (report_dir / 'audit.json').write_text(json.dumps(audit, indent=2, ensure_ascii=True))
        with open(report_dir / 'audit.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Original path', 'Kind', 'Size', 'SHA256', 'Outcome', 'Error'])
            safe = lambda v: "'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else str(v)
            for r in records:
                writer.writerow([safe(r[k] if r[k] is not None else '') for k in ('path', 'kind', 'size', 'sha256', 'outcome', 'error')])
        from .repair import history
        (report_dir / 'repairs.json').write_text(json.dumps(history(self, job['id']), indent=2))
        errors = [f'{r["path"]}: {r["error"]}' for r in records if r['error']]
        errors += [f'{r["path"]} [{stage}]: {v["reason"]}' for r in records for stage, v in r['stages'].items() if isinstance(v, dict) and v.get('status') in {'FAIL', 'WARNING', 'UNKNOWN'}]
        (report_dir / 'errors.log').write_text('\n'.join(errors) + '\n')
        return report_dir


class SourceUnavailable(Exception):
    pass


class ChangedDuringAudit(Exception):
    pass
