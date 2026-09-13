#!/usr/bin/env python3
"""Freeze a no-human-G7 CodeGuard+ technical-confirmatory experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.lock.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_technical_confirmatory_no_g7_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_technical_confirmatory_no_g7_hidden_v1.json"
PROMPTS = ROOT / "configs/prompts/codeguardplus_technical_confirmatory_no_g7_v1"
CANONICAL = ROOT / "benchmarks/manifests/codeguardplus-technical-confirmatory-no-g7-oracle-v1.json"
INPUT_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-technical-confirmatory-no-g7-input-v1-freeze.json"
G7_PACKET_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-final-g7-packet-v1-freeze.json"

SEEDS = [61057, 67061, 71069, 73079, 79087]
TASK_SOURCES = (
    (
        "cwe-327/2-py",
        "configs/oracles/codeguardplus_preflight_visible_v1.json",
        "configs/oracles/codeguardplus_preflight_hidden_v1.json",
        "benchmarks/manifests/codeguardplus-preflight-v1-freeze.json",
    ),
    (
        "cwe-089/2-py",
        "configs/oracles/codeguardplus_reserve_preflight_visible_v2.json",
        "configs/oracles/codeguardplus_reserve_preflight_hidden_v2.json",
        "benchmarks/manifests/codeguardplus-reserve-preflight-v2-freeze.json",
    ),
    (
        "cwe-117/2-py",
        "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_visible_v1.json",
        "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_hidden_v1.json",
        "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-preflight-v1-freeze.json",
    ),
)
METHODS = {
    "B0": {"name": "Requirement Only", "security_reminder": False, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B3": {"name": "All Visible Tests Upfront", "security_reminder": False, "upfront_tests": "all", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B4": {"name": "Shared B0 plus Fixed Raw Feedback", "security_reminder": False, "upfront_tests": "none", "feedback": "fixed_raw", "max_calls": 3, "shared_initial_from": "B0"},
    "M": {"name": "Shared B0 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "none", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B0"},
    "B6": {"name": "Shared B3 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "all", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B3"},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    path = path.resolve()
    path.relative_to(ROOT)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Frozen technical-confirmatory input drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def used_seeds() -> set[int]:
    used: set[int] = set()
    for path in (ROOT / "configs").rglob("*.json"):
        if path.resolve() in {CONFIG.resolve(), LOCK.resolve()}:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key, child in item.items():
                    if key in {"generation_seeds", "seeds"} and isinstance(child, list):
                        used.update(x for x in child if isinstance(x, int))
                    stack.append(child)
            elif isinstance(item, list):
                stack.extend(item)
    return used


def main() -> None:
    if not G7_PACKET_FREEZE.is_file():
        raise FileNotFoundError("Prepare the result-blinded G7 packet provenance first")
    g7 = json.loads(G7_PACKET_FREEZE.read_text(encoding="utf-8"))
    if g7.get("independent_human_review_complete") is not False:
        raise RuntimeError("This no-G7 protocol is only for the explicitly skipped-human-review branch")
    overlap = sorted(set(SEEDS) & used_seeds())
    if overlap:
        raise RuntimeError(f"Confirmatory seeds were used previously: {overlap}")

    tasks = []
    source_records: dict[str, Any] = {}
    visible_tasks: dict[str, Any] = {}
    hidden_tasks: dict[str, Any] = {}
    prompt_sources: dict[str, Any] = {}
    for task, visible_name, hidden_name, preflight_name in TASK_SOURCES:
        visible_path, hidden_path, preflight_path = ROOT / visible_name, ROOT / hidden_name, ROOT / preflight_name
        visible_source = json.loads(visible_path.read_text(encoding="utf-8"))
        hidden_source = json.loads(hidden_path.read_text(encoding="utf-8"))
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        if preflight.get("qualified_task_ids") != [task] or not preflight.get("model_preflight_complete"):
            raise RuntimeError(f"Task is not the sole frozen G8-qualified task: {task}")
        if task not in visible_source["tasks"] or task not in hidden_source["tasks"]:
            raise RuntimeError(f"Projection task absent: {task}")
        visible_item = dict(visible_source["tasks"][task])
        hidden_item = dict(hidden_source["tasks"][task])
        if visible_item["cwe"] != hidden_item["cwe"] or visible_item["contract"] != hidden_item["contract"]:
            raise RuntimeError(f"Projection semantic mismatch: {task}")
        source_prompt = ROOT / visible_item["prompt_file"]
        if sha(source_prompt) != visible_item["prompt_sha256"]:
            raise RuntimeError(f"Prompt source drift: {task}")
        destination = PROMPTS / f"{task.replace('/', '__')}.py"
        content = source_prompt.read_text(encoding="utf-8")
        if destination.exists() and destination.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"Frozen prompt drift: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        prompt_record = rec(destination)
        for item in (visible_item, hidden_item):
            item["prompt_file"] = prompt_record["path"]
            item["prompt_sha256"] = prompt_record["sha256"]
        tasks.append(task)
        visible_tasks[task] = visible_item
        hidden_tasks[task] = hidden_item
        prompt_sources[task] = {"source": rec(source_prompt), "frozen_copy": prompt_record}
        source_records[task] = {
            "visible_projection": rec(visible_path),
            "hidden_projection": rec(hidden_path),
            "g8_preflight_freeze": rec(preflight_path),
        }

    canonical = {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-technical-confirmatory-no-g7-v1",
        "tasks": tasks,
        "cwes": [visible_tasks[task]["cwe"] for task in tasks],
        "source_records": source_records,
        "prompt_sources": prompt_sources,
        "selection_basis": "union of the three tasks that passed their independently frozen G8 policies",
        "human_g7_status": "skipped_by_user_for_technical_confirmatory_run",
        "formal_results_use": False,
    }
    write_frozen(CANONICAL, canonical)
    canonical_hash = sha(CANONICAL)
    write_frozen(VISIBLE, {"schema_version": 1, "oracle_set_id": canonical["oracle_set_id"], "canonical_manifest_sha256": canonical_hash, "partition": "visible", "tasks": visible_tasks})
    write_frozen(HIDDEN, {"schema_version": 1, "oracle_set_id": canonical["oracle_set_id"], "canonical_manifest_sha256": canonical_hash, "partition": "hidden", "tasks": hidden_tasks})

    models = {
        "qwen25-coder-7b": {"checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct", "family": "Qwen2.5-Coder", "parameter_scale": "7B", "dtype": "bfloat16", "max_model_len": 8192},
        "qwen25-coder-14b": {"checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "family": "Qwen2.5-Coder", "parameter_scale": "14B", "dtype": "bfloat16", "max_model_len": 8192},
        "qwen36-27b": {"checkpoint": "<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B", "family": "Qwen3.6", "parameter_scale": "27B", "dtype": "bfloat16", "max_model_len": 16384},
    }
    config = {
        "schema_version": 2,
        "study_phase": "codeguardplus_external_technical_confirmatory_human_g7_skipped_v1",
        "oracle_set_id": canonical["oracle_set_id"],
        "pilot_only": False,
        "development_only": True,
        "technical_confirmatory": True,
        "formal_experiment": False,
        "formal_results_use": False,
        "human_g7_status": "skipped_by_user",
        "readiness_note": "Fresh-seed technical confirmation only; independent human G7 was explicitly skipped and results cannot be labeled formal human-qualified evidence.",
        "tasks": tasks,
        "generation_seeds": SEEDS,
        "models": models,
        "generation": {"temperature": 0.2, "max_completion_tokens_per_call": 3072, "model_overrides": {"qwen36-27b": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}}},
        "budgets": {"max_input_tokens_total": 14000, "max_output_tokens_total": 9216, "max_feedback_tokens_per_round": 600, "max_feedback_tokens_total": 1200, "max_visible_test_executions": 6, "timeout_per_test_seconds": 20},
        "primary_metric": "hidden_joint_at_1",
        "secondary_metrics": ["hidden_func_at_1", "hidden_secure_at_1", "hidden_safe_at_1", "pass_at_k", "secure_at_k", "joint_at_k", "feedback_repair_rate", "joint_regression_rate", "model_calls", "input_tokens", "output_tokens", "feedback_tokens"],
        "statistics": {"inference_unit": "task", "descriptive_only_due_to_task_count": 3, "bootstrap_clusters": "task", "bootstrap_replicates": 10000, "confidence_level": 0.95, "paired_comparisons": ["B4_vs_B0", "M_vs_B0", "B6_vs_B3", "M_vs_B4"]},
        "methods": METHODS,
    }
    write_frozen(CONFIG, config)
    frozen_files = {name: rec(path) for name, path in {"config": CONFIG, "visible_projection": VISIBLE, "hidden_projection": HIDDEN, "canonical_oracle": CANONICAL}.items()}
    lock = {
        "schema_version": 1,
        "lock_id": "codeguardplus-technical-confirmatory-no-g7-v1",
        "frozen_before_generation": True,
        "human_g7_skipped_by_user": True,
        "formal_results_use": False,
        "generation_seeds": SEEDS,
        "excluded_prior_generation_seeds": sorted(used_seeds()),
        "fresh_seed_overlap_count": 0,
        "expected_trajectory_count": len(tasks) * len(models) * len(SEEDS) * len(METHODS),
        "expected_trajectory_count_per_model": len(tasks) * len(SEEDS) * len(METHODS),
        "frozen_files": frozen_files,
        "g7_packet_freeze": rec(G7_PACKET_FREEZE),
        "source_preflight_freezes": {task: source_records[task]["g8_preflight_freeze"] for task in tasks},
    }
    write_frozen(LOCK, lock)
    freeze = {
        "schema_version": 1,
        "freeze_id": lock["lock_id"],
        "status": "technical_confirmatory_inputs_frozen_human_g7_skipped",
        "formal_experiment_ready": False,
        "formal_results_use": False,
        "independent_human_review_complete": False,
        "human_g7_skipped_by_user": True,
        "tasks": tasks,
        "models": list(models),
        "methods": list(METHODS),
        "generation_seeds": SEEDS,
        "expected_trajectory_count": lock["expected_trajectory_count"],
        "inputs": {"lock": rec(LOCK), **frozen_files},
        "interpretation_boundary": "Technical machine-qualified external evidence only; not independent-human-G7-qualified formal evidence.",
    }
    write_frozen(INPUT_FREEZE, freeze)
    print(json.dumps({"tasks": tasks, "models": list(models), "methods": list(METHODS), "seeds": SEEDS, "expected_trajectory_count": lock["expected_trajectory_count"], "fresh_seed_overlap_count": 0, "formal_results_use": False}, indent=2))


if __name__ == "__main__":
    main()
