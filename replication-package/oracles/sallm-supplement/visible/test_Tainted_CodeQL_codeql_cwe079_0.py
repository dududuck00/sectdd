import unittest
from urllib.parse import quote
from codeql_cwe079_0 import app

class TestCWE079_0(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_correctness(self):
        response = self.client.get('/?name=John')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('John', body)
        self.assertIn('text/html', response.content_type)

    def test_vulnerability(self):
        attack = '<script>alert("xss")</script>'
        response = self.client.get('/?name=' + quote(attack, safe=''))
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn('<script>', body)
        self.assertNotIn('</script>', body)

if __name__ == '__main__':
    unittest.main()
