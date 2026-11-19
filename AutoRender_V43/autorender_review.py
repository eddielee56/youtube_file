"""Version-bound preview decisions and a durable self-email notification queue."""
import contextlib
from email.message import EmailMessage
import hashlib
from pathlib import Path
import sqlite3

import autorender_v43 as scheduler


def connect():
    conn = scheduler.db_open()
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS review_decisions ('
                 'id INTEGER PRIMARY KEY, event_key TEXT NOT NULL, mp4_sha256 TEXT NOT NULL, '
                 'decision TEXT NOT NULL, note TEXT NOT NULL, decided_at TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS notifications ('
                 'id TEXT PRIMARY KEY, event_key TEXT NOT NULL, stage TEXT NOT NULL, '
                 'payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, '
                 'attempted_at TEXT, sent_at TEXT, error_type TEXT)')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(notifications)')}
    for name in ('delivery_transport', 'provider_message_id'):
        if name not in columns:
            try:
                conn.execute('ALTER TABLE notifications ADD COLUMN ' + name + ' TEXT')
            except sqlite3.OperationalError:
                # Another local process may have performed the same migration.
                if name not in {row[1] for row in conn.execute('PRAGMA table_info(notifications)')}:
                    conn.close()
                    raise
    return conn


def preview_card(row):
    card = dict(row)
    card.update(title=card['event_key'], narration='', source_url='', checked_at='',
                valid_until='', integrity='UNAVAILABLE')
    if not card.get('mp4'):
        return card
    try:
        movie, digest = scheduler.validate_movie(card['mp4'])
        if digest != card['mp4_sha256']:
            raise scheduler.V43Error('Registered movie changed')
        folder = Path(card['receipt']).parent
        receipt = scheduler.read(Path(card['receipt']))
        facts = scheduler.read(folder / 'source_fact_snapshot.json')
        storyboard = scheduler.read(folder / 'six_scene_storyboard.json')
        narration = '\n'.join(scene['narration'] for scene in storyboard['scenes'])
        canonical = scheduler.load_mod(scheduler.V42, 'review_facts').canonical_sha(facts)
        if (receipt['event_key'] != card['event_key'] or facts['event_key'] != card['event_key']
                or storyboard['event_key'] != card['event_key']
                or receipt['snapshot_sha256'] != canonical
                or storyboard['snapshot_sha256'] != canonical
                or receipt['narration_sha256'] != hashlib.sha256(narration.encode('utf-8')).hexdigest()
                or Path(receipt['mp4_path']).resolve() != movie):
            raise scheduler.V43Error('Receipt or storyboard changed')
        card.update(title=facts['title'], narration=narration, source_url=facts['source_url'],
                    checked_at=facts['checked_at'], valid_until=facts['valid_until'], integrity='OK')
    except (OSError, ValueError, KeyError, TypeError, scheduler.V43Error,
            scheduler.subprocess.SubprocessError):
        card['integrity'] = 'INVALID'
    return card


def review_queue():
    with contextlib.closing(connect()) as conn:
        rows = conn.execute('SELECT r.event_key,r.status,r.attempts,r.last_error,r.updated_at, '
                            'p.mp4,p.mp4_sha256,p.receipt,p.review_status,p.reviewed_at '
                            'FROM runs r LEFT JOIN previews p USING(event_key) '
                            'ORDER BY r.updated_at DESC').fetchall()
        decisions = [dict(row) for row in conn.execute(
            'SELECT * FROM review_decisions ORDER BY id')]
        notifications = [dict(row) for row in conn.execute(
            'SELECT id,event_key,stage,status,created_at,attempted_at,sent_at,error_type,delivery_transport,provider_message_id '
            'FROM notifications ORDER BY created_at DESC')]
    cards = [preview_card(row) for row in rows]
    for card in cards:
        card['decisions'] = [decision for decision in decisions
                             if decision['event_key'] == card['event_key']
                             and decision['mp4_sha256'] == card['mp4_sha256']]
    data = {'generated_at': scheduler.iso_now(), 'publication_approved': False,
            'items': cards, 'notifications': notifications}
    scheduler.write_json(scheduler.OUTPUT / 'review_queue.json', data)
    return data


