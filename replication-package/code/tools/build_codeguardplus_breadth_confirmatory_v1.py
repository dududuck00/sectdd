#!/usr/bin/env python3
"""Freeze the outcome-unfiltered 11-task CodeGuard+ breadth experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/experiments/codeguardplus_breadth_confirmatory_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_breadth_confirmatory_v1.lock.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_breadth_confirmatory_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_breadth_confirmatory_hidden_v1.json"
PROMPTS = ROOT / "configs/prompts/codeguardplus_breadth_confirmatory_v1"
CANONICAL = ROOT / "benchmarks/manifests/codeguardplus-breadth-confirmatory-oracle-v1.json"
INPUT_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-breadth-confirmatory-input-v1-freeze.json"

REQUEST_SLOTS = [107021, 109049, 113051, 127081, 131071]
TASK_GROUPS = (
    (
        "configs/oracles/codeguardplus_preflight_visible_v1.json",
        "configs/oracles/codeguardplus_preflight_hidden_v1.json",
        "benchmarks/manifests/codeguardplus-semantic-machine-v2-freeze.json",
    ),
    (
        "configs/oracles/codeguardplus_reserve_preflight_visible_v2.json",
        "configs/oracles/codeguardplus_reserve_preflight_hidden_v2.json",
        "benchmarks/manifests/codeguardplus-reserve-semantic-machine-v2-freeze.json",
    ),
    (
        "configs/oracles/codeguardplus_reserve_breadth_wave3_preflight_visible_v1.json",
        "configs/oracles/codeguardplus_reserve_breadth_wave3_preflight_hidden_v1.json",
        "benchmarks/manifests/codeguardplus-reserve-breadth-wave3-semantic-machine-v1-freeze.json",
    ),
    (
        "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_visible_v1.json",
        "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_hidden_v1.json",
        "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-machine-v1-freeze.json",
    ),
)

METHODS = {
    "B0": {"name": "Requirement Only", "security_reminder": False, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B3": {"name": "All Visible Tests Upfront", "security_reminder": False, "upfront_tests": "all", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B4": {"name": "Shared B0 plus Fixed Raw Feedback", "security_reminder": False, "upfront_tests": "none", "feedback": "fixed_raw", "max_calls": 3, "shared_initial_from": "B0"},
    "B5": {"name": "Shared B0 plus Random Raw Feedback", "security_reminder": False, "upfront_tests": "none", "feedback": "random_raw", "max_calls": 3, "shared_initial_from": "B0"},
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
        raise RuntimeError(f"Frozen breadth input drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def used_seeds() -> set[int]:
    used: set[int] = set()
    excluded = {CONFIG.resolve(), LOCK.resolve()}
    for path in (ROOT / "configs").rglob("*.json"):
        if path.resolve() in excluded:
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
                    if key in {"generation_seeds", "generation_request_slots", "seeds"} and isinstance(child, list):
                        used.update(x for x in child if isinstance(x, int))
                    stack.append(child)
            elif isinstance(item, list):
                stack.extend(item)
    return used


def main() -> None:
    prior = used_seeds()
    overlap = sorted(set(REQUEST_SLOTS) & prior)
    if overlap:
        raise RuntimeError(f"Breadth request slots were used previously: {overlap}")
    tasks: list[str] = []
    visible_tasks: dict[str, Any] = {}
    hidden_tasks: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    prompt_sources: dict[str, Any] = {}
    for visible_name, hidden_name, semantic_name in TASK_GROUPS:
        visible_path, hidden_path, semantic_path = ROOT / visible_name, ROOT / hidden_name, ROOT / semantic_name
        visible_source = json.loads(visible_path.read_text(encoding="utf-8"))
        hidden_source = json.loads(hidden_path.read_text(encoding="utf-8"))
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
        if semantic.get("machine_semantic_review_complete") is not True:
            raise RuntimeError(f"Machine semantic panel is incomplete: {semantic_path}")
        qualified = semantic.get("qualified_task_ids", [])
        if not qualified:
            raise RuntimeError(f"No machine-semantic qualified tasks: {semantic_path}")
        for task in qualified:
            if task in visible_tasks:
                raise RuntimeError(f"Duplicate qualified task: {task}")
            if task not in visible_source["tasks"] or task not in hidden_source["tasks"]:
                raise RuntimeError(f"Qualified task absent from projection: {task}")
            visible_item = dict(visible_source["tasks"][task])
            hidden_item = dict(hidden_source["tasks"][task])
            for key in ("cwe", "contract"):
                if visible_item[key] != hidden_item[key]:
                    raise RuntimeError(f"Projection mismatch for {task}: {key}")
            source_prompt = ROOT / visible_item["prompt_file"]
            if sha(source_prompt) != visible_item["prompt_sha256"]:
                raise RuntimeError(f"Prompt source drift: {task}")
            destination = PROMPTS / f"{task.replace('/', '__')}.py"
            content = source_prompt.read_text(encoding="utf-8")
            if destination.exists() and destination.read_text(encoding="utf-8") != content:
                raise RuntimeError(f"Frozen prompt drift: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            prompt = rec(destination)
            for item in (visible_item, hidden_item):
                item["prompt_file"] = prompt["path"]
                item["prompt_sha256"] = prompt["sha256"]
            tasks.append(task)
            visible_tasks[task] = visible_item
            hidden_tasks[task] = hidden_item
            prompt_sources[task] = {"source": rec(source_prompt), "frozen_copy": prompt}
            sources[task] = {
                "visible_projection": rec(visible_path),
                "hidden_projection": rec(hidden_path),
                "machine_semantic_freeze": rec(semantic_path),
            }
    if len(tasks) != 11:
        raise RuntimeError(f"Expected 11 unique qualified tasks, got {len(tasks)}")
    canonical = {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-breadth-confirmatory-v1",
        "tasks": tasks,
        "cwes": sorted({visible_tasks[task]["cwe"] for task in tasks}),
        "source_records": sources,
        "prompt_sources": prompt_sources,
        "selection_basis": "union of all tasks accepted by four frozen machine-semantic panels; no G8 outcome or feedback-trigger filter applied",
        "g8_outcome_filter_applied": False,
        "independent_human_g7_complete": False,
        "formal_results_use": False,
    }
    write_frozen(CANONICAL, canonical)
    canonical_hash = sha(CANONICAL)
    write_frozen(VISIBLE, {"schema_version": 1, "oracle_set_id": canonical["oracle_set_id"], "canonical_manifest_sha256": canonical_hash, "partition": "visible", "tasks": visible_tasks})
    write_frozen(HIDDEN, {"schema_version": 1, "oracle_set_id": canonical["oracle_set_id"], "canonical_manifest_sha256": canonical_hash, "partition": "hidden", "tasks": hidden_tasks})
    models = {
        "qwen25-coder-14b": {
            "provider": "local", "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "family": "Qwen2.5-Coder", "parameter_scale": "14B", "dtype": "bfloat16", "max_model_len": 8192,
        },
        "deepseek-v4-flash": {
            "provider": "deepseek", "remote_model": True, "remote_model_id": "deepseek-v4-flash", "api_base": "https://api.deepseek.com", "family": "DeepSeek", "parameter_scale": "undisclosed_api", "tokenizer_proxy": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "tokenizer_accounting": "local_proxy_for_budget_only", "max_model_len": 16384,
        },
    }
    config = {
        "schema_version": 3,
        "study_phase": "codeguardplus_outcome_unfiltered_breadth_confirmatory_v1",
        "oracle_set_id": canonical["oracle_set_id"],
        "pilot_only": False,
        "development_only": False,
        "technical_confirmatory": True,
        "formal_experiment": False,
        "formal_results_use": False,
        "human_g7_status": "not_completed",
        "selection_policy": canonical["selection_basis"],
        "tasks": tasks,
        "generation_seeds": REQUEST_SLOTS,
        "generation_request_slots": REQUEST_SLOTS,
        "models": models,
        "generation": {
            "temperature": 0.2,
            "max_completion_tokens_per_call": 3072,
            "model_overrides": {"deepseek-v4-flash": {"extra_body": {"thinking": {"type": "disabled"}}}},
        },
        "budgets": {"max_input_tokens_total": 14000, "max_output_tokens_total": 9216, "max_feedback_tokens_per_round": 600, "max_feedback_tokens_total": 1200, "max_visible_test_executions": 6, "timeout_per_test_seconds": 20},
        "primary_metric": "hidden_joint_at_1",
        "secondary_metrics": ["hidden_func_at_1", "hidden_secure_at_1", "hidden_safe_at_1", "security_given_functional", "tfor", "feedback_repair_rate", "joint_regression_rate", "function_regression_rate", "model_calls", "input_tokens", "output_tokens", "feedback_tokens"],
        "statistics": {"inference_unit": "task", "bootstrap_clusters": "task", "bootstrap_replicates": 10000, "confidence_level": 0.95, "paired_comparisons": ["B4_vs_B0", "B5_vs_B0", "M_vs_B0", "B6_vs_B3", "M_vs_B4", "M_vs_B5"]},
        "methods": METHODS,
        "remote_provider": {"credential_env": "DEEPSEEK_API_KEY", "credential_persisted": False, "provider_seed_supported": False, "external_data_transfer": True},
    }
    write_frozen(CONFIG, config)
    frozen_files = {name: rec(path) for name, path in {"config": CONFIG, "visible_projection": VISIBLE, "hidden_projection": HIDDEN, "canonical_oracle": CANONICAL}.items()}
    per_model = len(tasks) * len(METHODS) * len(REQUEST_SLOTS)
    lock = {
        "schema_version": 1,
        "lock_id": canonical["oracle_set_id"],
        "frozen_before_generation": True,
        "formal_results_use": False,
        "technical_confirmatory": True,
        "g8_outcome_filter_applied": False,
        "independent_human_g7_complete": False,
        "models": list(models),
        "methods": list(METHODS),
        "generation_request_slots": REQUEST_SLOTS,
        "excluded_prior_generation_seeds": sorted(prior),
        "fresh_seed_overlap_count": 0,
        "expected_trajectory_count_per_model": per_model,
        "expected_trajectory_count": per_model * len(models),
        "maximum_model_calls_per_model": len(tasks) * len(REQUEST_SLOTS) * sum(x["max_calls"] for x in METHODS.values()),
        "maximum_paid_api_calls": len(tasks) * len(REQUEST_SLOTS) * sum(x["max_calls"] for x in METHODS.values()),
        "frozen_files": frozen_files,
        "source_semantic_freezes": {task: sources[task]["machine_semantic_freeze"] for task in tasks},
        "interpretation_boundary": "Outcome-unfiltered machine-semantic breadth evidence; independent human G7 remains incomplete and formal_results_use=false.",
    }
    write_frozen(LOCK, lock)
    write_frozen(INPUT_FREEZE, {
        "schema_version": 1,
        "freeze_id": "codeguardplus-breadth-confirmatory-input-v1",
        "complete": True,
        "formal_results_use": False,
        "tasks": tasks,
        "models": list(models),
        "methods": list(METHODS),
        "generation_request_slots": REQUEST_SLOTS,
        "expected_trajectory_count": lock["expected_trajectory_count"],
        "inputs": {"lock": rec(LOCK), **frozen_files},
        "interpretation_boundary": lock["interpretation_boundary"],
    })
    print(json.dumps({"tasks": len(tasks), "models": len(models), "methods": len(METHODS), "request_slots": len(REQUEST_SLOTS), "trajectories_per_model": per_model, "total_trajectories": per_model * 2, "maximum_paid_api_calls": lock["maximum_paid_api_calls"], "formal_results_use": False}, indent=2))


if __name__ == "__main__":
    main()
