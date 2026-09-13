#!/usr/bin/env python3
"""Verify and freeze completed no-G7 CodeGuard+ technical evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1"
CONFIG = ROOT / "configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.lock.json"
REPORT = RUN / "report.json"
MARKDOWN = ROOT / "docs/codeguardplus-technical-confirmatory-no-g7-v1.md"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-technical-confirmatory-no-g7-results-v1-freeze.json"
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b", "qwen36-27b")
EXPECTED_PER_MODEL = 75
EXPECTED_TOTAL = 225


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def main() -> None:
    if FREEZE.exists():
        raise FileExistsError(FREEZE)
    for path in (CONFIG, LOCK, REPORT, MARKDOWN):
        if not path.is_file():
            raise FileNotFoundError(path)
    config, lock, report = [json.loads(path.read_text(encoding="utf-8")) for path in (CONFIG, LOCK, REPORT)]
    if not lock.get("human_g7_skipped_by_user") or lock.get("formal_results_use") is not False:
        raise RuntimeError("No-G7 interpretation boundary drift")
    if lock["fresh_seed_overlap_count"] != 0 or lock["generation_seeds"] != config["generation_seeds"]:
        raise RuntimeError("Fresh confirmatory seed policy drift")
    if report.get("formal_results_use") is not False or report.get("human_g7_status") != "skipped_by_user":
        raise RuntimeError("Report incorrectly claims formal readiness")
    model_records = {}
    observed = 0
    for model in MODELS:
        root = RUN / model
        manifest_path, summary_path = root / "run_manifest.json", root / "summary.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["model"] != model or manifest["tasks"] != config["tasks"] or manifest["seeds"] != config["generation_seeds"] or manifest["methods"] != list(config["methods"]):
            raise RuntimeError(f"Model grid drift: {model}")
        if manifest.get("formal_results_use") is not False or not manifest.get("technical_confirmatory"):
            raise RuntimeError(f"Model interpretation boundary drift: {model}")
        for key in ("config", "visible_projection", "hidden_projection"):
            if manifest["input_sha256"][key] != lock["frozen_files"][key]["sha256"]:
                raise RuntimeError(f"Frozen input drift: {model}/{key}")
        paths = sorted((root / "trajectories").glob("*/*/seed_*/trajectory.json"))
        if len(paths) != EXPECTED_PER_MODEL or manifest["trajectory_count"] != EXPECTED_PER_MODEL:
            raise RuntimeError(f"Incomplete model run: {model}")
        hashes = {path.relative_to(root).as_posix(): sha(path) for path in paths}
        if hashes != manifest["trajectory_sha256"]:
            raise RuntimeError(f"Trajectory hash drift: {model}")
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            audit = value["hidden_leak_audit"]
            if not audit["passed"] or audit["hidden_evaluation_count"] != 1 or audit["hidden_feedback_used"]:
                raise RuntimeError(f"Hidden isolation failure: {path}")
        observed += len(paths)
        model_records[model] = {"run_manifest": rec(manifest_path), "summary": rec(summary_path), "trajectory_count": len(paths)}
    if observed != EXPECTED_TOTAL or report["design"]["trajectories"] != EXPECTED_TOTAL:
        raise RuntimeError("Incomplete technical-confirmatory grid")
    value = {"schema_version": 1, "freeze_id": "codeguardplus-technical-confirmatory-no-g7-results-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "technical_confirmatory_complete_human_g7_skipped", "technical_confirmatory": True, "formal_experiment_ready": False, "formal_results_use": False, "independent_human_review_complete": False, "human_g7_skipped_by_user": True, "summary": {"trajectory_count": observed, "model_count": len(MODELS), "task_count": len(config["tasks"]), "method_count": len(config["methods"]), "seed_count": len(config["generation_seeds"])}, "inputs": {"config": rec(CONFIG), "lock": rec(LOCK)}, "outputs": {"report": rec(REPORT), "markdown": rec(MARKDOWN), "model_runs": model_records}, "interpretation_boundary": "Fresh-seed technical machine-qualified external evidence only; not independent-human-G7-qualified formal evidence."}
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**value["summary"], "formal_results_use": False, "human_g7_status": "skipped_by_user"}, indent=2))


if __name__ == "__main__":
    main()
