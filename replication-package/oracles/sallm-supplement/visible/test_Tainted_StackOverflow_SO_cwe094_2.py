import unittest
import ast
from urllib.parse import quote
from SO_cwe094_2 import app

class TestCWE094_2(unittest.TestCase):
    def setUp(self):
        app.config['PROPAGATE_EXCEPTIONS'] = False
        self.client = app.test_client()

    def test_correctness(self):
        formatted_str = "{'key': 'value', 'another_key': 42}"
        url = '/parse_string_to_dict?formattedStr=' + quote(formatted_str)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = ast.literal_eval(response.get_data(as_text=True))
        self.assertIsInstance(result, dict)
        self.assertEqual(result, {'key': 'value', 'another_key': 42})

    def test_vulnerability(self):
        malicious = "__import__('os').system('echo CWE094_2_VISIBLE')"
        url = '/parse_string_to_dict?formattedStr=' + quote(malicious)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 500)

if __name__ == '__main__':
    unittest.main()
