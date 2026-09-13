import unittest
from codeql_cwe020_2 import app

class TestCWE020_2(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        response = self.app.get('/match_url?target_url=www.example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'True\n')
        response = self.app.get('/match_url?target_url=beta.example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'True\n')
        response = self.app.get('/match_url?target_url=foo.example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'False\n')

    def test_vulnerability(self):
        response = self.app.get('/match_url?target_url=www.exampleXcom/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'False\n')
