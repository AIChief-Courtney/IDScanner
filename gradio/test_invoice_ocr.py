"""Browser workflow tests use a local server, without consuming OCR credits."""
import asyncio
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import invoice_ocr
from app import app


class Site(BaseHTTPRequestHandler):
    credits = 1
    conversion_error = None
    show_limit = False
    verification = False
    reject_verification = False
    verification_delay_ms = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        if self.show_limit:
            self.wfile.write(b'''<input id="clickupload" type="file"><script>function handlefiles() { document.body.insertAdjacentHTML('beforeend', '<div class="modal show">Daily Limit Reached</div>'); } document.querySelector('#clickupload').onchange=handlefiles;</script>''')
            return
        if self.verification:
            handler = '' if self.reject_verification else "document.querySelector('[name=cf-turnstile-response]').value='local-test';document.querySelector('button').classList.remove('disabled')"
            self.wfile.write(('<div class="cf-turnstile" style="width:300px;height:65px" onclick="' + handler + '"><input type="checkbox">Local test checkbox</div><input type="hidden" name="cf-turnstile-response">').encode())
            if self.verification_delay_ms:
                self.wfile.write(('''<script>document.querySelector('.cf-turnstile input').style.visibility='hidden';setTimeout(()=>document.querySelector('.cf-turnstile input').style.visibility='visible',%s);</script>''' % self.verification_delay_ms).encode())
        self.wfile.write(('''<div class="modal" style="display:none">Daily Limit Reached</div><input id="clickupload" type="file">
        <button class="convert_button disabled">Convert</button>
        <script>
        (() => {
        let credits = %s, isProUser = false;
        async function handlefiles() {
            await fetch('/uploadImage', {method:'POST'});
            if (!document.querySelector('.cf-turnstile')) document.querySelector('button').classList.remove('disabled');
        }
        document.querySelector('#clickupload').onchange = handlefiles;
        document.querySelector('button').onclick = () => fetch('/ocrtools', {method:'POST'});
        })();
        </script>''' % self.credits).encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/uploadImage':
            data = {'path': '/uploaded.png'}
        elif self.conversion_error:
            data = {'error': self.conversion_error}
        else:
            data = {'json': {'invoice_number': 'TEST-1001', 'total': 55}, 'filename': 'invoice.xlsx'}
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class InvoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        Site.credits = 1
        Site.conversion_error = None
        Site.show_limit = False
        Site.verification = False
        Site.reject_verification = False
        Site.verification_delay_ms = 0

    def run_browser(self, **options):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'invoice.png'
            path.write_bytes(b'test fixture')
            settings = {'engine': 'chromium', 'auto_verify': False}
            settings.update(options)
            with patch.object(invoice_ocr, 'INVOICE_URL', f'http://127.0.0.1:{self.server.server_port}'):
                return asyncio.run(invoice_ocr.extract_invoice(path, headless=True, timeout=10000, **settings))

    def test_browser_upload_convert_and_json(self):
        result = self.run_browser()
        self.assertEqual(result['data']['invoice_number'], 'TEST-1001')
        self.assertEqual(result['data']['total'], 55)

    def test_zero_internal_credits_does_not_block_guest_upload(self):
        Site.credits = 0
        self.assertEqual(self.run_browser()['data']['total'], 55)

    def test_visible_daily_limit_after_upload(self):
        Site.show_limit = True
        with self.assertRaises(invoice_ocr.InvoiceOCRError) as error:
            self.run_browser()
        self.assertEqual(error.exception.code, 'usage_limit')

    def test_verification_explains_actual_required_action(self):
        Site.verification = True
        with self.assertRaisesRegex(invoice_ocr.InvoiceOCRError, 'Verify you are human') as error:
            self.run_browser()
        self.assertEqual(error.exception.code, 'verification_required')

    def test_opt_in_click_resumes_only_after_button_enabled(self):
        Site.verification = True
        result = self.run_browser(auto_verify=True, verification_timeout=5000)
        self.assertEqual(result['data']['total'], 55)

    def test_widget_not_ready_does_not_consume_click_attempt(self):
        Site.verification = True
        Site.verification_delay_ms = 1200
        messages = []
        result = self.run_browser(auto_verify=True, verification_timeout=5000, progress=messages.append)
        self.assertEqual(result['data']['total'], 55)
        self.assertTrue(any(isinstance(m, str) and 'No attempt was counted' in m for m in messages))
        self.assertTrue(any(isinstance(m, str) and 'click 1/2 delivered' in m for m in messages))

    def test_rejected_click_does_not_report_success(self):
        Site.verification = True
        Site.reject_verification = True
        messages = []
        with self.assertRaises(invoice_ocr.InvoiceOCRError) as error:
            self.run_browser(auto_verify=True, verification_timeout=700, progress=messages.append)
        self.assertEqual(error.exception.code, 'verification_required')
        self.assertNotIn('retry and complete', str(error.exception).lower())
        self.assertFalse(any(isinstance(m, str) and ('ACTION REQUIRED' in m or 'Manual diagnostic' in m) for m in messages))

    def test_camoufox_launch_failure_does_not_switch_engine(self):
        messages = []
        with patch('camoufox.async_api.AsyncCamoufox') as manager:
            manager.return_value.__aenter__.side_effect = invoice_ocr.PlaywrightError('GPU browser failed')
            with self.assertRaises(invoice_ocr.InvoiceOCRError) as error:
                self.run_browser(engine='camoufox', progress=messages.append)
        self.assertEqual(error.exception.code, 'browser_startup')
        self.assertIn('No other browser was used', str(error.exception))
        self.assertFalse(any(isinstance(m, str) and 'Opening Chromium instead' in m for m in messages))

    def test_conversion_failure_is_not_success(self):
        Site.conversion_error = 'daily_limit'
        with self.assertRaisesRegex(invoice_ocr.InvoiceOCRError, 'daily_limit'):
            self.run_browser()

    def test_usage_limit_returns_429(self):
        async def limit(*args, **kwargs):
            raise invoice_ocr.InvoiceOCRError('Daily limit reached.', 'usage_limit')
        with patch('app.extract_invoice', limit):
            response = app.test_client().post('/invoice_ocr', data={
                'file': (io.BytesIO(b'invoice data'), 'bill.pdf')
            })
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json['error_code'], 'usage_limit')

    def test_api_validation_and_cleanup(self):
        client = app.test_client()
        self.assertEqual(client.post('/invoice_ocr').status_code, 400)
        self.assertEqual(client.post('/invoice_ocr', data={'file': (io.BytesIO(b'x'), 'bad.exe')}).status_code, 400)
        saved_paths = []

        async def extract(path, **kwargs):
            saved_paths.append(path)
            self.assertEqual(path.read_bytes(), b'invoice data')
            return {'data': {'total': 55}}

        with patch('app.extract_invoice', extract):
            response = client.post('/invoice_ocr', data={'file': (io.BytesIO(b'invoice data'), 'bill.pdf')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['result']['data']['total'], 55)
        self.assertFalse(saved_paths[0].exists())

    def test_stream_sends_progress_before_result(self):
        async def extract(path, *, progress, **kwargs):
            self.assertTrue(kwargs['auto_verify'])
            self.assertEqual(kwargs['engine'], 'camoufox')
            progress('Uploading invoice...')
            progress('Converting invoice...')
            return {'data': {'total': 55}}
        with patch('app.extract_invoice', extract):
            response = app.test_client().post('/invoice_ocr', data={
                'file': (io.BytesIO(b'invoice data'), 'bill.pdf'), 'stream': 'true'
            })
            events = [json.loads(line) for line in response.data.splitlines()]
        self.assertEqual([e['type'] for e in events], ['progress', 'progress', 'result'])
        self.assertEqual(events[-1]['result']['data']['total'], 55)


if __name__ == '__main__':
    unittest.main()
