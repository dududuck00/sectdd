#!/usr/bin/env python3
"""Build a provisional node-level visible/hidden split for CWEval Python."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-result", type=Path, required=True)
    parser.add_argument("--visible-output", type=Path, required=True)
    parser.add_argument("--hidden-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    return parser.parse_args()


def case_entry(task: str, marker: str, ordinal: int, description: str) -> dict:
    return {
        "case_id": f"{task}:{marker}:{ordinal}",
        "task": task,
        "marker": marker,
        "ordinal": ordinal,
        "description": description,
    }


def main() -> None:
    args = parse_args()
    source = json.loads(args.reference_result.read_text(encoding="utf-8"))
    partitions = {"visible": {}, "hidden": {}}
    audit_tasks = {}

    for test_path, result in sorted(source.items()):
        task = Path(test_path).name.removesuffix("_test.py")
        task_audit = {}
        for marker in ("functionality", "security"):
            descriptions = [
                case["name"]
                for case in result["test_cases"]
                if case["marker"] == marker and "_unsafe" not in case["name"]
            ]
            visible_count = len(descriptions) // 2 if len(descriptions) >= 2 else 0
            entries = [
                case_entry(task, marker, ordinal, description)
                for ordinal, description in enumerate(descriptions)
            ]
            partitions["visible"].setdefault(task, {})[marker] = entries[
                :visible_count
            ]
            partitions["hidden"].setdefault(task, {})[marker] = entries[
                visible_count:
            ]
            task_audit[marker] = {
                "total": len(entries),
                "visible": visible_count,
                "hidden": len(entries) - visible_count,
                "splittable": len(entries) >= 2,
            }
        audit_tasks[task] = task_audit

    common = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(args.reference_result.resolve()),
        "cweval_commit": "e9a2a124c8c53679b6d8d27adfd2f6c40e7576d7",
        "pilot_only": True,
        "policy": (
            "Within each task and marker, the first floor(n/2) collected "
            "cases are visible and the remainder are hidden. A singleton "
            "case remains hidden. Ordinals follow pytest collection order."
        ),
        "warning": (
            "This is an engineering split for pipeline validation, not the "
            "paper-final behavior-family split or independently generated "
            "hidden oracle."
        ),
    }
    for name, output in (
        ("visible", args.visible_output),
        ("hidden", args.hidden_output),
    ):
        payload = {**common, "partition": name, "tasks": partitions[name]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    totals = {}
    for marker in ("functionality", "security"):
        totals[marker] = {
            field: sum(
                task[marker][field] for task in audit_tasks.values()
            )
            for field in ("total", "visible", "hidden")
        }
    singleton_tasks = {
        marker: [
            task
            for task, counts in audit_tasks.items()
            if not counts[marker]["splittable"]
        ]
        for marker in ("functionality", "security")
    }
    audit = {
        **common,
        "task_count": len(audit_tasks),
        "totals": totals,
        "singleton_tasks": singleton_tasks,
        "tasks": audit_tasks,
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Visible split: {args.visible_output.resolve()}")
    print(f"Hidden split: {args.hidden_output.resolve()}")
    print(f"Audit: {args.audit_output.resolve()}")


if __name__ == "__main__":
    main()

