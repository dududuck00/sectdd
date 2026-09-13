#!/usr/bin/env python3
"""Freeze a result-blind CodeGuard+ reserve oracle-breadth wave."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PAIRS = ROOT / "benchmarks/manifests/codeguardplus-reserve-oracle-pairs-v1.json"
PARTITION_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-partitioned-v1-freeze.json"
CANDIDATE_AUDIT = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/partitioned-qualification/candidate_audit.jsonl"
G8_INPUT_CONFIG = ROOT / "configs/experiments/codeguardplus_reserve_preflight_v2.json"
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
OUTPUT_PAIRS = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave3-pairs.json"
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_breadth_wave3.lock.json"
TARGET_TASKS = 5


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_existing() -> None:
    for path in (OUTPUT_PAIRS, LOCK):
        if not path.is_file():
            raise FileNotFoundError(path)
    pairs = json.loads(OUTPUT_PAIRS.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    expected = ["cwe-611/0-py", "cwe-022/1-py", "cwe-078/2-py", "cwe-079/2-py", "cwe-377/1-py"]
    if pairs["qualified_task_ids"] != expected or lock["selected_task_ids"] != expected:
        raise RuntimeError("Wave-3 selected task drift")
    if lock["frozen_pairs"]["sha256"] != sha(OUTPUT_PAIRS):
        raise RuntimeError("Wave-3 pair manifest drift")
    if not lock["frozen_before_oracle_generation"] or lock["g8_outcomes_read_for_selection"]:
        raise RuntimeError("Wave-3 result-blind lock invalid")
    for item in pairs["tasks"]:
        for field in ("safe_reference", "vulnerability_mutant"):
            path = ROOT / item[field]["path"]
            if sha(path) != item[field]["sha256"]:
                raise RuntimeError(f"Wave-3 implementation drift: {item['task_id']} {field}")
    print(json.dumps({"lock_valid": True, "selected_task_ids": expected}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_existing()
        return
    for path in (SOURCE_PAIRS, PARTITION_FREEZE, CANDIDATE_AUDIT, G8_INPUT_CONFIG, BENCHMARK):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT_PAIRS, LOCK):
        if path.exists():
            raise FileExistsError(path)

    source = json.loads(SOURCE_PAIRS.read_text(encoding="utf-8"))
    partition = json.loads(PARTITION_FREEZE.read_text(encoding="utf-8"))
    g8_input = json.loads(G8_INPUT_CONFIG.read_text(encoding="utf-8"))
    benchmark = {item["task_id"]: item for item in json.loads(BENCHMARK.read_text(encoding="utf-8"))["tasks"]}
    pair_by_task = {item["task_id"]: item for item in source["tasks"]}
    order = {task: index for index, task in enumerate(source["qualified_task_ids"])}
    g8_exposed_tasks = set(g8_input["tasks"])
    g8_exposed_cwes = {pair_by_task[task]["cwe"] for task in g8_exposed_tasks}

    rows = [json.loads(line) for line in CANDIDATE_AUDIT.read_text(encoding="utf-8").splitlines() if line]
    by_attempt: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_attempt[(row["task_id"], row["attempt_index"])].append(row)

    candidates = []
    for rejected in partition["rejected"]:
        task = rejected["task_id"]
        cwe = rejected["cwe"]
        if task in g8_exposed_tasks or cwe in g8_exposed_cwes:
            continue
        attempts = []
        for (observed_task, attempt), values in by_attempt.items():
            if observed_task != task or len(values) != 4:
                continue
            distance = sum(
                value["state"]
                != ("F+S+" if value["subject"] == "safe_reference" else "F+S-")
                for value in values
            )
            attempts.append((distance, attempt))
        distance, best_attempt = min(attempts, default=(999, None))
        candidates.append(
            {
                "task_id": task,
                "cwe": cwe,
                "prior_best_repair_distance": distance,
                "prior_best_attempt_index": best_attempt,
                "source_pair_order": order[task],
                "prior_partition_rejection_reason": rejected["reason"],
            }
        )

    representatives = {}
    for item in candidates:
        key = item["cwe"]
        rank = (item["prior_best_repair_distance"], item["source_pair_order"])
        if key not in representatives or rank < representatives[key][0]:
            representatives[key] = (rank, item)
    ranked = [value[1] for value in sorted(representatives.values(), key=lambda value: value[0])]
    selected_audit = ranked[:TARGET_TASKS]
    selected = [item["task_id"] for item in selected_audit]
    if len(selected) != TARGET_TASKS or len({item["cwe"] for item in selected_audit}) != TARGET_TASKS:
        raise RuntimeError("Breadth selection did not produce five distinct CWEs")
    expected = ["cwe-611/0-py", "cwe-022/1-py", "cwe-078/2-py", "cwe-079/2-py", "cwe-377/1-py"]
    if selected != expected:
        raise RuntimeError(f"Frozen wave-3 selection drift: {selected}")
    if set(selected) & g8_exposed_tasks:
        raise RuntimeError("Wave-3 selection contains a G8-exposed task")

    selected_pairs = [pair_by_task[task] for task in selected]
    for pair in selected_pairs:
        for field in ("safe_reference", "vulnerability_mutant"):
            path = ROOT / pair[field]["path"]
            if sha(path) != pair[field]["sha256"]:
                raise RuntimeError(f"Frozen implementation drift: {pair['task_id']} {field}")
        if benchmark[pair["task_id"]]["cwe"] != pair["cwe"]:
            raise RuntimeError(f"Benchmark CWE drift: {pair['task_id']}")

    pairs_manifest = {
        "schema_version": 1,
        "manifest_id": "codeguardplus-reserve-breadth-wave3-pairs",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "selection_policy": {
            "g8_outcomes_read": False,
            "exclude_all_preflight_input_tasks_and_cwes": True,
            "one_task_per_cwe": True,
            "ranking": ["minimum prior oracle repair distance", "source pair freeze order"],
            "target_task_count": TARGET_TASKS,
        },
        "qualified_task_ids": selected,
        "selected_cwes": [item["cwe"] for item in selected_audit],
        "selection_audit": selected_audit,
        "tasks": selected_pairs,
        "source_files": {
            "source_pairs": record(SOURCE_PAIRS),
            "prior_partition_freeze": record(PARTITION_FREEZE),
            "prior_candidate_audit": record(CANDIDATE_AUDIT),
            "g8_input_config_without_outcomes": record(G8_INPUT_CONFIG),
            "benchmark_manifest": record(BENCHMARK),
        },
    }
    write(OUTPUT_PAIRS, pairs_manifest)
    lock = {
        "schema_version": 1,
        "lock_id": "codeguardplus-reserve-breadth-wave3",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_oracle_generation": True,
        "g8_outcomes_read_for_selection": False,
        "selected_task_ids": selected,
        "selected_cwes": pairs_manifest["selected_cwes"],
        "authoring": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_base": "https://api.deepseek.com",
            "attempts_per_task": 3,
            "temperature": 0.35,
            "top_p": 0.95,
            "max_tokens": 12288,
            "thinking": "enabled",
            "reasoning_effort": "high",
            "benchmark_tests_exposed_to_model": False,
            "codeql_query_exposed_to_model": False,
            "benchmark_probe_exposed_to_model": False,
        },
        "expected_oracle_candidate_count": TARGET_TASKS * 3,
        "frozen_pairs": record(OUTPUT_PAIRS),
    }
    write(LOCK, lock)
    print(
        json.dumps(
            {
                "selected_task_ids": selected,
                "selected_cwes": pairs_manifest["selected_cwes"],
                "expected_oracle_candidate_count": TARGET_TASKS * 3,
                "g8_outcomes_read": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
