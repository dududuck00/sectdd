#!/usr/bin/env python3
"""Freeze SALLM expansion wave 2 from the untouched wave-1 reserve pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/benchmarks/sallm_expansion_candidates_v1.json"
OUTPUT = ROOT / "configs/benchmarks/sallm_expansion_candidates_v2.json"
REPORT = ROOT / "docs/sallm-expansion-candidates-v2.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--max-selected", type=int, default=24)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def checked(path: Path, exists: bool) -> Path:
    result = path.expanduser().resolve()
    result.relative_to(ROOT)
    if exists and not result.is_file():
        raise FileNotFoundError(result)
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cost_key(item: dict[str, Any]) -> tuple[Any, ...]:
    cost = item["execution_cost"]
    return (
        cost["fixture_count"],
        cost["declared_python_requirement_count"],
        cost["reference_audit_wall_seconds"],
        cost["source_and_test_size_bytes"],
        item["task_id"],
    )


def cwe_number(value: str) -> int:
    return int(value.removeprefix("CWE-"))


def build(source: dict[str, Any], source_path: Path, cap: int) -> dict[str, Any]:
    if cap < 1:
        raise ValueError("--max-selected must be positive")
    if source.get("plan_id") != "sallm-expansion-candidates-v1":
        raise RuntimeError("Unexpected source plan")
    if source["selection_policy"]["model_outputs_used_for_selection"] is not False:
        raise RuntimeError("Source selection was not model-blind")
    reserves = json.loads(json.dumps(source["reserve_candidates"]))
    if len(reserves) != source["summary"]["reserve_task_count"]:
        raise RuntimeError("Wave-1 reserve count drifted")
    if {item["selection_reason"] for item in reserves} != {
        "alternate_task_for_selected_new_cwe",
        "existing_formal_cwe_replication_reserve",
    }:
        raise RuntimeError("Unexpected reserve reason in wave-1 plan")

    # All 15 alternates preserve the newly introduced CWE strata.  Add the
    # cheapest representative for each of the nine existing-formal CWE strata.
    alternates = [
        item
        for item in reserves
        if item["selection_reason"] == "alternate_task_for_selected_new_cwe"
    ]
    existing_by_cwe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in reserves:
        if item["selection_reason"] == "existing_formal_cwe_replication_reserve":
            existing_by_cwe[item["cwe"]].append(item)
    representatives = [
        min(group, key=cost_key) for group in existing_by_cwe.values()
    ]
    base = alternates + representatives
    base_ids = {item["task_id"] for item in base}
    if len(base) > cap:
        raise RuntimeError(
            f"Wave-2 stratified base has {len(base)} tasks, above cap {cap}"
        )
    remaining = sorted(
        (item for item in reserves if item["task_id"] not in base_ids),
        key=lambda item: (cost_key(item), cwe_number(item["cwe"])),
    )
    selected = base + remaining[: cap - len(base)]
    selected_ids = {item["task_id"] for item in selected}
    if len(selected) != cap or len(selected_ids) != cap:
        raise RuntimeError("Could not construct the requested wave-2 size")

    for item in selected:
        old_reason = item["selection_reason"]
        item["selection_state"] = "selected"
        item["selection_reason"] = (
            "wave1_new_cwe_alternate"
            if old_reason == "alternate_task_for_selected_new_cwe"
            else "lowest_cost_existing_cwe_replication_representative"
        )
    reserve = []
    for item in reserves:
        if item["task_id"] in selected_ids:
            continue
        item["selection_state"] = "reserve"
        item["selection_reason"] = "existing_cwe_additional_replication_reserve"
        reserve.append(item)
    selected.sort(key=lambda item: (cwe_number(item["cwe"]), item["task_id"]))
    reserve.sort(key=lambda item: (cwe_number(item["cwe"]), cost_key(item)))
    reasons = Counter(item["selection_reason"] for item in selected)

    return {
        "$schema": source["$schema"],
        "schema_version": 1,
        "plan_id": "sallm-expansion-candidates-v2",
        "status": "secure_reference_generation_ready",
        "formal_experiment_ready": False,
        "remaining_work": (
            "Selected tasks require safe-reference qualification, repeated "
            "unsafe/safe/mutant audits, partitioned oracles, semantic review, "
            "and a model-blind preflight with fresh seeds."
        ),
        "selection_policy": {
            "policy_version": 2,
            "source_pool": "wave-1 reserve only",
            "rules": [
                "include every wave-1 alternate for a newly covered CWE",
                "include the lowest-cost representative for each existing-formal CWE",
                "if capacity remains, fill by the frozen execution-cost tuple",
            ],
            "representative_order": source["selection_policy"]["representative_order"],
            "max_selected": cap,
            "model_outputs_used_for_selection": False,
            "wave1_candidate_or_preflight_results_used_for_selection": False,
        },
        "qualification_gates": [
            dict(gate, state=("passed" if gate["gate"] == "G1" else "pending"))
            for gate in source["qualification_gates"]
        ],
        "inputs": {
            "wave1_plan": {
                "path": source_path.relative_to(ROOT).as_posix(),
                "sha256": sha256(source_path),
                "size_bytes": source_path.stat().st_size,
            },
            **source["inputs"],
        },
        "repository_commit": source["repository_commit"],
        "summary": {
            "source_reserve_task_count": len(reserves),
            "source_reserve_cwe_count": len({item["cwe"] for item in reserves}),
            "selected_task_count": len(selected),
            "selected_cwe_count": len({item["cwe"] for item in selected}),
            "selected_reason_counts": dict(sorted(reasons.items())),
            "remaining_reserve_task_count": len(reserve),
            "remaining_reserve_cwe_count": len({item["cwe"] for item in reserve}),
        },
        "tasks": [item["task_id"] for item in selected],
        "selected_candidates": selected,
        "reserve_candidates": reserve,
    }


def render_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def render_report(plan: dict[str, Any]) -> bytes:
    summary = plan["summary"]
    lines = [
        "# SALLM expansion candidates v2",
        "",
        "Wave 2 is selected only from the 47-task reserve frozen before any wave-1 model generation.",
        "It includes all 15 new-CWE alternates plus the lowest-cost representative for each of nine existing-formal CWE strata.",
        "No wave-1 generation, oracle, semantic-review, or preflight outcome was used.",
        "",
        f"Selected {summary['selected_task_count']} tasks spanning {summary['selected_cwe_count']} CWEs; {summary['remaining_reserve_task_count']} tasks remain.",
        "",
        "| CWE | Task | Selection basis | Fixtures | Requirements | Audit s | Bytes |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for item in plan["selected_candidates"]:
        cost = item["execution_cost"]
        lines.append(
            f"| {item['cwe']} | `{item['task_id']}` | {item['selection_reason']} | "
            f"{cost['fixture_count']} | {cost['declared_python_requirement_count']} | "
            f"{cost['reference_audit_wall_seconds']:.3f} | {cost['source_and_test_size_bytes']} |"
        )
    lines.extend(
        [
            "",
            "This is a construction plan. Only G1 is complete; no selected task is formal-experiment ready.",
            "",
        ]
    )
    return ("\n".join(lines) + "\n").encode()


def main() -> None:
    args = parse_args()
    source_path = checked(args.source, True)
    output = checked(args.output, False)
    report = checked(args.report, False)
    plan = build(json.loads(source_path.read_text(encoding="utf-8")), source_path, args.max_selected)
    expected = ((output, render_json(plan)), (report, render_report(plan)))
    if args.check:
        stale = [str(path) for path, content in expected if not path.is_file() or path.read_bytes() != content]
        if stale:
            raise SystemExit("Stale wave-2 outputs: " + ", ".join(stale))
        print(f"OK: {output}")
        print(f"OK: {report}")
        return
    for path, content in expected:
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"Wrote {path}")
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
