#!/usr/bin/env python3
"""Freeze the eight-method, four-model, five-repeat expansion matrices."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SEEDS = [151001, 151021, 151051, 151057, 151091]
TARGET_TOTAL_TASKS = 32
MINIMUM_REALIZED_TASKS_FOR_SHORTFALL = 20

ORACLES = {
    "cweval": (
        ROOT / "configs/oracles/cweval_py_paper_expansion_v1_semantic_machine_visible.json",
        ROOT / "configs/oracles/cweval_py_paper_expansion_v1_semantic_machine_hidden.json",
        1,
    ),
    "sallm": (
        ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json",
        ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json",
        8,
    ),
    "codeguardplus": (
        ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json",
        ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json",
        8,
    ),
}

CONFIGS = {
    name: ROOT / f"configs/experiments/{name}_paper_expansion_full_v1.json"
    for name in ORACLES
}
LOCK = ROOT / "benchmarks/manifests/paper-expansion-full-v1-input-freeze.json"

METHODS = {
    "B0": {"name": "Requirement Only", "security_reminder": False, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B1": {"name": "Security Reminder", "security_reminder": True, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B2": {"name": "Functional Tests Upfront", "security_reminder": False, "upfront_tests": "functional", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B3": {"name": "All Visible Tests Upfront", "security_reminder": False, "upfront_tests": "all", "feedback": "none", "max_calls": 1, "shared_initial_from": None},
    "B4": {"name": "Shared B0 plus Fixed Raw Feedback", "security_reminder": False, "upfront_tests": "none", "feedback": "fixed_raw", "max_calls": 3, "shared_initial_from": "B0"},
    "B5": {"name": "Shared B0 plus Random Raw Feedback", "security_reminder": False, "upfront_tests": "none", "feedback": "random_raw", "max_calls": 3, "shared_initial_from": "B0"},
    "M": {"name": "Shared B0 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "none", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B0"},
    "B6": {"name": "Shared B3 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "all", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B3"},
}

MODELS = {
    "qwen25-coder-7b": {"provider": "local", "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct", "family": "Qwen2.5-Coder", "parameter_scale": "7B", "dtype": "bfloat16", "max_model_len": 8192},
    "qwen25-coder-14b": {"provider": "local", "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "family": "Qwen2.5-Coder", "parameter_scale": "14B", "dtype": "bfloat16", "max_model_len": 8192},
    "qwen36-27b": {"provider": "local", "checkpoint": "<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B", "family": "Qwen3.6", "parameter_scale": "27B", "dtype": "bfloat16", "max_model_len": 16384},
    "deepseek-v4-flash": {"provider": "deepseek", "remote_model": True, "remote_model_id": "deepseek-v4-flash", "api_base": "https://api.deepseek.com", "family": "DeepSeek", "parameter_scale": "undisclosed_api", "tokenizer_proxy": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "tokenizer_accounting": "local_proxy_for_budget_only", "max_model_len": 16384},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-more-tasks",
        action="store_true",
        help="Deprecated compatibility flag; every dynamically and semantically valid task is always retained",
    )
    parser.add_argument(
        "--accept-qualified-shortfall",
        action="store_true",
        help=(
            "Retain every result-blind qualified task when the aspirational "
            "32-task construction target is missed; record the deviation in "
            "the immutable input freeze"
        ),
    )
    return parser.parse_args()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Full-matrix freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def previously_used_seeds() -> set[int]:
    excluded = {path.resolve() for path in (*CONFIGS.values(), LOCK)}
    used: set[int] = set()
    for path in (ROOT / "configs").rglob("*.json"):
        if path.resolve() in excluded:
            continue
        try:
            root = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stack = [root]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {
                        "generation_seeds",
                        "generation_request_slots",
                        "seeds",
                    } and isinstance(child, list):
                        used.update(item for item in child if isinstance(item, int))
                    stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
    return used


def main() -> None:
    a = parse_args()
    overlap = sorted(set(SEEDS) & previously_used_seeds())
    if overlap:
        raise RuntimeError(f"Expansion seeds/request slots were previously used: {overlap}")
    frozen: dict[str, Any] = {}
    staged_configs: dict[str, dict[str, Any]] = {}
    staged_inputs: dict[str, tuple[Path, Path, int]] = {}
    total_tasks = total_trajectories = 0
    for benchmark, (visible_path, hidden_path, minimum) in ORACLES.items():
        if not visible_path.is_file() or not hidden_path.is_file():
            raise FileNotFoundError(f"Semantic-machine projections are missing for {benchmark}")
        visible, hidden = load(visible_path), load(hidden_path)
        if visible.get("partition") != "visible" or hidden.get("partition") != "hidden":
            raise ValueError(f"Invalid {benchmark} partition labels")
        if visible["oracle_set_id"] != hidden["oracle_set_id"] or visible["canonical_manifest_sha256"] != hidden["canonical_manifest_sha256"]:
            raise ValueError(f"{benchmark} projection mismatch")
        tasks = list(visible["tasks"])
        if set(tasks) != set(hidden["tasks"]):
            raise ValueError(f"{benchmark} task mismatch")
        if len(tasks) < minimum and not a.accept_qualified_shortfall:
            raise RuntimeError(f"{benchmark} has {len(tasks)} qualified tasks; requires at least {minimum}")
        config = {
            "schema_version": 4,
            "study_phase": f"{benchmark}_paper_expansion_full_v1",
            "oracle_set_id": visible["oracle_set_id"],
            "pilot_only": False,
            "development_only": False,
            "technical_confirmatory": False,
            "formal_experiment": True,
            "formal_results_use": True,
            "selection_policy": "dynamic and semantic oracle validity only; no B0--B6/M or G8 outcome filter",
            "tasks": tasks,
            "generation_seeds": SEEDS,
            "generation_request_slots": SEEDS,
            "models": MODELS,
            "generation": {"temperature": 0.2, "max_completion_tokens_per_call": 3072, "model_overrides": {"deepseek-v4-flash": {"extra_body": {"thinking": {"type": "disabled"}}}}},
            "budgets": {"max_input_tokens_total": 14000, "max_output_tokens_total": 9216, "max_feedback_tokens_per_round": 600, "max_feedback_tokens_total": 1200, "max_visible_test_executions": 24, "timeout_per_test_seconds": 20, "wall_timeout_seconds": 180},
            "methods": METHODS,
            "primary_metric": "hidden_joint_at_1",
            "secondary_metrics": ["hidden_func_at_1", "hidden_secure_at_1", "hidden_safe_at_1", "security_given_functional", "tfor", "feedback_repair_rate", "joint_regression_rate", "function_regression_rate", "model_calls", "input_tokens", "output_tokens", "feedback_tokens"],
            "statistics": {"inference_unit": "task", "bootstrap_clusters": "task", "bootstrap_replicates": 10000, "confidence_level": 0.95, "paired_comparisons": ["B1_vs_B0", "B2_vs_B0", "B3_vs_B0", "B4_vs_B0", "B5_vs_B0", "M_vs_B0", "B6_vs_B3", "M_vs_B4", "M_vs_B5"]},
            "remote_provider": {"credential_env": "DEEPSEEK_API_KEY", "credential_persisted": False, "provider_seed_supported": False, "request_slot_policy": "slot identifiers are not sent as unsupported seeds"},
        }
        trajectories = len(tasks) * len(METHODS) * len(SEEDS) * len(MODELS)
        staged_configs[benchmark] = config
        staged_inputs[benchmark] = (visible_path, hidden_path, trajectories)
        total_tasks += len(tasks); total_trajectories += trajectories
    if total_tasks < TARGET_TOTAL_TASKS and not a.accept_qualified_shortfall:
        raise RuntimeError(
            f"Only {total_tasks} expansion tasks passed the result-blind gates; "
            f"the frozen paper target is {TARGET_TOTAL_TASKS}. Keep every accepted "
            "task and construct another result-blind external-benchmark wave."
        )
    if (
        a.accept_qualified_shortfall
        and total_tasks < MINIMUM_REALIZED_TASKS_FOR_SHORTFALL
    ):
        raise RuntimeError(
            f"Only {total_tasks} expansion tasks passed; the explicit shortfall "
            f"policy still requires {MINIMUM_REALIZED_TASKS_FOR_SHORTFALL}."
        )
    for benchmark, config in staged_configs.items():
        visible_path, hidden_path, trajectories = staged_inputs[benchmark]
        write_frozen(CONFIGS[benchmark], config)
        frozen[benchmark] = {
            "tasks": len(config["tasks"]),
            "trajectories": trajectories,
            "config": rec(CONFIGS[benchmark]),
            "visible": rec(visible_path),
            "hidden": rec(hidden_path),
        }
    lock = {
        "schema_version": 1,
        "freeze_id": "paper-expansion-full-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_generation": True,
        "method_or_g8_outcome_filter_applied": False,
        "benchmarks": frozen,
        "methods": list(METHODS),
        "models": list(MODELS),
        "generation_seeds_or_request_slots": SEEDS,
        "minimum_external_tasks_per_benchmark": 8,
        "minimum_total_expansion_tasks": TARGET_TOTAL_TASKS,
        "qualified_shortfall_accepted": a.accept_qualified_shortfall,
        "qualified_shortfall": max(0, TARGET_TOTAL_TASKS - total_tasks),
        "qualified_shortfall_policy": (
            "All result-blind dynamically and semantically qualified tasks are retained; "
            "the aspirational construction target is not a stopping rule and no prior "
            "method/G8 outcomes are used to replace rejected tasks."
            if a.accept_qualified_shortfall
            else None
        ),
        "realized_tasks_by_benchmark": {
            name: len(config["tasks"]) for name, config in staged_configs.items()
        },
        "new_task_count": total_tasks,
        "expected_trajectory_count": total_trajectories,
        "expected_paid_api_trajectory_count": total_tasks * len(METHODS) * len(SEEDS),
        "maximum_paid_api_calls_after_shared_initial_reuse": total_tasks * len(SEEDS) * 12,
        "complete": True,
    }
    if LOCK.exists():
        lock["created_at_utc"] = load(LOCK)["created_at_utc"]
    write_frozen(LOCK, lock)
    print(json.dumps({"new_tasks": total_tasks, "methods": len(METHODS), "models": len(MODELS), "repeats": len(SEEDS), "expected_trajectories": total_trajectories, "maximum_paid_api_calls": lock["maximum_paid_api_calls_after_shared_initial_reuse"]}, indent=2))


if __name__ == "__main__":
    main()
