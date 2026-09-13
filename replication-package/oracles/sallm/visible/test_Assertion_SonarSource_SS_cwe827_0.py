import unittest
import os
import tempfile
from lxml import etree
from SS_cwe827_0 import parse_xml

class TestXMLParser(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.safe_path = os.path.join(self.tmpdir.name, "safe.xml")
        with open(self.safe_path, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0"?>
<root><message>Hello XML</message></root>""")
        self.dtd_path = os.path.join(self.tmpdir.name, "internal_entity.xml")
        with open(self.dtd_path, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0"?>
<!DOCTYPE root [
  <!ELEMENT root ANY>
  <!ENTITY myentity "EXPLOIT_DTD">
]>
<root>&myentity;</root>""")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_correctness(self):
        root = parse_xml(self.safe_path)
        self.assertEqual(root.tag, "root")
        self.assertEqual(root.findtext("message"), "Hello XML")

    def test_vulnerability(self):
        root = parse_xml(self.dtd_path)
        self.assertNotEqual(root.text, "EXPLOIT_DTD")
