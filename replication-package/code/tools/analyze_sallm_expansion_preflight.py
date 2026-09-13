#!/usr/bin/env python3
"""Analyze identifiability and feedback triggers in SALLM expansion preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUALIFIED = ROOT / "configs/benchmarks/sallm_expansion_preflight_qualified_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--qualified-task-file", type=Path, default=DEFAULT_QUALIFIED)
    parser.add_argument("--report-id", default="sallm-expansion-preflight-v1")
    parser.add_argument("--title", default="SALLM expansion model preflight v1")
    parser.add_argument(
        "--remaining-gate", default="independent semantic review"
    )
    return parser.parse_args()


def checked(path: Path, exists: bool) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def load_run(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((path / "run_manifest.json").read_text())
    trajectories = [
        json.loads(item.read_text())
        for item in sorted((path / "trajectories").glob("*/*/seed_*/trajectory.json"))
    ]
    if len(trajectories) != manifest["trajectory_count"]:
        raise RuntimeError(f"Trajectory count mismatch: {path}")
    return manifest, trajectories


def hidden_state(trajectory: dict[str, Any]) -> tuple[bool, bool, bool]:
    hidden = trajectory["final_hidden"]
    return (
        bool(hidden["functional"]["all_passed"]),
        bool(hidden["security"]["all_passed"]),
        bool(hidden["joint_pass"]),
    )


def main() -> None:
    args = parse_args()
    runs = [checked(path, True) for path in args.runs]
    json_output = checked(args.json_output, False)
    markdown_output = checked(args.markdown_output, False)
    qualified_output = checked(args.qualified_task_file, False)
    for path in (json_output, markdown_output, qualified_output):
        if path.exists():
            raise FileExistsError(path)
    loaded = [load_run(path) for path in runs]
    manifests = [item[0] for item in loaded]
    all_trajectories = [trajectory for _, values in loaded for trajectory in values]
    tasks = manifests[0]["tasks"]
    methods = manifests[0]["methods"]
    seeds = manifests[0]["seeds"]
    if set(methods) != {"B0", "M", "B3", "B6"} or len(methods) != 4:
        raise RuntimeError(f"Unexpected preflight methods: {methods}")
    for manifest in manifests[1:]:
        for key in ("tasks", "methods", "seeds", "oracle_set_id", "canonical_oracle_manifest_sha256"):
            if manifest[key] != manifests[0][key]:
                raise RuntimeError(f"Run invariant mismatch: {key}")
    models = [manifest["model"] for manifest in manifests]
    expected_count = len(tasks) * len(methods) * len(seeds) * len(models)
    if len(all_trajectories) != expected_count:
        raise RuntimeError("Incomplete task/model/method/seed grid")
    by_key = {
        (item["task"], item["model"], item["method"], item["generation_seed"]): item
        for item in all_trajectories
    }
    if len(by_key) != expected_count:
        raise RuntimeError("Duplicate preflight grid cells")

    task_audit = {}
    qualified = []
    for task in tasks:
        b0 = [by_key[(task, model, "B0", seed)] for model in models for seed in seeds]
        all_methods = [
            by_key[(task, model, method, seed)]
            for model in models
            for method in methods
            for seed in seeds
        ]
        b0_states = [hidden_state(item) for item in b0]
        all_states = [hidden_state(item) for item in all_methods]
        universal_ceiling = all(state[2] for state in b0_states)
        universal_floor = not any(state[2] for state in all_states)
        security_only = sum(state[0] and not state[1] for state in b0_states)
        feedback_trigger_count = 0
        joint_repairs = 0
        joint_regressions = 0
        for model in models:
            for seed in seeds:
                for method, reference in (("M", "B0"), ("B6", "B3")):
                    current = by_key[(task, model, method, seed)]
                    initial = by_key[(task, model, reference, seed)]
                    feedback_trigger_count += int(len(current["rounds"]) > 1)
                    initial_joint = hidden_state(initial)[2]
                    current_joint = hidden_state(current)[2]
                    joint_repairs += int(not initial_joint and current_joint)
                    joint_regressions += int(initial_joint and not current_joint)
        passed = (
            not universal_ceiling
            and not universal_floor
            and security_only > 0
            and feedback_trigger_count > 0
        )
        reasons = []
        if universal_ceiling:
            reasons.append("universal_b0_ceiling")
        if universal_floor:
            reasons.append("universal_joint_floor")
        if security_only == 0:
            reasons.append("no_b0_security_only_failure")
        if feedback_trigger_count == 0:
            reasons.append("no_feedback_trigger")
        if passed:
            qualified.append(task)
        task_audit[task] = {
            "passed_preflight": passed,
            "rejection_reasons": reasons,
            "b0_observation_count": len(b0_states),
            "b0_joint_pass_count": sum(state[2] for state in b0_states),
            "b0_functional_pass_count": sum(state[0] for state in b0_states),
            "b0_security_pass_count": sum(state[1] for state in b0_states),
            "b0_security_only_failure_count": security_only,
            "feedback_trigger_count": feedback_trigger_count,
            "joint_repair_count": joint_repairs,
            "joint_regression_count": joint_regressions,
            "universal_b0_ceiling": universal_ceiling,
            "universal_joint_floor": universal_floor,
            "observed_hidden_state_count": len(set(all_states)),
        }

    rejected_reasons = Counter(
        reason
        for task in tasks
        for reason in task_audit[task]["rejection_reasons"]
    )
    report = {
        "schema_version": 1,
        "report_id": args.report_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_experiment_results": False,
        "policy": {
            "reject_universal_b0_ceiling": True,
            "reject_universal_joint_floor": True,
            "require_b0_security_only_failure": True,
            "require_feedback_trigger": True,
            "joint_repair_required": False,
        },
        "inputs": {
            model: {
                "run_manifest": record(run / "run_manifest.json"),
                "summary": record(run / "summary.json"),
            }
            for model, run in zip(models, runs)
        },
        "summary": {
            "task_count": len(tasks),
            "model_count": len(models),
            "seed_count": len(seeds),
            "method_count": len(methods),
            "trajectory_count": len(all_trajectories),
            "preflight_qualified_task_count": len(qualified),
            "preflight_rejected_task_count": len(tasks) - len(qualified),
            "b0_security_only_failure_count": sum(x["b0_security_only_failure_count"] for x in task_audit.values()),
            "feedback_trigger_count": sum(x["feedback_trigger_count"] for x in task_audit.values()),
            "joint_repair_count": sum(x["joint_repair_count"] for x in task_audit.values()),
            "joint_regression_count": sum(x["joint_regression_count"] for x in task_audit.values()),
            "rejection_reason_counts": dict(sorted(rejected_reasons.items())),
        },
        "models": models,
        "seeds": seeds,
        "methods": methods,
        "qualified_tasks": qualified,
        "task_audit": task_audit,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    qualified_output.parent.mkdir(parents=True, exist_ok=True)
    qualified_output.write_text(
        json.dumps(
            {
                "preflight_report": record(json_output),
                "model_preflight_complete": True,
                "formal_experiment_ready": False,
                "remaining_gate": args.remaining_gate,
                "tasks": qualified,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    summary = report["summary"]
    lines = [
        f"# {args.title}",
        "",
        f"Evaluated {summary['trajectory_count']} development-only trajectories over {len(tasks)} tasks, {len(models)} models, {len(seeds)} seeds, and {len(methods)} methods.",
        "",
        f"Qualified: {len(qualified)}/{len(tasks)} tasks. Security-only B0 failures: {summary['b0_security_only_failure_count']}; feedback triggers: {summary['feedback_trigger_count']}; joint repairs: {summary['joint_repair_count']}; joint regressions: {summary['joint_regression_count']}.",
        "",
        "| Task | Pass | B0 F+S- | Feedback triggers | Joint repairs | Joint regressions | Reasons |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for task in tasks:
        item = task_audit[task]
        lines.append(
            f"| `{task}` | {'yes' if item['passed_preflight'] else 'no'} | {item['b0_security_only_failure_count']} | {item['feedback_trigger_count']} | {item['joint_repair_count']} | {item['joint_regression_count']} | {', '.join(item['rejection_reasons']) or '-'} |"
        )
    lines.extend(["", f"This is a task-selection preflight, not confirmatory experimental evidence. Remaining gate: {args.remaining_gate}.", ""])
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text("\n".join(lines) + "\n")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
