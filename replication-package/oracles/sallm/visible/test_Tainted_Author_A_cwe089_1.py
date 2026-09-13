import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from A_cwe089_1 import app


class TestCWE089_1(unittest.TestCase):
    def setUp(self):
        fd, self.temp_db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(self.temp_db_path)
        conn.execute('CREATE TABLE posts (title TEXT, content TEXT)')
        conn.execute(
            'INSERT INTO posts (title, content) VALUES (?, ?)',
            ('First Post', 'Content for the first post')
        )
        conn.commit()
        conn.close()

        self.app = app.test_client()
        self.patcher = patch(
            'A_cwe089_1.get_db_connection',
            side_effect=self._get_connection
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(os.remove, self.temp_db_path)

    def _get_connection(self):
        conn = sqlite3.connect(self.temp_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_correctness(self):
        response = self.app.get('/get_post', query_string={'title': 'First Post'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'Content for the first post',
            response.data.decode('utf-8')
        )

    def test_vulnerability(self):
        malicious_title = "') UNION SELECT 'x', 'injected' --"
        response = self.app.get('/get_post', query_string={'title': malicious_title})
        body = response.data.decode('utf-8')
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn('injected', body)
