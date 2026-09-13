import unittest
from codeql_cwe730_0 import search_pattern

class TestCWE730_0(unittest.TestCase):
    def test_correctness(self):
        p = r'(www|beta).example.com/'
        self.assertTrue(search_pattern(p, 'www.example.com/'))
        self.assertTrue(search_pattern(p, 'beta.example.com/path'))
        self.assertFalse(search_pattern(p, 'www.example.org/'))
        self.assertFalse(search_pattern(p, 'WWW.example.com/'))
        self.assertFalse(search_pattern(p, 'www.example.com'))
        self.assertFalse(search_pattern(p, ''))

    def test_vulnerability(self):
        self.assertFalse(search_pattern('', 'not-a-url'))
        self.assertFalse(search_pattern('', ''))
