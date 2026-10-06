import tempfile
import unittest
import zipfile
from pathlib import Path
from threading import Event

try:
    from auditor import media
except ImportError:
    media = None


class MediaChecks(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(media, 'Read-only media checks are missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_filename_never_invents_catalog(self):
        r = media.filename(Path('Unknown Artist - Unknown Title.mp3'), 'karaoke', 'artist-title')
        self.assertEqual(r['status'], 'WARNING')
        self.assertFalse(r['disk_id'])
        self.assertIn('MISSING DISK ID', r['issues'])
        self.assertIn('UNKNOWN ARTIST', r['issues'])
        self.assertIn('UNKNOWN TITLE', r['issues'])

    def test_unicode_and_featured_are_preserved(self):
        r = media.filename(Path('ABC123-04 - Beyoncé ft. Artist 2 - Déjà Vu.zip'), 'karaoke', 'disc-artist-title')
        self.assertEqual(r['artist'], 'Beyoncé ft. Artist 2')
        self.assertEqual(r['title'], 'Déjà Vu')
        self.assertEqual(r['disk_id'], 'ABC123-04')

    def test_archive_rejects_path_traversal(self):
        p = self.root / 'bad.zip'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('../song.mp3', b'a')
            z.writestr('../song.cdg', b'b')
        r = media.archive(p, Event())
        self.assertEqual(r['status'], 'FAIL')
        self.assertIn('unsafe', r['reason'].lower())
        self.assertFalse((self.root.parent / 'song.mp3').exists())

    def test_archive_mismatched_pair(self):
        p = self.root / 'mismatch.zip'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('a.mp3', b'ID3audio')
            z.writestr('b.cdg', bytes(24))
        r = media.archive(p, Event())
        self.assertEqual(r['status'], 'WARNING')
        self.assertIn('mismatch', r['reason'].lower())

    def test_cdg_valid_instruction_and_truncation(self):
        p = self.root / 'song.cdg'
        p.write_bytes(bytes([9, 1]) + bytes(22))
        self.assertEqual(media.cdg(p, Event())['status'], 'PASS')
        p.write_bytes(p.read_bytes() + b'x')
        self.assertEqual(media.cdg(p, Event())['status'], 'FAIL')

    def test_audio_corruption_and_zero_bytes(self):
        p = self.root / 'bad.mp3'
        p.write_bytes(b'ID3bad media')
        self.assertEqual(media.audio(p, Event())['status'], 'FAIL')
        p.write_bytes(b'')
        self.assertEqual(media.signature(p)['status'], 'FAIL')

if __name__ == '__main__':
    unittest.main()
