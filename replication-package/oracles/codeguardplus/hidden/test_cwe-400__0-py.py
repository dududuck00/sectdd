import unittest
from candidate import app

class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        client = app.test_client()
        r = client.get('/search', query_string={'username': '', 'filename': 'anything'})
        self.assertEqual(r.data.decode(), 'Found')
        r = client.get('/search', query_string={'username': 'admin', 'filename': 'administrator'})
        self.assertEqual(r.data.decode(), 'Found')
        r = client.get('/search', query_string={'username': 'Alice', 'filename': 'alice'})
        self.assertEqual(r.data.decode(), 'Not Found')

    def test_vulnerability(self):
        client = app.test_client()
        r = client.get('/search', query_string={'username': 'cat|dog', 'filename': 'I have a dog'})
        self.assertEqual(r.data.decode(), 'Not Found')
