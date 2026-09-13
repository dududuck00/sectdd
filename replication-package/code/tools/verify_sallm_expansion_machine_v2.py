#!/usr/bin/env python3
"""Verify hashes, task filtering, and replay results for machine v2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "benchmarks/manifests/sallm-expansion-machine-adjudicated-v2-freeze.json"
TASKS = ROOT / "configs/benchmarks/sallm_expansion_machine_adjudicated_v2.json"
ADJUDICATION = ROOT / "configs/reviews/sallm_expansion_semantic_adjudication_v2.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, default=FREEZE)
    return parser.parse_args()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_record(value: dict[str, Any]) -> Path:
    path = (ROOT / value["path"]).resolve()
    path.relative_to(ROOT)
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256(path) != value["sha256"] or path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Frozen record changed: {path}")
    return path


def main() -> None:
    args = parse_args()
    freeze_path = args.freeze.expanduser().resolve()
    freeze_path.relative_to(ROOT)
    freeze = load(freeze_path)
    if freeze["formal_experiment_ready"] is not False:
        raise RuntimeError("Machine-only freeze must not be formal-ready")
    if freeze["independent_human_review_complete"] is not False:
        raise RuntimeError("Human review status is inconsistent")
    for value in freeze["inputs"].values():
        verify_record(value)
    for partition in freeze["runs"].values():
        for runs in partition.values():
            for run in runs:
                verify_record(run)

    task_config = load(TASKS)
    adjudication = load(ADJUDICATION)
    accepted = sorted(
        task
        for task, decision in adjudication["decisions"].items()
        if decision["decision"] == "accept"
    )
    rejected = sorted(set(adjudication["decisions"]) - set(accepted))
    if task_config["tasks"] != accepted or task_config["rejected_tasks"] != rejected:
        raise RuntimeError("Task filtering does not match semantic adjudication")
    if sorted(freeze["tasks"]) != accepted or sorted(freeze["rejected_tasks"]) != rejected:
        raise RuntimeError("Freeze task sets do not match adjudication")

    for projection_key in ("visible_projection_v2", "hidden_projection_v2"):
        projection = load(verify_record(freeze["inputs"][projection_key]))
        if sorted(projection["tasks"]) != accepted:
            raise RuntimeError(f"Projection task mismatch: {projection_key}")
    for overlay_key in ("visible_overlay_v2", "hidden_overlay_v2"):
        overlay = load(verify_record(freeze["inputs"][overlay_key]))
        if sorted(overlay["test_overrides"]) != accepted:
            raise RuntimeError(f"Overlay task mismatch: {overlay_key}")
        if overlay["scope"]["qualified_task_ids"] != accepted:
            raise RuntimeError(f"Overlay scope mismatch: {overlay_key}")

    summary = freeze["summary"]
    expected_observations = len(accepted) * 2 * 3 * summary["repeat_count"]
    if summary["replay_observation_count"] != expected_observations:
        raise RuntimeError("Replay observation count mismatch")
    print(
        json.dumps(
            {
                "status": "verified",
                "machine_adjudicated_task_count": len(accepted),
                "semantic_rejected_task_count": len(rejected),
                "replay_observation_count": expected_observations,
                "independent_human_review": "pending",
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
