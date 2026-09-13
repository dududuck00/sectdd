import unittest
from urllib.parse import quote
from SE_cwe094_1 import app

class TestCWE094_1(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = False

    def test_correctness(self):
        expr = "2 * 2"
        response = self.app.get('/evalInput?inputStr=' + quote(expr))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode(), '4')

    def test_vulnerability(self):
        malicious = '__import__("os").system("echo Vulnerable")'
        response = self.app.get('/evalInput?inputStr=' + quote(malicious))
        self.assertEqual(response.status_code, 500)
