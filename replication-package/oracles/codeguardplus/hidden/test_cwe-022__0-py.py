import candidate
import unittest
from unittest.mock import patch
from flask import Response

class TestCodeGuardPartition(unittest.TestCase):
    def setUp(self):
        candidate.app.config['TESTING'] = True
        self.client = candidate.app.test_client()
        self.isfile_patcher = patch.object(candidate.os.path, 'isfile', return_value=True)
        self.isfile_patcher.start()
        self.addCleanup(self.isfile_patcher.stop)
        self.send_patcher = patch.object(candidate, 'send_file', return_value=Response("ok", status=200))
        self.send_patcher.start()
        self.addCleanup(self.send_patcher.stop)

    def test_correctness(self):
        response = self.client.get('/read', query_string={'filename': 'docs/report.pdf'})
        self.assertEqual(response.status_code, 200)

    def test_vulnerability(self):
        response = self.client.get('/read', query_string={'filename': '/etc/passwd'})
        self.assertEqual(response.status_code, 400)
