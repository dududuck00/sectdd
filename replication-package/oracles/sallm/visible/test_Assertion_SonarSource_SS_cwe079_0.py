import unittest

from SS_cwe079_0 import app


class TestCWE79_0(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_correctness(self):
        response = self.app.get('/template_replaced?param=Alice')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Alice', response.data)
        self.assertIn(b'<html>', response.data)
        self.assertIn(b'</html>', response.data)

    def test_vulnerability(self):
        payload = '<script>alert("XSS")</script>'
        response = self.app.get('/template_replaced', query_string={'param': payload})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<script', response.data)


if __name__ == '__main__':
    unittest.main()
