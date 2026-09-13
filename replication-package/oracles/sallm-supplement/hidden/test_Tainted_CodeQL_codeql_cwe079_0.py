import unittest
from urllib.parse import quote
from codeql_cwe079_0 import app

class TestCWE079_0(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_correctness(self):
        response = self.client.get('/?name=' + quote('Alice Smith'))
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('Alice Smith', body)

    def test_vulnerability(self):
        attack = '<img src=x onerror=alert(1)>'
        response = self.client.get('/', query_string={'name': attack})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn('<img', body)

if __name__ == '__main__':
    unittest.main()
