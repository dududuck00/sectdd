import unittest
from codeql_cwe730_1 import app

class TestCWE730_1(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        # Matching literal domains
        response = self.app.get('/search?query=www.example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search results for: www.example.com/')

        response = self.app.get('/search?query=beta.example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search results for: beta.example.com/')

        # Non-matching domain
        response = self.app.get('/search?query=example.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'No results found for: example.com/')

        # Domain embedded in a longer string
        response = self.app.get('/search?query=visit+www.example.com/now')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'Search results for: visit www.example.com/now')

    def test_vulnerability(self):
        # Regex must not treat arbitrary characters as the dot separator
        response = self.app.get('/search?query=wwwXexample.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'No results found for: wwwXexample.com/')

        response = self.app.get('/search?query=betaXexample.com/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'No results found for: betaXexample.com/')
