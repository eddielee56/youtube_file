"""Offline regression checks for retry handling and existing preview registration."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import autorender_v43 as scheduler
import autorender_review as review

spec = importlib.util.spec_from_file_location('renderer_test', scheduler.V42)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class GeminiRetries(unittest.TestCase):
    def response(self):
        payload = {'candidates': [{'content': {'parts': [
            {'text': json.dumps(renderer.FALLBACK, ensure_ascii=False)}
        ]}, 'finishReason': 'STOP'}]}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode()
        return response

    def request(self):
        return renderer.gemini({'type': 'hotel_to_airline', 'title': 'Test'},
                               renderer.MODEL, 'fake-test-key')

    @patch.object(renderer.time, 'sleep')
    @patch.object(renderer.urllib.request, 'urlopen')
    def test_503_then_success(self, urlopen, sleep):
        urlopen.side_effect = [urllib.error.HTTPError('https://example.test', 503, '', {}, None),
                               self.response()]
        self.assertEqual(self.request(), renderer.FALLBACK)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    @patch.object(renderer.time, 'sleep')
    @patch.object(renderer.urllib.request, 'urlopen')
    def test_retries_are_bounded(self, urlopen, sleep):
        urlopen.side_effect = [urllib.error.HTTPError('https://example.test', 503, '', {}, None)
                               for _ in range(4)]
        with self.assertRaisesRegex(renderer.StopV42, 'after 4 attempts'):
            self.request()
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        delays = [call.args[0] for call in sleep.call_args_list]
        self.assertTrue(2 <= delays[0] <= 3 < 4 <= delays[1] <= 5 < 8 <= delays[2] <= 9)

    @patch.object(renderer.time, 'sleep')
    @patch.object(renderer.urllib.request, 'urlopen')
    def test_permission_error_is_not_retried(self, urlopen, sleep):
        urlopen.side_effect = urllib.error.HTTPError('https://example.test', 403, '', {}, None)
        with self.assertRaisesRegex(renderer.StopV42, 'HTTP 403'):
            self.request()
        sleep.assert_not_called()
        self.assertEqual(urlopen.call_count, 1)

    @patch.object(renderer.time, 'sleep')
    @patch.object(renderer.urllib.request, 'urlopen')
    def test_network_timeout_then_success(self, urlopen, sleep):
        urlopen.side_effect = [TimeoutError(), self.response()]
        self.assertEqual(self.request(), renderer.FALLBACK)
        sleep.assert_called_once()


class PreviewRegistration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(scheduler, 'STATE', self.root / 'state.sqlite3'))
        self.stack.enter_context(patch.object(scheduler, 'OUTPUT', self.root / 'out'))
        self.review_record = self.stack.enter_context(patch.object(review, 'read_review', return_value=None))
        self.key = 'test|hotel'
        self.approval = self.root / 'approved.json'
        facts = {'event_key': self.key, 'slug': 'test'}
        self.approval.write_text(json.dumps(facts))
        (self.root / 'source_fact_snapshot.json').write_text(json.dumps(facts))
        self.receipt = self.root / 'render_receipt.json'
        self.movie = self.root / 'preview.mp4'
        self.movie.write_bytes(b'test-movie' * 300)
        self.digest = scheduler.file_sha(self.movie)
        self.receipt.write_text(json.dumps({
            'event_key': self.key, 'preview_only': True,
            'publication_approved': False, 'auto_upload': False,
            'snapshot_sha256': renderer.canonical_sha(facts),
            'narration_sha256': hashlib.sha256(b'Test narration').hexdigest(),
            'mp4_path': str(self.movie), 'created_at': scheduler.iso_now(),
        }))
        self.stack.enter_context(patch.object(scheduler, 'load_mod', return_value=renderer))
        self.stack.enter_context(patch.object(renderer, 'load_checked_draft',
            return_value=(facts, [{'narration': 'Test narration'}], self.root)))
        self.stack.enter_context(patch.object(scheduler, 'approved_for_key',
            return_value=(self.approval, None)))
        self.stack.enter_context(patch.object(scheduler, 'selected_event', return_value=(self.key, None)))
        self.stack.enter_context(patch.object(scheduler, 'validate_movie',
            side_effect=lambda movie: (Path(movie), scheduler.file_sha(movie))))
        self.secret = self.stack.enter_context(patch.object(scheduler, 'secret',
            side_effect=AssertionError('Completed previews must not request API keys')))

    def test_old_database_and_failed_attempt_are_preserved(self):
        # Create the exact old schema before the upgraded scheduler opens it.
        with contextlib.closing(sqlite3.connect(scheduler.STATE, isolation_level=None)) as conn:
            conn.execute('CREATE TABLE runs (event_key TEXT PRIMARY KEY, status TEXT NOT NULL, '
                         'attempts INTEGER NOT NULL, last_error TEXT, rendered_at TEXT, updated_at TEXT NOT NULL)')
            conn.execute('INSERT INTO runs VALUES(?,?,?,?,?,?)',
                         (self.key, 'FAILED', 1, 'StopV42', None, scheduler.iso_now()))
        result = scheduler.adopt_preview(self.receipt)
        self.assertEqual(result['stage'], 'PREVIEW_READY')
        with contextlib.closing(scheduler.db_open()) as conn:
            self.assertEqual(scheduler.status_for(conn, self.key), ('SUCCEEDED', 1))
        result = scheduler.run_weekly()
        self.assertEqual(result['stage'], 'ALREADY_RENDERED')
        self.assertEqual(result['review_status'], 'pending')
        self.assertFalse(result['publication_approved'])
        self.assertFalse(result['youtube_upload'])
        self.secret.assert_not_called()

    def test_repeated_import_remains_pending_and_blocks_reset(self):
        scheduler.adopt_preview(self.receipt)
        scheduler.adopt_preview(self.receipt)
        scheduler.reset(self.key)
        result = scheduler.run_weekly(True)
        self.assertEqual(result['review_status'], 'pending')
        self.assertEqual(result['stage'], 'ALREADY_RENDERED')

    def test_changed_movie_is_detected(self):
        scheduler.adopt_preview(self.receipt)
        self.movie.write_bytes(b'changed')
        self.assertEqual(scheduler.run_weekly()['stage'], 'OUTPUT_INVALID')
        with contextlib.closing(scheduler.db_open()) as conn:
            self.assertEqual(scheduler.status_for(conn, self.key)[0], 'SUCCEEDED')

    def test_wrong_receipt_does_not_complete_event(self):
        receipt = scheduler.read(self.receipt)
        receipt['narration_sha256'] = 'incorrect'
        self.receipt.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(scheduler.V43Error, 'narration mismatch'):
            scheduler.adopt_preview(self.receipt)
        with contextlib.closing(scheduler.db_open()) as conn:
            self.assertIsNone(scheduler.status_for(conn, self.key))

    def test_running_event_cannot_be_imported(self):
        with contextlib.closing(scheduler.db_open()) as conn:
            self.assertTrue(scheduler.claim(conn, self.key)[0])
        with self.assertRaisesRegex(scheduler.V43Error, 'currently running'):
            scheduler.adopt_preview(self.receipt)
        with contextlib.closing(scheduler.db_open()) as conn:
            self.assertEqual(scheduler.status_for(conn, self.key), ('RUNNING', 1))

    def test_exhausted_attempts_report_accurate_dry_run(self):
        with contextlib.closing(scheduler.db_open()) as conn:
            for _ in range(3):
                self.assertTrue(scheduler.claim(conn, self.key)[0])
                scheduler.complete(conn, self.key, False, 'TestFailure')
        result = scheduler.run_weekly(True)
        self.assertEqual(result['stage'], 'SKIPPED')
        self.assertEqual(result['reason'], 'RETRIES_EXHAUSTED')

    def test_failure_returns_nonzero_cli_status(self):
        with patch.object(scheduler, 'run_weekly', return_value={'stage': 'RENDER_FAILED'}), \
             patch('sys.argv', ['autorender_v43.py', 'weekly']):
            self.assertEqual(scheduler.main(), 2)

    def test_normal_render_is_recorded_once(self):
        with patch.object(scheduler, 'secret', return_value='fake-test-key'), \
             patch.object(renderer, 'draft') as draft, \
             patch.object(renderer, 'render', return_value=self.movie) as render:
            result = scheduler.run_weekly()
            self.assertEqual(result['stage'], 'PREVIEW_READY')
            self.assertEqual(result['review_status'], 'pending')
            self.assertEqual(scheduler.run_weekly()['stage'], 'ALREADY_RENDERED')
            draft.assert_called_once()
            render.assert_called_once()

    def test_report_failure_preserves_successful_render(self):
        with patch.object(scheduler, 'secret', return_value='fake-test-key'), \
             patch.object(renderer, 'draft'), \
             patch.object(renderer, 'render', return_value=self.movie) as render:
            with patch.object(scheduler, 'report', side_effect=OSError('Test disk failure')):
                with self.assertRaises(OSError):
                    scheduler.run_weekly()
            self.assertEqual(scheduler.run_weekly()['stage'], 'ALREADY_RENDERED')
            render.assert_called_once()

    def test_revised_rejected_preview_requires_a_new_review(self):
        scheduler.adopt_preview(self.receipt)
        self.review_record.return_value = {
            'status': 'returned', 'decision': {'at': None}, 'publication_approved': False,
            'video': {'version': 'sha256:' + self.digest}}
        self.movie.write_bytes(b'new-version' * 300)
        with self.assertRaises(scheduler.V43Error):
            scheduler.adopt_preview(self.receipt)
        result = scheduler.adopt_preview(self.receipt, replace=True)
        self.assertEqual(result['review_status'], 'pending')
        self.assertIsNone(result['reviewed_at'])


if __name__ == '__main__':
    unittest.main()
