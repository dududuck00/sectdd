#!/usr/bin/env python3
"""Run one oracle test file and write structured results without failing outer bwrap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


class ResultCollector:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.collection_errors: list[str] = []

    def pytest_collection_modifyitems(self, session, config, items):
        for item in items:
            markers = [
                marker
                for marker in ("functionality", "security")
                if item.get_closest_marker(marker)
            ]
            self.records[item.nodeid] = {
                "nodeid": item.nodeid,
                "markers": markers,
                "run": False,
                "passed": False,
                "phase": None,
                "failure": None,
            }

    def pytest_runtest_logreport(self, report):
        record = self.records.get(report.nodeid)
        if record is None:
            return
        if report.when == "call":
            record["run"] = True
            record["passed"] = report.passed
            record["phase"] = "call"
            if not report.passed:
                record["failure"] = report.longreprtext
        elif report.failed and report.when in ("setup", "teardown"):
            record["run"] = report.when == "teardown"
            record["passed"] = False
            record["phase"] = report.when
            record["failure"] = report.longreprtext

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors.append(report.longreprtext)


def main() -> None:
    args = parse_args()
    collector = ResultCollector()
    exit_code = pytest.main(
        [
            str(args.test_file.resolve()),
            "--tb=short",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        plugins=[collector],
    )
    cases = list(collector.records.values())
    result = {
        "pytest_exit_code": int(exit_code),
        "collection_errors": collector.collection_errors,
        "cases": cases,
        "summary": {
            "collected": len(cases),
            "run": sum(case["run"] for case in cases),
            "passed": sum(case["passed"] for case in cases),
            "all_passed": (
                bool(cases)
                and not collector.collection_errors
                and all(case["passed"] for case in cases)
            ),
        },
    }
    args.output.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Oracle result: {args.output}", flush=True)


if __name__ == "__main__":
    main()
