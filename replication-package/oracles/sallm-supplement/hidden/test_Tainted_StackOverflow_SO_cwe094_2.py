import unittest
import ast
import os
import tempfile
from urllib.parse import quote
from SO_cwe094_2 import app

class TestCWE094_2(unittest.TestCase):
    def setUp(self):
        app.config['PROPAGATE_EXCEPTIONS'] = False
        self.client = app.test_client()

    def test_correctness(self):
        formatted_str = "{'nested': {'a': [1, 2], 'b': True}, 'c': None}"
        url = '/parse_string_to_dict?formattedStr=' + quote(formatted_str)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        result = ast.literal_eval(response.get_data(as_text=True))
        self.assertEqual(result, {'nested': {'a': [1, 2], 'b': True}, 'c': None})

    def test_vulnerability(self):
        tmpdir = tempfile.mkdtemp(prefix='cwe094_hidden_')
        target = os.path.join(tmpdir, 'pwned.txt')
        try:
            payload = "open({0!r}, 'w').write('PWNED')".format(target)
            url = '/parse_string_to_dict?formattedStr=' + quote(payload)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 500)
            self.assertFalse(os.path.exists(target))
        finally:
            if os.path.exists(target):
                os.remove(target)
            os.rmdir(tmpdir)

if __name__ == '__main__':
    unittest.main()
