"""Regressions for Muse-only review authority and repository writeback."""
import contextlib
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import autorender_review as review
import autorender_v43 as scheduler


class MuseReviews(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(review, 'repository', return_value=self.root))
        self.stack.enter_context(patch.object(scheduler, 'STATE', self.root / 'state.sqlite3'))
        self.stack.enter_context(patch.object(scheduler, 'OUTPUT', self.root / 'output'))
        self.key = 'hotel_transfer|cathay|50|test'
        self.digest = hashlib.sha256(b'test movie').hexdigest()
        commit = 'a' * 40
        repo_path = 'previews/test.mp4'
        self.record = {
            'event_key': self.key, 'title': 'Accor test', 'program': 'ALL Accor x Cathay',
            'video': {'repo_path': repo_path,
                      'raw_url': 'https://raw.githubusercontent.com/eddielee56/youtube_file/' + commit + '/' + repo_path,
                      'duration_s': 50.367, 'width': 540, 'height': 960,
                      'version': 'sha256:' + self.digest, 'commit_sha': commit},
            'facts': {name: '' for name in review.FACTS}, 'evidence': [],
            'checks': {name: {'status': 'pending', 'note': ''} for name in review.CHECKS},
            'status': 'pending', 'decision': {'result': 'pending', 'by': None, 'at': None, 'note': ''},
            'publication_approved': False,
        }
        self.record['facts'].update(checked_at='2026-11-18', valid_until='2027-01-04')
        review.prepare_review(self.record)

    def test_exact_requested_fields_and_encoded_windows_filename(self):
        self.assertEqual(review.validate(review.read_review(self.key)), self.record)
        path = review.review_path(self.key)
        self.assertEqual(path.parent, self.root / 'reviews')
        self.assertEqual(path.name, 'hotel_transfer%7Ccathay%7C50%7Ctest.review.json')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['event_key'], self.key)

    def test_muse_decision_writes_back_to_repository(self):
        updated = copy.deepcopy(self.record)
        updated['status'] = 'approved'
        updated['checks'] = {name: {'status': 'pass', 'note': 'Checked by Muse'} for name in review.CHECKS}
        updated['decision'] = {'result': 'approved', 'by': 'Muse',
                               'at': '2026-11-19T12:00:00+08:00', 'note': 'Approved on Muse page'}
        updated['publication_approved'] = True
        review.import_muse_review(updated, self.record['video']['version'])
        self.assertEqual(review.read_review(self.key), updated)
        review.prepare_review(self.record)
        self.assertEqual(review.read_review(self.key), updated)

    def test_stale_video_cannot_overwrite_current_decision(self):
        updated = copy.deepcopy(self.record)
        updated['video']['version'] = 'different version'
        with self.assertRaises(scheduler.V43Error):
            review.import_muse_review(updated, self.record['video']['version'])
        with self.assertRaises(scheduler.V43Error):
            review.import_muse_review(self.record, 'stale version')
        self.assertEqual(review.read_review(self.key)['status'], 'pending')

    def test_new_version_resets_to_pending(self):
        approved = copy.deepcopy(self.record)
        approved['status'] = 'approved'
        approved['decision']['result'] = 'approved'
        review.import_muse_review(approved, self.record['video']['version'])
        changed = copy.deepcopy(self.record)
        changed['video']['version'] = 'sha256:' + 'b' * 64
        review.prepare_review(changed)
        self.assertEqual(review.read_review(self.key)['status'], 'pending')

    def test_legacy_sqlite_approval_is_ignored(self):
        with contextlib.closing(scheduler.db_open()) as conn:
            scheduler.claim(conn, self.key)
            scheduler.save_preview(conn, self.key, self.root / 'test.mp4', self.digest, self.root / 'receipt.json')
            conn.execute("UPDATE previews SET review_status='APPROVED',reviewed_at='old approval'")
            fields = scheduler.preview_fields(conn, self.key)
        self.assertEqual(fields['review_status'], 'pending')
        self.assertIsNone(fields['reviewed_at'])
        self.assertEqual(fields['review_source'], 'Muse')
        self.assertFalse(fields['publication_approved'])

    def test_only_repo_review_controls_reported_status(self):
        approved = copy.deepcopy(self.record)
        approved['status'] = 'approved'
        approved['decision']['at'] = '2026-11-19T12:00:00+08:00'
        review.import_muse_review(approved, self.record['video']['version'])
        with contextlib.closing(scheduler.db_open()) as conn:
            scheduler.save_preview(conn, self.key, self.root / 'test.mp4', self.digest, self.root / 'receipt.json')
            self.assertEqual(scheduler.preview_fields(conn, self.key)['review_status'], 'approved')
            conn.execute("UPDATE previews SET mp4_sha256='changed'")
            self.assertEqual(scheduler.preview_fields(conn, self.key)['review_status'], 'pending')

    def test_local_reviewed_flag_is_disabled(self):
        with self.assertRaisesRegex(scheduler.V43Error, 'Muse'):
            scheduler.adopt_preview('unused', reviewed=True)

    def test_notifications_are_muse_handoffs_and_do_not_load_gmail(self):
        with patch.object(scheduler, 'load_mod', side_effect=AssertionError('No Gmail module allowed')):
            result = review.finish({'stage': 'RENDER_FAILED', 'event_key': self.key, 'exception_type': 'StopV42'})
            review.finish({'stage': 'RENDER_FAILED', 'event_key': self.key, 'exception_type': 'StopV42'})
        self.assertEqual(result['channel'], 'muse_conversation')
        self.assertEqual(result['delivery_status'], 'PENDING_MUSE')
        events = scheduler.read(scheduler.OUTPUT / 'muse_events.json')['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['status'], 'PENDING_MUSE')

    def test_old_notify_command_cannot_send_mail(self):
        with patch.object(scheduler, 'load_mod', side_effect=AssertionError('No mail')), \
             patch('sys.argv', ['autorender_v43.py', 'notify', '--retry-failed']):
            self.assertEqual(scheduler.main(), 0)

    def test_missing_check_or_invalid_status_is_rejected(self):
        invalid = copy.deepcopy(self.record)
        del invalid['checks']['copyright']
        with self.assertRaises(scheduler.V43Error):
            review.validate(invalid)
        invalid = copy.deepcopy(self.record)
        invalid['checks']['quality']['status'] = 'approved'
        with self.assertRaises(scheduler.V43Error):
            review.validate(invalid)

    def test_unsafe_video_path_is_rejected(self):
        invalid = copy.deepcopy(self.record)
        invalid['video']['repo_path'] = '../private.mp4'
        with self.assertRaises(scheduler.V43Error):
            review.validate(invalid)

    def test_concurrent_preparation_preserves_complete_json(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: review.prepare_review(self.record), range(2)))
        self.assertEqual(review.read_review(self.key), self.record)


if __name__ == '__main__':
    unittest.main()
