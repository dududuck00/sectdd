#!/usr/bin/env python3
"""Run one projected paper-candidate oracle and emit structured case results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    return parser.parse_args()


class PaperOracleCollector:
    def __init__(self, task: str, task_data: dict, timeout_per_test: float):
        self.task = task
        self.task_data = task_data
        self.timeout_per_test = timeout_per_test
        self.by_name = {
            case["test_name"]: case for case in task_data["cases"]
        }
        self.records: dict[str, dict] = {}
        self.collection_errors: list[str] = []

    def pytest_collection_modifyitems(self, session, config, items):
        selected = []
        deselected = []
        for item in items:
            case = self.by_name.get(item.name)
            if case is None:
                deselected.append(item)
                continue
            item.add_marker(
                pytest.mark.timeout(self.timeout_per_test, method="signal")
            )
            selected.append(item)
            self.records[item.nodeid] = {
                **case,
                "task": self.task,
                "nodeid": item.nodeid,
                "run": False,
                "passed": False,
                "phase": None,
                "failure": None,
            }
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        items[:] = selected

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
    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    if args.task not in projection["tasks"]:
        raise ValueError(f"Task absent from projection: {args.task}")
    task_data = projection["tasks"][args.task]
    collector = PaperOracleCollector(
        args.task, task_data, args.timeout_per_test
    )
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
    expected = len(task_data["cases"])
    result = {
        "schema_version": 1,
        "oracle_set_id": projection["oracle_set_id"],
        "oracle_status": projection["oracle_status"],
        "partition": projection["partition"],
        "task": args.task,
        "pytest_exit_code": int(exit_code),
        "collection_errors": collector.collection_errors,
        "cases": cases,
        "summary": {
            "expected": expected,
            "collected": len(cases),
            "run": sum(case["run"] for case in cases),
            "passed": sum(case["passed"] for case in cases),
            "all_passed": (
                expected > 0
                and len(cases) == expected
                and not collector.collection_errors
                and all(case["passed"] for case in cases)
            ),
        },
    }
    args.output.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Paper-oracle result: {args.output}", flush=True)


if __name__ == "__main__":
    main()
