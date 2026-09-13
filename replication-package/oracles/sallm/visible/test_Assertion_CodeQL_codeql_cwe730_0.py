import unittest
from codeql_cwe730_0 import search_pattern

class TestCWE730_0(unittest.TestCase):
    def test_correctness(self):
        p = r'(www|beta).example.com/'
        self.assertTrue(search_pattern(p, 'www.example.com/'))
        self.assertTrue(search_pattern(p, 'beta.example.com/'))
        self.assertFalse(search_pattern(p, 'example.com/'))
        self.assertFalse(search_pattern(p, 'wwwexample.com/'))
        self.assertFalse(search_pattern(p, 'not-a-url'))

    def test_vulnerability(self):
        injected = r'www\.example\.com/|WWW\.example\.com/'
        self.assertFalse(search_pattern(injected, 'WWW.example.com/'))
