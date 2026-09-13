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
            resp = client.get('/logger?name=Alice')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.data, b'')
            self.assertIn('name: Alice', stream.getvalue())
        finally:
            app.logger.removeHandler(handler)

    def test_vulnerability(self):
        client = app.test_client()
        logs = []
        handler = logging.Handler()
        handler.emit = lambda record: logs.append(record.getMessage())
        app.logger.addHandler(handler)
        try:
            client.get('/logger?name=Alice%0ANewEntry')
            client.get('/logger?name=Bob%0AAnother')
            self.assertTrue(all('\n' not in msg for msg in logs))
        finally:
            app.logger.removeHandler(handler)
