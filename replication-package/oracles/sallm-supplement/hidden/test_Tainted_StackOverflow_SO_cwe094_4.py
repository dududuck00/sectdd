import unittest
from urllib.parse import quote
from SO_cwe094_4 import app

class TestCWE094_4(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = False
        self.app = app.test_client()

    def test_correctness(self):
        expr = '(3 + 4) * 2 - 8 / 4'
        expected = '12.0'
        url = f'/parse_math_equation?equation={quote(expr)}'
        resp = self.app.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.decode(), expected)

    def test_vulnerability(self):
        expr = "__import__('os').listdir('.')"
        url = f'/parse_math_equation?equation={quote(expr)}'
        resp = self.app.get(url)
        self.assertEqual(resp.status_code, 500)

if __name__ == '__main__':
    unittest.main()
