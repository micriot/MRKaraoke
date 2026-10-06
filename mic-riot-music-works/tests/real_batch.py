"""Read-only opt-in real-media validation; never scan the full master tree."""
import hashlib
import json
import statistics
import sys
import time
from itertools import islice
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auditor import media
from auditor.store import Project, create_project

APP = Path(__file__).resolve().parents[1]
KARAOKE = Path('/Volumes/JStewart 1TB MC/KARAOKE/master_Karaoke')
BREAK = Path('/Users/justinstewart/Documents/Mic Riot Karaoke/ntertainment/My Music/Break Music')


def batch():
    songs = []
    # Small specific directories only. No root-wide rglob.
    for p in islice(KARAOKE.glob('*.zip'), 4):
        songs.append({'path': str(p), 'kind': 'karaoke'})
    for p in islice((KARAOKE / 'Z').glob('*.cdg'), 2):
        songs.append({'path': str(p), 'kind': 'karaoke'})
        c = media.companion(p)
        if c:
            songs.append({'path': str(c), 'kind': 'karaoke'})
    videos = KARAOKE / 'BDE_Karaoke lib.' / 'Mstr Karaoke CDG' / 'Party tymt (pm)'
    for p in islice(videos.glob('*.mp4'), 2):
        songs.append({'path': str(p), 'kind': 'karaoke'})
    for ext in ('mp3', 'flac', 'm4a'):
        p = next(BREAK.rglob('*.' + ext), None)
        if p:
            songs.append({'path': str(p), 'kind': 'break'})
    if len(songs) < 9:
        raise RuntimeError('Representative sources unavailable; do not substitute generated media')
    return songs[:25]


def main():
    sources = batch()
    originals = [Path(s['path']) for s in sources]
    before = {str(p): media.hash_file(p, Event()) for p in originals}
    p = Project(create_project(APP / 'Libraries', 'Mic Riot — Actual Sample'))
    p.config(naming='disc-title-artist')
    p.new_job(sources)
    start = time.perf_counter()
    p.run(Event(), workers=2)
    cold = time.perf_counter() - start
    first = p.snapshot()
    start = time.perf_counter()
    p.run(Event(), workers=2)
    resume = time.perf_counter() - start
    p.new_job()
    start = time.perf_counter()
    p.run(Event(), workers=2)
    cached = time.perf_counter() - start
    timings = []
    for _ in range(30):
        start = time.perf_counter()
        p.snapshot()
        timings.append(time.perf_counter() - start)
    after = {str(p): media.hash_file(p, Event()) for p in originals}
    final = p.snapshot()
    exported = p.export()
    evidence = {'project_path': str(p.path), 'sources': sources, 'original_hashes_before': before, 'original_hashes_after': after, 'originals_unchanged': before == after, 'cold_audit_seconds': cold, 'unchanged_resume_seconds': resume, 'new_inventory_cached_audit_seconds': cached, 'snapshot_median_ms': statistics.median(timings) * 1000, 'first_counts': first['counts'], 'counts': final['counts'], 'cache_hits': final['job']['cache_hits'], 'report_path': str(exported), 'checks': [{'path': f['path'], 'outcome': f['outcome'], 'error': f['error'], 'stages': f['stages']} for f in final['files']]}
    (APP / 'docs' / 'Real-Batch-Results.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=True))
    print(json.dumps({k: v for k, v in evidence.items() if k not in {'sources', 'original_hashes_before', 'original_hashes_after', 'checks'}}, indent=2))
    if not evidence['originals_unchanged']:
        raise RuntimeError('Original-preservation test failed')

if __name__ == '__main__':
    main()
