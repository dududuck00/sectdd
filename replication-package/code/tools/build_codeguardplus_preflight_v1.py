#!/usr/bin/env python3
"""Freeze fresh-seed CodeGuard+ G8 preflight inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "configs/benchmarks/codeguardplus_semantic_machine_qualified_v2.json"
SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-semantic-machine-v2-freeze.json"
ORACLE = ROOT / "oracles/codeguardplus_partitioned_v2/manifest.json"
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
CONFIG = ROOT / "configs/experiments/codeguardplus_preflight_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_preflight_v1.lock.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_preflight_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_preflight_hidden_v1.json"
PROMPTS = ROOT / "configs/prompts/codeguardplus_preflight_v1"
SEEDS = [13007, 17011]

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def record(path: Path) -> dict[str, Any]: return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}
def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def prior_seeds() -> set[int]:
    result = set()
    for path in (ROOT / "configs/experiments").glob("*.json"):
        if path in {CONFIG, LOCK}: continue
        try: value = json.loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        if isinstance(value.get("generation_seeds"), list): result.update(map(int, value["generation_seeds"]))
    return result

def main() -> None:
    for path in (TASK_FILE, SOURCE_FREEZE, ORACLE, BENCHMARK):
        if not path.is_file(): raise FileNotFoundError(path)
    for path in (CONFIG, LOCK, VISIBLE, HIDDEN, PROMPTS):
        if path.exists(): raise FileExistsError(path)
    used = prior_seeds()
    if used.intersection(SEEDS): raise RuntimeError("Preflight seed reuse")
    tasks = json.loads(TASK_FILE.read_text())["tasks"]
    oracle = json.loads(ORACLE.read_text())["tasks"]
    benchmark = {item["task_id"]: item for item in json.loads(BENCHMARK.read_text())["tasks"]}
    PROMPTS.mkdir(parents=True)
    prompt_records = {}
    for task in tasks:
        source = benchmark[task]["source"]
        file_context = ROOT / source["file_context"]["path"]
        function_context = ROOT / source["function_context"]["path"]
        path = PROMPTS / f"{task.replace('/', '__')}.py"
        path.write_text(file_context.read_text(encoding="utf-8").rstrip() + "\n\n" + function_context.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")
        prompt_records[task] = record(path)
    def projection(partition: str) -> dict[str, Any]:
        return {"schema_version": 1, "oracle_set_id": "codeguardplus-preflight-v1", "canonical_manifest_sha256": sha(SOURCE_FREEZE), "partition": partition, "tasks": {task: {"cwe": oracle[task]["cwe"], "contract": oracle[task]["contract"], "prompt_file": prompt_records[task]["path"], "prompt_sha256": prompt_records[task]["sha256"], "oracle_file": oracle[task][f"{partition}_test"]["path"], "oracle_sha256": oracle[task][f"{partition}_test"]["sha256"], "cases": [{"case_id": f"{task.replace('/', '__')}-{partition}-f", "marker": "functionality", "test_method": "test_correctness", "description": oracle[task]["families"][partition]["functionality"], "behavior_family": oracle[task]["families"][partition]["functionality"]}, {"case_id": f"{task.replace('/', '__')}-{partition}-s", "marker": "security", "test_method": "test_vulnerability", "description": oracle[task]["families"][partition]["security"], "behavior_family": oracle[task]["families"][partition]["security"]}]} for task in tasks}}
    write(VISIBLE, projection("visible")); write(HIDDEN, projection("hidden"))
    models = {"qwen25-coder-7b": {"checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct", "family": "Qwen2.5", "parameter_scale": "7B", "dtype": "bfloat16", "max_model_len": 8192}, "qwen25-coder-14b": {"checkpoint": "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct", "family": "Qwen2.5", "parameter_scale": "14B", "dtype": "bfloat16", "max_model_len": 8192}}
    methods = {"B0": {"name": "Requirement Only", "security_reminder": False, "upfront_tests": "none", "feedback": "none", "max_calls": 1, "shared_initial_from": None}, "M": {"name": "Shared B0 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "none", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B0"}, "B3": {"name": "All Visible Tests Upfront", "security_reminder": False, "upfront_tests": "all", "feedback": "none", "max_calls": 1, "shared_initial_from": None}, "B6": {"name": "Shared B3 plus SecTDD Structured Priority", "security_reminder": False, "upfront_tests": "all", "feedback": "sectdd_structured", "max_calls": 3, "shared_initial_from": "B3"}}
    config = {"schema_version": 1, "pilot_only": True, "development_only": True, "study_phase": "codeguardplus_model_preflight_v1", "oracle_set_id": "codeguardplus-preflight-v1", "tasks": tasks, "generation_seeds": SEEDS, "models": models, "generation": {"temperature": 0.2, "max_completion_tokens_per_call": 3072}, "budgets": {"max_input_tokens_total": 14000, "max_output_tokens_total": 9216, "max_feedback_tokens_per_round": 600, "max_feedback_tokens_total": 1200, "max_visible_test_executions": 6, "timeout_per_test_seconds": 20}, "methods": methods, "preflight_policy": {"models": 2, "seeds_per_model": 2, "formal_results_use": False}}
    write(CONFIG, config)
    write(LOCK, {"schema_version": 1, "lock_id": "codeguardplus-preflight-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "frozen_before_generation": True, "generation_seeds": SEEDS, "excluded_prior_generation_seeds": sorted(used), "fresh_seed_overlap_count": 0, "expected_trajectory_count": len(tasks) * 2 * 2 * 4, "inputs": {"semantic_freeze": record(SOURCE_FREEZE), "task_file": record(TASK_FILE), "oracle_manifest": record(ORACLE)}, "frozen_files": {"config": record(CONFIG), "visible_projection": record(VISIBLE), "hidden_projection": record(HIDDEN)}, "prompt_files": prompt_records})
    print(json.dumps({"tasks": tasks, "seeds": SEEDS, "models": list(models), "expected_trajectory_count": len(tasks) * 2 * 2 * 4}, indent=2))

if __name__ == "__main__": main()
