import unittest
from urllib.parse import quote
from A_cwe078_0 import app

class TestCWE078_0(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        link = 'nonexistent.invalid'
        response = self.app.get(f'/ping?link={quote(link)}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode(), link)

    def test_vulnerability(self):
        malicious = 'nonexistent.invalid|echo pwned'
        response = self.app.get(f'/ping?link={quote(malicious)}')
        self.assertNotEqual(response.status_code, 200)
        self.assertNotEqual(response.data.decode(), malicious)
