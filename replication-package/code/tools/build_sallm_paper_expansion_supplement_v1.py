#!/usr/bin/env python3
"""Freeze every remaining result-blind SALLM construction candidate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifests/sallm-v1.json"
QUALIFICATION = ROOT / "benchmarks/manifests/sallm-reference-qualified-v1.json"
WAVE1 = ROOT / "configs/benchmarks/sallm_paper_expansion_v1_tasks.json"
TASKS = ROOT / "configs/benchmarks/sallm_paper_expansion_supplement_v1_tasks.json"
FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-supplement-v1-candidate-freeze.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"SALLM supplement candidate freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def prior_method_tasks() -> set[str]:
    tasks: set[str] = set()
    for path in (ROOT / "configs/experiments").glob("*.json"):
        try:
            value = load(path)
        except (OSError, json.JSONDecodeError):
            continue
        tasks.update(item for item in value.get("tasks", []) if isinstance(item, str))
    return tasks


def main() -> None:
    for path in (MANIFEST, QUALIFICATION, WAVE1):
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest = load(MANIFEST)
    by_id = {item["task_id"]: item for item in manifest["tasks"]}
    qualified = {
        item["task_id"]
        for item in load(QUALIFICATION)["tasks"]
        if item.get("decision") == "candidate"
    }
    excluded = prior_method_tasks() | set(load(WAVE1)["tasks"])
    selected = sorted(
        task
        for task in qualified - excluded
        if task in by_id and by_id[task]["eligibility"].get("candidate_for_oracle_audit")
    )
    if len(selected) != 26:
        raise RuntimeError(f"Expected 26 unused SALLM candidates, found {len(selected)}")
    task_value = {
        "schema_version": 1,
        "plan_id": "sallm-paper-expansion-supplement-v1",
        "tasks": selected,
        "selection_reads_method_outcomes": False,
        "selection_rule": "all remaining reference-qualified, audit-eligible, previously method-unexposed SALLM tasks",
    }
    write_frozen(TASKS, task_value)
    freeze = {
        "schema_version": 1,
        "freeze_id": "sallm-paper-expansion-supplement-v1-candidate-freeze",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_supplement_generation": True,
        "method_or_g8_outcomes_read_for_selection": False,
        "candidate_task_count": len(selected),
        "candidate_tasks": selected,
        "inputs": {
            "benchmark_manifest": record(MANIFEST),
            "reference_qualification": record(QUALIFICATION),
            "wave1_candidate_tasks": record(WAVE1),
        },
        "outputs": {"task_file": record(TASKS)},
    }
    if FREEZE.exists():
        freeze["created_at_utc"] = load(FREEZE)["created_at_utc"]
    write_frozen(FREEZE, freeze)
    print(json.dumps({"candidate_task_count": len(selected), "complete": True}, indent=2))


if __name__ == "__main__":
    main()
