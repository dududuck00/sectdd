#!/usr/bin/env python3
"""Verify and freeze completed CodeGuard+ reserve-v2 G8 preflight evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/g8-preflight-v2"
REPORT = RUN_ROOT / "report.json"
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_preflight_v2.lock.json"
QUALIFIED = ROOT / "configs/benchmarks/codeguardplus_reserve_preflight_qualified_v2.json"
SEMANTIC = ROOT / "benchmarks/manifests/codeguardplus-reserve-semantic-machine-v2-freeze.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-preflight-v2-freeze.json"
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b")


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
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    qualified = json.loads(QUALIFIED.read_text(encoding="utf-8"))
    semantic = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    if lock["lock_id"] != "codeguardplus-reserve-preflight-v2" or not lock["frozen_before_generation"]:
        raise RuntimeError("Invalid preflight lock")
    if lock["fresh_seed_overlap_count"] != 0 or lock["generation_seeds"] != [23011, 29021]:
        raise RuntimeError("Fresh-seed policy mismatch")
    if lock["inputs"]["semantic_machine_freeze"]["sha256"] != sha(SEMANTIC):
        raise RuntimeError("Machine-semantic freeze drifted after G8 lock")
    if report["report_id"] != "codeguardplus-reserve-preflight-v2":
        raise RuntimeError("Unexpected G8 report identity")
    if report["models"] != list(MODELS) or report["seeds"] != lock["generation_seeds"]:
        raise RuntimeError("G8 model/seed grid drift")
    if set(report["methods"]) != {"B0", "M", "B3", "B6"}:
        raise RuntimeError("G8 method grid drift")
    expected_tasks = semantic["qualified_task_ids"]
    if set(report["task_audit"]) != set(expected_tasks):
        raise RuntimeError("G8 task grid drift")
    if report["summary"]["trajectory_count"] != 32 or lock["expected_trajectory_count"] != 32:
        raise RuntimeError("G8 trajectory count mismatch")
    if qualified["tasks"] != report["qualified_tasks"]:
        raise RuntimeError("G8 report/qualification mismatch")
    if qualified["formal_experiment_ready"] is not False or report["formal_experiment_results"] is not False:
        raise RuntimeError("Preflight cannot claim formal experiment readiness")

    trajectory_records = {}
    observed = 0
    for model in MODELS:
        run = RUN_ROOT / model
        manifest_path = run / "run_manifest.json"
        summary_path = run / "summary.json"
        if not manifest_path.is_file() or not summary_path.is_file():
            raise FileNotFoundError(run)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["model"] != model or manifest["tasks"] != expected_tasks:
            raise RuntimeError(f"Model run identity drift: {model}")
        for name, frozen_name in (
            ("config", "config"),
            ("visible_projection", "visible_projection"),
            ("hidden_projection", "hidden_projection"),
        ):
            if manifest["input_sha256"][name] != lock["frozen_files"][frozen_name]["sha256"]:
                raise RuntimeError(f"Frozen input drift for {model}: {name}")
        paths = sorted((run / "trajectories").glob("*/*/seed_*/trajectory.json"))
        if len(paths) != manifest["trajectory_count"] or len(paths) != 16:
            raise RuntimeError(f"Incomplete model run: {model}")
        expected_hashes = {
            path.relative_to(run).as_posix(): sha(path)
            for path in paths
        }
        if manifest.get("trajectory_sha256") != expected_hashes:
            raise RuntimeError(f"Trajectory hash drift: {model}")
        cells = set()
        for path in paths:
            trajectory = json.loads(path.read_text(encoding="utf-8"))
            cell = (
                trajectory["task"],
                trajectory["model"],
                trajectory["method"],
                trajectory["generation_seed"],
            )
            if cell in cells:
                raise RuntimeError(f"Duplicate G8 cell: {cell}")
            cells.add(cell)
            audit = trajectory["hidden_leak_audit"]
            if not audit["passed"] or audit["hidden_evaluation_count"] != 1 or audit["hidden_feedback_used"]:
                raise RuntimeError(f"Hidden isolation failure: {path}")
        observed += len(paths)
        trajectory_records[model] = {
            "run_manifest": record(manifest_path),
            "summary": record(summary_path),
            "trajectory_count": len(paths),
        }
    if observed != 32:
        raise RuntimeError("Incomplete total G8 grid")

    rejected = {
        task: value
        for task, value in report["task_audit"].items()
        if not value["passed_preflight"]
    }
    blockers = ["independent second-researcher semantic review (G7)"]
    if rejected:
        blockers.insert(0, "repair or replace G8-rejected tasks without reusing observed preflight seeds")
    blockers.extend(
        [
            "CodeGuard+ reserve slice is too narrow for a standalone broad benchmark claim",
            "final prompt/oracle/model/budget freeze",
        ]
    )
    value = {
        "schema_version": 1,
        "freeze_id": "codeguardplus-reserve-preflight-v2",
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
        "generation_seeds": report["seeds"],
        "models": report["models"],
        "methods": report["methods"],
        "inputs": {
            "semantic_machine_freeze": record(SEMANTIC),
            "preflight_lock": record(LOCK),
        },
        "outputs": {
            "report": record(REPORT),
            "qualified_tasks": record(QUALIFIED),
            "model_runs": trajectory_records,
        },
        "formal_readiness_blockers": blockers,
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "trajectory_count": observed,
                "qualified_task_count": len(report["qualified_tasks"]),
                "rejected_task_count": len(rejected),
                "formal_experiment_ready": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
