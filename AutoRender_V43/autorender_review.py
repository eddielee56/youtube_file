"""Muse-owned repository review records and conversation event handoff."""
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
from urllib.parse import quote

import autorender_v43 as scheduler

CHECKS = ('fact', 'originality', 'copyright', 'sensitive', 'quality')
FACTS = ('headline', 'benefit', 'eligibility', 'deadline', 'caveat',
         'source_url', 'checked_at', 'valid_until')


def repository():
    configuration = scheduler.ROOT / 'runtime_config.json'
    config = scheduler.read(configuration) if configuration.is_file() else {}
    configured = os.environ.get('AUTORENDER_REVIEW_REPO') or config.get('review_repository')
    root = Path(configured).resolve() if configured else scheduler.PROJECT.resolve()
    if not (root / '.git').exists():
        raise scheduler.V43Error('Configure review_repository with the local youtube_file Git checkout')
    return root


def review_path(event_key):
    if not isinstance(event_key, str) or not event_key.strip():
        raise scheduler.V43Error('Review event_key is required')
    # Windows forbids | in filenames. Encoding is reversible and also prevents traversal.
    return repository() / 'reviews' / (quote(event_key, safe='') + '.review.json')


@contextlib.contextmanager
def review_lock(path):
    root = repository()
    gitdir = subprocess.check_output(['git', '-C', str(root), 'rev-parse', '--absolute-git-dir'],
                                    text=True, encoding='utf-8').strip()
    locks = Path(gitdir) / 'autorender-review-locks'
    locks.mkdir(exist_ok=True)
    lock_path = locks / (hashlib.sha256(path.name.encode()).hexdigest() + '.lock')
    with lock_path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def require_fields(obj, names, label):
    if not isinstance(obj, dict) or set(obj) != set(names):
        raise scheduler.V43Error('Invalid fields in ' + label)


def validate(record):
    require_fields(record, ('event_key', 'title', 'program', 'video', 'facts', 'evidence',
                            'checks', 'status', 'decision', 'publication_approved'), 'review')
    for field in ('event_key', 'title', 'program'):
        if not isinstance(record[field], str) or not record[field].strip():
            raise scheduler.V43Error('Review text required: ' + field)
    video = record['video']
    require_fields(video, ('repo_path', 'raw_url', 'duration_s', 'width', 'height', 'version', 'commit_sha'), 'video')
    for field in ('repo_path', 'raw_url', 'version', 'commit_sha'):
        if not isinstance(video[field], str) or not video[field]:
            raise scheduler.V43Error('Video text required: ' + field)
    path = PurePosixPath(video['repo_path'])
    if path.is_absolute() or '..' in path.parts or '\\' in video['repo_path'] or ':' in video['repo_path']:
        raise scheduler.V43Error('Video repo_path must be a repository-relative path')
    if not re.fullmatch(r'[0-9a-f]{40}', video['commit_sha']):
        raise scheduler.V43Error('Video commit_sha must be a full Git commit SHA')
    if (type(video['duration_s']) not in (int, float) or not math.isfinite(video['duration_s'])
            or video['duration_s'] <= 0):
        raise scheduler.V43Error('Video duration must be positive')
    for field in ('width', 'height'):
        if type(video[field]) is not int or video[field] <= 0:
            raise scheduler.V43Error('Video dimensions must be positive integers')
    expected_raw = 'https://raw.githubusercontent.com/eddielee56/youtube_file/' + video['commit_sha'] + '/' + video['repo_path']
    if video['raw_url'] != expected_raw:
        raise scheduler.V43Error('Video raw_url must match its pinned repository path and commit')
    require_fields(record['facts'], FACTS, 'facts')
    if any(not isinstance(value, str) for value in record['facts'].values()):
        raise scheduler.V43Error('Fact fields must contain text')
    for field in ('checked_at', 'valid_until'):
        dt.date.fromisoformat(record['facts'][field])
    if not isinstance(record['evidence'], list):
        raise scheduler.V43Error('Evidence must be a list')
    for item in record['evidence']:
        require_fields(item, ('field', 'official_url', 'excerpt'), 'evidence')
        if any(not isinstance(value, str) for value in item.values()):
            raise scheduler.V43Error('Evidence fields must contain text')
    require_fields(record['checks'], CHECKS, 'checks')
    for item in record['checks'].values():
        require_fields(item, ('status', 'note'), 'check')
        if item['status'] not in ('pass', 'fail', 'pending') or not isinstance(item['note'], str):
            raise scheduler.V43Error('Invalid review check')
    if record['status'] not in ('pending', 'approved', 'returned'):
        raise scheduler.V43Error('Invalid review status')
    require_fields(record['decision'], ('result', 'by', 'at', 'note'), 'decision')
    for field in ('result', 'by', 'at'):
        if record['decision'][field] is not None and not isinstance(record['decision'][field], str):
            raise scheduler.V43Error('Decision fields must contain text or null')
    if not isinstance(record['decision']['note'], str):
        raise scheduler.V43Error('Decision note must contain text')
    if type(record['publication_approved']) is not bool:
        raise scheduler.V43Error('publication_approved must be a boolean')
    if record['publication_approved'] and record['status'] != 'approved':
        raise scheduler.V43Error('Publication approval requires an approved review')
    return record


