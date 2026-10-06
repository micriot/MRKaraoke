"""Bounded read-only media checks. No repairs, network, rendering or AI claims."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

EXTENSIONS = {'.zip', '.mp3', '.cdg', '.mp4', '.wav', '.flac', '.m4a', '.mov', '.mpeg', '.mpg', '.avi', '.aac', '.ogg', '.wma'}
MAX_MEMBER = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
INSTRUCTIONS = {1, 2, 6, 20, 24, 28, 30, 31, 38}


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


def result(status, reason, **extra):
    return {'status': status, 'reason': reason, **extra}


def hash_file(path, cancel):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while block := f.read(1024 * 1024):
            check_cancel(cancel)
            h.update(block)
    return h.hexdigest()


def signature(path):
    with open(path, 'rb') as f:
        b = f.read(4096)
    if not b:
        return result('FAIL', 'ZERO BYTE FILE', format='empty')
    fmt = 'unknown'
    if b[:4] in {b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'}:
        fmt = 'zip'
    elif b.startswith(b'ID3') or (len(b) > 1 and b[0] == 255 and b[1] & 224 == 224):
        fmt = 'mp3'
    elif b.startswith(b'fLaC'):
        fmt = 'flac'
    elif b.startswith(b'RIFF') and b[8:12] == b'WAVE':
        fmt = 'wav'
    elif b.startswith(b'RIFF') and b[8:12] == b'AVI ':
        fmt = 'avi'
    elif b[4:8] == b'ftyp':
        fmt = 'iso-media'
    elif b.startswith(b'OggS'):
        fmt = 'ogg'
    elif b.startswith(b'\x00\x00\x01'):
        fmt = 'mpeg'
    elif Path(path).suffix.lower() == '.cdg':
        return result('WARNING', 'CDG has no unique magic signature; packet validation required', format='cdg')
    expected = {'.zip': 'zip', '.mp3': 'mp3', '.flac': 'flac', '.wav': 'wav', '.avi': 'avi', '.mp4': 'iso-media', '.m4a': 'iso-media', '.ogg': 'ogg'}
    mismatch = fmt != 'unknown' and Path(path).suffix.lower() in expected and expected[Path(path).suffix.lower()] != fmt
    return result('WARNING' if fmt == 'unknown' or mismatch else 'PASS', 'Extension/signature mismatch' if mismatch else ('Recognized container signature' if fmt != 'unknown' else 'Unrecognized signature; probe required'), format=fmt)


def filename(path, kind, naming='disc-artist-title'):
    stem = Path(path).stem.strip()
    parts = [p.strip() for p in stem.split(' - ')]
    artist = title = disk = ''
    if kind == 'break' or naming == 'artist-title':
        if len(parts) >= 2:
            artist, title = parts[0], ' - '.join(parts[1:])
        else:
            title = stem
    elif naming == 'title-artist':
        title, artist = (parts[0], ' - '.join(parts[1:])) if len(parts) >= 2 else (stem, '')
    elif len(parts) >= 3:
        if naming == 'disc-title-artist':
            disk, title, artist = parts[0], parts[1], ' - '.join(parts[2:])
        elif naming == 'artist-title-disc':
            artist, title, disk = parts[0], ' - '.join(parts[1:-1]), parts[-1]
        elif naming == 'title-artist-disc':
            title, artist, disk = ' - '.join(parts[:-2]), parts[-2], parts[-1]
        else:
            disk, artist, title = parts[0], parts[1], ' - '.join(parts[2:])
    else:
        title = stem
    issues = []
    unknown = lambda s: not s or bool(re.fullmatch(r'(unknown(?: artist| title)?|untitled|track\s*\d+|song\s*\d+|\d+)', s, re.I))
    if unknown(artist):
        issues.append('UNKNOWN ARTIST')
    if unknown(title):
        issues.append('UNKNOWN TITLE')
    if kind == 'karaoke' and not disk:
        issues.append('MISSING DISK ID')
    elif kind == 'karaoke' and not re.search(r'\d', disk):
        issues.append('CATALOG PREFIX ONLY — VERIFY DISK ID')
    if any(x in stem for x in (' – ', ' — ', ' − ')):
        issues.append('NONCANONICAL SEPARATOR')
    if re.search(r'\b(feat\.?|featuring|ft(?!\.))\b', artist, re.I):
        issues.append('FEATURED ARTIST NEEDS VERIFICATION')
    if re.search(r'[<>:"/\\|?*]', stem):
        issues.append('WINDOWS UNSAFE NAME')
    if len(parts) > 3 and kind == 'karaoke':
        issues.append('AMBIGUOUS EXTRA FIELDS')
    return result('WARNING' if issues else 'PASS', '; '.join(issues) or 'Filename fields parsed; identity not independently verified', artist=artist, title=title, disk_id=disk, issues=issues, naming=naming, evidence='filename only', identity_verified=False)


def _safe_members(z):
    entries = z.infolist()
    if len(entries) > 1000:
        raise ValueError('Archive member count exceeds safety limit')
    if sum(i.file_size for i in entries) > MAX_EXPANDED:
        raise ValueError('Archive expanded size exceeds safety limit')
    for i in entries:
        n = i.filename.replace('\\', '/')
        parts = PurePosixPath(n).parts
        if n.startswith('/') or '..' in parts or re.match(r'^[a-zA-Z]:', n) or stat.S_ISLNK(i.external_attr >> 16):
            raise ValueError('Unsafe archive member path or symlink')
        if i.file_size > MAX_MEMBER or i.file_size / max(i.compress_size, 1) > 1000:
            raise ValueError('Archive expansion exceeds safety limit')
        if i.flag_bits & 1:
            raise NotImplementedError('Encrypted archive requires manual review')
    return entries


def archive(path, cancel):
    try:
        with zipfile.ZipFile(path) as z:
            entries = _safe_members(z)
            members = [{'name': i.filename, 'size': i.file_size, 'compression': i.compress_type, 'utf8': bool(i.flag_bits & 2048)} for i in entries if not i.is_dir()]
            for i in entries:
                if i.is_dir():
                    continue
                with z.open(i) as f:
                    while f.read(1024 * 1024):
                        check_cancel(cancel)
            junk = lambda n: '__MACOSX' in n.replace('\\', '/').split('/') or PurePosixPath(n.replace('\\', '/')).name.startswith('.')
            mp3 = [i.filename for i in entries if i.filename.lower().endswith('.mp3') and not junk(i.filename)]
            cdgs = [i.filename for i in entries if i.filename.lower().endswith('.cdg') and not junk(i.filename)]
            warnings = []
            if len(mp3) != 1 or len(cdgs) != 1:
                return result('FAIL', 'ZIP needs exactly one MP3 and one CDG', members=members, crc='PASS', mp3=mp3, cdg=cdgs)
            if PurePosixPath(mp3[0].replace('\\', '/')).stem != PurePosixPath(cdgs[0].replace('\\', '/')).stem:
                warnings.append('MP3/CDG basename mismatch; identity uncertain')
            if any(junk(i.filename) for i in entries):
                warnings.append('Archive contains hidden/junk entries')
            if any(i.file_size == 0 for i in entries if i.filename in mp3 + cdgs):
                return result('FAIL', 'Zero-byte media component', members=members, crc='PASS', mp3=mp3, cdg=cdgs)
            return result('WARNING' if warnings else 'PASS', '; '.join(warnings) or 'CRC passed; one matching basename pair (identity unverified)', members=members, mp3=mp3, cdg=cdgs, crc='PASS')
    except Cancelled:
        raise
    except (NotImplementedError, UnicodeDecodeError) as e:
        return result('UNKNOWN', f'Unsupported archive encoding/compression: {e}; not a corruption verdict')
    except (ValueError, RuntimeError, zipfile.BadZipFile, EOFError) as e:
        return result('FAIL', str(e))


@contextmanager
def component(path, name, working, cancel):
    """Copy a named member to an owned random file; never use archive paths."""
    if name is None:
        yield Path(path)
        return
    with tempfile.TemporaryDirectory(dir=working, prefix='component-') as td:
        target = Path(td) / ('media' + Path(name).suffix.lower())
        with zipfile.ZipFile(path) as z:
            _safe_members(z)
            with z.open(name) as src, open(target, 'wb') as dst:
                while block := src.read(1024 * 1024):
                    check_cancel(cancel)
                    dst.write(block)
        yield target


def _command(args, cancel, timeout=120):
    """Bound output, time and cancellation without blocking the web server."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        start = time.monotonic()
        try:
            while proc.poll() is None:
                check_cancel(cancel)
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f'Media check exceeded {timeout}s limit')
                if out.tell() > 1024 * 1024 or err.tell() > 1024 * 1024:
                    raise ValueError('Media check output limit exceeded')
                cancel.wait(.05)
            out.seek(0)
            err.seek(0)
            return proc.returncode, out.read(1024 * 1024).decode('utf-8', 'replace'), err.read(4000).decode('utf-8', 'replace')
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def audio(path, cancel):
    # Access errors belong to scan recovery, never to a corruption cache.
    with open(path, 'rb') as source:
        source.read(1)
    ffprobe, ffmpeg = shutil.which('ffprobe'), shutil.which('ffmpeg')
    if not ffprobe or not ffmpeg:
        return result('UNKNOWN', 'Install FFmpeg/ffprobe to test actual audio decoding')
    try:
        code, raw, err = _command([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams', '-of', 'json', str(path)], cancel, 20)
        if code:
            if any(s in err.lower() for s in ('permission denied', 'input/output error', 'operation not permitted')):
                raise OSError(err.strip())
            return result('FAIL', 'No readable audio container found' + (' — MP4 index (moov atom) missing' if 'moov atom not found' in err else ''), diagnostic=err.strip())
        info = json.loads(raw)
        streams = info.get('streams', [])
        aud = next((s for s in streams if s.get('codec_type') == 'audio'), None)
        if not aud:
            return result('FAIL', 'No audio stream found')
        duration = float(info.get('format', {}).get('duration') or aud.get('duration') or 0)
        if duration <= 0:
            return result('FAIL', 'No valid positive audio duration')
        code, _, err = _command([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-map', '0:a:0', '-f', 'null', '-'], cancel)
        fields = {'duration': duration, 'sample_rate': aud.get('sample_rate'), 'channels': aud.get('channels'), 'codec': aud.get('codec_name'), 'bitrate': info.get('format', {}).get('bit_rate'), 'tags': info.get('format', {}).get('tags', {}), 'video_present': any(s.get('codec_type') == 'video' for s in streams), 'decode': 'PASS' if code == 0 else 'FAIL'}
        if code and any(s in err.lower() for s in ('permission denied', 'input/output error', 'operation not permitted')):
            raise OSError(err.strip())
        return result('PASS' if code == 0 else 'FAIL', 'Entire audio stream decoded; playback and loudness not tested' if code == 0 else 'Audio decoding found invalid data; review this file', diagnostic=err.strip(), **fields)
    except Cancelled:
        raise
    except (ValueError, TimeoutError, json.JSONDecodeError) as e:
        return result('UNKNOWN' if isinstance(e, TimeoutError) else 'FAIL', str(e))


def cdg(path, cancel):
    size = Path(path).stat().st_size
    if not size or size % 24:
        return result('FAIL', 'Zero-byte or truncated CDG (24-byte packets required)', size=size)
    packets = graphics = invalid = 0
    colors = set()
    with open(path, 'rb') as f:
        while block := f.read(24 * 4096):
            check_cancel(cancel)
            for off in range(0, len(block), 24):
                p = block[off:off + 24]
                packets += 1
                command, instruction = p[0] & 63, p[1] & 63
                if command == 9:
                    graphics += 1
                    if instruction not in INSTRUCTIONS:
                        invalid += 1
                    if instruction in {1, 2}:
                        colors.add(p[4] & 15)
    if invalid:
        return result('WARNING', 'Unrecognized CDG instructions; review rendering', packets=packets, graphics_packets=graphics, invalid_instructions=invalid, duration=size / 7200)
    if not graphics:
        return result('FAIL', 'No CD+G graphics commands found', packets=packets)
    return result('PASS', 'CDG packet structure parsed; parity, rendering, lyrics and sync not tested', packets=packets, graphics_packets=graphics, duration=size / 7200, background_indexes=sorted(colors))


def companion(path):
    p = Path(path)
    target = '.mp3' if p.suffix.lower() == '.cdg' else '.cdg'
    exact = p.with_suffix(target)
    if exact.is_file() and not exact.is_symlink():
        return exact
    # Case and Unicode aliases are warnings, never silently chosen as a pair.
    return None


def pair(path, is_zip, archive_result=None):
    if is_zip:
        a = archive_result or {}
        if a.get('status') not in {'PASS', 'WARNING'}:
            return result('UNKNOWN', 'Archive checks did not establish a media pair')
        return result(a['status'], a['reason'], evidence='archive structure only', identity_verified=False)
    p = Path(path)
    if p.suffix.lower() not in {'.mp3', '.cdg'}:
        return result('PASS', 'Single media file; MP3/CDG pairing not applicable')
    c = companion(p)
    if not c:
        return result('FAIL' if p.suffix.lower() == '.cdg' else 'WARNING', 'MISSING MP3' if p.suffix.lower() == '.cdg' else 'MISSING CDG — may be intentional audio-only music')
    if c.stat().st_size == 0:
        return result('FAIL', 'Companion is zero bytes', companion=str(c))
    return result('PASS', 'Exact basename companion exists; song identity unverified', companion=str(c), size=c.stat().st_size, mtime_ns=c.stat().st_mtime_ns, identity_verified=False)
