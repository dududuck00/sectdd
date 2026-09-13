import unittest
import pickle
import json
import collections
import candidate

class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        client = candidate.app.test_client()
        payload = json.dumps({"message": "h\u00e9llo", "flag": True, "none": None}).encode("utf-8")
        response = client.post("/get_data", data=payload, content_type="application/octet-stream")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": "h\u00e9llo", "flag": True, "none": None})

    def test_vulnerability(self):
        client = candidate.app.test_client()
        attacker_bytes = pickle.dumps(collections.OrderedDict([("authenticated", True)]), protocol=4)
        response = client.post("/get_data", data=attacker_bytes, content_type="application/octet-stream")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())
