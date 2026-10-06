"""Independent, deterministic repair of copies with durable evidence. No AI claims."""
import json, os, shutil, tempfile, time, uuid, zipfile, fcntl
from pathlib import Path, PurePosixPath
from . import media


def setup(project):
    with project.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS repairs(id TEXT PRIMARY KEY,file INTEGER,job TEXT,state TEXT,action TEXT,output TEXT,evidence TEXT,error TEXT,updated REAL)')


def history(project, job=None, limit=None):
    setup(project)
    with project.db() as db:
        rows=db.execute('SELECT * FROM repairs'+(' WHERE job=?' if job else '')+' ORDER BY updated DESC'+(' LIMIT '+str(max(1,min(int(limit),100))) if limit is not None else ''), (job,) if job else ()).fetchall()
    return [dict(r, evidence=json.loads(r['evidence'] or '{}')) for r in rows]


def plan(project, fid):
    row=project.file_detail(fid); stages=row['stages']; p=Path(row['path'])
    problems=[{'check':k,'problem':v.get('reason','Check incomplete')} for k,v in stages.items() if not k.startswith('_') and isinstance(v,dict) and v.get('status') in {'FAIL','WARNING','UNKNOWN'}]
    answer={'file':fid,'action':'review','explanation':'No safe automatic repair is established. Review the findings or provide a valid replacement.','problems':problems}
    if row['state'] not in {'complete','failed'} or not row['sha256']:
        answer['explanation']='Finish scanning this file before repair.'; return answer
    if stages.get('audio',{}).get('status')!='PASS':
        answer['explanation']='Audio is missing, unreadable, or not fully checked. A valid replacement may be needed; packaging cannot restore missing sound.';return answer
    if row['kind']=='karaoke' and stages.get('cdg',{}).get('status')=='PASS':
        arc=stages.get('zip',{})
        if arc.get('status') in {'PASS','WARNING'} and len(arc.get('mp3',[]))==len(arc.get('cdg',[]))==1:
            a,c=arc['mp3'][0],arc['cdg'][0]
            if PurePosixPath(a.replace('\\','/')).stem!=PurePosixPath(c.replace('\\','/')).stem:
                answer['explanation']='Audio and lyrics have different names. Confirm that they belong to the same song before pairing.';return answer
            if any('/' in n or '\\' in n for n in (a,c)) or len(arc.get('members',[]))!=2:
                answer.update(action='normalize_zip',explanation='Create a clean ZIP with one matching audio/lyrics pair at the top level, removing extra archive entries. Original media bytes are preserved.');return answer
        if p.suffix.lower()=='.cdg' and stages.get('pair',{}).get('status')=='PASS':
            c=media.companion(p)
            if c and media.signature(c).get('format')=='mp3':
                answer.update(action='package_pair',explanation='Package the exact-name MP3/CDG pair into a checked ZIP copy. Originals stay in place.');return answer
    if not problems:
        answer.update(action='none',explanation='All available independent checks passed. No repair needed; playback and song identity are not verified.')
    return answer


