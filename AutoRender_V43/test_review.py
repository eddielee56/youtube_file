"""Offline review, notification and loopback HTTP regressions."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
from urllib.parse import urlencode

import autorender_review as review
import autorender_v43 as scheduler
import review_server


class ReviewWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(scheduler, 'STATE', self.root / 'state.sqlite3'))
        self.stack.enter_context(patch.object(scheduler, 'OUTPUT', self.root / 'out'))
        self.key = 'hotel|test'
        self.movie = self.root / 'preview.mp4'
        self.movie.write_bytes(b'preview-content' * 300)
        self.digest = scheduler.file_sha(self.movie)
        self.facts = {'event_key': self.key, 'title': '<script>example</script>',
                      'source_url': 'https://example.test/terms',
                      'checked_at': '2026-11-19', 'valid_until': '2027-01-01'}
        self.canonical = lambda obj: hashlib.sha256(json.dumps(
            obj, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.receipt = self.root / 'render_receipt.json'
        scheduler.write_json(self.root / 'source_fact_snapshot.json', self.facts)
        scheduler.write_json(self.root / 'six_scene_storyboard.json', {
            'event_key': self.key, 'snapshot_sha256': self.canonical(self.facts),
            'scenes': [{'narration': 'Test narration'}]})
        scheduler.write_json(self.receipt, {
            'event_key': self.key, 'snapshot_sha256': self.canonical(self.facts),
            'narration_sha256': hashlib.sha256(b'Test narration').hexdigest(),
            'mp4_path': str(self.movie)})
        self.mail = Mock()
        self.mail.settings.return_value = {'enabled': True, 'address': 'test@example.test'}
        self.mail.password.return_value = 'fake-app-password'
        self.module = Mock(canonical_sha=self.canonical)
        self.stack.enter_context(patch.object(scheduler, 'load_mod', side_effect=lambda path, name:
            self.mail if Path(path).name == 'autorender_email.py' else self.module))
        self.stack.enter_context(patch.object(scheduler, 'validate_movie', side_effect=lambda path:
            (Path(path).resolve(), scheduler.file_sha(path))))
        with contextlib.closing(review.connect()) as conn:
            scheduler.claim(conn, self.key)
            scheduler.save_preview(conn, self.key, self.movie, self.digest, self.receipt)
            scheduler.complete(conn, self.key, True)
        self.result = {'stage': 'PREVIEW_READY', 'event_key': self.key,
                       'mp4': str(self.movie), 'mp4_sha256': self.digest,
                       'review_status': 'PENDING'}

    def test_queue_contains_review_material(self):
        card = review.review_queue()['items'][0]
        self.assertEqual(card['integrity'], 'OK')
        self.assertEqual(card['narration'], 'Test narration')
        self.assertEqual(card['source_url'], self.facts['source_url'])

    def test_approve_and_reject_keep_audit_history(self):
        review.decide(self.key, self.digest, 'approve')
        review.decide(self.key, self.digest, 'reject', 'Correct the subtitles')
        card = review.review_queue()['items'][0]
        self.assertEqual(card['review_status'], 'CHANGES_REQUESTED')
        self.assertEqual([d['decision'] for d in card['decisions']], ['approve', 'reject'])
        self.assertFalse(review.review_queue()['publication_approved'])

    def test_rejected_preview_can_be_retried_explicitly(self):
        review.decide(self.key, self.digest, 'reject', 'Fix the subtitles')
        scheduler.reset(self.key)
        with contextlib.closing(review.connect()) as conn:
            self.assertEqual(tuple(scheduler.status_for(conn, self.key)), ('FAILED', 0))

    def test_failed_render_can_notify_without_a_preview(self):
        review.queue_notification({'stage': 'RENDER_FAILED', 'event_key': 'other-event',
                                   'exception_type': 'StopV42'})
        self.assertEqual(review.notify()['sent'], 1)
        self.assertIn('StopV42', self.mail.send.call_args.args[1].get_content())

    def test_double_click_records_one_decision(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: review.decide(self.key, self.digest, 'approve'), range(2)))
        self.assertEqual(len(results[-1]['items'][0]['decisions']), 1)

    def test_reject_requires_note(self):
        with self.assertRaises(scheduler.V43Error):
            review.decide(self.key, self.digest, 'reject')

    def test_wrong_version_cannot_be_approved(self):
        with self.assertRaises(scheduler.V43Error):
            review.decide(self.key, 'different-version', 'approve')
        self.movie.write_bytes(b'changed movie')
        with self.assertRaises(scheduler.V43Error):
            review.decide(self.key, self.digest, 'approve')

    def test_narration_tampering_cannot_be_approved(self):
        storyboard = scheduler.read(self.root / 'six_scene_storyboard.json')
        storyboard['scenes'][0]['narration'] = 'changed'
        scheduler.write_json(self.root / 'six_scene_storyboard.json', storyboard)
        with self.assertRaises(scheduler.V43Error):
            review.decide(self.key, self.digest, 'approve')

    def test_notification_replay_sends_once_to_configured_self(self):
        review.queue_notification(self.result)
        review.queue_notification({**self.result, 'stage': 'ALREADY_RENDERED'})
        self.assertEqual(review.notify()['sent'], 1)
        self.assertEqual(review.notify()['status'], 'NO_PENDING')
        self.mail.send.assert_called_once()
        address, message, password = self.mail.send.call_args.args
        self.assertEqual(message['To'], address)
        self.assertNotIn(password, message.as_string())

    def test_notification_setup_failure_remains_retryable(self):
        review.queue_notification(self.result)
        self.mail.password.side_effect = RuntimeError('test credential unavailable')
        self.assertEqual(review.notify()['status'], 'SETUP_FAILED')
        self.mail.password.side_effect = None
        self.mail.password.return_value = 'fake-app-password'
        self.assertEqual(review.notify()['sent'], 1)

    def test_ambiguous_delivery_failure_is_not_resent_automatically(self):
        review.queue_notification(self.result)
        self.mail.send.side_effect = OSError('test SMTP connection lost')
        self.assertEqual(review.notify()['failed'], 1)
        result = review.notify()
        self.assertEqual(result['unresolved'], 1)
        self.assertEqual(self.mail.send.call_count, 1)

    def test_concurrent_notifiers_send_once(self):
        review.queue_notification(self.result)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: review.notify(), range(2)))
        self.mail.send.assert_called_once()

    def test_dry_run_cannot_send_or_modify_delivery_state(self):
        review.queue_notification(self.result)
        result = review.notify(dry_run=True)
        self.assertEqual(result['pending'], 1)
        self.mail.password.assert_not_called()
        self.mail.send.assert_not_called()

    def test_page_escapes_source_content(self):
        markup = review_server.page(review.review_queue(), 'test-token')
        self.assertIn('&lt;script&gt;example&lt;/script&gt;', markup)
        self.assertNotIn('<script>example</script>', markup)

    def test_http_review_and_video_range(self):
        server, token = review_server.make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with self.assertRaises(urllib.error.HTTPError) as response:
            urllib.request.urlopen(base)
        self.assertEqual(response.exception.code, 403)
        with urllib.request.urlopen(base + '/?token=' + token) as response:
            self.assertIn('text/html', response.headers['Content-Type'])
        media = base + '/media?' + urlencode({'token': token, 'event_key': self.key, 'sha256': self.digest})
        with urllib.request.urlopen(urllib.request.Request(media, headers={'Range': 'bytes=0-9'})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), self.movie.read_bytes()[:10])
        body = urlencode({'event_key': self.key, 'sha256': self.digest, 'decision': 'approve'}).encode()
        request = urllib.request.Request(base + '/decision', data=body,
            headers={'Origin': base, 'X-Review-Token': token})
        with urllib.request.urlopen(request) as response:
            self.assertTrue(json.load(response)['saved'])
        self.assertEqual(review.review_queue()['items'][0]['review_status'], 'APPROVED')
        request = urllib.request.Request(base + '/decision', data=body,
            headers={'Origin': 'https://other.example', 'X-Review-Token': token})
        with self.assertRaises(urllib.error.HTTPError) as response:
            urllib.request.urlopen(request)
        self.assertEqual(response.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
