import unittest
import os
import tempfile
from pathlib import Path
from lxml import etree
from SS_cwe827_0 import parse_xml

class TestXMLParser(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.safe_path = os.path.join(self.tmpdir.name, "safe.xml")
        with open(self.safe_path, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0"?>
<root id="42"><child attr="value">data</child><child>more</child></root>""")
        self.secret_path = os.path.join(self.tmpdir.name, "secret.txt")
        with open(self.secret_path, "w", encoding="utf-8") as f:
            f.write("TOP_SECRET_FROM_FILE")
        self.xxe_path = os.path.join(self.tmpdir.name, "external_entity.xml")
        uri = Path(self.secret_path).as_uri()
        xml = '<?xml version="1.0"?>\n' \
              '<!DOCTYPE root [\n' \
              '  <!ELEMENT root ANY>\n' \
              '  <!ENTITY xxe SYSTEM "' + uri + '">\n' \
              ']>\n' \
              '<root>&xxe;</root>'
        with open(self.xxe_path, "w", encoding="utf-8") as f:
            f.write(xml)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_correctness(self):
        root = parse_xml(self.safe_path)
        self.assertEqual(root.tag, "root")
        self.assertEqual(root.attrib["id"], "42")
        children = root.findall("child")
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0].text, "data")
        self.assertEqual(children[1].text, "more")

    def test_vulnerability(self):
        root = parse_xml(self.xxe_path)
        self.assertNotIn("TOP_SECRET_FROM_FILE", root.text or "")
