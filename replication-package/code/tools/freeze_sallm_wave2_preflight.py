#!/usr/bin/env python3
"""Verify and freeze the completed wave-2 G8 preflight."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/sallm-wave2-preflight/preflight-v1"
REPORT = RUN_ROOT / "report.json"
LOCK = ROOT / "configs/experiments/sallm_wave2_preflight_v1.lock.json"
CONFIG = ROOT / "configs/experiments/sallm_wave2_preflight_v1.json"
QUALIFIED = ROOT / "configs/benchmarks/sallm_wave2_preflight_qualified_v1.json"
SEMANTIC_FREEZE = ROOT / "benchmarks/manifests/sallm-wave2-semantic-machine-v1-freeze.json"
FREEZE = ROOT / "benchmarks/manifests/sallm-wave2-preflight-v1-freeze.json"
VERIFICATION = RUN_ROOT / "verification.json"
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b", "qwen36-27b")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "size_bytes": path.stat().st_size}


def verify_record(value: dict[str, Any]) -> Path:
    path = ROOT / value["path"]
    if digest(path) != value["sha256"] or path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Frozen record mismatch: {path}")
    return path


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    for path in (RUN_ROOT, REPORT, LOCK, CONFIG, QUALIFIED, SEMANTIC_FREEZE):
        if not path.exists():
            raise FileNotFoundError(path)
    for path in (FREEZE, VERIFICATION):
        if path.exists():
            raise FileExistsError(path)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for value in lock["inputs"].values():
        verify_record(value)
    for value in lock["frozen_files"].values():
        verify_record(value)
    if lock["fresh_seed_overlap_count"] != 0 or not lock["frozen_before_generation"]:
        raise RuntimeError("Seed lock is invalid")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    qualified = json.loads(QUALIFIED.read_text(encoding="utf-8"))
    summary = report["summary"]
    if report["seeds"] != lock["generation_seeds"] or report["seeds"] != config["generation_seeds"]:
        raise RuntimeError("Seed mismatch")
    if report["models"] != list(MODELS):
        raise RuntimeError("Model grid mismatch")
    if summary["trajectory_count"] != lock["expected_trajectory_count"] or summary["trajectory_count"] != 48:
        raise RuntimeError("Trajectory grid is incomplete")
    if report["qualified_tasks"] != qualified["tasks"]:
        raise RuntimeError("Qualified task output mismatch")
    if summary["preflight_qualified_task_count"] != len(report["qualified_tasks"]):
        raise RuntimeError("Qualified count mismatch")

    run_inputs = {}
    observed = 0
    for model in MODELS:
        run = RUN_ROOT / model
        manifest_path = run / "run_manifest.json"
        summary_path = run / "summary.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["model"] != model or manifest["trajectory_count"] != 16:
            raise RuntimeError(f"Invalid model run: {model}")
        trajectories = list(run.glob("trajectories/*/*/seed_*/trajectory.json"))
        if len(trajectories) != 16:
            raise RuntimeError(f"Incomplete trajectories: {model}")
        for path in trajectories:
            item = json.loads(path.read_text(encoding="utf-8"))
            if not item["hidden_leak_audit"]["passed"]:
                raise RuntimeError(f"Hidden leak audit failed: {path}")
        observed += len(trajectories)
        run_inputs[model] = {"run_manifest": record(manifest_path), "summary": record(summary_path)}
    if observed != 48:
        raise RuntimeError("Observed trajectory count mismatch")

    freeze = {
        "schema_version": 1,
        "freeze_id": "sallm-wave2-preflight-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "g8_complete_no_qualified_tasks" if not report["qualified_tasks"] else "g8_complete",
        "formal_experiment_ready": False,
        "formal_results_use": False,
        "g8_complete": True,
        "independent_human_review_complete": False,
        "generation_seeds": report["seeds"],
        "models": report["models"],
        "methods": report["methods"],
        "summary": summary,
        "qualified_tasks": report["qualified_tasks"],
        "rejected_tasks": {
            task: audit for task, audit in report["task_audit"].items()
            if not audit["passed_preflight"]
        },
        "inputs": {
            "semantic_machine_freeze": record(SEMANTIC_FREEZE),
            "seed_lock": record(LOCK),
            "experiment_config": record(CONFIG),
            "preflight_report": record(REPORT),
            "qualified_task_file": record(QUALIFIED),
            "model_runs": run_inputs,
        },
        "interpretation": "Task-selection preflight only; rejected tasks are excluded from confirmatory method-effect experiments.",
    }
    write(FREEZE, freeze)
    verification = {
        "status": "verified",
        "trajectory_count": observed,
        "model_count": len(MODELS),
        "seed_count": len(report["seeds"]),
        "method_count": len(report["methods"]),
        "task_count": summary["task_count"],
        "qualified_task_count": len(report["qualified_tasks"]),
        "rejected_task_count": len(freeze["rejected_tasks"]),
        "hidden_leak_audit_passed": True,
        "freeze": record(FREEZE),
    }
    write(VERIFICATION, verification)
    print(json.dumps(verification, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
