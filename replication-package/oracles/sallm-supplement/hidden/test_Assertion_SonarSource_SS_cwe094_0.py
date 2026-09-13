import unittest

from SS_cwe094_0 import app

class TestCWE94_0(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        for name in ['Alice', 'Bob', 'Carol']:
            response = self.app.get('/render_template_string', query_string={'username': name})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, ('<p>Hello ' + name + '</p>').encode())

    def test_vulnerability(self):
        response = self.app.get('/render_template_string', query_string={'username': '{{config}}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'<p>Hello {{config}}</p>')
