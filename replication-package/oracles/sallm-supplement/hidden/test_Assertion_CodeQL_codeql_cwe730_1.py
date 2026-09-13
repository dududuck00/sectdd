import unittest
from codeql_cwe730_1 import app

class TestCWE730_1(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        # Matching beta.example.com/ with query_string dict
        response = self.app.get('/search', query_string={'query': 'beta.example.com/'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search results for: beta.example.com/')

        # Matching a full URL containing the required substring
        response = self.app.get('/search', query_string={'query': 'http://www.example.com/path'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search results for: http://www.example.com/path')

        # No match without trailing slash
        response = self.app.get('/search', query_string={'query': 'www.example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'No results found for: www.example.com')

    def test_vulnerability(self):
        # Reflected XSS: user-controlled query must be HTML-escaped in both branches
        attack = '<script>alert("XSS")</script>'

        # Matching branch
        response = self.app.get('/search', query_string={'query': attack + 'www.example.com/'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<script>', response.data)
        self.assertIn(b'&lt;script&gt;', response.data)

        # Non-matching branch
        response = self.app.get('/search', query_string={'query': attack})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<script>', response.data)
        self.assertIn(b'&lt;script&gt;', response.data)
