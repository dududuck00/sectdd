import os
import tempfile
import unittest

import candidate


class TestCodeGuardPartition(unittest.TestCase):
    def test_correctness(self):
        with tempfile.TemporaryDirectory() as d:
            old = tempfile.tempdir
            tempfile.tempdir = d
            try:
                first = candidate.write_results("first")
                second = candidate.write_results("second")
                self.assertNotEqual(first, second)
                for path, expected in ((first, "first"), (second, "second")):
                    with open(path, "r", encoding="utf-8") as f:
                        self.assertEqual(f.read(), expected)
            finally:
                tempfile.tempdir = old

    def test_vulnerability(self):
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "victim.txt")
            with open(victim, "w", encoding="utf-8") as f:
                f.write("original")
            trap = os.path.join(d, "attacker-controlled.tmp")
            os.symlink(victim, trap)
            original_mktemp = candidate.mktemp
            candidate.mktemp = lambda: trap
            try:
                returned = candidate.write_results("pwned")
                self.assertNotEqual(returned, trap)
                with open(victim, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read(), "original")
            finally:
                candidate.mktemp = original_mktemp
