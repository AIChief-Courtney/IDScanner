import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from proxy_settings import parse_proxy_url, load_proxy_settings


class ProxyTests(unittest.TestCase):
    def test_evomi_host_first_format(self):
        result = parse_proxy_url(r'http\://dcp.evomi.com:2000:testuser:testpass')
        self.assertEqual(result, {'server': 'http://dcp.evomi.com:2000', 'username': 'testuser', 'password': 'testpass'})

    def test_standard_url_encoded_authentication(self):
        result = parse_proxy_url('http://user%40name:p%3Ass@proxy.example:8000')
        self.assertEqual(result['username'], 'user@name')
        self.assertEqual(result['password'], 'p:ss')
        self.assertNotIn('user', result['server'])

    def test_locked_session_is_stable_across_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'proxy.json'
            path.write_text(json.dumps({'server': 'http://dcp.evomi.com:2000', 'username': 'testuser', 'password': 'testpass', 'evomi_locked_session': 'invoice01'}))
            with patch('proxy_settings.PROXY_FILE', path), patch.dict('os.environ', {}, clear=True):
                first, second = load_proxy_settings(), load_proxy_settings()
            self.assertEqual(first, second)
            self.assertEqual(first['password'], 'testpass_lockedsession-invoice01')

    def test_empty_environment_override_disables_proxy(self):
        with patch.dict('os.environ', {'INVOICE_PROXY_URL': ''}):
            self.assertIsNone(load_proxy_settings())

    def test_invalid_port_rejected(self):
        with self.assertRaises(ValueError):
            parse_proxy_url('http://proxy.example:99999')


if __name__ == '__main__':
    unittest.main()
