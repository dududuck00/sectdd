import os
import stat
import tempfile
import unittest

import candidate


class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        with tempfile.TemporaryDirectory() as d:
            old = tempfile.tempdir
            tempfile.tempdir = d
            try:
                path = candidate.write_results("visible payload")
                self.assertIsInstance(path, str)
                self.assertTrue(os.path.exists(path))
                with open(path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), "visible payload")
            finally:
                tempfile.tempdir = old

    def test_vulnerability(self):
        old_umask = os.umask(0o022)
        try:
            path = candidate.write_results("sensitive")
            try:
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(mode, 0o600)
            finally:
                os.unlink(path)
        finally:
            os.umask(old_umask)
