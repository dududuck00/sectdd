#!/usr/bin/env python3
"""Freeze result-blind candidate pools for the paper breadth expansion.

The selection stage is deliberately prohibited from reading B0--B6/M model
outcomes.  It may use benchmark inventory, original-oracle executability,
language/dependency metadata, and static construction cost only.  Oracle
construction failures are retained later; they never silently change this
candidate freeze.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CWEVAL_SPLIT = ROOT / "configs/splits/cweval_python25_pilot_visible.json"
CWEVAL_CURRENT = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.json"
SALLM_MANIFEST = ROOT / "benchmarks/manifests/sallm-v1.json"
SALLM_QUALIFICATION = ROOT / "benchmarks/manifests/sallm-reference-qualified-v1.json"
SALLM_CURRENT = ROOT / "configs/experiments/sallm_partitioned_main_v1_1.json"
CODEGUARD_PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
CODEGUARD_MANIFEST = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
CODEGUARD_CURRENT = ROOT / "configs/experiments/codeguardplus_breadth_confirmatory_v1.json"

OUTPUT = ROOT / "benchmarks/manifests/paper-expansion-v1-candidate-freeze.json"
CWEVAL_TASKS = ROOT / "configs/benchmarks/cweval_paper_expansion_v1_tasks.json"
SALLM_TASKS = ROOT / "configs/benchmarks/sallm_paper_expansion_v1_tasks.json"
CODEGUARD_SUBSET = ROOT / "configs/benchmarks/codeguardplus_paper_expansion_v1_plan.json"
REPORT = ROOT / "docs/paper-expansion-v1-candidate-freeze.md"

# Earlier qualification waves retained roughly one quarter or fewer of their
# construction pools after dynamic and semantic gates.  Thirty-two candidates
# per external benchmark is therefore the smallest defensible pool for an
# eight-task retained target without relaxing any gate.
SALLM_CONSTRUCTION_TARGET = 32
CODEGUARD_CONSTRUCTION_TARGET = 32


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Frozen expansion input drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def cwe_number(value: str) -> int:
    return int(value.upper().removeprefix("CWE-").removeprefix("CWE_"))


def task_cwe(task_id: str) -> str:
    pieces = task_id.lower().split("cwe", 1)[1]
    digits = "".join(ch for ch in pieces if ch.isdigit())
    # The first underscore or slash separates the CWE number from the variant.
    if "_" in pieces:
        digits = "".join(ch for ch in pieces.split("_", 1)[0] if ch.isdigit())
    elif "/" in pieces:
        digits = "".join(ch for ch in pieces.split("/", 1)[0] if ch.isdigit())
    return f"CWE-{int(digits)}"


def previously_exposed_task_ids() -> set[str]:
    """Collect every task placed in a prior method-generation config."""

    exposed: set[str] = set()
    for path in (ROOT / "configs/experiments").glob("*.json"):
        try:
            value = load(path)
        except (OSError, json.JSONDecodeError):
            continue
        tasks = value.get("tasks") if isinstance(value, dict) else None
        if isinstance(tasks, list):
            exposed.update(item for item in tasks if isinstance(item, str))
    return exposed


def diversity_select(
    candidates: list[dict[str, Any]],
    current_cwes: set[str],
    limit: int,
    cost_key,
) -> list[dict[str, Any]]:
    """Prefer new CWEs, then one representative per remaining CWE, then fill."""

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        groups[item["cwe"]].append(item)
    for values in groups.values():
        values.sort(key=cost_key)

    cwes = sorted(
        groups,
        key=lambda cwe: (cwe in current_cwes, cost_key(groups[cwe][0]), cwe_number(cwe)),
    )
    selected: list[dict[str, Any]] = []
    for cwe in cwes:
        if len(selected) >= limit:
            break
        selected.append(groups[cwe].pop(0))
    leftovers = sorted(
        (item for values in groups.values() for item in values), key=cost_key
    )
    selected.extend(leftovers[: max(0, limit - len(selected))])
    return selected


def main() -> None:
    sources = (
        CWEVAL_SPLIT,
        CWEVAL_CURRENT,
        SALLM_MANIFEST,
        SALLM_QUALIFICATION,
        SALLM_CURRENT,
        CODEGUARD_PLAN,
        CODEGUARD_MANIFEST,
        CODEGUARD_CURRENT,
    )
    for path in sources:
        if not path.is_file():
            raise FileNotFoundError(path)

    cweval_all = sorted(load(CWEVAL_SPLIT)["tasks"])
    cweval_current = set(load(CWEVAL_CURRENT)["tasks"])
    cweval_selected = [task for task in cweval_all if task not in cweval_current]
    if len(cweval_all) != 25 or len(cweval_selected) != 16:
        raise RuntimeError(
            f"Expected CWEval 25 total/16 new, got {len(cweval_all)}/{len(cweval_selected)}"
        )

    sallm_manifest = load(SALLM_MANIFEST)
    sallm_by_id = {item["task_id"]: item for item in sallm_manifest["tasks"]}
    sallm_qualified = {
        item["task_id"]
        for item in load(SALLM_QUALIFICATION)["tasks"]
        if item.get("decision") == "candidate"
    }
    prior_exposed = previously_exposed_task_ids()
    sallm_current = set(load(SALLM_CURRENT)["tasks"])
    sallm_current_cwes = {sallm_by_id[task]["cwe"] for task in sallm_current}
    sallm_candidates = []
    for task_id in sorted(sallm_qualified - sallm_current - prior_exposed):
        item = sallm_by_id[task_id]
        if not item["eligibility"].get("candidate_for_oracle_audit"):
            continue
        sallm_candidates.append(
            {
                "task_id": task_id,
                "cwe": item["cwe"],
                "origin": item["source"]["origin"],
                "technique": item["source"]["technique"],
                "requirement_count": len(item["dependencies"].get("python_requirements", [])),
                "source_test_bytes": (
                    item["source"]["reference_file"]["size_bytes"]
                    + item["tests"]["entrypoint"]["size_bytes"]
                ),
            }
        )
    sallm_selected = diversity_select(
        sallm_candidates,
        sallm_current_cwes,
        SALLM_CONSTRUCTION_TARGET,
        lambda item: (
            item["requirement_count"],
            item["source_test_bytes"],
            item["origin"],
            item["technique"],
            item["task_id"],
        ),
    )

    codeguard_source_plan = load(CODEGUARD_PLAN)
    codeguard_manifest = load(CODEGUARD_MANIFEST)
    codeguard_by_id = {item["task_id"]: item for item in codeguard_manifest["tasks"]}
    codeguard_current = set(load(CODEGUARD_CURRENT)["tasks"])
    codeguard_current_cwes = {codeguard_by_id[task]["cwe"] for task in codeguard_current}
    codeguard_candidates = []
    for item in codeguard_source_plan["tasks"]:
        task_id = item["task_id"]
        if (
            task_id in codeguard_current
            or task_id in prior_exposed
            or task_id not in codeguard_by_id
            or item.get("selection_state") not in {"primary", "reserve"}
        ):
            continue
        benchmark = codeguard_by_id[task_id]
        if benchmark.get("language") != "python":
            continue
        security = item["qualification_oracles"]["security"]
        if security.get("source_type") not in {"codeql_standard_bundle", "benchmark_repository"}:
            continue
        cost = item["selection_cost"]
        codeguard_candidates.append(
            {
                "task_id": task_id,
                "cwe": item["cwe"],
                "source_selection_state": item["selection_state"],
                "query_source": security["source_type"],
                "benchmark_probe_available": bool(item["benchmark_probe_candidates"]),
                "static_cost": (
                    cost["query_source_penalty"],
                    cost["missing_benchmark_probe_penalty"],
                    cost["fixture_bytes"],
                    cost["functional_test_bytes"],
                    cost["public_context_bytes"],
                ),
                "source_plan_item": item,
            }
        )
    codeguard_selected = diversity_select(
        codeguard_candidates,
        codeguard_current_cwes,
        CODEGUARD_CONSTRUCTION_TARGET,
        lambda item: (*item["static_cost"], item["task_id"]),
    )

    write_frozen(
        CWEVAL_TASKS,
        {
            "schema_version": 1,
            "plan_id": "cweval-paper-expansion-v1",
            "tasks": cweval_selected,
            "selection_reads_method_outcomes": False,
            "selection_rule": "all Python-25 tasks absent from the frozen nine-task deep matrix",
        },
    )
    write_frozen(
        SALLM_TASKS,
        {
            "schema_version": 1,
            "plan_id": "sallm-paper-expansion-v1",
            "tasks": [item["task_id"] for item in sallm_selected],
            "target_qualified_tasks": 8,
            "selection_reads_method_outcomes": False,
            "selection_rule": "reference-oracle candidates selected by CWE diversity then static execution cost",
            "selection_audit": sallm_selected,
        },
    )

    selected_plan_items = []
    for selected in codeguard_selected:
        item = dict(selected["source_plan_item"])
        item["selection_state"] = "primary"
        item["selection_reason"] = "paper_expansion_v1_result_blind_diversity_and_static_cost"
        item["source_selection_state"] = selected["source_selection_state"]
        selected_plan_items.append(item)
    subset_plan = dict(codeguard_source_plan)
    subset_plan.update(
        {
            "plan_id": "codeguardplus-paper-expansion-v1",
            "study_phase": "paper_expansion_oracle_construction",
            "development_only": True,
            "formal_results_use": False,
            "selection_frozen_before_candidate_generation": True,
            "selection_reads_model_outputs": False,
            "selection_reads_oracle_outcomes": False,
            "selection_policy": {
                "rule": "CWE diversity followed by the source plan's frozen static-cost tuple",
                "method_outcomes_read": False,
                "g8_outcomes_read": False,
                "target_qualified_tasks": 8,
            },
            "tasks": selected_plan_items,
            "primary_task_ids": [item["task_id"] for item in selected_plan_items],
            "reserve_task_ids": [],
            "development_excluded_task_ids": [],
            "counts": {
                "eligible": len(selected_plan_items),
                "primary": len(selected_plan_items),
                "reserve": 0,
                "development_excluded": 0,
                "primary_cwes": len({item["cwe"] for item in selected_plan_items}),
            },
        }
    )
    write_frozen(CODEGUARD_SUBSET, subset_plan)

    freeze = {
        "schema_version": 1,
        "freeze_id": "paper-expansion-v1-candidate-freeze",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_oracle_generation": True,
        "frozen_before_method_generation": True,
        "method_or_g8_outcomes_read_for_selection": False,
        "construction_targets": {
            "cweval": len(cweval_selected),
            "sallm": len(sallm_selected),
            "codeguardplus": len(codeguard_selected),
        },
        "paper_target_qualified_additions": {
            "cweval": 16,
            "sallm": 8,
            "codeguardplus": 8,
            "total": 32,
        },
        "tasks": {
            "cweval": cweval_selected,
            "sallm": [item["task_id"] for item in sallm_selected],
            "codeguardplus": [item["task_id"] for item in codeguard_selected],
        },
        "inputs": {path.stem: rec(path) for path in sources},
        "outputs": {
            "cweval_task_file": rec(CWEVAL_TASKS),
            "sallm_task_file": rec(SALLM_TASKS),
            "codeguardplus_subset_plan": rec(CODEGUARD_SUBSET),
        },
    }
    # created_at is intentionally stable after the first freeze.
    if OUTPUT.exists():
        prior = load(OUTPUT)
        freeze["created_at_utc"] = prior["created_at_utc"]
    write_frozen(OUTPUT, freeze)

    lines = [
        "# Paper expansion v1 candidate freeze",
        "",
        "Selection is result-blind: no B0--B6/M or G8 outcome was read.",
        "",
        f"- CWEval construction candidates: {len(cweval_selected)} (all remaining Python-25 tasks)",
        f"- SALLM construction candidates: {len(sallm_selected)} (target at least 8 qualified)",
        f"- CodeGuard+ construction candidates: {len(codeguard_selected)} (target at least 8 qualified)",
        "- Target final task count: 31 + 32 = 63",
        "",
        "Qualification may reject invalid oracles, but no task may be rejected because a generation method has a ceiling, floor, lacks feedback triggers, or fails to improve.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    rendered_report = "\n".join(lines)
    if REPORT.exists() and REPORT.read_text(encoding="utf-8") != rendered_report:
        raise RuntimeError(f"Frozen report drift: {REPORT}")
    REPORT.write_text(rendered_report, encoding="utf-8")
    print(json.dumps(freeze["construction_targets"], indent=2))


if __name__ == "__main__":
    main()
