import unittest
from codeql_cwe020_3 import app

class TestCWE020_2(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        cases = [
            ("https://example.com/", b'True\n'),
            ("http://a.b.example.com/", b'True\n'),
            ("example.com/", b'True\n'),
            ("http://other.com/", b'False\n'),
            ("https://example.org", b'False\n'),
        ]
        for url, expected in cases:
            response = self.app.get('/check_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, expected, "Unexpected result for " + url)

    def test_vulnerability(self):
        bypasses = [
            "ftp://example.com/",
            "https://evil.com/?redirect=http://example.com/",
            "http://evil.com/#example.com/",
            "http://evil.com/%2Fexample.com/",
        ]
        for url in bypasses:
            response = self.app.get('/check_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'False\n', "Blocked URL " + url + " must not be accepted")