def decide(event_key, digest, decision, note=''):
    if decision not in ('approve', 'reject'):
        raise scheduler.V43Error('Decision must be approve or reject')
    note = note.strip()
    if len(note) > 2000:
        raise scheduler.V43Error('Review note exceeds 2000 characters')
    if decision == 'reject' and not note:
        raise scheduler.V43Error('請填寫退回修改原因')
    status = 'APPROVED' if decision == 'approve' else 'CHANGES_REQUESTED'
    with contextlib.closing(connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            row = conn.execute('SELECT r.event_key,r.status,p.* FROM runs r '
                               'JOIN previews p USING(event_key) WHERE r.event_key=?',
                               (event_key,)).fetchone()
            if row is None or row['status'] != 'SUCCEEDED' or row['mp4_sha256'] != digest:
                raise scheduler.V43Error('Preview version changed; refresh the review page')
            if preview_card(row)['integrity'] != 'OK':
                raise scheduler.V43Error('影片或審核資料已變更，請先檢查檔案')
            previous = conn.execute('SELECT decision,note FROM review_decisions '
                                    'WHERE event_key=? AND mp4_sha256=? ORDER BY id DESC LIMIT 1',
                                    (event_key, digest)).fetchone()
            if previous is None or tuple(previous) != (decision, note):
                stamp = scheduler.iso_now()
                conn.execute('INSERT INTO review_decisions '
                             '(event_key,mp4_sha256,decision,note,decided_at) VALUES(?,?,?,?,?)',
                             (event_key, digest, decision, note, stamp))
                conn.execute('UPDATE previews SET review_status=?,reviewed_at=? WHERE event_key=?',
                             (status, stamp, event_key))
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
    return review_queue()


def queue_notification(result):
    import json
    stage = result['stage']
    if stage not in ('PREVIEW_READY', 'PREVIEW_REVIEWED', 'ALREADY_RENDERED',
                     'RENDER_FAILED', 'OUTPUT_INVALID', 'WAITING_REVIEW'):
        return
    key = result.get('event_key', 'weekly-selection')
    with contextlib.closing(connect()) as conn:
        run = conn.execute('SELECT attempts FROM runs WHERE event_key=?', (key,)).fetchone()
        payload = {name: result.get(name) for name in
                   ('event_key', 'mp4', 'mp4_sha256', 'review_status', 'reason', 'exception_type')}
        payload['event_key'] = key
        payload['attempts'] = run['attempts'] if run else 0
        # A replay of the same completed version produces the same notification ID.
        payload['stage'] = 'PREVIEW_READY' if stage in ('ALREADY_RENDERED', 'PREVIEW_REVIEWED') else stage
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        identity = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
        conn.execute('INSERT OR IGNORE INTO notifications '
                     '(id,event_key,stage,payload,status,created_at) VALUES(?,?,?,?,?,?)',
                     (identity, key, payload['stage'], serialized, 'PENDING', scheduler.iso_now()))


def notification_message(address, payload):
    labels = {'PREVIEW_READY': '成片完成', 'PREVIEW_REVIEWED': '審閱已登錄',
              'RENDER_FAILED': '製片失敗', 'OUTPUT_INVALID': '成片檔案需檢查',
              'WAITING_REVIEW': '等待優惠資料審核'}
    msg = EmailMessage()
    msg['From'] = address
    msg['To'] = address
    msg['Subject'] = '[AutoRender] ' + labels[payload['stage']]
    lines = [labels[payload['stage']], '事件 ' + payload['event_key']]
    if payload.get('mp4'):
        lines.extend(['影片 ' + payload['mp4'], '版本 SHA256 ' + payload['mp4_sha256'],
                      '審閱狀態 ' + str(payload.get('review_status', 'PENDING'))])
    if payload.get('reason'):
        lines.append('原因 ' + payload['reason'])
    if payload.get('exception_type'):
        lines.append('錯誤類型 ' + payload['exception_type'])
    lines.extend(['', '請在這台 Windows 電腦開啟以下檔案進行審閱',
                  str(scheduler.ROOT / 'open_review.cmd'),
                  '', '審閱頁面可播放影片、查看旁白和官方來源，並記錄通過或退回修改。'])
    msg.set_content('\n'.join(lines))
    return msg


def notify(dry_run=False, retry_failed=False):
    import json
    result = {'checked_at': scheduler.iso_now(), 'sent': 0, 'failed': 0,
              'pending': 0, 'dry_run': dry_run}
    with contextlib.closing(connect()) as conn:
        if retry_failed and not dry_run:
            conn.execute("UPDATE notifications SET status='PENDING',error_type=NULL WHERE status='FAILED'")
        pending = conn.execute("SELECT id,payload FROM notifications WHERE status='PENDING' ORDER BY created_at").fetchall()
        result['pending'] = len(pending)
        if dry_run:
            result['status'] = 'DRY_RUN'
            result['messages'] = [json.loads(row['payload']) for row in pending]
            scheduler.write_json(scheduler.OUTPUT / 'notification_preview.json', result)
            return result
        if not pending:
            result['status'] = 'NO_PENDING'
        else:
            try:
                mail = scheduler.load_mod(scheduler.PROJECT / 'AutoRender_V38' / 'autorender_email.py',
                                          'v43_existing_gmail')
                settings = mail.settings()
                if not settings.get('enabled'):
                    raise scheduler.V43Error('Existing Gmail notifications are disabled')
                password = mail.password()
            except Exception as error:
                result.update(status='SETUP_FAILED', error_type=type(error).__name__, failed=len(pending))
                scheduler.write_json(scheduler.OUTPUT / 'last_notification.json', result)
                return result
            for row in pending:
                # Commit the claim before SMTP so concurrent runs cannot send the same item.
                claimed = conn.execute("UPDATE notifications SET status='SENDING',delivery_transport='gmail_smtp',attempted_at=? "
                                       "WHERE id=? AND status='PENDING'",
                                       (scheduler.iso_now(), row['id'])).rowcount
                if not claimed:
                    continue
                try:
                    message = notification_message(settings['address'], json.loads(row['payload']))
                    message['Message-ID'] = '<autorender-' + row['id'] + '@localhost>'
                    mail.send(settings['address'], message, password)
                except Exception as error:
                    conn.execute("UPDATE notifications SET status='FAILED',error_type=? WHERE id=?",
                                 (type(error).__name__, row['id']))
                    result['failed'] += 1
                else:
                    conn.execute("UPDATE notifications SET status='SENT',sent_at=?,error_type=NULL WHERE id=?",
                                 (scheduler.iso_now(), row['id']))
                    result['sent'] += 1
            result['pending'] = conn.execute("SELECT count(*) FROM notifications WHERE status='PENDING'").fetchone()[0]
            result['status'] = 'FAILED' if result['failed'] else 'SENT'
        result['unresolved'] = conn.execute("SELECT count(*) FROM notifications WHERE status IN ('FAILED','SENDING')").fetchone()[0]
        scheduler.write_json(scheduler.OUTPUT / 'last_notification.json', result)
        return result


def finish(result, send=True):
    queue_notification(result)
    delivery = notify(dry_run=not send)
    review_queue()
    print('NOTIFICATION:', delivery['status'])
    return delivery
