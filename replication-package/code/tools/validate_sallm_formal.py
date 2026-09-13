#!/usr/bin/env python3
"""Validate a partitioned SALLM formal/smoke run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sectdd.sallm_formal_orchestrator import aggregate_trajectories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested_close(actual, expected, location="root") -> None:
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise AssertionError(f"{location}: keys differ")
        for key in expected:
            nested_close(actual[key], expected[key], f"{location}.{key}")
    elif isinstance(expected, float):
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{location}: {actual} != {expected}")
    elif actual != expected:
        raise AssertionError(f"{location}: {actual} != {expected}")


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    run_dir.relative_to(ROOT)
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    config_path = ROOT / manifest["config"]
    visible_path = ROOT / manifest["visible_projection"]
    hidden_path = ROOT / manifest["hidden_projection"]
    for key, path in (
        ("config", config_path),
        ("visible_projection", visible_path),
        ("hidden_projection", hidden_path),
    ):
        if sha256(path) != manifest["input_sha256"][key]:
            raise AssertionError(f"Frozen input changed: {path}")
    config = json.loads(config_path.read_text())
    visible = json.loads(visible_path.read_text())
    hidden = json.loads(hidden_path.read_text())
    expected = {
        (method, task, seed)
        for method in manifest["methods"]
        for task in manifest["tasks"]
        for seed in manifest["seeds"]
    }
    trajectories = []
    observed = set()
    for path in sorted(run_dir.glob("trajectories/*/*/seed_*/trajectory.json")):
        item = json.loads(path.read_text())
        key = (item["method"], item["task"], item["generation_seed"])
        if key in observed:
            raise AssertionError(f"Duplicate condition: {key}")
        observed.add(key)
        if item["oracle_set_id"] != manifest["oracle_set_id"]:
            raise AssertionError(f"{path}: oracle mismatch")
        budgets = config["budgets"]
        usage = item["budget_usage"]
        method = config["methods"][item["method"]]
        task = item["task"]
        expected_visible = len(visible["tasks"][task]["cases"])
        expected_hidden = len(hidden["tasks"][task]["cases"])
        if usage["model_calls"] > method["max_calls"]:
            raise AssertionError(f"{path}: call budget")
        for used, limit in (
            ("input_tokens", "max_input_tokens_total"),
            ("output_tokens", "max_output_tokens_total"),
            ("feedback_tokens", "max_feedback_tokens_total"),
            ("visible_test_executions", "max_visible_test_executions"),
        ):
            if usage[used] > budgets[limit]:
                raise AssertionError(f"{path}: {used} budget")
        round_input = round_output = round_feedback = 0
        for record in item["rounds"]:
            accounting = record["token_accounting"]
            round_input += accounting["reported_input_tokens"]
            round_output += accounting["reported_output_tokens"]
            round_feedback += accounting["feedback_tokens"]
            if accounting["feedback_tokens"] > budgets[
                "max_feedback_tokens_per_round"
            ]:
                raise AssertionError(f"{path}: per-round feedback budget")
            visible_result = record["visible_result"]
            if (
                visible_result["partition"] != "visible"
                or visible_result["summary"]["expected"] != expected_visible
                or visible_result["summary"]["collected"] != expected_visible
            ):
                raise AssertionError(f"{path}: visible execution invalid")
            candidate = ROOT / record["candidate"]["path"]
            if sha256(candidate) != record["candidate"]["sha256"]:
                raise AssertionError(f"{path}: candidate hash mismatch")
        if (
            round_input != usage["input_tokens"]
            or round_output != usage["output_tokens"]
            or round_feedback != usage["feedback_tokens"]
        ):
            raise AssertionError(f"{path}: token accounting mismatch")
        hidden_result = item["final_hidden"]["raw"]
        if (
            hidden_result["partition"] != "hidden"
            or hidden_result["summary"]["expected"] != expected_hidden
            or hidden_result["summary"]["collected"] != expected_hidden
        ):
            raise AssertionError(f"{path}: hidden execution invalid")
        audit = item["hidden_leak_audit"]
        if (
            not audit["passed"]
            or audit["leaked_terms"]
            or audit["hidden_evaluation_count"] != 1
            or audit["hidden_feedback_used"]
            or not audit["hidden_projection_loaded_after_candidate_frozen"]
        ):
            raise AssertionError(f"{path}: hidden leak audit")
        functional = item["final_hidden"]["functional"]["all_passed"]
        security = item["final_hidden"]["security"]["all_passed"]
        if item["final_hidden"]["joint_pass"] != (functional and security):
            raise AssertionError(f"{path}: joint outcome mismatch")

        prompt_text = json.dumps(
            [
                [
                    message
                    for message in record["messages"]
                    if message["role"] != "assistant"
                ]
                for record in item["rounds"]
            ],
            ensure_ascii=False,
        )
        initial_prompt_text = json.dumps(
            item["rounds"][0]["messages"], ensure_ascii=False
        )
        visible_cases = visible["tasks"][item["task"]]["cases"]
        expected_markers = {
            "none": set(),
            "functional": {"functionality"},
            "all": {"functionality", "security"},
        }[method["upfront_tests"]]
        for case in visible_cases:
            present = case["case_id"] in initial_prompt_text
            expected_upfront = case["marker"] in expected_markers
            if present != expected_upfront:
                raise AssertionError(
                    f"{path}: visible upfront policy mismatch for "
                    f"{case['case_id']}"
                )
        hidden_cases = hidden["tasks"][item["task"]]["cases"]
        if any(case["case_id"] in prompt_text for case in hidden_cases):
            raise AssertionError(f"{path}: hidden case ID leaked")
        trajectories.append(item)
    if observed != expected:
        raise AssertionError(
            f"Condition grid mismatch: missing={expected-observed}, "
            f"extra={observed-expected}"
        )

    index = {
        (item["method"], item["task"], item["generation_seed"]): item
        for item in trajectories
    }
    for method in manifest["methods"]:
        reference = config["methods"][method].get("shared_initial_from")
        if reference is None:
            continue
        for task in manifest["tasks"]:
            for seed in manifest["seeds"]:
                source = index[(reference, task, seed)]["rounds"][0]
                reused = index[(method, task, seed)]["rounds"][0]
                if not reused["generation_reused"]:
                    raise AssertionError(f"{method}/{task}/{seed}: not reused")
                for key in ("messages", "request_seed", "response", "usage"):
                    if reused[key] != source[key]:
                        raise AssertionError(
                            f"{method}/{task}/{seed}: shared {key} differs"
                        )
    recorded = json.loads((run_dir / "summary.json").read_text())
    nested_close(recorded, aggregate_trajectories(trajectories))
    print(
        f"OK: {len(trajectories)} SALLM trajectories; condition grid, "
        "budgets, candidate hashes, visible policy, hidden isolation, shared "
        "initial candidates, outcomes, and summary verified."
    )


if __name__ == "__main__":
    main()
