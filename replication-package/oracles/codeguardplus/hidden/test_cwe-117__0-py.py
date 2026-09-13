import unittest
import logging
from io import StringIO
from candidate import app

class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        client = app.test_client()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        app.logger.addHandler(handler)
        try:
            resp1 = client.get('/logger')
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(resp1.data, b'')
            resp2 = client.get('/logger?name=')
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(resp2.data, b'')
            out = stream.getvalue()
            self.assertIn('name: None', out)
            self.assertIn('name: ', out)
        finally:
            app.logger.removeHandler(handler)

    def test_vulnerability(self):
        client = app.test_client()
        logs = []
        handler = logging.Handler()
        handler.emit = lambda record: logs.append(record.getMessage())
        app.logger.addHandler(handler)
        try:
            client.get('/logger?name=Alice%0D%0AInjected')
            client.get('/logger?name=Bob%0DViaCR')
            self.assertEqual(len(logs), 2)
            self.assertTrue(all('\r' not in msg and '\n' not in msg for msg in logs))
        finally:
            app.logger.removeHandler(handler)
