import unittest
from codeql_cwe020_3 import app

class TestCWE020_2(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        valid_urls = [
            "http://example.com/",
            "https://www.example.com/",
            "http://subdomain.example.com/",
        ]
        for url in valid_urls:
            response = self.app.get('/check_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'True\n', "Expected True for " + url)
        invalid_urls = [
            "http://example.net/",
            "www.example.com",
            "http://evil.com/",
        ]
        for url in invalid_urls:
            response = self.app.get('/check_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'False\n', "Expected False for " + url)

    def test_vulnerability(self):
        bypasses = [
            "http://evil.com/example.com/",
            "http://example.com@evil.com/example.com/",
            "http://example.com.evil.com/example.com/",
            "http://evil.com/?next=http://example.com/",
        ]
        for url in bypasses:
            response = self.app.get('/check_url', query_string={'target_url': url})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'False\n', "Rejected URL " + url + " must not be accepted")
