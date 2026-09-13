#!/usr/bin/env python3
"""Verify hashes and machine gates for the SALLM expansion pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = ROOT / "benchmarks/manifests/sallm-expansion-safe-selection-v1.json"
DEFAULT_PARTITIONED = ROOT / "benchmarks/manifests/sallm-expansion-partitioned-oracle-v1-freeze.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--partitioned", type=Path, default=DEFAULT_PARTITIONED)
    parser.add_argument("--preflight-report", type=Path)
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Verify only the original-oracle qualification selection",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def verify_record(value: dict[str, Any]) -> Path:
    path = (ROOT / value["path"]).resolve()
    path.relative_to(ROOT)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != value["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if len(content) != value["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")
    return path


def verify_execution_record(value: dict[str, Any]) -> Path:
    manifest_path = verify_record(value)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise RuntimeError(f"Execution did not complete: {manifest_path}")
    results = ROOT / manifest["results"]["path"]
    if hashlib.sha256(results.read_bytes()).hexdigest() != manifest["results"]["sha256"]:
        raise RuntimeError(f"Execution result hash mismatch: {results}")
    summary = ROOT / manifest["results"]["summary_path"]
    if not summary.is_file():
        raise RuntimeError(f"Execution summary missing: {summary}")
    return manifest_path


def verify_selection(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    for item in value["inputs"].values():
        verify_record(item)
    for task, item in value["tasks"].items():
        for name in ("safe_reference", "generation_metadata", "targeted_mutant", "mutation_provenance"):
            verify_record(item[name])
        for mode in item["repeat_audit"].values():
            if not mode["stable"] or not mode["passed_gate"]:
                raise RuntimeError(f"Failed selection gate: {task}")
            for observation in mode["observations"]:
                results = ROOT / observation["run"] / "results.jsonl"
                if hashlib.sha256(results.read_bytes()).hexdigest() != observation["results_sha256"]:
                    raise RuntimeError(f"Selection result hash mismatch: {results}")
        passing_indices = [
            observation["candidate_index"]
            for observation in item["screening"]
            if observation["joint_pass"] is True
        ]
        if not passing_indices or item["candidate_index"] != min(passing_indices):
            raise RuntimeError(f"Selection is not the lowest joint-pass index: {task}")
    runs = value["runs"]
    screening = runs["candidate_screening"]
    if len(screening) != 3:
        raise RuntimeError("Expected three candidate screening runs")
    for item in screening.values():
        verify_execution_record(item)
    repeated = runs["repeat_audit"]
    if set(repeated) != {"unsafe_reference", "safe_reference", "targeted_mutant"}:
        raise RuntimeError("Unexpected repeat-audit modes")
    for mode, records in repeated.items():
        if len(records) != value["summary"]["repeat_count"]:
            raise RuntimeError(f"Repeat count mismatch: {mode}")
        for item in records:
            verify_execution_record(item)
    if len(value["tasks"]) != value["summary"]["three_repeat_qualified_task_count"]:
        raise RuntimeError("Selection task count mismatch")
    if len(value["tasks"]) + len(value["rejected_tasks"]) != value["summary"]["requested_task_count"]:
        raise RuntimeError("Qualified/rejected task accounting mismatch")
    return value


def verify_partitioned(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    for item in value["inputs"].values():
        verify_record(item)
    for task, item in value["tasks"].items():
        for name in (
            "visible_oracle",
            "hidden_oracle",
            "prompt",
            "safe_reference",
            "targeted_mutant",
        ):
            verify_record(item[name])
        visible = set(item["families"]["visible"].values())
        hidden = set(item["families"]["hidden"].values())
        if visible & hidden:
            raise RuntimeError(f"Behavior-family overlap: {task}")
        for partition in item["repeat_audit"].values():
            for mode in partition.values():
                if not mode["stable"] or not mode["passed_gate"]:
                    raise RuntimeError(f"Failed partition gate: {task}")
                for observation in mode["observations"]:
                    results = ROOT / observation["run"] / "results.jsonl"
                    if hashlib.sha256(results.read_bytes()).hexdigest() != observation["results_sha256"]:
                        raise RuntimeError(f"Partition result hash mismatch: {results}")
    summary = value["summary"]
    if len(value["tasks"]) != summary["partition_repeat_qualified_task_count"]:
        raise RuntimeError("Partition task count mismatch")
    if summary["behavior_family_overlap_count"] != 0:
        raise RuntimeError("Behavior-family overlap count is nonzero")
    repeat_count = summary["repeat_count"]
    runs = value["runs"]
    if set(runs) != {"visible", "hidden"}:
        raise RuntimeError("Unexpected partition run set")
    expected_modes = {"unsafe_reference", "safe_reference", "targeted_mutant"}
    formal_run_count = 0
    for partition, partition_runs in runs.items():
        if set(partition_runs) != expected_modes:
            raise RuntimeError(f"Unexpected run modes: {partition}")
        for mode, records in partition_runs.items():
            if len(records) != repeat_count:
                raise RuntimeError(f"Partition repeat count mismatch: {partition} {mode}")
            formal_run_count += len(records)
            for item in records:
                verify_execution_record(item)
    expected_observations = len(value["tasks"]) * formal_run_count
    if "formal_run_count" in summary and summary["formal_run_count"] != formal_run_count:
        raise RuntimeError("Formal run count mismatch")
    if (
        "formal_task_observation_count" in summary
        and summary["formal_task_observation_count"] != expected_observations
    ):
        raise RuntimeError("Formal task-observation count mismatch")
    return value


def verify_preflight(path: Path, partitioned: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text())
    for item in value["inputs"].values():
        verify_record(item["run_manifest"])
        verify_record(item["summary"])
    if set(value["qualified_tasks"]) - set(partitioned["tasks"]):
        raise RuntimeError("Preflight qualified an unknown partitioned task")
    for task in value["qualified_tasks"]:
        if not value["task_audit"][task]["passed_preflight"]:
            raise RuntimeError(f"Preflight task is not marked passed: {task}")
    return value


def main() -> None:
    args = parse_args()
    selection_path = args.selection.expanduser().resolve()
    selection_path.relative_to(ROOT)
    selection = verify_selection(selection_path)
    result = {
        "status": "verified",
        "original_oracle_qualified_task_count": len(selection["tasks"]),
        "original_oracle_rejected_task_count": len(selection["rejected_tasks"]),
        "formal_experiment_ready": selection["formal_experiment_ready"],
    }
    if not args.selection_only:
        partitioned_path = args.partitioned.expanduser().resolve()
        partitioned_path.relative_to(ROOT)
        partitioned = verify_partitioned(partitioned_path)
        result["partition_qualified_task_count"] = len(partitioned["tasks"])
        result["independent_semantic_review"] = partitioned["review"]["status"]
        if args.preflight_report:
            preflight_path = args.preflight_report.expanduser().resolve()
            preflight_path.relative_to(ROOT)
            preflight = verify_preflight(preflight_path, partitioned)
            result["preflight_qualified_task_count"] = len(preflight["qualified_tasks"])
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.relative_to(ROOT)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
