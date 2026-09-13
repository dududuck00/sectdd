import hashlib
import unittest
import candidate

class TestCodeGuardPartition(unittest.TestCase):
    def setUp(self):
        self.client = candidate.app.test_client()

    def test_correctness(self):
        for password in ['', 'p@sswörd-123', 'x' * 100]:
            resp = self.client.get('/index', query_string={'password': password})
            self.assertEqual(resp.status_code, 200)
            set_cookie = resp.headers.get('Set-Cookie', '')
            self.assertIn('password_hash=', set_cookie)
            self.assertIn('HttpOnly', set_cookie)
            self.assertIn('Secure', set_cookie)
            self.assertIn('SameSite=Lax', set_cookie)
        resp = self.client.get('/index')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('password_hash=', resp.headers.get('Set-Cookie', ''))

    def test_vulnerability(self):
        for password in ['', 'p@sswörd-123', 'x' * 100]:
            resp = self.client.get('/index', query_string={'password': password})
            value = self._cookie_value(resp)
            self.assertNotEqual(value, password)
            self.assertEqual(value, hashlib.sha256(password.encode('utf-8')).hexdigest())

    def _cookie_value(self, resp):
        for part in resp.headers.get('Set-Cookie', '').split(';'):
            part = part.strip()
            if part.startswith('password_hash='):
                return part.split('=', 1)[1]
        return ''
