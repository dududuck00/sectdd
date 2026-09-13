#!/usr/bin/env python3
"""Filter partitioned expansion oracles by a result-blind semantic panel."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", choices=("sallm", "codeguardplus"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--visible", type=Path, required=True)
    parser.add_argument("--hidden", type=Path, required=True)
    parser.add_argument("--output-visible", type=Path, required=True)
    parser.add_argument("--output-hidden", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--oracle-set-id", required=True)
    parser.add_argument("--minimum-tasks", type=int, default=8)
    return parser.parse_args()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.resolve().relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Semantic freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def accepted_tasks(report: dict[str, Any]) -> list[str]:
    for key in (
        "unanimous_machine_accept_tasks",
        "unanimous_accept_tasks",
        "qualified_task_ids",
    ):
        value = report.get(key)
        if isinstance(value, list):
            return value
    audit = report.get("task_audit")
    if isinstance(audit, dict):
        accepted = []
        for task, value in audit.items():
            if value.get("decision") in {"unanimous_machine_accept", "accept"}:
                accepted.append(task)
        return accepted
    raise ValueError("Semantic report does not expose accepted tasks")


def main() -> None:
    a = args()
    paths = [a.report, a.visible, a.hidden, a.output_visible, a.output_hidden, a.canonical_output, a.freeze]
    resolved = [path.resolve() for path in paths]
    for path in resolved:
        path.relative_to(ROOT)
    report_path, visible_path, hidden_path = resolved[:3]
    report, visible, hidden = load(report_path), load(visible_path), load(hidden_path)
    if report.get("method_outcomes_read") is True:
        raise RuntimeError("Semantic selection read method outcomes")
    if visible.get("partition") != "visible" or hidden.get("partition") != "hidden":
        raise ValueError("Invalid partition labels")
    if visible["oracle_set_id"] != hidden["oracle_set_id"]:
        raise ValueError("Source oracle-set mismatch")
    accepted = accepted_tasks(report)
    if len(accepted) != len(set(accepted)):
        raise ValueError("Duplicate accepted task")
    missing = sorted(set(accepted) - set(visible["tasks"]) | set(accepted) - set(hidden["tasks"]))
    if missing:
        raise ValueError(f"Accepted tasks absent from projections: {missing}")
    if len(accepted) < a.minimum_tasks:
        raise RuntimeError(
            f"Only {len(accepted)} machine-semantic tasks passed; target is {a.minimum_tasks}. "
            "Keep the frozen rejection evidence and run another result-blind construction wave."
        )
    accepted = [task for task in visible["tasks"] if task in set(accepted)]
    canonical = {
        "schema_version": 1,
        "oracle_set_id": a.oracle_set_id,
        "benchmark": a.benchmark,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tasks": accepted,
        "selection_basis": "unanimous acceptance by the blinded machine semantic panel after dynamic oracle qualification",
        "method_or_g8_outcome_filter_applied": False,
        "independent_human_review_complete": False,
        "formal_results_use": False,
        "sources": {"semantic_report": rec(report_path), "visible_projection": rec(visible_path), "hidden_projection": rec(hidden_path)},
    }
    if resolved[5].exists():
        canonical["created_at_utc"] = load(resolved[5])["created_at_utc"]
    write_frozen(resolved[5], canonical)
    canonical_hash = sha(resolved[5])
    common = {
        "schema_version": 1,
        "oracle_set_id": a.oracle_set_id,
        "canonical_manifest_sha256": canonical_hash,
        "machine_semantic_review_complete": True,
        "independent_human_review_complete": False,
    }
    write_frozen(resolved[3], {**common, "partition": "visible", "tasks": {task: visible["tasks"][task] for task in accepted}})
    write_frozen(resolved[4], {**common, "partition": "hidden", "tasks": {task: hidden["tasks"][task] for task in accepted}})
    freeze = {
        "schema_version": 1,
        "freeze_id": a.oracle_set_id,
        "complete": True,
        "benchmark": a.benchmark,
        "machine_semantic_review_complete": True,
        "independent_human_review_complete": False,
        "method_or_g8_outcome_filter_applied": False,
        "qualified_task_count": len(accepted),
        "qualified_tasks": accepted,
        "formal_results_use": False,
        "inputs": {"semantic_report": rec(report_path), "source_visible": rec(visible_path), "source_hidden": rec(hidden_path)},
        "outputs": {"canonical": rec(resolved[5]), "visible": rec(resolved[3]), "hidden": rec(resolved[4])},
    }
    write_frozen(resolved[6], freeze)
    print(json.dumps({"benchmark": a.benchmark, "qualified_task_count": len(accepted), "minimum_tasks": a.minimum_tasks, "complete": True}, indent=2))


if __name__ == "__main__":
    main()
