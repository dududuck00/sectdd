#!/usr/bin/env python3
"""Freeze the final result-blind CodeGuard+ reserve breadth wave."""

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
INITIAL_G8_INPUT = ROOT / "configs/experiments/codeguardplus_reserve_preflight_v2.json"
WAVE3_PAIRS = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave3-pairs.json"
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
OUTPUT_PAIRS = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-pairs.json"
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_breadth_wave4.lock.json"
EXPECTED = ["cwe-327/0-py", "cwe-730/1-py", "cwe-117/2-py", "cwe-502/4-py"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify() -> None:
    for path in (OUTPUT_PAIRS, LOCK):
        if not path.is_file():
            raise FileNotFoundError(path)
    pairs, lock = load(OUTPUT_PAIRS), load(LOCK)
    if pairs["qualified_task_ids"] != EXPECTED or lock["selected_task_ids"] != EXPECTED:
        raise RuntimeError("Wave4 selection drift")
    if lock["frozen_pairs"]["sha256"] != sha(OUTPUT_PAIRS):
        raise RuntimeError("Wave4 pair manifest drift")
    if lock["g8_outcomes_read_for_selection"] or not lock["all_remaining_distinct_cwes_selected"]:
        raise RuntimeError("Wave4 result-blind selection policy drift")
    for item in pairs["tasks"]:
        for field in ("safe_reference", "vulnerability_mutant"):
            path = ROOT / item[field]["path"]
            if sha(path) != item[field]["sha256"]:
                raise RuntimeError(f"Wave4 implementation drift: {item['task_id']} {field}")
    print(json.dumps({"lock_valid": True, "selected_task_ids": EXPECTED}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify()
        return
    inputs = (SOURCE_PAIRS, PARTITION_FREEZE, CANDIDATE_AUDIT, INITIAL_G8_INPUT, WAVE3_PAIRS, BENCHMARK)
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT_PAIRS, LOCK):
        if path.exists():
            raise FileExistsError(path)
    source, partition = load(SOURCE_PAIRS), load(PARTITION_FREEZE)
    pair_by_task = {item["task_id"]: item for item in source["tasks"]}
    order = {task: index for index, task in enumerate(source["qualified_task_ids"])}
    benchmark = {item["task_id"]: item for item in load(BENCHMARK)["tasks"]}
    exposed = set(load(INITIAL_G8_INPUT)["tasks"])
    exposed.update(load(WAVE3_PAIRS)["qualified_task_ids"])
    exposed_cwes = {pair_by_task[task]["cwe"] for task in exposed}
    rows = [json.loads(line) for line in CANDIDATE_AUDIT.read_text(encoding="utf-8").splitlines() if line]
    by_attempt: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_attempt[(row["task_id"], row["attempt_index"])].append(row)
    candidates = []
    for rejected in partition["rejected"]:
        task, cwe = rejected["task_id"], rejected["cwe"]
        if task in exposed or cwe in exposed_cwes:
            continue
        attempts = []
        for (observed, attempt), values in by_attempt.items():
            if observed == task and len(values) == 4:
                distance = sum(value["state"] != ("F+S+" if value["subject"] == "safe_reference" else "F+S-") for value in values)
                attempts.append((distance, attempt))
        distance, attempt = min(attempts, default=(999, None))
        candidates.append({
            "task_id": task,
            "cwe": cwe,
            "prior_best_repair_distance": distance,
            "prior_best_attempt_index": attempt,
            "source_pair_order": order[task],
            "prior_partition_rejection_reason": rejected["reason"],
        })
    representatives = {}
    for item in candidates:
        rank = (item["prior_best_repair_distance"], item["source_pair_order"])
        if item["cwe"] not in representatives or rank < representatives[item["cwe"]][0]:
            representatives[item["cwe"]] = (rank, item)
    selected_audit = [value[1] for value in sorted(representatives.values(), key=lambda value: value[0])]
    selected = [item["task_id"] for item in selected_audit]
    if selected != EXPECTED or len(selected) != len({item["cwe"] for item in selected_audit}):
        raise RuntimeError(f"Final remaining-CWE selection drift: {selected}")
    selected_pairs = [pair_by_task[task] for task in selected]
    for pair in selected_pairs:
        if benchmark[pair["task_id"]]["cwe"] != pair["cwe"]:
            raise RuntimeError(f"Benchmark CWE drift: {pair['task_id']}")
        for field in ("safe_reference", "vulnerability_mutant"):
            path = ROOT / pair[field]["path"]
            if sha(path) != pair[field]["sha256"]:
                raise RuntimeError(f"Frozen implementation drift: {pair['task_id']} {field}")
    manifest = {
        "schema_version": 1,
        "manifest_id": "codeguardplus-reserve-breadth-wave4-pairs",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "selection_policy": {
            "g8_outcomes_read": False,
            "exclude_all_previously_exposed_tasks_and_cwes": True,
            "one_task_per_cwe": True,
            "select_all_remaining_distinct_cwes": True,
            "within_cwe_ranking": ["minimum prior oracle repair distance", "source pair freeze order"],
        },
        "qualified_task_ids": selected,
        "selected_cwes": [item["cwe"] for item in selected_audit],
        "selection_audit": selected_audit,
        "tasks": selected_pairs,
        "source_files": {"source_pairs": record(SOURCE_PAIRS), "prior_partition_freeze": record(PARTITION_FREEZE), "prior_candidate_audit": record(CANDIDATE_AUDIT), "initial_g8_input_without_outcomes": record(INITIAL_G8_INPUT), "wave3_pairs_without_g8_outcomes": record(WAVE3_PAIRS), "benchmark_manifest": record(BENCHMARK)},
    }
    write(OUTPUT_PAIRS, manifest)
    write(LOCK, {
        "schema_version": 1,
        "lock_id": "codeguardplus-reserve-breadth-wave4",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_oracle_generation": True,
        "g8_outcomes_read_for_selection": False,
        "all_remaining_distinct_cwes_selected": True,
        "selected_task_ids": selected,
        "selected_cwes": manifest["selected_cwes"],
        "authoring": {"provider": "deepseek", "model": "deepseek-v4-flash", "api_base": "https://api.deepseek.com", "attempts_per_task": 3, "temperature": 0.35, "top_p": 0.95, "max_tokens": 12288, "thinking": "enabled", "reasoning_effort": "high", "benchmark_tests_exposed_to_model": False, "codeql_query_exposed_to_model": False, "benchmark_probe_exposed_to_model": False},
        "expected_oracle_candidate_count": 12,
        "frozen_pairs": record(OUTPUT_PAIRS),
    })
    print(json.dumps({"selected_task_ids": selected, "selected_cwes": manifest["selected_cwes"], "expected_oracle_candidate_count": 12, "g8_outcomes_read": False}, indent=2))


if __name__ == "__main__":
    main()
