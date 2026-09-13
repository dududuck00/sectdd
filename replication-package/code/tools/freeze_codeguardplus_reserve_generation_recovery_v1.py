#!/usr/bin/env python3
"""Freeze a blind fallback for failed reserve-generation slots before oracle use."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WAVE_LOCK = ROOT / "configs/experiments/codeguardplus_reserve_expansion_v1.lock.json"
PRIMARY = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-safe"
OUTPUT = ROOT / "configs/experiments/codeguardplus_reserve_generation_recovery_v1.lock.json"
FALLBACK_BASE_SEED = 20360910


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def used_seeds() -> set[int]:
    values = set()
    for path in ROOT.glob("artifacts/codeguardplus*/**/run_manifest.json"):
        try:
            seed = json.loads(path.read_text(encoding="utf-8")).get("base_seed")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(seed, int):
            values.add(seed)
    return values


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    wave = json.loads(WAVE_LOCK.read_text(encoding="utf-8"))
    config_path = ROOT / wave["frozen_config"]["path"]
    if sha(config_path) != wave["frozen_config"]["sha256"]:
        raise RuntimeError("Wave configuration drift")
    manifest_path = PRIMARY / "run_manifest.json"
    summary_path = PRIMARY / "summary.json"
    candidates_path = PRIMARY / "candidates.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = [
        {
            "task_id": row["task_id"],
            "candidate_index": row["candidate_index"],
            "error_type": row.get("error_type"),
            "error": row.get("error"),
        }
        for row in rows
        if row["status"] != "success"
    ]
    if summary["failed_count"] != len(failed) or failed != [{
        "task_id": "cwe-078/6-py",
        "candidate_index": 2,
        "error_type": "JSONDecodeError",
        "error": "Unterminated string starting at: line 2 column 11 (char 12)",
    }]:
        raise RuntimeError(f"Unexpected failed-slot set: {failed}")
    if FALLBACK_BASE_SEED in used_seeds():
        raise RuntimeError("Fallback base seed was already used")
    if manifest.get("tests_exposed_to_model") is not False or manifest.get("security_query_exposed_to_model") is not False:
        raise RuntimeError("Primary generation was not oracle blind")
    payload = {
        "schema_version": 1,
        "lock_id": "codeguardplus-reserve-generation-recovery-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_any_functional_or_security_oracle_execution": True,
        "development_only": True,
        "formal_results_use": False,
        "trigger_rule": "apply fallback to every recorded non-success generation slot; never inspect candidate quality or oracle outcomes",
        "failed_slots": failed,
        "fallback": {
            "base_seed": FALLBACK_BASE_SEED,
            "effective_seed_by_slot": {"cwe-078/6-py#2": FALLBACK_BASE_SEED + 2},
            "model": manifest["model"],
            "local_thinking": "disabled",
            "temperature": manifest["temperature"],
            "top_p": manifest["top_p"],
            "max_tokens": manifest["max_tokens"],
            "merge_policy": "primary_success_else_first_successful_fallback_in_argument_order",
        },
        "inputs": {
            "wave_lock": record(WAVE_LOCK),
            "primary_manifest": record(manifest_path),
            "primary_summary": record(summary_path),
            "primary_candidates": record(candidates_path),
        },
        "expected_outputs": {
            "fallback_run": "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-safe-fallback-01",
            "merged_run": "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-safe-merged",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"failed_slots": failed, "fallback_base_seed": FALLBACK_BASE_SEED, "lock": record(OUTPUT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
