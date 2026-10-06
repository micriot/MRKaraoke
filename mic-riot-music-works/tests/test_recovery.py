import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from threading import Event
from unittest.mock import patch

from auditor import media
from auditor.store import Project, create_project


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.src = self.root / 'source'
        self.src.mkdir()
        self.p = Project(create_project(self.root / 'projects', 'Recovery'))

    def wav(self, name='Artist - Title.wav'):
        p = self.src / name
        with wave.open(str(p), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(bytes(16000))
        return p

    def test_reconciliation_access_error_blocks_preserving_queue(self):
        f = self.wav()
        self.p.new_job([{"path": str(f), "kind": "break"}])
        self.p.discover_step(Event())
        with patch.object(self.p, "_reconcile_file", side_effect=PermissionError("Reconnect source")):
            self.p.run(Event(), workers=1)
        self.assertEqual(self.p.get_job()["state"], "blocked")
        self.assertEqual(self.p.snapshot()["counts"]["pending"], 1)

    def test_scheduler_refills_before_slow_file_finishes(self):
        for i in range(3):
            self.wav(f'{i}.wav')
        self.p.new_job([{'path': str(self.src), 'kind': 'break'}])
        while self.p.discover_step(Event()):
            pass
        third_started = Event()
        def audit(fid, cancel):
            if fid == 1:
                self.assertTrue(third_started.wait(2), 'Idle worker waited for slow batch member')
            if fid == 3:
                third_started.set()
            with self.p.db() as db:
                db.execute("UPDATE files SET state='complete' WHERE id=?", (fid,))
        with patch.object(self.p, 'audit_file', side_effect=audit):
            self.p.run(Event(), workers=2)
        self.assertTrue(third_started.is_set())
        self.assertEqual(self.p.get_job()['state'], 'complete')

    def test_full_decode_cache_reused_on_new_scan(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        self.assertEqual(self.p.file_detail(1)['stages']['audio']['status'], 'PASS')
        self.p.new_job()
        with patch('auditor.media.audio', side_effect=AssertionError('Decoded unchanged file twice')):
            self.p.run(Event(), workers=1)
        self.assertGreater(self.p.snapshot()['job']['cache_hits'], 0)
        self.assertEqual(self.p.file_detail(2)['stages']['audio']['status'], 'PASS')

    def test_interrupted_directory_keeps_committed_children(self):
        for i in range(150):
            (self.src / f'{i}.mp3').write_bytes(b'ID3fixture')
        self.p.new_job([{'path': str(self.src), 'kind': 'karaoke'}])
        cancel = Event()
        original = self.p._flush_discovery
        def flush(*args):
            original(*args)
            cancel.set()
        with patch.object(self.p, '_flush_discovery', side_effect=flush):
            self.p.run(cancel)
        self.assertEqual(self.p.snapshot()['counts']['discovered'], 64)
        self.assertEqual(self.p.directory_states()[str(self.src)], 'pending')
        p = Project(self.p.path)
        p.discover_step(Event())
        self.assertEqual(p.snapshot()['counts']['discovered'], 150)

    def test_disconnected_source_keeps_queue(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        moved = f.with_suffix('.offline')
        f.rename(moved)
        self.p.run(Event())
        self.assertEqual(self.p.snapshot()['job']['state'], 'blocked')
        self.assertEqual(self.p.directory_states()[str(f)], 'pending')
        moved.rename(f)
        self.p.run(Event(), workers=1)
        self.assertEqual(self.p.snapshot()['job']['state'], 'complete')

    def test_crash_during_audio_keeps_prior_hash_and_stages(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self._crash('audio')
        r = self.p.file_detail(1)
        self.assertTrue(r['sha256'])
        self.assertIn('signature', r['stages'])
        self.assertNotIn('audio', r['stages'])
        old_hash = r['sha256']
        p = Project(self.p.path)
        with patch('auditor.media.hash_file', side_effect=AssertionError('Repeated saved hash')):
            p.run(Event(), workers=1)
        self.assertEqual(p.file_detail(1)['sha256'], old_hash)
        self.assertEqual(p.file_detail(1)['stages']['audio']['status'], 'PASS')

    def test_crash_during_hash_resumes_only_unfinished_work(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self._crash('hash_file')
        self.assertEqual(self.p.directory_states()[str(f)], 'complete')
        self.assertIsNone(self.p.file_detail(1)['sha256'])
        p = Project(self.p.path)
        enumerations = p.snapshot()['job']['enumerations']
        p.run(Event(), workers=1)
        self.assertTrue(p.file_detail(1)['sha256'])
        self.assertEqual(p.snapshot()['job']['enumerations'], enumerations)

    def _crash(self, function):
        marker = self.root / 'entered'
        code = ('import time\nfrom pathlib import Path\nfrom threading import Event\n'
                'from auditor import media\nfrom auditor.store import Project\n'
                'def hold(*args, **kwargs):\n'
                f' Path({str(marker)!r}).write_text("entered")\n time.sleep(60)\n'
                f'media.{function}=hold\nProject({str(self.p.path)!r}).run(Event(),workers=1)\n')
        proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline and proc.poll() is None:
                time.sleep(.02)
            if not marker.exists():
                proc.kill()
                _, err = proc.communicate()
                self.fail('Crash injection did not reach target stage: ' + err.decode())
            proc.kill()
            proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_changed_companion_invalidates_only_dependent_checks(self):
        cdg = self.src / 'D01 - Artist - Title.cdg'
        cdg.write_bytes((bytes([9, 1]) + bytes(22)) * 300)
        mp3 = cdg.with_suffix('.mp3')
        mp3.write_bytes(b'ID3bad')
        self.p.new_job([{'path': str(cdg), 'kind': 'karaoke'}])
        self.p.run(Event(), workers=1)
        saved = self.p.file_detail(1)['stages']['cdg']
        mp3.write_bytes(b'ID3changed companion')
        p = Project(self.p.path)
        with patch('auditor.media.cdg', side_effect=AssertionError('Repeated unchanged CDG validation')):
            p.run(Event(), workers=1)
        self.assertEqual(p.file_detail(1)['stages']['cdg'], saved)
        self.assertEqual(p.file_detail(1)['stages']['pair']['size'], mp3.stat().st_size)

    def test_analysis_version_change_invalidates_saved_checks(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        p = Project(self.p.path)
        with patch('auditor.store.VERSION', 'changed-analysis-version'):
            with patch('auditor.media.audio', wraps=media.audio) as decode:
                p.run(Event(), workers=1)
        self.assertEqual(decode.call_count, 1, 'Stale audio checks survived analysis-version change')

    def test_stop_cancels_resume_reconciliation(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        cancel = Event()
        cancel.set()
        with self.assertRaises(media.Cancelled):
            self.p._refresh_pending(self.p.latest_job()['id'], cancel)

    def test_removed_child_of_online_source_is_recorded_not_blocked(self):
        f = self.wav()
        self.p.new_job([{'path': str(self.src), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        f.unlink()
        self.p.run(Event(), workers=1)
        self.assertEqual(self.p.snapshot()['job']['state'], 'complete')
        self.assertEqual(self.p.file_detail(1)['state'], 'skipped')
        self.assertIn('missing', self.p.file_detail(1)['error'].lower())

    def test_hash_access_error_preserves_pending_for_retry(self):
        f = self.wav()
        self.p.new_job([{'path': str(f), 'kind': 'break'}])
        with patch('auditor.media.hash_file', side_effect=PermissionError('Drive temporarily unavailable')):
            self.p.run(Event(), workers=1)
        self.assertEqual(self.p.file_detail(1)['state'], 'pending')
        self.assertEqual(self.p.snapshot()['job']['state'], 'blocked')

    def test_companion_changed_during_decode_is_not_cached_pass(self):
        c = self.src / 'D01 - Artist - Title.cdg'
        c.write_bytes((bytes([9, 1]) + bytes(22)) * 300)
        a = c.with_suffix('.mp3')
        a.write_bytes(b'ID3before')
        self.p.new_job([{'path': str(c), 'kind': 'karaoke'}])
        def changing(*args):
            a.write_bytes(b'ID3after with different bytes')
            return media.result('PASS', 'Injected successful decode', duration=1)
        with patch('auditor.media.audio', side_effect=changing):
            self.p.run(Event(), workers=1)
        self.assertEqual(self.p.snapshot()['job']['state'], 'blocked')
        self.assertEqual(self.p.file_detail(1)['state'], 'pending')
        self.assertNotIn('audio', self.p.file_detail(1)['stages'])

    def test_incremental_discovery_visits_only_changed_folders(self):
        (self.src / 'stable').mkdir()
        (self.src / 'changed').mkdir()
        self.wav()
        (self.src / 'stable' / 'one.mp3').write_bytes(b'ID3fixture')
        self.p.new_job([{'path': str(self.src), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        (self.src / 'changed' / 'two.mp3').write_bytes(b'ID3new')
        self.p.new_job(incremental=True)
        self.assertEqual(self.p.directory_states()[str(self.src)], 'check')
        self.assertEqual(self.p.directory_states()[str(self.src / 'stable')], 'check')
        self.p.run(Event(), workers=1)
        self.assertEqual(self.p.snapshot()['counts']['discovered'], 3)
        self.assertEqual(self.p.snapshot()['job']['enumerations'], 1)

    def test_old_scan_evidence_and_reports_are_accessible(self):
        f = self.wav()
        old = self.p.new_job([{'path': str(f), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        old_hash = self.p.file_detail(1)['sha256']
        self.p.new_job()
        self.p.run(Event(), workers=1)
        saved = self.p.snapshot(job_id=old)
        self.assertEqual(saved['job']['id'], old)
        self.assertEqual(saved['files'][0]['sha256'], old_hash)
        report = self.p.export(job_id=old)
        self.assertEqual(json.loads((report / 'audit.json').read_text())['job']['id'], old)

    def test_problem_filter_includes_failed_and_review_files(self):
        self.wav()
        (self.src / 'Unknown Title.mp3').write_bytes(b'ID3bad')
        self.p.new_job([{'path': str(self.src), 'kind': 'break'}])
        self.p.run(Event(), workers=1)
        self.assertEqual(self.p.snapshot(status='PROBLEMS')['filtered_total'], 1)
        self.assertEqual(self.p.snapshot(status='AUDIT_PASS')['filtered_total'], 1)

    def test_real_process_crash_mid_discovery_retains_committed_batch(self):
        for i in range(150):
            (self.src / f'{i}.mp3').write_bytes(b'ID3fixture')
        self.p.new_job([{'path': str(self.src), 'kind': 'karaoke'}])
        marker = self.root / 'discovery-entered'
        code = ('import time\nfrom pathlib import Path\nfrom threading import Event\n'
                'from auditor.store import Project\n'
                f'p=Project({str(self.p.path)!r})\noriginal=p._flush_discovery\n'
                'def hold(*args):\n original(*args)\n'
                f' Path({str(marker)!r}).write_text("entered")\n time.sleep(60)\n'
                'p._flush_discovery=hold\np.run(Event(),workers=1)\n')
        proc = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline and proc.poll() is None:
                time.sleep(.02)
            self.assertTrue(marker.exists(), 'Process never reached committed directory batch')
        finally:
            proc.kill()
            proc.communicate(timeout=5)
        p = Project(self.p.path)
        self.assertEqual(p.snapshot()['counts']['discovered'], 64)
        # Public resume recovers stale leases before enumeration.
        with patch('auditor.media.audio', return_value=media.result('FAIL', 'Generated corrupt fixture')):
            p.run(Event(), workers=1)
        self.assertEqual(p.snapshot()['counts']['discovered'], 150)
        self.assertEqual(p.snapshot()['job']['state'], 'complete')

if __name__ == '__main__':
    unittest.main()
