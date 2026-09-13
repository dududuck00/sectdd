#!/usr/bin/env python3
"""Freeze verdict-blind third-review inputs for CodeGuard+ paper expansion."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-partition-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_paper_expansion_v1/manifest.json"
PANEL = ROOT / "artifacts/paper-expansion-v1/codeguardplus/semantic-review/report.json"
OUTPUT_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-dispute-freeze.json"
OUTPUT_ORACLE = ROOT / "oracles/codeguardplus_paper_expansion_v1_dispute/manifest.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def write_frozen(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"CodeGuard+ semantic-dispute freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def panel_sets(panel: dict[str, Any]) -> tuple[list[str], list[str]]:
    disputed = sorted(
        task
        for task, audit in panel["task_audit"].items()
        if set(audit["reviewer_verdicts"].values()) == {"accept", "reject"}
    )
    unanimous_reject = sorted(
        task
        for task, audit in panel["task_audit"].items()
        if set(audit["reviewer_verdicts"].values()) == {"reject"}
    )
    return disputed, unanimous_reject


def verify() -> None:
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, OUTPUT_FREEZE, OUTPUT_ORACLE):
        if not path.is_file():
            raise FileNotFoundError(path)
    panel = load(PANEL)
    freeze = load(OUTPUT_FREEZE)
    oracle = load(OUTPUT_ORACLE)
    disputed, unanimous_reject = panel_sets(panel)
    if freeze["qualified_task_ids"] != disputed:
        raise RuntimeError("CodeGuard+ dispute task drift")
    if freeze["unanimous_reject_tasks_not_disputed"] != unanimous_reject:
        raise RuntimeError("CodeGuard+ unanimous-reject set drift")
    if set(oracle["tasks"]) != set(disputed):
        raise RuntimeError("CodeGuard+ dispute oracle task drift")
    if freeze["third_reviewer_packet_contains_prior_verdicts"] is not False:
        raise RuntimeError("Third-reviewer packet is not verdict-blind")
    if freeze["outputs"]["subset_oracle_manifest"]["sha256"] != sha(OUTPUT_ORACLE):
        raise RuntimeError("CodeGuard+ dispute oracle hash drift")
    print(
        json.dumps(
            {
                "disputed_tasks": disputed,
                "unanimous_reject_tasks": unanimous_reject,
                "freeze_valid": True,
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify()
        return
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUTPUT_FREEZE.exists() or OUTPUT_ORACLE.exists():
        raise FileExistsError(OUTPUT_FREEZE if OUTPUT_FREEZE.exists() else OUTPUT_ORACLE)

    source_oracle = load(SOURCE_ORACLE)
    panel = load(PANEL)
    disputed, unanimous_reject = panel_sets(panel)
    if not disputed:
        raise RuntimeError("No split CodeGuard+ semantic decisions require adjudication")

    subset = {
        **{key: value for key, value in source_oracle.items() if key != "tasks"},
        "oracle_set_id": "codeguardplus-paper-expansion-v1-semantic-dispute",
        "status": "blinded_third_model_review_pending",
        "source_oracle_manifest": rec(SOURCE_ORACLE),
        "tasks": {task: source_oracle["tasks"][task] for task in disputed},
    }
    write_frozen(OUTPUT_ORACLE, subset)
    freeze = {
        "schema_version": 1,
        "freeze_id": "codeguardplus-paper-expansion-v1-semantic-dispute",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "selection_uses_panel_outcomes": True,
        "third_reviewer_packet_contains_prior_verdicts": False,
        "resolution_policy": "blinded Qwen3-32B tie-break; two-of-three majority",
        "qualified_task_ids": disputed,
        "unanimous_reject_tasks_not_disputed": unanimous_reject,
        "inputs": {
            "source_construction_freeze": rec(SOURCE_FREEZE),
            "source_oracle_manifest": rec(SOURCE_ORACLE),
            "two_model_panel": rec(PANEL),
        },
        "outputs": {"subset_oracle_manifest": rec(OUTPUT_ORACLE)},
    }
    write_frozen(OUTPUT_FREEZE, freeze)
    verify()


if __name__ == "__main__":
    main()
