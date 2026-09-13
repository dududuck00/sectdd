#!/usr/bin/env python3
"""Validate a completed behavior-family formal-pilot run."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sectdd.formal_orchestrator import aggregate_trajectories, sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
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


def verify_upfront_visibility(
    trajectory: dict,
    visible_projection: dict,
) -> None:
    task = trajectory["task"]
    method = trajectory["method"]
    prompt = json.dumps(trajectory["rounds"][0]["messages"], ensure_ascii=False)
    cases = visible_projection["tasks"][task]["cases"]
    expected_markers = {
        "none": set(),
        "functional": {"functionality"},
        "all": {"functionality", "security"},
    }[trajectory["method_config"]["upfront_tests"]]
    for case in cases:
        present = (
            case["case_id"] in prompt
            and case["test_name"] in prompt
        )
        should_be_present = case["marker"] in expected_markers
        if present != should_be_present:
            raise AssertionError(
                f"{task}/{method}: upfront visibility mismatch for "
                f"{case['case_id']}"
            )


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    if manifest.get("schema_version") not in {2, 3} or not (
        manifest.get("formal_experiment") or manifest.get("formal_pilot")
    ):
        raise AssertionError("Not a formal experiment run manifest")
    config_path = Path(manifest["config"])
    visible_path = Path(manifest["visible_projection"])
    hidden_path = Path(manifest["hidden_projection"])
    config = json.loads(config_path.read_text())
    visible = json.loads(visible_path.read_text())
    hidden = json.loads(hidden_path.read_text())
    for key, path in (
        ("config", config_path),
        ("visible_projection", visible_path),
        ("hidden_projection", hidden_path),
    ):
        actual_hash = sha256_file(path)
        expected_hash = manifest["input_sha256"][key]
        if actual_hash != expected_hash:
            raise AssertionError(
                f"{key} changed after run: {actual_hash} != {expected_hash}"
            )
    if manifest["oracle_set_id"] != visible["oracle_set_id"]:
        raise AssertionError("Oracle set mismatch")
    if manifest["canonical_oracle_manifest_sha256"] != visible[
        "canonical_manifest_sha256"
    ]:
        raise AssertionError("Canonical oracle hash mismatch")
    if config.get("generation_seeds") is not None and manifest[
        "seeds"
    ] != config["generation_seeds"]:
        raise AssertionError("Manifest seeds differ from frozen config")
    if config.get("tasks") is not None:
        frozen_tasks = config["tasks"]
        if (
            not manifest["tasks"]
            or any(task not in frozen_tasks for task in manifest["tasks"])
            or manifest["tasks"]
            != [task for task in frozen_tasks if task in manifest["tasks"]]
        ):
            raise AssertionError(
                "Manifest tasks are not an ordered subset of frozen tasks"
            )
    model_registry = config.get("models", {})
    if model_registry:
        model = manifest["model"]
        if model not in model_registry:
            raise AssertionError("Manifest model absent from frozen config")
        freeze = manifest.get("model_freeze")
        if not freeze:
            raise AssertionError("Frozen model identity is missing")
        model_record = model_registry[model]
        provider = model_record.get("provider", "local")
        if manifest.get("provider", "local") != provider:
            raise AssertionError("Frozen model provider mismatch")
        if provider == "local":
            checkpoint = Path(model_record["checkpoint"]).resolve()
            if Path(freeze["path"]).resolve() != checkpoint:
                raise AssertionError("Frozen model path mismatch")
            for name, expected_hash in freeze["files_sha256"].items():
                actual_hash = sha256_file(checkpoint / name)
                if actual_hash != expected_hash:
                    raise AssertionError(
                        f"Model identity file changed: {name}"
                    )
        else:
            # Remote APIs do not expose a local checkpoint.  Their frozen
            # identity is the provider/model record committed in the config.
            if freeze != model_record:
                raise AssertionError("Frozen remote model identity mismatch")
            if manifest.get("provider_seed_supported") is not False:
                raise AssertionError("Remote provider seed policy mismatch")
            if manifest.get("remote_seed_policy") != (
                "generation_seeds_are_request_slot_ids_not_sent_to_provider"
            ):
                raise AssertionError("Remote request-slot policy mismatch")

    paths = sorted(run_dir.glob("trajectories/*/*/seed_*/trajectory.json"))
    if len(paths) != manifest["trajectory_count"]:
        raise AssertionError("Trajectory count mismatch")
    expected_conditions = {
        (method, task, seed)
        for method in manifest["methods"]
        for task in manifest["tasks"]
        for seed in manifest["seeds"]
    }
    observed_conditions = set()
    trajectories = []
    budgets = config["budgets"]
    max_prompt_count_delta = 0
    for path in paths:
        trajectory = json.loads(path.read_text())
        if trajectory["schema_version"] != 2:
            raise AssertionError(f"{path}: schema version mismatch")
        condition = (
            trajectory["method"],
            trajectory["task"],
            trajectory["generation_seed"],
        )
        if condition in observed_conditions:
            raise AssertionError(f"Duplicate condition: {condition}")
        observed_conditions.add(condition)
        if trajectory["oracle_set_id"] != manifest["oracle_set_id"]:
            raise AssertionError(f"{path}: oracle set mismatch")
        usage = trajectory["budget_usage"]
        if usage["model_calls"] > trajectory["method_config"]["max_calls"]:
            raise AssertionError(f"{path}: call budget exceeded")
        if usage["input_tokens"] > budgets["max_input_tokens_total"]:
            raise AssertionError(f"{path}: input-token budget exceeded")
        if usage["output_tokens"] > budgets["max_output_tokens_total"]:
            raise AssertionError(f"{path}: output-token budget exceeded")
        if usage["feedback_tokens"] > budgets["max_feedback_tokens_total"]:
            raise AssertionError(f"{path}: feedback-token budget exceeded")
        if usage["visible_test_executions"] > budgets[
            "max_visible_test_executions"
        ]:
            raise AssertionError(f"{path}: visible-test budget exceeded")
        round_input = 0
        round_output = 0
        round_feedback = 0
        task = trajectory["task"]
        expected_visible = len(visible["tasks"][task]["cases"])
        expected_hidden = len(hidden["tasks"][task]["cases"])
        for record in trajectory["rounds"]:
            accounting = record["token_accounting"]
            delta = abs(
                accounting["estimated_input_tokens"]
                - accounting["reported_input_tokens"]
            )
            max_prompt_count_delta = max(max_prompt_count_delta, delta)
            round_input += accounting["reported_input_tokens"]
            round_output += accounting["reported_output_tokens"]
            round_feedback += accounting["feedback_tokens"]
            if accounting["feedback_tokens"] > budgets[
                "max_feedback_tokens_per_round"
            ]:
                raise AssertionError(
                    f"{path}: per-round feedback budget exceeded"
                )
            result = record["visible_result"]
            valid_visible_collection = (
                result["summary"]["collected"] == expected_visible
                or (
                    result["summary"]["collected"] == 0
                    and result["summary"]["run"] == 0
                    and bool(result["collection_errors"])
                    and not result["summary"]["all_passed"]
                )
            )
            if (
                result["partition"] != "visible"
                or result["summary"]["expected"] != expected_visible
                or not valid_visible_collection
            ):
                raise AssertionError(f"{path}: invalid visible execution")
            if not record["visible_execution"]["minimal_project_mount"]:
                raise AssertionError(f"{path}: visible mount is not minimal")
        if (
            round_input != usage["input_tokens"]
            or round_output != usage["output_tokens"]
            or round_feedback != usage["feedback_tokens"]
        ):
            raise AssertionError(f"{path}: token accounting mismatch")
        hidden_result = trajectory["final_hidden"]["raw"]
        valid_hidden_collection = (
            hidden_result["summary"]["collected"] == expected_hidden
            or (
                hidden_result["summary"]["collected"] == 0
                and hidden_result["summary"]["run"] == 0
                and bool(hidden_result["collection_errors"])
                and not hidden_result["summary"]["all_passed"]
            )
        )
        if (
            hidden_result["partition"] != "hidden"
            or hidden_result["summary"]["expected"] != expected_hidden
            or not valid_hidden_collection
        ):
            raise AssertionError(f"{path}: invalid hidden execution")
        audit = trajectory["hidden_leak_audit"]
        if (
            not audit["passed"]
            or audit["leaked_terms"]
            or not audit["hidden_projection_loaded_after_candidate_frozen"]
            or audit["hidden_evaluation_count"] != 1
            or audit["hidden_feedback_used"]
            or not audit["visible_execution_minimal_mount"]
            or not audit["hidden_execution_minimal_mount"]
        ):
            raise AssertionError(f"{path}: hidden isolation audit failed")
        hidden_outcome = trajectory["final_hidden"]
        expected_joint = (
            hidden_outcome["functional"]["all_passed"]
            and hidden_outcome["security"]["all_passed"]
        )
        if hidden_outcome["joint_pass"] != expected_joint:
            raise AssertionError(f"{path}: hidden joint mismatch")
        verify_upfront_visibility(trajectory, visible)
        trajectories.append(trajectory)
    if observed_conditions != expected_conditions:
        raise AssertionError(
            f"Condition grid mismatch: "
            f"missing={sorted(expected_conditions-observed_conditions)}, "
            f"extra={sorted(observed_conditions-expected_conditions)}"
        )
    shared_policies = manifest.get("shared_initial_candidate_policies")
    if shared_policies is None:
        legacy_policy = manifest.get("shared_initial_candidate_policy")
        shared_policies = [] if not legacy_policy else [
            {
                "method": method,
                "reference_method": legacy_policy["reference_method"],
            }
            for method in legacy_policy["reused_by"]
        ]
    if shared_policies:
        index = {
            (item["method"], item["task"], item["generation_seed"]): item
            for item in trajectories
        }
        for policy in shared_policies:
            reference_method = policy["reference_method"]
            method = policy["method"]
            if method not in manifest["methods"]:
                continue
            for task in manifest["tasks"]:
                for seed in manifest["seeds"]:
                    reference = index[(reference_method, task, seed)]["rounds"][0]
                    candidate = index[(method, task, seed)]["rounds"][0]
                    if not candidate.get("generation_reused"):
                        raise AssertionError(
                            f"{method}/{task}/{seed}: initial generation not reused"
                        )
                    for key in ("messages", "request_seed", "response", "usage"):
                        if candidate[key] != reference[key]:
                            raise AssertionError(
                                f"{method}/{task}/{seed}: shared initial {key} differs"
                            )
    recorded_summary = json.loads((run_dir / "summary.json").read_text())
    assert_nested_close(recorded_summary, aggregate_trajectories(trajectories))
    print(
        f"OK: {len(trajectories)} trajectories; condition grid, immutable "
        "inputs, full visible-test policy, tokenizer budgets, minimal mounts, "
        "hidden isolation, shared initial candidates, outcomes, and summary "
        "verified. "
        f"max tokenizer/vLLM prompt-count delta={max_prompt_count_delta}."
    )


if __name__ == "__main__":
    main()