def read_review(event_key):
    path = review_path(event_key)
    if not path.is_file():
        return None
    record = validate(scheduler.read(path))
    if record['event_key'] != event_key:
        raise scheduler.V43Error('Review filename and event_key disagree')
    return record


def record_matches_movie(record, digest):
    version = record['video']['version']
    if version.startswith('sha256:'):
        return version == 'sha256:' + digest
    content = subprocess.check_output(['git', '-C', str(repository()), 'show',
                                      record['video']['commit_sha'] + ':' + record['video']['repo_path']],
                                     stderr=subprocess.DEVNULL)
    return hashlib.sha256(content).hexdigest() == digest


def build_record(offer, movie, repo_path, commit_sha):
    movie, digest = scheduler.validate_movie(movie)
    content = subprocess.check_output(['git', '-C', str(repository()), 'show', commit_sha + ':' + repo_path],
                                     stderr=subprocess.DEVNULL)
    if hashlib.sha256(content).hexdigest() != digest:
        raise scheduler.V43Error('Local video differs from the pinned GitHub video')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height:format=duration', '-of', 'json', str(movie)],
                           capture_output=True, timeout=30, check=True)
    metadata = json.loads(probe.stdout)
    dimensions = metadata['streams'][0]
    record = {
        'event_key': offer['event_key'], 'title': offer['title'], 'program': offer['program'],
        'video': {'repo_path': repo_path,
                  'raw_url': 'https://raw.githubusercontent.com/eddielee56/youtube_file/' + commit_sha + '/' + repo_path,
                  'duration_s': float(metadata['format']['duration']),
                  'width': dimensions['width'], 'height': dimensions['height'],
                  'version': 'sha256:' + digest, 'commit_sha': commit_sha},
        'facts': {name: offer[name] for name in FACTS},
        'evidence': offer['evidence'],
        'checks': {name: {'status': 'pending', 'note': '待 Muse 審核'} for name in CHECKS},
        'status': 'pending',
        'decision': {'result': 'pending', 'by': None, 'at': None, 'note': '等待 Muse 審核頁決定'},
        'publication_approved': False,
    }
    return validate(record)


def prepare_review(record):
    validate(record)
    if record['status'] != 'pending' or record['publication_approved']:
        raise scheduler.V43Error('New review records must be pending')
    path = review_path(record['event_key'])
    with review_lock(path):
        current = read_review(record['event_key'])
        compared = ('title', 'program', 'video', 'facts', 'evidence')
        if current and all(current[name] == record[name] for name in compared):
            return current
        scheduler.write_json(path, record)
    return record


def import_muse_review(record, expected_version):
    validate(record)
    path = review_path(record['event_key'])
    with review_lock(path):
        current = read_review(record['event_key'])
        if current is None:
            raise scheduler.V43Error('Prepare the video review record before importing a Muse decision')
        if current['video']['version'] != expected_version or record['video'] != current['video']:
            raise scheduler.V43Error('Video version changed; refresh the Muse review page')
        scheduler.write_json(path, record)
    return record


def connect():
    conn = scheduler.db_open()
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS notifications ('
                 'id TEXT PRIMARY KEY, event_key TEXT NOT NULL, stage TEXT NOT NULL, '
                 'payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, '
                 'attempted_at TEXT, sent_at TEXT, error_type TEXT,delivery_transport TEXT,provider_message_id TEXT)')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(notifications)')}
    if 'delivery_transport' not in columns:
        conn.execute('ALTER TABLE notifications ADD COLUMN delivery_transport TEXT')
    return conn


def queue_muse_event(result):
    payload = {name: result.get(name) for name in
               ('event_key', 'stage', 'mp4_sha256', 'review_status', 'reason', 'exception_type')}
    if payload['stage'] in ('ALREADY_RENDERED', 'PREVIEW_REVIEWED'):
        payload['stage'] = 'PREVIEW_READY'
    payload['channel'] = 'muse_conversation'
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    identity = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    with contextlib.closing(connect()) as conn:
        conn.execute('INSERT OR IGNORE INTO notifications '
                     '(id,event_key,stage,payload,status,created_at,delivery_transport) VALUES(?,?,?,?,?,?,?)',
                     (identity, result.get('event_key', 'weekly-selection'), payload['stage'], serialized,
                      'PENDING_MUSE', scheduler.iso_now(), 'muse_conversation'))
        events = [dict(row) for row in conn.execute(
            "SELECT id,payload,status,created_at FROM notifications WHERE delivery_transport='muse_conversation' ORDER BY created_at")]
    for event in events:
        event['payload'] = json.loads(event['payload'])
    handoff = {'channel': 'muse_conversation', 'delivery_status': 'PENDING_MUSE', 'events': events}
    scheduler.write_json(scheduler.OUTPUT / 'muse_events.json', handoff)
    return handoff


def finish(result):
    handoff = queue_muse_event(result)
    print('MUSE_EVENT:', json.dumps(result, ensure_ascii=False))
    print('MUSE_HANDOFF:', scheduler.OUTPUT / 'muse_events.json')
    return handoff
