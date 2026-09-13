#!/usr/bin/env python3
"""Build the frozen multi-model preflight config for SALLM expansion tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "configs/benchmarks/sallm_expansion_partitioned_qualified_v1.json"
DEFAULT_OUTPUT = ROOT / "configs/experiments/sallm_expansion_preflight_v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_path = args.task_file.expanduser().resolve()
    output = args.output.expanduser().resolve()
    task_path.relative_to(ROOT)
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError(output)
    tasks = json.loads(task_path.read_text(encoding="utf-8"))["tasks"]
    if not tasks:
        raise RuntimeError("No partition-qualified tasks are available")
    config = {
        "schema_version": 1,
        "pilot_only": True,
        "development_only": True,
        "study_phase": "sallm_expansion_model_preflight_v1",
        "oracle_set_id": "sallm-expansion-partitioned-v1",
        "tasks": tasks,
        "generation_seeds": [1701, 2903],
        "models": {
            "qwen25-coder-7b": {
                "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct",
                "family": "Qwen2.5",
                "parameter_scale": "7B",
                "dtype": "bfloat16",
                "tensor_parallel_size": 1,
                "max_model_len": 8192,
            },
            "qwen25-coder-14b": {
                "checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct",
                "family": "Qwen2.5",
                "parameter_scale": "14B",
                "dtype": "bfloat16",
                "tensor_parallel_size": 1,
                "max_model_len": 8192,
            },
            "qwen36-27b": {
                "checkpoint": "<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B",
                "family": "Qwen3.6",
                "parameter_scale": "27B",
                "dtype": "bfloat16",
                "tensor_parallel_size": 1,
                "max_model_len": 16384,
            },
        },
        "generation": {
            "temperature": 0.2,
            "max_completion_tokens_per_call": 3072,
            "model_overrides": {
                "qwen36-27b": {
                    "extra_body": {
                        "chat_template_kwargs": {"enable_thinking": False}
                    }
                }
            },
        },
        "budgets": {
            "max_input_tokens_total": 14000,
            "max_output_tokens_total": 9216,
            "max_feedback_tokens_per_round": 600,
            "max_feedback_tokens_total": 1200,
            "max_visible_test_executions": 6,
            "timeout_per_test_seconds": 20,
        },
        "primary_metric": "preflight_identifiability",
        "secondary_metrics": [
            "hidden_func_at_1",
            "hidden_secure_at_1",
            "hidden_joint_at_1",
            "security_only_failure_rate",
            "feedback_trigger_rate",
            "joint_repair_rate",
        ],
        "methods": {
            "B0": {
                "name": "Requirement Only",
                "security_reminder": False,
                "upfront_tests": "none",
                "feedback": "none",
                "max_calls": 1,
                "shared_initial_from": None,
            },
            "M": {
                "name": "Shared B0 plus SecTDD Structured Priority",
                "security_reminder": False,
                "upfront_tests": "none",
                "feedback": "sectdd_structured",
                "max_calls": 3,
                "shared_initial_from": "B0",
            },
            "B3": {
                "name": "All Visible Tests Upfront",
                "security_reminder": False,
                "upfront_tests": "all",
                "feedback": "none",
                "max_calls": 1,
                "shared_initial_from": None,
            },
            "B6": {
                "name": "Shared B3 plus SecTDD Structured Priority",
                "security_reminder": False,
                "upfront_tests": "all",
                "feedback": "sectdd_structured",
                "max_calls": 3,
                "shared_initial_from": "B3",
            },
        },
        "preflight_policy": {
            "models": 3,
            "seeds_per_model": 2,
            "reject_universal_ceiling": True,
            "reject_universal_floor": True,
            "require_security_only_failure_observation": True,
            "require_any_feedback_trigger": True,
            "formal_results_use": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"task_count": len(tasks), "trajectory_count": len(tasks) * 3 * 2 * 4, "output": output.relative_to(ROOT).as_posix()}, indent=2))


if __name__ == "__main__":
    main()
