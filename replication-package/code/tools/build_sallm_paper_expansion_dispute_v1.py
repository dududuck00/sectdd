#!/usr/bin/env python3
"""Freeze verdict-blind packets for split SALLM semantic-panel decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "artifacts/paper-expansion-v1/sallm/semantic-review/report.json"
SOURCE_ORACLE = ROOT / "oracles/sallm_paper_expansion_v1/manifest.json"
SOURCE_FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-partition-freeze.json"
OUTPUT_TASKS = ROOT / "configs/benchmarks/sallm_paper_expansion_v1_disputed.json"
OUTPUT_ORACLE = ROOT / "oracles/sallm_paper_expansion_v1_dispute/manifest.json"
OUTPUT_FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-semantic-dispute-freeze.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"SALLM semantic-dispute freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def expected_disputes(panel: dict[str, Any]) -> list[str]:
    return sorted(
        task
        for task, audit in panel["task_audit"].items()
        if set(audit["reviewer_verdicts"].values()) == {"accept", "reject"}
    )


def verify() -> None:
    panel, tasks, oracle, freeze = map(
        load, (PANEL, OUTPUT_TASKS, OUTPUT_ORACLE, OUTPUT_FREEZE)
    )
    expected = expected_disputes(panel)
    if tasks["tasks"] != expected or list(oracle["tasks"]) != expected:
        raise RuntimeError("SALLM dispute task drift")
    if freeze["disputed_tasks"] != expected:
        raise RuntimeError("SALLM dispute freeze task drift")
    if freeze["third_reviewer_packet_contains_prior_verdicts"] is not False:
        raise RuntimeError("Third-reviewer packet is not verdict-blind")
    if freeze["outputs"]["subset_oracle_manifest"]["sha256"] != sha(OUTPUT_ORACLE):
        raise RuntimeError("SALLM dispute oracle drift")
    print(json.dumps({"disputed_tasks": expected, "freeze_valid": True}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify()
        return
    for path in (PANEL, SOURCE_ORACLE, SOURCE_FREEZE):
        if not path.is_file():
            raise FileNotFoundError(path)
    panel, source_oracle = load(PANEL), load(SOURCE_ORACLE)
    disputed = expected_disputes(panel)
    if not disputed:
        raise RuntimeError("The initial SALLM panel has no split decisions")
    unanimous_rejects = sorted(
        task
        for task, audit in panel["task_audit"].items()
        if set(audit["reviewer_verdicts"].values()) == {"reject"}
    )
    write_frozen(
        OUTPUT_TASKS,
        {
            "schema_version": 1,
            "selection_reason": "one-accept/one-reject blinded machine-panel split",
            "prior_verdicts_in_reviewer_packet": False,
            "tasks": disputed,
        },
    )
    write_frozen(
        OUTPUT_ORACLE,
        {
            **{key: value for key, value in source_oracle.items() if key != "tasks"},
            "oracle_set_id": "sallm-paper-expansion-v1-semantic-dispute",
            "status": "blinded_third_model_review_pending",
            "tasks": {task: source_oracle["tasks"][task] for task in disputed},
        },
    )
    write_frozen(
        OUTPUT_FREEZE,
        {
            "schema_version": 1,
            "freeze_id": "sallm-paper-expansion-v1-semantic-dispute",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "selection_uses_panel_outcomes": True,
            "third_reviewer_packet_contains_prior_verdicts": False,
            "resolution_policy": "blinded Qwen3-32B tie-break; two-of-three majority",
            "disputed_tasks": disputed,
            "unanimous_reject_tasks_not_disputed": unanimous_rejects,
            "formal_results_use": False,
            "inputs": {
                "source_partition_freeze": record(SOURCE_FREEZE),
                "source_oracle_manifest": record(SOURCE_ORACLE),
                "initial_semantic_panel": record(PANEL),
            },
            "outputs": {
                "task_file": record(OUTPUT_TASKS),
                "subset_oracle_manifest": record(OUTPUT_ORACLE),
            },
        },
    )
    verify()


if __name__ == "__main__":
    main()
