#!/usr/bin/env python3
"""Correct construction projections before paper-expansion generation resumes.

The correction is schema-only: task membership, prompts/contracts, executable
tests, methods, seeds, and budgets are unchanged.  It adds the missing SALLM
execution overlay and converts CodeGuard+ construction projections into the
formal-runner schema.  Every before/after hash is retained in an audit record.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORRECTION = ROOT / "benchmarks/manifests/paper-expansion-full-v1-runtime-input-correction.json"
INPUT_FREEZE = ROOT / "benchmarks/manifests/paper-expansion-full-v1-input-freeze.json"
SALLM_VISIBLE = ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json"
SALLM_HIDDEN = ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json"
SALLM_FREEZE = ROOT / "benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json"
SALLM_OVERLAYS = {
    "visible": ROOT / "configs/benchmarks/sallm_paper_expansion_v1_semantic_machine_visible.json",
    "hidden": ROOT / "configs/benchmarks/sallm_paper_expansion_v1_semantic_machine_hidden.json",
}
SALLM_SOURCES = {
    "visible": [
        ROOT / "configs/oracles/sallm_paper_expansion_v1_visible.json",
        ROOT / "configs/oracles/sallm_paper_expansion_supplement_v1_visible.json",
    ],
    "hidden": [
        ROOT / "configs/oracles/sallm_paper_expansion_v1_hidden.json",
        ROOT / "configs/oracles/sallm_paper_expansion_supplement_v1_hidden.json",
    ],
}
CG_VISIBLE = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json"
CG_HIDDEN = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json"
CG_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-machine-freeze.json"
CG_SOURCE_VISIBLE = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_visible.json"
CG_SOURCE_HIDDEN = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_hidden.json"
CG_ORACLE = ROOT / "oracles/codeguardplus_paper_expansion_v1/manifest.json"
CG_BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
CG_PROMPTS = ROOT / "configs/prompts/codeguardplus_paper_expansion_full_v1"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verified_text(record: dict[str, Any]) -> str:
    path = ROOT / record["path"]
    if sha(path) != record["sha256"] or path.stat().st_size != record["size_bytes"]:
        raise RuntimeError(f"Frozen source drift: {path}")
    return path.read_text(encoding="utf-8")


def repair_sallm() -> dict[str, Any]:
    before = {partition: rec(path) for partition, path in (("visible", SALLM_VISIBLE), ("hidden", SALLM_HIDDEN))}
    for partition, projection_path in (("visible", SALLM_VISIBLE), ("hidden", SALLM_HIDDEN)):
        projection = load(projection_path)
        accepted = list(projection["tasks"])
        source_projections = [load(path) for path in SALLM_SOURCES[partition]]
        source_overlays = [load(ROOT / value["execution_overlay"]["path"]) for value in source_projections]
        overlay = dict(source_overlays[0])
        overlay["overlay_id"] = f"sallm-paper-expansion-v1-semantic-machine-{partition}"
        overlay["oracle_set_id"] = projection["oracle_set_id"]
        overlay["oracle_partition"] = partition
        overlay["scope"] = {"qualified_task_ids": accepted, "task_count": len(accepted)}
        overlay["test_overrides"] = {}
        for task in accepted:
            matches = [source["test_overrides"][task] for source in source_overlays if task in source.get("test_overrides", {})]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one SALLM overlay source for {task}/{partition}")
            overlay["test_overrides"][task] = matches[0]
        write(SALLM_OVERLAYS[partition], overlay)
        projection["execution_overlay"] = rec(SALLM_OVERLAYS[partition])
        write(projection_path, projection)
    freeze = load(SALLM_FREEZE)
    freeze["outputs"]["visible"] = rec(SALLM_VISIBLE)
    freeze["outputs"]["hidden"] = rec(SALLM_HIDDEN)
    freeze["outputs"]["execution_overlays"] = {key: rec(path) for key, path in SALLM_OVERLAYS.items()}
    freeze["runtime_schema_correction"] = "added combined execution overlays; task/test membership unchanged"
    write(SALLM_FREEZE, freeze)
    return {
        "before": before,
        "after": {partition: rec(path) for partition, path in (("visible", SALLM_VISIBLE), ("hidden", SALLM_HIDDEN))},
        "overlays": {key: rec(path) for key, path in SALLM_OVERLAYS.items()},
    }


def repair_codeguardplus() -> dict[str, Any]:
    before = {"visible": rec(CG_VISIBLE), "hidden": rec(CG_HIDDEN)}
    source_projections = {"visible": load(CG_SOURCE_VISIBLE), "hidden": load(CG_SOURCE_HIDDEN)}
    oracle = load(CG_ORACLE)["tasks"]
    benchmark = {item["task_id"]: item for item in load(CG_BENCHMARK)["tasks"]}
    current = load(CG_VISIBLE)
    accepted = list(current["tasks"])
    prompt_records: dict[str, Any] = {}
    tasks: dict[str, dict[str, Any]] = {"visible": {}, "hidden": {}}
    for task in accepted:
        source = benchmark[task]["source"]
        file_context = verified_text(source["file_context"]).rstrip()
        function_context = verified_text(source["function_context"]).rstrip()
        prompt_text = "\n\n".join(value for value in (file_context, function_context) if value) + "\n"
        prompt_path = CG_PROMPTS / f"{task.replace('/', '__')}.py"
        if prompt_path.exists() and prompt_path.read_text(encoding="utf-8") != prompt_text:
            raise RuntimeError(f"Prompt correction drift: {prompt_path}")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        prompt_records[task] = rec(prompt_path)
        for partition in ("visible", "hidden"):
            item = source_projections[partition]["tasks"][task]
            test = item["oracle_file"]
            cases = []
            for case in item["cases"]:
                method = case.get("test_method", case.get("unittest_method"))
                if not method:
                    raise RuntimeError(f"Missing CodeGuard+ test method: {task}/{partition}")
                cases.append({
                    "case_id": case["case_id"], "marker": case["marker"],
                    "behavior_family": case["behavior_family"],
                    "description": case.get("description", case["behavior_family"]),
                    "test_method": method,
                })
            tasks[partition][task] = {
                "cwe": item["cwe"], "contract": oracle[task]["contract"],
                "prompt_file": prompt_records[task]["path"], "prompt_sha256": prompt_records[task]["sha256"],
                "oracle_file": test["path"], "oracle_sha256": test["sha256"], "cases": cases,
            }
    for partition, path in (("visible", CG_VISIBLE), ("hidden", CG_HIDDEN)):
        projection = load(path)
        projection["tasks"] = tasks[partition]
        write(path, projection)
    freeze = load(CG_FREEZE)
    freeze["outputs"]["visible"] = rec(CG_VISIBLE)
    freeze["outputs"]["hidden"] = rec(CG_HIDDEN)
    freeze["outputs"]["prompts"] = prompt_records
    freeze["runtime_schema_correction"] = "normalized construction projections for formal runner; task/test membership unchanged"
    write(CG_FREEZE, freeze)
    return {
        "before": before,
        "after": {"visible": rec(CG_VISIBLE), "hidden": rec(CG_HIDDEN)},
        "prompts": prompt_records,
    }


def update_input_freeze() -> dict[str, Any]:
    before = rec(INPUT_FREEZE)
    freeze = load(INPUT_FREEZE)
    for benchmark, visible, hidden in (
        ("sallm", SALLM_VISIBLE, SALLM_HIDDEN),
        ("codeguardplus", CG_VISIBLE, CG_HIDDEN),
    ):
        freeze["benchmarks"][benchmark]["visible"] = rec(visible)
        freeze["benchmarks"][benchmark]["hidden"] = rec(hidden)
    freeze["runtime_input_correction"] = {
        "correction_id": "paper-expansion-full-v1-runtime-input-correction",
        "selection_or_method_outcomes_changed": False,
        "task_test_method_seed_budget_membership_changed": False,
        "reason": "restore runner-required projection metadata and disable default Qwen3.6 thinking in orchestrator",
    }
    write(INPUT_FREEZE, freeze)
    return {"before": before, "after": rec(INPUT_FREEZE)}


def verify() -> None:
    for path in (SALLM_VISIBLE, SALLM_HIDDEN):
        projection = load(path)
        overlay = projection.get("execution_overlay")
        if not isinstance(overlay, dict) or sha(ROOT / overlay["path"]) != overlay["sha256"]:
            raise RuntimeError(f"Invalid repaired SALLM projection: {path}")
    required = {"cwe", "contract", "prompt_file", "prompt_sha256", "oracle_file", "oracle_sha256", "cases"}
    for path in (CG_VISIBLE, CG_HIDDEN):
        projection = load(path)
        for task, item in projection["tasks"].items():
            if set(item) != required or any("test_method" not in case for case in item["cases"]):
                raise RuntimeError(f"Invalid repaired CodeGuard+ projection: {task}")


def main() -> None:
    if CORRECTION.exists():
        verify()
        print(json.dumps({"correction": rec(CORRECTION), "verified": True}, indent=2))
        return
    sallm = repair_sallm()
    codeguardplus = repair_codeguardplus()
    input_freeze = update_input_freeze()
    verify()
    write(CORRECTION, {
        "schema_version": 1,
        "correction_id": "paper-expansion-full-v1-runtime-input-correction",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_or_method_outcomes_changed": False,
        "task_test_method_seed_budget_membership_changed": False,
        "invalidated_scope": "qwen36-27b partial trajectories created before explicit thinking disablement",
        "sallm": sallm,
        "codeguardplus": codeguardplus,
        "input_freeze": input_freeze,
    })
    print(json.dumps({"correction": rec(CORRECTION), "verified": True}, indent=2))


if __name__ == "__main__":
    main()