def queue(project, ids=None, cancel=None):
    setup(project);job=project.latest_job()
    if not job or job['state'] in {'running','abandoned'}:raise ValueError('Pause or finish the scan before repairing completed files')
    if ids is None:
        with project.db() as db:ids=[r['id'] for r in db.execute('SELECT id FROM files WHERE job=? AND state IN (\'complete\',\'failed\')',(job['id'],))]
    for record in history(project):
        if record['state']=='verified':
            out=Path(record['output']) if record['output'] else None
            if not out or not out.is_file() or media.hash_file(out,cancel or __import__('threading').Event())!=record['evidence'].get('output_sha256'):
                with project.db() as db:db.execute("UPDATE repairs SET state='failed',error='Verified output missing or changed; eligible for regeneration' WHERE id=?",(record['id'],))
    count=0
    for fid in ids:
        if cancel is not None:media.check_cancel(cancel)
        row=project.file_detail(fid)
        if row['job']!=job['id']:raise ValueError('Select a file from the current scan')
        try:proposal=plan(project,fid)
        except (OSError,ValueError) as e:
            with project.db() as db:db.execute('INSERT INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),fid,row['job'],'failed','review',None,'{}',str(e),time.time()))
            continue
        if proposal['action'] not in {'normalize_zip','package_pair'}:continue
        with project.db() as db:
            if db.execute("SELECT 1 FROM repairs WHERE file=? AND state IN ('pending','running','verified')",(fid,)).fetchone():continue
            db.execute('INSERT INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),fid,job['id'],'pending',proposal['action'],None,json.dumps(proposal),None,time.time()));count+=1
    return count


def execute(project, fid, cancel, repair_id=None):
    setup(project); row=project.file_detail(fid);proposal={'action':'review','explanation':'Planning pending'}
    rid=repair_id or str(uuid.uuid4()); now=time.time()
    with project.db() as db:
        db.execute('INSERT OR IGNORE INTO repairs VALUES(?,?,?,?,?,?,?,?,?)',(rid,fid,row['job'],'running',proposal['action'],None,json.dumps(proposal),None,now))
        db.execute("UPDATE repairs SET state='running',error=NULL,updated=? WHERE id=?",(now,rid))
    source=Path(row['path']); output=None; published=False
    try:
        proposal=plan(project,fid)
        if proposal['action'] not in {'normalize_zip','package_pair'}:raise ValueError(proposal['explanation'])
        media.check_cancel(cancel)
        if media.hash_file(source,cancel)!=row['sha256']:raise ValueError('Original changed since scan; scan changes before repair')
        originals={source:row['sha256']}
        with tempfile.TemporaryDirectory(prefix='repair-',dir=project.path/'WORKING') as td:
            td=Path(td); audio=td/'pair.mp3';cdg=td/'pair.cdg'
            if proposal['action']=='normalize_zip':
                snapshot=td/'original.zip'
                with source.open('rb') as inp,snapshot.open('wb') as dst:
                    while block:=inp.read(1024*1024):media.check_cancel(cancel);dst.write(block)
                if media.hash_file(snapshot,cancel)!=row['sha256']:raise ValueError('Archive snapshot differs from scanned original')
                arc=media.archive(snapshot,cancel)
                if arc['status'] not in {'PASS','WARNING'}:raise ValueError('Archive validation changed')
                with zipfile.ZipFile(snapshot) as z:
                    media._safe_members(z)
                    for member,target in ((arc['mp3'][0],audio),(arc['cdg'][0],cdg)):
                        with z.open(member) as src,target.open('wb') as dst:
                            while block:=src.read(1024*1024):media.check_cancel(cancel);dst.write(block)
            else:
                companion=media.companion(source)
                saved=row['stages'].get('_companion',{})
                if not companion or not saved.get('sha256'):raise ValueError('Companion evidence missing; rescan first')
                originals[companion]=saved['sha256']
                if media.hash_file(companion,cancel)!=saved['sha256']:raise ValueError('Audio companion changed; rescan first')
                for src,target in ((companion,audio),(source,cdg)):
                    with src.open('rb') as inp,target.open('wb') as dst:
                        while block:=inp.read(1024*1024):media.check_cancel(cancel);dst.write(block)
            if proposal['action']=='package_pair':
                if media.hash_file(audio,cancel)!=originals[companion] or media.hash_file(cdg,cancel)!=originals[source]:raise ValueError('Working copy differs from scanned media')
            if media.signature(audio)['format']!='mp3':raise ValueError('Audio bytes are not MP3; refuse misleading packaging')
            checks={'audio':media.audio(audio,cancel),'cdg':media.cdg(cdg,cancel)}
            if any(v['status']!='PASS' for v in checks.values()):raise ValueError('Copied media did not pass verification')
            candidate=td/'verified.zip';stem=source.stem
            with zipfile.ZipFile(candidate,'w',compression=zipfile.ZIP_STORED) as z:
                z.write(audio,stem+'.mp3');z.write(cdg,stem+'.cdg')
            checks['zip']=media.archive(candidate,cancel)
            if checks['zip']['status']!='PASS':raise ValueError('Rebuilt archive failed integrity checks')
            # Verify exact member bytes, not just successful decoding.
            with zipfile.ZipFile(candidate) as z:
                for member,target in ((stem+'.mp3',audio),(stem+'.cdg',cdg)):
                    import hashlib
                    h=hashlib.sha256()
                    with z.open(member) as src:
                        while block:=src.read(1024*1024):media.check_cancel(cancel);h.update(block)
                    if h.hexdigest()!=media.hash_file(target,cancel):raise ValueError('Media bytes changed during packaging')
            for path,digest in originals.items():
                if media.hash_file(path,cancel)!=digest:raise ValueError('Source changed during repair; output not published')
            media.check_cancel(cancel)
            with candidate.open('rb') as f:os.fsync(f.fileno())
            output=project.path/'FIXED'/(stem+' — '+rid[:8]+'.zip')
            evidence={**proposal,'checks':checks,'originals':{str(k):v for k,v in originals.items()},'output_sha256':media.hash_file(candidate,cancel),'limits':'Packaging and decode verified; song identity, rendering and synchronization unverified'}
            with project.db() as db:db.execute("UPDATE repairs SET state='publishing',output=?,evidence=?,updated=? WHERE id=?",(str(output),json.dumps(evidence),time.time(),rid))
            os.link(candidate,output) # atomic no-overwrite publication on same filesystem
            published=True
            fd=os.open(output.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            with project.db() as db:db.execute("UPDATE repairs SET state='verified',output=?,evidence=?,updated=? WHERE id=?",(str(output),json.dumps(evidence),time.time(),rid))
    except media.Cancelled:
        if published and output and output.exists():output.unlink() # only this run's unpublished owned output
        with project.db() as db:db.execute("UPDATE repairs SET state='pending',output=NULL,updated=? WHERE id=?",(time.time(),rid))
        raise
    except Exception as e:
        if published and output and output.exists():output.unlink()
        with project.db() as db:db.execute("UPDATE repairs SET state='failed',error=?,updated=? WHERE id=?",(str(e),time.time(),rid))
    return next(r for r in history(project) if r['id']==rid)


def run(project,cancel):
    with open(project.path / '.worker.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another worker is using this library')
        return _run(project,cancel)


def _run(project,cancel):
    setup(project)
    for record in history(project):
        if record['state'] not in {'publishing','verified'}:continue
        output=Path(record['output']) if record['output'] else None
        valid=bool(output and output.is_file() and media.hash_file(output,cancel)==record['evidence'].get('output_sha256'))
        with project.db() as db:
            if valid:db.execute("UPDATE repairs SET state='verified',updated=? WHERE id=?",(time.time(),record['id']))
            elif output and output.exists():db.execute("UPDATE repairs SET state='failed',error='Output differs from verified evidence; existing file retained',updated=? WHERE id=?",(time.time(),record['id']))
            else:db.execute("UPDATE repairs SET state='pending',output=NULL,updated=? WHERE id=?",(time.time(),record['id']))
    with project.db() as db:db.execute("UPDATE repairs SET state='pending' WHERE state='running'")
    while not cancel.is_set():
        with project.db() as db:row=db.execute("SELECT id,file FROM repairs WHERE state='pending' ORDER BY updated LIMIT 1").fetchone()
        if not row:return
        execute(project,row['file'],cancel,row['id'])


def work(project,cancel,ids=None,resume=False):
    with open(project.path / '.worker.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another worker is using this library')
        if not resume:queue(project,ids,cancel)
        return _run(project,cancel)


def counts(project,job):
    setup(project)
    with project.db() as db:
        return {r['state']:r['n'] for r in db.execute('SELECT state,count(*) AS n FROM repairs WHERE job=? GROUP BY state',(job,))}
