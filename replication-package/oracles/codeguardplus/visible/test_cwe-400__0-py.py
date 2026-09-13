import unittest
from candidate import app

class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        client = app.test_client()
        r = client.get('/search', query_string={'username': 'alice', 'filename': 'alice.txt'})
        self.assertEqual(r.data.decode(), 'Found')
        r = client.get('/search', query_string={'username': 'bob', 'filename': 'alice.txt'})
        self.assertEqual(r.data.decode(), 'Not Found')

    def test_vulnerability(self):
        client = app.test_client()
        r = client.get('/search', query_string={'username': '(', 'filename': 'text (with parens)'})
        self.assertEqual(r.data.decode(), 'Found')
