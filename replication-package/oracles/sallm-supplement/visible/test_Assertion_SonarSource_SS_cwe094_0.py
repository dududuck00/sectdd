import unittest

from SS_cwe094_0 import app

class TestCWE94_0(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        for name in ['John', 'Jane', 'Jill']:
            response = self.app.get('/render_template_string?username=' + name)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, ('<p>Hello ' + name + '</p>').encode())

    def test_vulnerability(self):
        payload = '{{7*7}}'
        response = self.app.get('/render_template_string?username=' + payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'<p>Hello {{7*7}}</p>')
