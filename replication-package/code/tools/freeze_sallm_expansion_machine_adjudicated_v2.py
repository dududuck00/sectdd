#!/usr/bin/env python3
"""Filter, replay, and freeze the machine-adjudicated SALLM expansion set."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import qualify_sallm_expansion as qualification


ROOT = Path(__file__).resolve().parents[1]
ADJUDICATION = ROOT / "configs/reviews/sallm_expansion_semantic_adjudication_v2.json"
PANEL = ROOT / "artifacts/sallm-semantic-review-v2/report.json"
PRE_FLIGHT = ROOT / "artifacts/sallm_expansion_preflight/preflight-v1/report.json"
TASKS = ROOT / "configs/benchmarks/sallm_expansion_preflight_qualified_v1.json"
VISIBLE_V1 = ROOT / "configs/oracles/sallm_expansion_oracle_visible_v1.json"
HIDDEN_V1 = ROOT / "configs/oracles/sallm_expansion_oracle_hidden_v1.json"
VISIBLE_OVERLAY_V1 = ROOT / "configs/benchmarks/sallm_expansion_oracle_visible_v1.json"
HIDDEN_OVERLAY_V1 = ROOT / "configs/benchmarks/sallm_expansion_oracle_hidden_v1.json"
ORACLE_ROOT = ROOT / "oracles/sallm_expansion_v1"

VISIBLE_V2 = ROOT / "configs/oracles/sallm_expansion_oracle_visible_v2.json"
HIDDEN_V2 = ROOT / "configs/oracles/sallm_expansion_oracle_hidden_v2.json"
VISIBLE_OVERLAY_V2 = ROOT / "configs/benchmarks/sallm_expansion_oracle_visible_v2.json"
HIDDEN_OVERLAY_V2 = ROOT / "configs/benchmarks/sallm_expansion_oracle_hidden_v2.json"
FINAL_TASKS = ROOT / "configs/benchmarks/sallm_expansion_machine_adjudicated_v2.json"
FREEZE = ROOT / "benchmarks/manifests/sallm-expansion-machine-adjudicated-v2-freeze.json"
OUTPUT = ROOT / "artifacts/sallm-expansion-machine-adjudicated-v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def filter_projection(source: dict[str, Any], tasks: list[str], partition: str) -> dict[str, Any]:
    result = json.loads(json.dumps(source))
    result["oracle_set_id"] = "sallm-expansion-machine-adjudicated-v2"
    result["oracle_status"] = "machine_semantic_adjudication_complete_human_review_pending"
    result["partition"] = partition
    result["tasks"] = {task: source["tasks"][task] for task in tasks}
    return result


def filter_overlay(source: dict[str, Any], tasks: list[str], partition: str) -> dict[str, Any]:
    result = json.loads(json.dumps(source))
    result["overlay_id"] = f"sallm-expansion-machine-adjudicated-v2-{partition}"
    result["oracle_set_id"] = "sallm-expansion-machine-adjudicated-v2"
    result["oracle_partition"] = partition
    result["scope"] = {"task_count": len(tasks), "qualified_task_ids": tasks}
    result["test_overrides"] = {
        task: source["test_overrides"][task] for task in tasks
    }
    return result


def main() -> None:
    args = parse_args()
    if args.repeats < 3:
        raise ValueError("At least three repeats are required")
    inputs = (
        ADJUDICATION,
        PANEL,
        PRE_FLIGHT,
        TASKS,
        VISIBLE_V1,
        HIDDEN_V1,
        VISIBLE_OVERLAY_V1,
        HIDDEN_OVERLAY_V1,
    )
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    outputs = (
        VISIBLE_V2,
        HIDDEN_V2,
        VISIBLE_OVERLAY_V2,
        HIDDEN_OVERLAY_V2,
        FINAL_TASKS,
        FREEZE,
        OUTPUT,
    )
    for path in outputs:
        if path.exists():
            raise FileExistsError(path)

    original_tasks = load(TASKS)["tasks"]
    adjudication = load(ADJUDICATION)
    decisions = adjudication["decisions"]
    if set(decisions) != set(original_tasks):
        raise RuntimeError("Adjudication grid does not match preflight-qualified tasks")
    tasks = sorted(
        task for task in original_tasks if decisions[task]["decision"] == "accept"
    )
    rejected = sorted(set(original_tasks) - set(tasks))
    if not tasks or not rejected:
        raise RuntimeError("Expected both accepted and rejected semantic decisions")

    visible_projection = filter_projection(load(VISIBLE_V1), tasks, "visible")
    hidden_projection = filter_projection(load(HIDDEN_V1), tasks, "hidden")
    visible_overlay = filter_overlay(load(VISIBLE_OVERLAY_V1), tasks, "visible")
    hidden_overlay = filter_overlay(load(HIDDEN_OVERLAY_V1), tasks, "hidden")
    write(VISIBLE_V2, visible_projection)
    write(HIDDEN_V2, hidden_projection)
    write(VISIBLE_OVERLAY_V2, visible_overlay)
    write(HIDDEN_OVERLAY_V2, hidden_overlay)
    write(
        FINAL_TASKS,
        {
            "oracle_set_id": "sallm-expansion-machine-adjudicated-v2",
            "machine_semantic_adjudication_complete": True,
            "independent_human_review_complete": False,
            "formal_experiment_ready": False,
            "remaining_gate": "independent second-researcher semantic review",
            "tasks": tasks,
            "rejected_tasks": rejected,
        },
    )

    modes: dict[str, Path | None] = {
        "unsafe_reference": None,
        "safe_reference": ORACLE_ROOT / "references",
        "targeted_mutant": ORACLE_ROOT / "mutants/primary",
    }
    expected = {
        "unsafe_reference": (True, False),
        "safe_reference": (True, True),
        "targeted_mutant": (True, False),
    }
    run_paths: dict[str, dict[str, list[Path]]] = {
        partition: {mode: [] for mode in modes}
        for partition in ("visible", "hidden")
    }
    for partition, overlay in (
        ("visible", VISIBLE_OVERLAY_V2),
        ("hidden", HIDDEN_OVERLAY_V2),
    ):
        for mode, candidate_root in modes.items():
            for repeat in range(1, args.repeats + 1):
                run = OUTPUT / "replay" / partition / mode / f"repeat-{repeat}"
                print(f"[{partition}] {mode} repeat={repeat}", flush=True)
                qualification.run_executor(
                    output=run,
                    overlay=overlay,
                    tasks=tasks,
                    candidate_root=candidate_root,
                    timeout_seconds=args.timeout_seconds,
                )
                results = qualification.read_results(run)
                for task in tasks:
                    pair = (
                        results[task]["functional_pass"],
                        results[task]["security_pass"],
                    )
                    if pair != expected[mode]:
                        raise RuntimeError(
                            f"Replay mismatch {task} {partition} {mode}: {pair}"
                        )
                run_paths[partition][mode].append(run)

    freeze = {
        "schema_version": 1,
        "freeze_id": "sallm-expansion-machine-adjudicated-v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "machine_semantic_adjudication_complete_human_review_pending",
        "formal_experiment_ready": False,
        "machine_semantic_adjudication_complete": True,
        "independent_human_review_complete": False,
        "formal_readiness_blockers": [
            "independent second-researcher semantic review"
        ],
        "summary": {
            "preflight_qualified_task_count": len(original_tasks),
            "machine_adjudicated_task_count": len(tasks),
            "semantic_rejected_task_count": len(rejected),
            "repeat_count": args.repeats,
            "partition_count": 2,
            "subject_mode_count": 3,
            "replay_observation_count": len(tasks) * 2 * 3 * args.repeats,
        },
        "tasks": {
            task: {
                "decision": decisions[task],
                "visible_projection": visible_projection["tasks"][task],
                "hidden_projection": hidden_projection["tasks"][task],
            }
            for task in tasks
        },
        "rejected_tasks": {
            task: decisions[task] for task in rejected
        },
        "inputs": {
            "semantic_machine_panel": record(PANEL),
            "semantic_evidence_adjudication": record(ADJUDICATION),
            "model_preflight": record(PRE_FLIGHT),
            "preflight_qualified_tasks": record(TASKS),
            "visible_projection_v2": record(VISIBLE_V2),
            "hidden_projection_v2": record(HIDDEN_V2),
            "visible_overlay_v2": record(VISIBLE_OVERLAY_V2),
            "hidden_overlay_v2": record(HIDDEN_OVERLAY_V2),
            "executor": record(qualification.EXECUTOR),
        },
        "runs": {
            partition: {
                mode: [record(run / "run_manifest.json") for run in runs]
                for mode, runs in mode_runs.items()
            }
            for partition, mode_runs in run_paths.items()
        },
        "review": {
            "machine_panel_complete": True,
            "evidence_adjudication_complete": True,
            "independent_human_reviewer": None,
            "independent_human_review_status": "pending",
        },
    }
    write(FREEZE, freeze)
    write(OUTPUT / "summary.json", freeze["summary"])
    write(
        OUTPUT / "run_manifest.json",
        {
            "schema_version": 1,
            "freeze": record(FREEZE),
            "final_tasks": record(FINAL_TASKS),
            "formal_experiment_ready": False,
        },
    )
    print(json.dumps(freeze["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
