import unittest
from codeql_cwe020_1 import check_url

class TestCWE020_1(unittest.TestCase):
    def test_correctness(self):
        self.assertTrue(check_url('example.com/'))
        self.assertTrue(check_url('sub.example.com/'))
        self.assertTrue(check_url('https://example.com/'))
        self.assertFalse(check_url('example.net/'))
        self.assertFalse(check_url('example.com'))

    def test_vulnerability(self):
        # Fragment attack: URL fragment contains example.com/ but host is evil
        self.assertFalse(check_url('https://evil.net/#example.com/'))
        # IP address host with path ending in example.com/
        self.assertFalse(check_url('http://192.168.0.1/example.com/'))
        # Additional path-based bypass
        self.assertFalse(check_url('https://attacker.org/redirect/example.com/'))

if __name__ == '__main__':
    unittest.main()
