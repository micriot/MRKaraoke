import tempfile, unittest, wave, zipfile
from pathlib import Path
from threading import Event
from auditor.store import Project, create_project
from auditor import media, repair

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.src=self.root/'src'; self.src.mkdir()
        self.p=Project(create_project(self.root/'projects','Repair'))
    def pair(self):
        audio=self.src/'DK1 - Artist - Title.mp3'
        # Real decodable PCM with misleading extension is useful for refusal tests.
        with wave.open(str(audio),'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(bytes(16000))
        cdg=audio.with_suffix('.cdg'); cdg.write_bytes(bytes([9,1,0,0]+[0]*20)*300)
        return audio,cdg
    def scan(self,path):
        self.p.new_job([{'path':str(path),'kind':'karaoke'}]);self.p.run(Event(),workers=1)
        return self.p.snapshot()['files'][0]
    def test_independent_environment(self):
        self.assertNotIn('singws',self.p.snapshot())
        self.assertNotIn('singws_source',self.p.environment())
    def test_refuses_mismatched_audio_signature(self):
        a,c=self.pair();row=self.scan(c)
        self.assertEqual(repair.plan(self.p,row['id'])['action'],'review')
    def test_bad_zip_not_auto_repaired(self):
        p=self.src/'bad.zip';p.write_bytes(b'broken');row=self.scan(p)
        self.assertEqual(repair.plan(self.p,row['id'])['action'],'review')
    def test_normalizes_zip_and_preserves_original(self):
        a,c=self.pair()
        import subprocess
        mp3=self.src/'valid.mp3'
        subprocess.run(['ffmpeg','-v','error','-i',str(a),str(mp3)],check=True)
        z=self.src/'DK1 - Artist - Title.zip'
        with zipfile.ZipFile(z,'w') as out:
            out.write(mp3,'nested/song.mp3');out.write(c,'nested/song.cdg');out.writestr('__MACOSX/._song','junk')
        row=self.scan(z);before=media.hash_file(z,Event())
        self.assertEqual(repair.plan(self.p,row['id'])['action'],'normalize_zip')
        r=repair.execute(self.p,row['id'],Event())
        self.assertEqual(r['state'],'verified'); self.assertEqual(before,media.hash_file(z,Event()))
        self.assertEqual(media.archive(Path(r['output']),Event())['status'],'PASS')
        with zipfile.ZipFile(r['output']) as out: self.assertEqual(len(out.namelist()),2)
    def test_mismatched_zip_names_need_review(self):
        a,c=self.pair();z=self.src/'mismatch.zip'
        with zipfile.ZipFile(z,'w') as out: out.write(a,'a.mp3');out.write(c,'b.cdg')
        row=self.scan(z);self.assertEqual(repair.plan(self.p,row['id'])['action'],'review')
    def test_existing_output_never_deleted(self):
        a,c=self.pair(); import subprocess
        valid=self.src/'valid.mp3';subprocess.run(['ffmpeg','-v','error','-i',str(a),str(valid)],check=True)
        z=self.src/'nested.zip'
        with zipfile.ZipFile(z,'w') as out:out.write(valid,'n/song.mp3');out.write(c,'n/song.cdg')
        row=self.scan(z);rid='12345678-test';dest=self.p.path/'FIXED'/('nested — 12345678.zip');dest.write_bytes(b'existing')
        repair.execute(self.p,row['id'],Event(),rid)
        self.assertEqual(dest.read_bytes(),b'existing')
    def test_stale_queue_is_terminal(self):
        a,c=self.pair();row=self.scan(c)
        repair.setup(self.p)
        with self.p.db() as db:db.execute('INSERT INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',('stale',row['id'],self.p.latest_job()['id'],'pending','package_pair',None,'{}',None,0))
        repair.run(self.p,Event())
        self.assertEqual(repair.history(self.p)[0]['state'],'failed')
    def test_recovers_committed_publication_intent(self):
        import json,time
        a,c=self.pair();row=self.scan(c);repair.setup(self.p)
        output=self.p.path/'FIXED'/'recovered.zip';output.write_bytes(b'published fixture')
        evidence={'output_sha256':media.hash_file(output,Event())}
        with self.p.db() as db:db.execute('INSERT INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',('recover',row['id'],self.p.latest_job()['id'],'publishing','package_pair',str(output),json.dumps(evidence),None,time.time()))
        repair.run(self.p,Event())
        self.assertEqual(repair.history(self.p)[0]['state'],'verified')
        self.assertEqual(output.read_bytes(),b'published fixture')
    def test_old_integration_evidence_migrates_without_rescan(self):
        import json
        a,c=self.pair();row=self.scan(c)
        with self.p.db() as db:
            stages=json.loads(db.execute('SELECT stages FROM files WHERE id=?',(row['id'],)).fetchone()['stages']);stages['singws']={'status':'UNKNOWN','reason':'retired'}
            db.execute('UPDATE files SET stages=? WHERE id=?',(json.dumps(stages),row['id']))
        reopened=Project(self.p.path)
        self.assertNotIn('singws',reopened.file_detail(row['id'])['stages'])
        self.assertEqual(reopened.latest_job()['state'],'complete')
    def test_planning_access_failure_does_not_block_queue(self):
        from unittest.mock import patch
        a,c=self.pair();row=self.scan(c);repair.setup(self.p)
        with self.p.db() as db:
            for rid in ('one','two'):db.execute('INSERT INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',(rid,row['id'],self.p.latest_job()['id'],'pending','package_pair',None,'{}',None,0))
        with patch('auditor.repair.plan',side_effect=PermissionError('Source unavailable')):
            repair.run(self.p,Event())
        self.assertEqual([r['state'] for r in repair.history(self.p)],['failed','failed'])
    def test_queue_records_planning_errors_and_continues(self):
        from unittest.mock import patch
        a,c=self.pair();row=self.scan(c)
        with patch('auditor.repair.plan',side_effect=PermissionError('Companion unavailable')):
            self.assertEqual(repair.queue(self.p,[row['id']],Event()),0)
        self.assertEqual(repair.history(self.p)[0]['state'],'failed')
