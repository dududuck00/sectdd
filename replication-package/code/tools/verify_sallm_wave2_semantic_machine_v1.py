#!/usr/bin/env python3
"""Verify the frozen SALLM wave-2 machine semantic review and replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FREEZE = ROOT / "benchmarks/manifests/sallm-wave2-semantic-machine-v1-freeze.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_record(value: dict[str, Any]) -> Path:
    path = (ROOT / value["path"]).resolve()
    path.relative_to(ROOT)
    if not path.is_file():
        raise FileNotFoundError(path)
    if digest(path) != value["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")
    return path


def verify_execution(value: dict[str, Any], expected: tuple[bool, bool], tasks: set[str]) -> None:
    manifest_path = verify_record(value)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise RuntimeError(f"Incomplete execution: {manifest_path}")
    results_path = ROOT / manifest["results"]["path"]
    if digest(results_path) != manifest["results"]["sha256"]:
        raise RuntimeError(f"Results hash mismatch: {results_path}")
    rows = {
        row["task_id"]: row
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
    }
    if set(rows) != tasks:
        raise RuntimeError(f"Unexpected task set: {results_path}")
    for task, row in rows.items():
        pair = (row["functional_pass"], row["security_pass"])
        if pair != expected:
            raise RuntimeError(f"Unexpected state {task} {pair}: {results_path}")


def main() -> None:
    args = parse_args()
    freeze_path = args.freeze.expanduser().resolve()
    freeze_path.relative_to(ROOT)
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze["formal_experiment_ready"] is not False:
        raise RuntimeError("Machine review must not mark the benchmark formally ready")
    if freeze["independent_human_review_complete"] is not False:
        raise RuntimeError("Independent human G7 was incorrectly marked complete")
    if freeze["model_preflight_complete"] is not False:
        raise RuntimeError("Model preflight was incorrectly marked complete")
    for value in freeze["inputs"].values():
        verify_record(value)

    tasks = set(freeze["tasks"])
    rejected = set(freeze["rejected_tasks"])
    if tasks & rejected:
        raise RuntimeError("Accepted and rejected task sets overlap")
    if any(value["decision"]["decision"] != "accept" for value in freeze["tasks"].values()):
        raise RuntimeError("Accepted set contains a non-accept decision")
    if any(value["decision"] != "reject" for value in freeze["rejected_tasks"].values()):
        raise RuntimeError("Rejected set contains a non-reject decision")

    expected = {
        "unsafe_reference": (True, False),
        "safe_reference": (True, True),
        "targeted_mutant": (True, False),
    }
    run_count = 0
    for partition in ("visible", "hidden"):
        if set(freeze["runs"][partition]) != set(expected):
            raise RuntimeError(f"Unexpected modes for {partition}")
        for mode, pair in expected.items():
            records = freeze["runs"][partition][mode]
            if len(records) != freeze["summary"]["repeat_count"]:
                raise RuntimeError(f"Repeat mismatch: {partition} {mode}")
            for record in records:
                verify_execution(record, pair, tasks)
                run_count += 1

    summary = freeze["summary"]
    observation_count = len(tasks) * run_count
    checks = {
        "machine_semantic_accepted_task_count": len(tasks),
        "semantic_rejected_task_count": len(rejected),
        "replay_run_count": run_count,
        "replay_observation_count": observation_count,
        "replay_passed_observation_count": observation_count,
    }
    for name, expected_value in checks.items():
        if summary[name] != expected_value:
            raise RuntimeError(f"Summary mismatch for {name}")

    panel_path = verify_record(freeze["inputs"]["semantic_machine_panel"])
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    if panel["formal_g7_complete"] is not False:
        raise RuntimeError("Panel incorrectly claims formal G7 completion")
    if len(panel["reviewers"]) < 2 or any(item["human_reviewer"] for item in panel["reviewers"]):
        raise RuntimeError("Expected at least two machine-only blinded reviewers")
    for audit in panel["task_audit"].values():
        for review in audit["reviews"].values():
            verify_record(review)

    result = {
        "status": "verified",
        "machine_semantic_accepted_task_count": len(tasks),
        "semantic_rejected_task_count": len(rejected),
        "replay_run_count": run_count,
        "replay_observation_count": observation_count,
        "formal_experiment_ready": False,
        "independent_human_review_complete": False,
        "model_preflight_complete": False,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.relative_to(ROOT)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
