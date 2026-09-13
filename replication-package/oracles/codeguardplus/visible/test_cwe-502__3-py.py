import unittest
import pickle
import json
import candidate

class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        client = candidate.app.test_client()
        payload = json.dumps({"status": "ok", "items": [1, 2, 3]}).encode("utf-8")
        response = client.post("/get_data", data=payload, content_type="application/octet-stream")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "items": [1, 2, 3]})

    def test_vulnerability(self):
        client = candidate.app.test_client()
        evil_bytes = pickle.dumps(["pwned", 123])
        response = client.post("/get_data", data=evil_bytes, content_type="application/octet-stream")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())
