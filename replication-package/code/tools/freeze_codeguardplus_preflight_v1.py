#!/usr/bin/env python3
"""Verify and freeze the completed CodeGuard+ G8 preflight evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/codeguardplus-preflight/v1"
REPORT = RUN_ROOT / "report.json"
LOCK = ROOT / "configs/experiments/codeguardplus_preflight_v1.lock.json"
QUALIFIED = ROOT / "configs/benchmarks/codeguardplus_preflight_qualified_v1.json"
SEMANTIC = ROOT / "benchmarks/manifests/codeguardplus-semantic-machine-v2-freeze.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-preflight-v1-freeze.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def main() -> None:
    if FREEZE.exists():
        raise FileExistsError(FREEZE)
    for path in (REPORT, LOCK, QUALIFIED, SEMANTIC):
        if not path.is_file():
            raise FileNotFoundError(path)
    report = json.loads(REPORT.read_text())
    lock = json.loads(LOCK.read_text())
    qualified = json.loads(QUALIFIED.read_text())
    if report["summary"]["trajectory_count"] != 64 or lock["expected_trajectory_count"] != 64:
        raise RuntimeError("Preflight count mismatch")
    if qualified["tasks"] != report["qualified_tasks"]:
        raise RuntimeError("Preflight report/qualification mismatch")
    trajectory_records = {}
    observed = 0
    for model in report["models"]:
        run = RUN_ROOT / model
        manifest = json.loads((run / "run_manifest.json").read_text())
        paths = sorted((run / "trajectories").glob("*/*/seed_*/trajectory.json"))
        if len(paths) != manifest["trajectory_count"] or len(paths) != 32:
            raise RuntimeError(f"Incomplete model run: {model}")
        for path in paths:
            audit = json.loads(path.read_text())["hidden_leak_audit"]
            if not audit["passed"] or audit["hidden_evaluation_count"] != 1 or audit["hidden_feedback_used"]:
                raise RuntimeError(f"Hidden isolation failure: {path}")
        observed += len(paths)
        trajectory_records[model] = {"run_manifest": record(run / "run_manifest.json"), "summary": record(run / "summary.json"), "trajectory_count": len(paths)}
    if observed != 64:
        raise RuntimeError("Incomplete total grid")
    rejected = {task: value for task, value in report["task_audit"].items() if not value["passed_preflight"]}
    value = {
        "schema_version": 1,
        "freeze_id": "codeguardplus-preflight-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "g8_complete_human_g7_and_breadth_expansion_pending",
        "formal_experiment_ready": False,
        "model_preflight_complete": True,
        "independent_human_review_complete": False,
        "breadth_sufficient_for_formal_external_experiment": False,
        "qualified_task_ids": report["qualified_tasks"],
        "rejected_tasks": rejected,
        "summary": report["summary"],
        "generation_seeds": report["seeds"],
        "models": report["models"],
        "methods": report["methods"],
        "inputs": {"semantic_machine_freeze": record(SEMANTIC), "preflight_lock": record(LOCK)},
        "outputs": {"report": record(REPORT), "qualified_tasks": record(QUALIFIED), "model_runs": trajectory_records},
        "formal_readiness_blockers": [
            "expand preflight-identifiable CodeGuard+ task breadth without reusing observed seeds",
            "independent second-researcher semantic review (G7)",
            "final prompt/oracle/model/budget freeze",
        ],
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"trajectory_count": observed, "qualified_task_count": len(report["qualified_tasks"]), "rejected_task_count": len(rejected), "formal_experiment_ready": False}, indent=2))


if __name__ == "__main__":
    main()
