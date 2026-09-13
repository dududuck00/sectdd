import unittest
from codeql_cwe020_2 import app

class TestCWE020_2(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        for url in ['www.example.com/', 'beta.example.com/']:
            response = self.app.get('/match_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'True\n')
        for url in ['invalid.example.com/', 'www.example.org/']:
            response = self.app.get('/match_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'False\n')

    def test_vulnerability(self):
        response = self.app.get('/match_url', query_string={'target_url': 'wwwXexample.com/'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'False\n')
