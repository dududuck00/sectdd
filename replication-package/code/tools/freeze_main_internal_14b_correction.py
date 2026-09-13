#!/usr/bin/env python3
"""Freeze the completed CWEval internal-main 14B checkpoint correction."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks/manifests/main-internal-14b-checkpoint-correction-v1-freeze.json"
CONFIG = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.json"
LOCK = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.lock.json"
REPORT_JSON = ROOT / "artifacts/reports/main-internal-main-003-corrected.json"
REPORT_MD = ROOT / "docs/main-internal-main-003-corrected.md"
INVALID_RUN = ROOT / "artifacts/main_internal/qwen25-coder-14b-main-002"
REPLACEMENT_RUN = ROOT / "artifacts/main_internal/qwen25-coder-14b-main-003-corrected"
PEER_RUNS = {
    "qwen25-coder-7b": ROOT / "artifacts/main_internal/qwen25-coder-7b-main-002",
    "qwen3-32b": ROOT / "artifacts/main_internal/qwen3-32b-main-002",
}
EXPECTED_CONFIG_SHA256 = "35f01d15aa73d4b4d6eae05aec6bbf1b74ae289af9754b9d2bd86a0b4374fd16"
EXPECTED_MODEL_CONFIG_SHA256 = "9051fe83840dcd3a0f7e9f5b3372fc3927419eb56983273eac2dc635a5da7eae"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": digest(path),
        "size_bytes": path.stat().st_size,
    }


def run_record(root: Path) -> dict[str, Any]:
    return {
        "run_manifest": record(root / "run_manifest.json"),
        "summary": record(root / "summary.json"),
    }


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    required = [CONFIG, LOCK, REPORT_JSON, REPORT_MD]
    for run in [INVALID_RUN, REPLACEMENT_RUN, *PEER_RUNS.values()]:
        required.extend([run / "run_manifest.json", run / "summary.json"])
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if digest(CONFIG) != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("Corrected config hash changed")

    replacement = json.loads((REPLACEMENT_RUN / "run_manifest.json").read_text())
    invalid = json.loads((INVALID_RUN / "run_manifest.json").read_text())
    report = json.loads(REPORT_JSON.read_text())
    if replacement["model"] != "qwen25-coder-14b" or replacement["trajectory_count"] != 315:
        raise RuntimeError("Replacement run does not have the frozen 14B shape")
    if replacement["input_sha256"]["config"] != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("Replacement run did not use the corrected config")
    replacement_model_hash = replacement["model_freeze"]["files_sha256"]["config.json"]
    invalid_model_hash = invalid["model_freeze"]["files_sha256"]["config.json"]
    if replacement_model_hash != EXPECTED_MODEL_CONFIG_SHA256:
        raise RuntimeError("Replacement run did not use the corrected Instruct model")
    if invalid_model_hash == replacement_model_hash:
        raise RuntimeError("Excluded and replacement checkpoint identities unexpectedly match")
    if report["design"]["trajectory_count"] != 945:
        raise RuntimeError("Corrected report does not contain the three-model grid")
    if not report["checkpoint_correction"]["design_equivalent_except_14b_checkpoint_path"]:
        raise RuntimeError("Report does not declare the constrained correction")

    methods = report["models"]["qwen25-coder-14b"]["methods"]
    payload = {
        "schema_version": 1,
        "freeze_id": "main-internal-14b-checkpoint-correction-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "checkpoint_correction_complete",
        "formal_result": True,
        "external_generalization_claim": False,
        "correction": {
            "scope": "Replace only the mislabeled Qwen2.5-Coder-14B condition; retain the frozen tasks, methods, seeds, budgets, prompts, and oracle projections.",
            "excluded_run": run_record(INVALID_RUN),
            "excluded_checkpoint_config_sha256": invalid_model_hash,
            "replacement_run": run_record(REPLACEMENT_RUN),
            "replacement_checkpoint_config_sha256": replacement_model_hash,
            "old_run_must_not_enter_effect_analysis": True,
        },
        "design": {
            "tasks": 9,
            "methods": ["B0", "B1", "B2", "B3", "B4", "B5", "M"],
            "seeds": [101, 202, 303, 404, 505],
            "replacement_trajectories": 315,
            "corrected_three_model_trajectories": 945,
        },
        "inputs": {
            "corrected_config": record(CONFIG),
            "pre_run_equivalence_lock": record(LOCK),
            "valid_peer_runs": {model: run_record(path) for model, path in PEER_RUNS.items()},
        },
        "outputs": {
            "corrected_report_json": record(REPORT_JSON),
            "corrected_report_markdown": record(REPORT_MD),
        },
        "qwen25_coder_14b_key_results": {
            method: {
                "hidden_secure_pass_at_1": methods[method]["hidden_secure_pass_at_1"],
                "hidden_safe_at_1": methods[method]["hidden_safe_at_1"],
                "hidden_func_at_1": methods[method]["hidden_func_at_1"],
                "hidden_secure_at_1": methods[method]["hidden_secure_at_1"],
                "mean_model_calls": methods[method]["cost"]["model_calls"]["mean"],
            }
            for method in ("B0", "B3", "B4", "B5", "M")
        },
        "interpretation_boundary": "Nine CWEval tasks participated in method development; this result supports internal repeatability and mechanism analysis, not external generalization.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"freeze": record(OUTPUT), "status": payload["status"]}, indent=2))


if __name__ == "__main__":
    main()
