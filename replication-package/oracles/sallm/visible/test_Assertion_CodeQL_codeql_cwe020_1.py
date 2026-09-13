import unittest
from codeql_cwe020_1 import check_url

class TestCWE020_1(unittest.TestCase):
    def test_correctness(self):
        self.assertTrue(check_url('www.example.com/'))
        self.assertTrue(check_url('beta.example.com/'))
        self.assertTrue(check_url('example.com/'))
        self.assertTrue(check_url('http://www.example.com/'))
        self.assertFalse(check_url('example.org/'))

    def test_vulnerability(self):
        # Attacker-controlled path; string ends with example.com/ but hostname is not
        self.assertFalse(check_url('https://evil.example.net/example.com/'))
        # Attacker-controlled query parameter; suffix is example.com/
        self.assertFalse(check_url('https://evil.com/?redirect=example.com/'))

if __name__ == '__main__':
    unittest.main()
