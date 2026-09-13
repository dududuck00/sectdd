#!/usr/bin/env python3
"""Verify and freeze breadth-wave3 G8 preflight evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3/g8-preflight-v1"
REPORT = RUN_ROOT / "report.json"
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_breadth_wave3_preflight_v1.lock.json"
QUALIFIED = ROOT / "configs/benchmarks/codeguardplus_reserve_breadth_wave3_preflight_qualified_v1.json"
SEMANTIC = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave3-semantic-machine-v1-freeze.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave3-preflight-v1-freeze.json"
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b")
SEEDS = [41017, 47059]
LOCK_ID = "codeguardplus-reserve-breadth-wave3-preflight-v1"
REPORT_ID = LOCK_ID
FREEZE_ID = LOCK_ID
EXPECTED_TOTAL = 48
EXPECTED_PER_MODEL = 24


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
    report, lock, qualified, semantic = [json.loads(path.read_text(encoding="utf-8")) for path in (REPORT, LOCK, QUALIFIED, SEMANTIC)]
    if lock["lock_id"] != LOCK_ID or not lock["frozen_before_generation"]:
        raise RuntimeError("Invalid preflight lock")
    if lock["generation_seeds"] != SEEDS or lock["fresh_seed_overlap_count"] != 0:
        raise RuntimeError("Fresh-seed policy mismatch")
    if lock["inputs"]["semantic_machine_freeze"]["sha256"] != sha(SEMANTIC):
        raise RuntimeError("Machine-semantic freeze drift")
    if report["report_id"] != REPORT_ID:
        raise RuntimeError("Unexpected report identity")
    if report["models"] != list(MODELS) or report["seeds"] != SEEDS or set(report["methods"]) != {"B0", "M", "B3", "B6"}:
        raise RuntimeError("G8 grid identity drift")
    tasks = semantic["qualified_task_ids"]
    if set(report["task_audit"]) != set(tasks) or report["summary"]["trajectory_count"] != EXPECTED_TOTAL or lock["expected_trajectory_count"] != EXPECTED_TOTAL:
        raise RuntimeError("G8 task or trajectory grid mismatch")
    if qualified["tasks"] != report["qualified_tasks"] or qualified["formal_experiment_ready"] is not False or report["formal_experiment_results"] is not False:
        raise RuntimeError("Preflight readiness boundary mismatch")

    model_records = {}
    observed = 0
    for model in MODELS:
        run = RUN_ROOT / model
        manifest_path, summary_path = run / "run_manifest.json", run / "summary.json"
        if not manifest_path.is_file() or not summary_path.is_file():
            raise FileNotFoundError(run)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["model"] != model or manifest["tasks"] != tasks or manifest["seeds"] != SEEDS:
            raise RuntimeError(f"Model run identity drift: {model}")
        for key in ("config", "visible_projection", "hidden_projection"):
            if manifest["input_sha256"][key] != lock["frozen_files"][key]["sha256"]:
                raise RuntimeError(f"Frozen input drift: {model} {key}")
        paths = sorted((run / "trajectories").glob("*/*/seed_*/trajectory.json"))
        if len(paths) != EXPECTED_PER_MODEL or manifest["trajectory_count"] != EXPECTED_PER_MODEL:
            raise RuntimeError(f"Incomplete model grid: {model}")
        expected_hashes = {path.relative_to(run).as_posix(): sha(path) for path in paths}
        if manifest.get("trajectory_sha256") != expected_hashes:
            raise RuntimeError(f"Trajectory hash drift: {model}")
        cells = set()
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            cell = (value["task"], value["model"], value["method"], value["generation_seed"])
            if cell in cells:
                raise RuntimeError(f"Duplicate trajectory cell: {cell}")
            cells.add(cell)
            audit = value["hidden_leak_audit"]
            if not audit["passed"] or audit["hidden_evaluation_count"] != 1 or audit["hidden_feedback_used"]:
                raise RuntimeError(f"Hidden isolation failure: {path}")
        observed += len(paths)
        model_records[model] = {"run_manifest": record(manifest_path), "summary": record(summary_path), "trajectory_count": len(paths)}
    if observed != EXPECTED_TOTAL:
        raise RuntimeError("Incomplete total G8 grid")
    rejected = {task: value for task, value in report["task_audit"].items() if not value["passed_preflight"]}
    blockers = []
    if rejected:
        blockers.append("repair or replace G8-rejected tasks without reusing observed preflight seeds")
    blockers += ["independent second-researcher semantic review (G7)", "CodeGuard+ slice remains narrow", "final prompt/oracle/model/budget freeze"]
    value = {
        "schema_version": 1,
        "freeze_id": FREEZE_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "g8_complete_human_g7_and_final_freeze_pending",
        "development_only": True,
        "formal_results_use": False,
        "formal_experiment_ready": False,
        "model_preflight_complete": True,
        "independent_human_review_complete": False,
        "breadth_sufficient_for_standalone_formal_external_experiment": False,
        "qualified_task_ids": report["qualified_tasks"],
        "rejected_tasks": rejected,
        "summary": report["summary"],
        "generation_seeds": SEEDS,
        "models": list(MODELS),
        "methods": report["methods"],
        "inputs": {"semantic_machine_freeze": record(SEMANTIC), "preflight_lock": record(LOCK)},
        "outputs": {"report": record(REPORT), "qualified_tasks": record(QUALIFIED), "model_runs": model_records},
        "formal_readiness_blockers": blockers,
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"trajectory_count": observed, "qualified_task_count": len(report["qualified_tasks"]), "rejected_task_count": len(rejected), "formal_experiment_ready": False}, indent=2))


if __name__ == "__main__":
    main()
