#!/usr/bin/env python3
"""Freeze the verdict-blind CWE-117 wave4 semantic dispute packet."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import ROOT, file_record, write_json


SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_reserve_breadth_wave4/manifest.json"
PANEL = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-review/report.json"
OUTPUT_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-dispute-v1.json"
OUTPUT_ORACLE = ROOT / "oracles/codeguardplus_reserve_breadth_wave4_dispute_v1/manifest.json"
EXPECTED_TASK = "cwe-117/2-py"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify() -> None:
    freeze, oracle = load(OUTPUT_FREEZE), load(OUTPUT_ORACLE)
    if freeze["qualified_task_ids"] != [EXPECTED_TASK] or set(oracle["tasks"]) != {EXPECTED_TASK}:
        raise RuntimeError("Wave4 semantic dispute task drift")
    if freeze["outputs"]["subset_oracle_manifest"]["sha256"] != file_record(OUTPUT_ORACLE)["sha256"]:
        raise RuntimeError("Wave4 dispute oracle drift")
    if freeze["third_reviewer_packet_contains_prior_verdicts"] is not False:
        raise RuntimeError("Third-reviewer packet is not verdict-blind")
    print(json.dumps({"disputed_tasks": [EXPECTED_TASK], "freeze_valid": True}, indent=2))


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
    for path in (OUTPUT_FREEZE, OUTPUT_ORACLE):
        if path.exists():
            raise FileExistsError(path)
    source, oracle, panel = load(SOURCE_FREEZE), load(SOURCE_ORACLE), load(PANEL)
    disputed = sorted(task for task, audit in panel["task_audit"].items() if audit["machine_panel_verdict"] != "accept")
    if disputed != [EXPECTED_TASK]:
        raise RuntimeError(f"Unexpected wave4 dispute set: {disputed}")
    verdicts = panel["task_audit"][EXPECTED_TASK]["reviewer_verdicts"]
    if verdicts != {"qwen25-coder-14b": "reject", "qwen36-35b-a3b": "accept"}:
        raise RuntimeError(f"Unexpected CWE-117 panel split: {verdicts}")
    if panel["unanimous_machine_accept_tasks"] != ["cwe-327/0-py"]:
        raise RuntimeError("Wave4 unanimous acceptance drift")
    OUTPUT_ORACLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_ORACLE, {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-reserve-breadth-wave4-dispute-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "subset_reason": "non-unanimous machine semantic panel verdict",
        "source_oracle_manifest": file_record(SOURCE_ORACLE),
        "tasks": {EXPECTED_TASK: oracle["tasks"][EXPECTED_TASK]},
    })
    write_json(OUTPUT_FREEZE, {
        "schema_version": 1,
        "freeze_id": "codeguardplus-reserve-breadth-wave4-semantic-dispute-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "selection_uses_panel_outcomes": True,
        "third_reviewer_packet_contains_prior_verdicts": False,
        "qualified_task_ids": [EXPECTED_TASK],
        "dispute": {"task_id": EXPECTED_TASK, "cwe": oracle["tasks"][EXPECTED_TASK]["cwe"], "reviewer_verdicts": verdicts, "resolution_policy": "blinded third-model review followed by conservative adjudication"},
        "inputs": {"source_construction_freeze": file_record(SOURCE_FREEZE), "source_oracle_manifest": file_record(SOURCE_ORACLE), "two_model_panel": file_record(PANEL)},
        "outputs": {"subset_oracle_manifest": file_record(OUTPUT_ORACLE)},
    })
    verify()


if __name__ == "__main__":
    main()
