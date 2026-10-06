import tempfile
import unittest
from pathlib import Path
from threading import Event

try:
    from auditor.store import Project, create_project
except ImportError:
    Project = create_project = None


class DurableJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.src = self.root / 'source'
        self.src.mkdir()

    def project(self, name='Customer A'):
        self.assertIsNotNone(create_project, 'Durable project engine is missing')
        return Project(create_project(self.root / 'projects', name))

    def test_discovery_resume_preserves_completed_directories(self):
        (self.src / 'a').mkdir()
        (self.src / 'a' / 'track.mp3').write_bytes(b'ID3sample')
        p = self.project()
        job = p.new_job([{'path': str(self.src), 'kind': 'karaoke'}])
        p.discover_step(Event())
        completed = p.directory_states()
        self.assertEqual(completed[str(self.src)], 'complete')
        p = Project(p.path)
        p.discover_step(Event())
        self.assertEqual(p.directory_states()[str(self.src)], 'complete')
        self.assertEqual(p.snapshot()['job']['id'], job)
        self.assertEqual(p.snapshot()['counts']['discovered'], 1)

    def test_project_isolation_and_original_bytes(self):
        f = self.src / 'Unknown Title.mp3'
        f.write_bytes(b'ID3not audio')
        a, b = self.project(), self.project('Customer B')
        a.new_job([{'path': str(f), 'kind': 'karaoke'}])
        a.run(Event(), workers=1)
        self.assertEqual(a.snapshot()['counts']['discovered'], 1)
        self.assertEqual(b.snapshot()['counts']['discovered'], 0)
        self.assertEqual(f.read_bytes(), b'ID3not audio')

    def test_unchanged_resume_keeps_hash_and_stages(self):
        f = self.src / 'D01 - Artist - Title.mp3'
        f.write_bytes(b'ID3bad')
        p = self.project()
        p.new_job([{'path': str(f), 'kind': 'karaoke'}])
        p.run(Event(), workers=1)
        first = p.file_detail(1)
        p = Project(p.path)
        p.run(Event(), workers=1)
        second = p.file_detail(1)
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(first['stages'], second['stages'])
        self.assertTrue(first['sha256'])

    def test_source_storage_overlap_rejected(self):
        p = self.project()
        with self.assertRaises(ValueError):
            p.new_job([{'path': str(self.root), 'kind': 'karaoke'}])

    def test_stop_before_discovery_keeps_pending(self):
        (self.src / 'one.mp3').write_bytes(b'ID3bad')
        p = self.project()
        p.new_job([{'path': str(self.src), 'kind': 'karaoke'}])
        cancel = Event()
        cancel.set()
        p.run(cancel)
        self.assertFalse(p.snapshot()['job']['discovery_complete'])
        p.run(Event(), workers=1)
        self.assertEqual(p.snapshot()['counts']['discovered'], 1)

if __name__ == '__main__':
    unittest.main()
