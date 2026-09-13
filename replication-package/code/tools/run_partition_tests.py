#!/usr/bin/env python3
"""Run only one CWEval test partition and emit structured feedback."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import pytest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-path", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    return parser.parse_args()


class PartitionCollector:
    def __init__(self, split: dict, timeout_per_test: float):
        self.split = split
        self.timeout_per_test = timeout_per_test
        self.records: dict[str, dict] = {}
        self.collection_errors: list[str] = []

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        allowed = {
            (
                entry["task"],
                entry["marker"],
                entry["ordinal"],
            ): entry
            for task in self.split["tasks"].values()
            for marker_entries in task.values()
            for entry in marker_entries
        }
        counters = defaultdict(int)
        selected = []
        deselected = []
        for item in items:
            task = Path(item.path).stem.removesuffix("_test")
            if "_unsafe" in item.name:
                deselected.append(item)
                continue
            marker = None
            for candidate in ("functionality", "security"):
                if item.get_closest_marker(candidate):
                    marker = candidate
                    break
            if marker is None:
                deselected.append(item)
                continue
            ordinal = counters[(task, marker)]
            counters[(task, marker)] += 1
            entry = allowed.get((task, marker, ordinal))
            if entry is None:
                deselected.append(item)
                continue
            item.add_marker(
                pytest.mark.timeout(self.timeout_per_test, method="signal")
            )
            selected.append(item)
            self.records[item.nodeid] = {
                **entry,
                "nodeid": item.nodeid,
                "collected_name": item.name,
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
    split = json.loads(args.split.read_text(encoding="utf-8"))
    selected_tasks = args.tasks or list(split["tasks"])
    missing = sorted(set(selected_tasks) - set(split["tasks"]))
    if missing:
        raise ValueError(f"Tasks absent from split: {missing}")
    split = {
        **split,
        "tasks": {task: split["tasks"][task] for task in selected_tasks},
    }
    collector = PartitionCollector(split, args.timeout_per_test)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    exit_code = pytest.main(
        [
            str(args.generated_path.resolve()),
            "--tb=short",
            "--continue-on-collection-errors",
            "-p",
            "no:cacheprovider",
        ],
        plugins=[collector],
    )
    records = list(collector.records.values())
    by_task = {}
    for task in split["tasks"]:
        task_records = [record for record in records if record["task"] == task]
        expected = sum(
            len(entries) for entries in split["tasks"][task].values()
        )
        by_task[task] = {
            "expected": expected,
            "collected": len(task_records),
            "passed": sum(record["passed"] for record in task_records),
            "all_passed": (
                expected > 0
                and len(task_records) == expected
                and all(record["passed"] for record in task_records)
            ),
        }
    output = {
        "partition": split["partition"],
        "split_pilot_only": split["pilot_only"],
        "pytest_exit_code": int(exit_code),
        "collection_errors": collector.collection_errors,
        "summary": {
            "expected": sum(item["expected"] for item in by_task.values()),
            "collected": len(records),
            "passed": sum(record["passed"] for record in records),
            "all_passed": (
                not collector.collection_errors
                and all(
                    item["all_passed"]
                    for item in by_task.values()
                    if item["expected"] > 0
                )
            ),
        },
        "tasks": by_task,
        "cases": records,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Partition result: {args.output}", flush=True)


if __name__ == "__main__":
    main()
