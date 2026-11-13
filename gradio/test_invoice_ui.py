import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from demo import process_invoice, confirmation_changed, reset_invoice_confirmation
from invoice_ui import progress_for


class FakeResponse:
    headers = {'Content-Type': 'application/x-ndjson'}

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_lines(self, **kwargs):
        for event in self.events:
            yield json.dumps(event).encode()


class InvoiceUITests(unittest.TestCase):
    def fixture(self, folder):
        path = Path(folder) / 'invoice.pdf'
        path.write_bytes(b'local fixture')
        file = SimpleNamespace(name=str(path))
        with patch('demo.start_invoice_job'):
            state = reset_invoice_confirmation(file)[0]
        from invoice_jobs import get_job
        return file, state, get_job(state['job_id'])

    def finish_confirmation(self, state, job):
        from demo import poll_invoice
        job.phase_until = time.monotonic() - .01
        poll_invoice(state)
        view = confirmation_changed(True, state)
        self.assertEqual(job.verification_phase, 'confirming')
        self.assertIsNone(view[2])
        self.assertEqual(view[3], '')
        self.assertAlmostEqual(job.phase_until - time.monotonic(), 5, delta=.2)
        job.phase_until = time.monotonic() - .01
        zero = poll_invoice(state)
        self.assertIn('0%', zero[3])
        self.assertIsNone(zero[2])
        job.progress_started = time.monotonic() - 1
        return poll_invoice(state)

    def test_background_ocr_finishes_while_first_loader_is_visible(self):
        from demo import poll_invoice
        stream = [{'type': 'result', 'resultCode': 'Ok', 'result': {'data': {'invoice_number': 'TEST-1001'}}}]
        with tempfile.TemporaryDirectory() as folder:
            file, state, job = self.fixture(folder)
            self.assertEqual(job.phase_until - job.created, 5)
            with patch('demo.requests.post', return_value=FakeResponse(stream)) as post:
                process_invoice(file, False, 'camoufox', state)
                job.worker.join(2)
                view = poll_invoice(state)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(job.verification_phase, 'preparing')
                self.assertTrue(view[8]['visible'])
                self.assertFalse(view[6]['visible'])
                self.assertIsNone(view[2])
                self.assertEqual(view[3], '')
                released = self.finish_confirmation(state, job)
                self.assertEqual(released[2]['data']['invoice_number'], 'TEST-1001')
                self.assertIn('100%', released[3])
                process_invoice(file, False, 'camoufox', state)
                self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['data']['processing_requested'], 'true')

    def test_checkbox_click_before_first_five_seconds_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            _, state, job = self.fixture(folder)
            confirmation_changed(True, state)
        self.assertEqual(job.verification_phase, 'preparing')
        self.assertFalse(job.confirmed)

    def test_failure_keeps_result_hidden_and_enables_retry(self):
        from demo import poll_invoice
        with tempfile.TemporaryDirectory() as folder:
            file, state, job = self.fixture(folder)
            with patch('demo.requests.post', return_value=FakeResponse([
                {'type': 'result', 'resultCode': 'Error', 'result': 'Service unavailable'}
            ])):
                process_invoice(file, False, 'camoufox', state)
                job.worker.join(2)
            view = poll_invoice(state)
        self.assertIsNone(view[2])
        self.assertEqual(view[5]['value'], 'Retry extraction')

    def test_unconfirmed_finished_result_stays_hidden(self):
        from demo import poll_invoice
        with tempfile.TemporaryDirectory() as folder:
            file, state, job = self.fixture(folder)
            with patch('demo.requests.post', return_value=FakeResponse([
                {'type': 'result', 'resultCode': 'Ok', 'result': {'data': {'total': 55}}}
            ])):
                process_invoice(file, False, 'camoufox', state)
                job.worker.join(2)
            job.phase_until = time.monotonic() - .01
            view = poll_invoice(state)
        self.assertEqual(job.verification_phase, 'awaiting')
        self.assertIn('role="alert"', view[0])
        self.assertIsNone(view[2])
        self.assertEqual(view[1], '')
        self.assertEqual(view[3], '')
        self.assertTrue(view[6]['visible'])

    def test_new_upload_keeps_state_reference_for_periodic_renderer(self):
        with tempfile.TemporaryDirectory() as folder:
            file, state, job = self.fixture(folder)
            original = state
            with patch('demo.start_invoice_job'):
                reset_invoice_confirmation(file, state)
        self.assertIs(original, state)
        self.assertTrue(job.cancelled)

    def test_estimated_progress_waits_for_real_result(self):
        from demo import job_view
        with tempfile.TemporaryDirectory() as folder:
            _, state, job = self.fixture(folder)
            job.verification_phase, job.confirmed = 'verified', True
            job.progress_started, job.progress_duration = time.monotonic() - 30, 10
            job.started, job.running = time.monotonic() - 40, True
            view = job_view(job)
        self.assertIn('95%', view[3])
        self.assertIn('Taking longer than estimated', view[3])
        self.assertIsNone(view[2])


if __name__ == '__main__':
    unittest.main()
