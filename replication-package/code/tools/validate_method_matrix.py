#!/usr/bin/env python3
"""Validate a completed CWEval method-matrix run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import jsonschema

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from sectdd.orchestrator import PROJECT_ROOT, aggregate_trajectories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=PROJECT_ROOT / "schemas" / "trajectory.schema.json",
    )
    return parser.parse_args()


def assert_nested_close(actual, expected, location: str = "summary") -> None:
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise AssertionError(f"{location}: keys differ")
        for key in expected:
            assert_nested_close(actual[key], expected[key], f"{location}.{key}")
    elif isinstance(expected, float):
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{location}: {actual} != {expected}")
    elif actual != expected:
        raise AssertionError(f"{location}: {actual!r} != {expected!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    config = json.loads(Path(manifest["config"]).read_text())
    visible_split = json.loads(Path(manifest["visible_split"]).read_text())
    hidden_split = json.loads(Path(manifest["hidden_split"]).read_text())
    expected_hashes = manifest.get("input_sha256", {})
    for key in ("config", "visible_split", "hidden_split"):
        if key in expected_hashes:
            actual_hash = sha256_file(Path(manifest[key]))
            if actual_hash != expected_hashes[key]:
                raise AssertionError(
                    f"{key} changed after the run: "
                    f"{actual_hash} != {expected_hashes[key]}"
                )
    schema = json.loads(args.schema.resolve().read_text())
    trajectory_paths = sorted(
        run_dir.glob("trajectories/*/*/seed_*/trajectory.json")
    )
    if len(trajectory_paths) != manifest["trajectory_count"]:
        raise AssertionError(
            f"Expected {manifest['trajectory_count']} trajectories, "
            f"found {len(trajectory_paths)}"
        )

    expected_conditions = {
        (method, task, seed)
        for method in manifest["methods"]
        for task in manifest["tasks"]
        for seed in manifest["seeds"]
    }
    trajectories = []
    observed_conditions = set()
    visible_ids = {
        entry["case_id"]
        for task in manifest["tasks"]
        for marker in visible_split["tasks"][task].values()
        for entry in marker
    }
    hidden_ids = {
        entry["case_id"]
        for task in manifest["tasks"]
        for marker in hidden_split["tasks"][task].values()
        for entry in marker
    }
    if visible_ids & hidden_ids:
        raise AssertionError("Visible and hidden case IDs overlap")

    budgets = config["budgets"]
    for path in trajectory_paths:
        trajectory = json.loads(path.read_text())
        jsonschema.validate(trajectory, schema)
        condition = (
            trajectory["method"],
            trajectory["task"],
            trajectory["generation_seed"],
        )
        if condition in observed_conditions:
            raise AssertionError(f"Duplicate condition: {condition}")
        observed_conditions.add(condition)
        rounds = trajectory["rounds"]
        usage = trajectory["budget_usage"]
        if len(rounds) > trajectory["method_config"]["max_calls"]:
            raise AssertionError(f"{path}: model-call budget exceeded")
        if usage["visible_test_executions"] > budgets[
            "max_visible_test_executions"
        ]:
            raise AssertionError(f"{path}: visible-test budget exceeded")
        feedback_lengths = [
            len(record["feedback"])
            for record in rounds
            if record["feedback"] is not None
        ]
        if any(
            length > budgets["max_feedback_chars_per_round"]
            for length in feedback_lengths
        ):
            raise AssertionError(f"{path}: per-round feedback budget exceeded")
        if sum(feedback_lengths) != usage["feedback_chars"]:
            raise AssertionError(f"{path}: feedback accounting mismatch")
        if usage["feedback_chars"] > budgets["max_feedback_chars_total"]:
            raise AssertionError(f"{path}: total feedback budget exceeded")

        prompt_text = json.dumps(
            [record["messages"] for record in rounds], ensure_ascii=False
        )
        task_hidden_ids = {
            entry["case_id"]
            for marker in hidden_split["tasks"][trajectory["task"]].values()
            for entry in marker
        }
        leaked = sorted(
            case_id for case_id in task_hidden_ids if case_id in prompt_text
        )
        if leaked or trajectory["hidden_leak_audit"] != {
            "leaked_case_ids": [],
            "passed": True,
        }:
            raise AssertionError(f"{path}: hidden case leakage: {leaked}")

        hidden = trajectory["final_hidden"]
        expected_joint = (
            hidden["functional"]["all_passed"]
            and hidden["security"]["all_passed"]
        )
        if hidden["joint_pass"] != expected_joint:
            raise AssertionError(f"{path}: hidden joint result mismatch")
        trajectories.append(trajectory)

    if observed_conditions != expected_conditions:
        raise AssertionError(
            "Condition grid mismatch: "
            f"missing={sorted(expected_conditions - observed_conditions)}, "
            f"extra={sorted(observed_conditions - expected_conditions)}"
        )
    recorded_summary = json.loads((run_dir / "summary.json").read_text())
    assert_nested_close(recorded_summary, aggregate_trajectories(trajectories))
    print(
        f"OK: {len(trajectories)} trajectories; condition grid, schema, "
        "budgets, split isolation, hidden leakage, outcomes, and summary verified."
    )


if __name__ == "__main__":
    main()
