#!/usr/bin/env python3
"""Freeze the wave-2 G8 preflight inputs before any model generation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "configs/benchmarks/sallm_wave2_semantic_machine_qualified_v1.json"
SOURCE_FREEZE = ROOT / "benchmarks/manifests/sallm-wave2-semantic-machine-v1-freeze.json"
VISIBLE_SOURCE = ROOT / "configs/oracles/sallm_wave2_semantic_machine_visible_v1.json"
HIDDEN_SOURCE = ROOT / "configs/oracles/sallm_wave2_semantic_machine_hidden_v1.json"
VISIBLE_OVERLAY = ROOT / "configs/benchmarks/sallm_wave2_semantic_machine_visible_v1.json"
HIDDEN_OVERLAY = ROOT / "configs/benchmarks/sallm_wave2_semantic_machine_hidden_v1.json"

CONFIG = ROOT / "configs/experiments/sallm_wave2_preflight_v1.json"
LOCK = ROOT / "configs/experiments/sallm_wave2_preflight_v1.lock.json"
VISIBLE = ROOT / "configs/oracles/sallm_wave2_preflight_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/sallm_wave2_preflight_hidden_v1.json"
SEEDS = [8113, 9277]


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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prior_seeds() -> set[int]:
    values: set[int] = set()
    for path in (ROOT / "configs/experiments").glob("*.json"):
        if path in {CONFIG, LOCK}:
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        seeds = item.get("generation_seeds")
        if isinstance(seeds, list):
            values.update(int(seed) for seed in seeds)
    return values


def projection(source_path: Path, overlay_path: Path, partition: str) -> dict[str, Any]:
    value = json.loads(source_path.read_text(encoding="utf-8"))
    value["oracle_set_id"] = "sallm-wave2-preflight-v1"
    value["oracle_status"] = "g8_preflight_frozen"
    value["partition"] = partition
    value["execution_overlay"] = record(overlay_path)
    return value


def main() -> None:
    inputs = (
        TASK_FILE,
        SOURCE_FREEZE,
        VISIBLE_SOURCE,
        HIDDEN_SOURCE,
        VISIBLE_OVERLAY,
        HIDDEN_OVERLAY,
    )
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (CONFIG, LOCK, VISIBLE, HIDDEN):
        if path.exists():
            raise FileExistsError(path)
    used = prior_seeds()
    overlap = used.intersection(SEEDS)
    if overlap:
        raise RuntimeError(f"Preflight seeds are not fresh: {sorted(overlap)}")
    if any(
        next((ROOT / "artifacts").glob(f"**/seed_{seed}"), None) is not None
        for seed in SEEDS
    ):
        raise RuntimeError("A selected seed already exists in an artifact trajectory")

    tasks_value = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    tasks = tasks_value["tasks"]
    if tasks_value.get("model_preflight_complete") is not False or len(tasks) != 2:
        raise RuntimeError("Expected exactly two machine-semantic-qualified tasks pending G8")
    write(VISIBLE, projection(VISIBLE_SOURCE, VISIBLE_OVERLAY, "visible"))
    write(HIDDEN, projection(HIDDEN_SOURCE, HIDDEN_OVERLAY, "hidden"))

    models = {
        "qwen25-coder-7b": {
            "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct",
            "family": "Qwen2.5", "parameter_scale": "7B", "dtype": "bfloat16",
            "tensor_parallel_size": 1, "max_model_len": 8192,
        },
        "qwen25-coder-14b": {
            "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct",
            "family": "Qwen2.5", "parameter_scale": "14B", "dtype": "bfloat16",
            "tensor_parallel_size": 1, "max_model_len": 8192,
        },
        "qwen36-27b": {
            "checkpoint": "<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B",
            "family": "Qwen3.6", "parameter_scale": "27B", "dtype": "bfloat16",
            "tensor_parallel_size": 1, "max_model_len": 16384,
        },
    }
    methods = {
        "B0": {"name": "Requirement Only", "security_reminder": False, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
        "M": {"name": "Shared B0 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "none", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B0"},
        "B3": {"name": "All Visible Tests Upfront", "security_reminder": False, "upfront_tests": "all", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
        "B6": {"name": "Shared B3 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "all", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B3"},
    }
    config = {
        "schema_version": 1,
        "pilot_only": True,
        "development_only": True,
        "study_phase": "sallm_wave2_model_preflight_v1",
        "oracle_set_id": "sallm-wave2-preflight-v1",
        "tasks": tasks,
        "generation_seeds": SEEDS,
        "models": models,
        "generation": {
            "temperature": 0.2,
            "max_completion_tokens_per_call": 3072,
            "model_overrides": {"qwen36-27b": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}},
        },
        "budgets": {
            "max_input_tokens_total": 14000, "max_output_tokens_total": 9216,
            "max_feedback_tokens_per_round": 600, "max_feedback_tokens_total": 1200,
            "max_visible_test_executions": 6, "timeout_per_test_seconds": 20,
        },
        "primary_metric": "preflight_identifiability",
        "secondary_metrics": ["hidden_func_at_1", "hidden_secure_at_1", "hidden_joint_at_1", "security_only_failure_rate", "feedback_trigger_rate", "joint_repair_rate"],
        "methods": methods,
        "preflight_policy": {
            "models": len(models), "seeds_per_model": len(SEEDS),
            "reject_universal_ceiling": True, "reject_universal_floor": True,
            "require_security_only_failure_observation": True,
            "require_any_feedback_trigger": True, "formal_results_use": False,
        },
    }
    write(CONFIG, config)
    lock = {
        "schema_version": 1,
        "lock_id": "sallm-wave2-preflight-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_generation": True,
        "generation_seeds": SEEDS,
        "excluded_prior_generation_seeds": sorted(used),
        "fresh_seed_overlap_count": 0,
        "expected_trajectory_count": len(tasks) * len(models) * len(SEEDS) * len(methods),
        "inputs": {"semantic_freeze": record(SOURCE_FREEZE), "task_file": record(TASK_FILE)},
        "frozen_files": {"config": record(CONFIG), "visible_projection": record(VISIBLE), "hidden_projection": record(HIDDEN), "visible_overlay": record(VISIBLE_OVERLAY), "hidden_overlay": record(HIDDEN_OVERLAY)},
    }
    write(LOCK, lock)
    print(json.dumps({"tasks": tasks, "seeds": SEEDS, "expected_trajectory_count": lock["expected_trajectory_count"]}, indent=2))


if __name__ == "__main__":
    main()
