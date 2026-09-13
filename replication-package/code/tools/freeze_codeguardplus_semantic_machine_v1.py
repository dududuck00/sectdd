#!/usr/bin/env python3
"""Replay and freeze CodeGuard+ tasks accepted by machine semantic adjudication."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import DEFAULT_PYTHON, ROOT, file_record, python_metadata, verified_record, write_json
from codeguardplus_partition_bwrap import run_method


SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-partitioned-v1-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_partitioned_v1/manifest.json"
PANEL = ROOT / "artifacts/codeguardplus-semantic-review-v1/report.json"
ADJUDICATION = ROOT / "configs/reviews/codeguardplus_partitioned_semantic_adjudication_v1.json"
OUTPUT = ROOT / "artifacts/codeguardplus-semantic-machine-v1"
TASKS = ROOT / "configs/benchmarks/codeguardplus_semantic_machine_qualified_v1.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_semantic_machine_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_semantic_machine_hidden_v1.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-semantic-machine-v1-freeze.json"
REPORT = ROOT / "docs/codeguardplus-semantic-machine-v1.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--num-workers", type=int, default=8)
    return parser.parse_args()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(task: str, partition: str, subject: str, candidate: Path, test: Path, repeat: int, python: Path, py_info: dict[str, Any], timeout: float) -> dict[str, Any]:
    root = OUTPUT / "replay" / task.replace("/", "__") / partition / subject / f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    functional = run_method(candidate=candidate, test=test, method="test_correctness", python=python, python_info=py_info, log=root / "functional.log", timeout_seconds=timeout)
    security = run_method(candidate=candidate, test=test, method="test_vulnerability", python=python, python_info=py_info, log=root / "security.log", timeout_seconds=timeout)
    state = "error" if functional["passed"] is None or security["passed"] is None else f"F{'+' if functional['passed'] else '-'}S{'+' if security['passed'] else '-'}"
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {"task_id": task, "partition": partition, "subject": subject, "repeat": repeat, "state": state, "expected_state": expected, "passed_gate": state == expected, "functional": functional, "security": security}


def projection(source: dict[str, Any], accepted: list[str], partition: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-semantic-machine-v1",
        "oracle_status": "machine_semantic_review_complete_human_g7_pending",
        "partition": partition,
        "canonical_freeze": {"path": FREEZE.relative_to(ROOT).as_posix()},
        "tasks": {
            task: {
                "cwe": source["tasks"][task]["cwe"],
                "oracle_file": source["tasks"][task][f"{partition}_test"],
                "cases": [
                    {"marker": "functional", "unittest_method": "test_correctness", "behavior_family": source["tasks"][task]["families"][partition]["functionality"]},
                    {"marker": "security", "unittest_method": "test_vulnerability", "behavior_family": source["tasks"][task]["families"][partition]["security"]},
                ],
            }
            for task in accepted
        },
    }


def main() -> None:
    args = parse_args()
    if args.repeats != 3 or not 1 <= args.num_workers <= 16:
        raise ValueError("Freeze requires exactly three repeats and 1-16 workers")
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, ADJUDICATION):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT, TASKS, VISIBLE, HIDDEN, FREEZE, REPORT):
        if path.exists():
            raise FileExistsError(path)
    source_freeze = load(SOURCE_FREEZE)
    source = load(SOURCE_ORACLE)
    panel = load(PANEL)
    adjudication = load(ADJUDICATION)
    if set(adjudication["decisions"]) != set(source_freeze["qualified_task_ids"]):
        raise RuntimeError("Adjudication does not cover the frozen task set")
    if adjudication["independent_human_review_complete"] is not False or panel["formal_g7_complete"] is not False:
        raise RuntimeError("Machine evidence must not claim independent human G7")
    accepted = sorted(task for task, value in adjudication["decisions"].items() if value["decision"] == "accept")
    rejected = sorted(set(adjudication["decisions"]) - set(accepted))
    if not accepted or not rejected:
        raise RuntimeError("Expected both accepted and rejected semantic decisions")

    OUTPUT.mkdir(parents=True)
    python = args.python.expanduser().absolute()
    py_info = python_metadata(python)
    jobs = []
    for task in accepted:
        item = source["tasks"][task]
        for partition in ("visible", "hidden"):
            test = verified_record(item[f"{partition}_test"])
            for subject in ("safe_reference", "vulnerability_mutant"):
                candidate = verified_record(item[subject])
                for repeat in range(1, args.repeats + 1):
                    jobs.append((task, partition, subject, candidate, test, repeat))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = [pool.submit(evaluate, *job, python, py_info, args.timeout_seconds) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{len(results)}/{len(jobs)}] {result['task_id']} {result['partition']} {result['subject']} r={result['repeat']} {result['state']}", flush=True)
    results.sort(key=lambda value: (value["task_id"], value["partition"], value["subject"], value["repeat"]))
    if not all(value["passed_gate"] for value in results):
        raise RuntimeError("Semantic replay state mismatch")
    with (OUTPUT / "replay_results.jsonl").open("w", encoding="utf-8") as stream:
        for value in results:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")

    visible = projection(source, accepted, "visible")
    hidden = projection(source, accepted, "hidden")
    VISIBLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(VISIBLE, visible)
    write_json(HIDDEN, hidden)
    write_json(TASKS, {
        "schema_version": 1, "oracle_set_id": "codeguardplus-semantic-machine-v1",
        "machine_semantic_review_complete": True, "independent_human_review_complete": False,
        "model_preflight_complete": False, "formal_experiment_ready": False,
        "tasks": accepted, "rejected_tasks": rejected,
        "remaining_gates": ["independent second-researcher semantic review (G7)", "fresh-seed multi-model preflight (G8)", "breadth repair before formal use"],
    })
    states = Counter(value["state"] for value in results)
    summary = {
        "partition_qualified_task_count": len(source_freeze["qualified_task_ids"]),
        "machine_semantic_accepted_task_count": len(accepted),
        "semantic_rejected_task_count": len(rejected),
        "replay_observation_count": len(results), "replay_passed_observation_count": len(results),
        "repeat_count": args.repeats, "partition_count": 2, "subject_count": 2,
        "state_counts": dict(sorted(states.items())),
    }
    write_json(OUTPUT / "summary.json", summary)
    write_json(OUTPUT / "run_manifest.json", {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_phase": "codeguardplus_machine_semantic_review_replay", "python_environment": py_info,
        "candidate_imported_in_parent": False, "ephemeral_workspace_per_test_method": True,
        "network_unshared_and_socket_denied": True, "results": file_record(OUTPUT / "replay_results.jsonl"),
    })
    freeze = {
        "schema_version": 1, "freeze_id": "codeguardplus-semantic-machine-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "machine_semantic_review_complete_breadth_repair_human_g7_and_g8_pending",
        "formal_experiment_ready": False, "machine_semantic_review_complete": True,
        "independent_human_review_complete": False, "model_preflight_complete": False,
        "breadth_sufficient_for_formal_external_experiment": False,
        "formal_readiness_blockers": ["repair visible/hidden oracle breadth", "independent second-researcher semantic review (G7)", "fresh-seed multi-model preflight (G8)"],
        "summary": summary, "qualified_task_ids": accepted,
        "tasks": {task: {"decision": adjudication["decisions"][task], "oracle": source["tasks"][task]} for task in accepted},
        "rejected_tasks": {task: adjudication["decisions"][task] for task in rejected},
        "inputs": {"source_partition_freeze": file_record(SOURCE_FREEZE), "source_oracle_manifest": file_record(SOURCE_ORACLE), "semantic_machine_panel": file_record(PANEL), "semantic_evidence_adjudication": file_record(ADJUDICATION)},
        "outputs": {"qualified_tasks": file_record(TASKS), "visible_projection": file_record(VISIBLE), "hidden_projection": file_record(HIDDEN), "replay_results": file_record(OUTPUT / "replay_results.jsonl"), "run_manifest": file_record(OUTPUT / "run_manifest.json")},
    }
    write_json(FREEZE, freeze)
    lines = [
        "# CodeGuard+ machine semantic review v1", "", "## Outcome", "",
        f"Seven partition-qualified tasks were reviewed from blinded packets by Qwen2.5-Coder-7B and 14B, then adjudicated against code evidence. {len(accepted)} task was retained and {len(rejected)} were rejected.", "",
        "| Task | CWE | 7B | 14B | Evidence decision |", "|---|---|---:|---:|---:|",
    ]
    for task in source_freeze["qualified_task_ids"]:
        verdicts = panel["task_audit"][task]["reviewer_verdicts"]
        lines.append(f"| `{task}` | {source['tasks'][task]['cwe']} | {verdicts['qwen25-coder-7b']} | {verdicts['qwen25-coder-14b']} | {adjudication['decisions'][task]['decision']} |")
    lines += [
        "", "## Replay", "", f"The retained task produced {len(results)}/{len(results)} expected safe/mutant states across visible/hidden partitions and three fresh Bubblewrap repeats.", "",
        "## Readiness boundary", "", "This is a machine-panel evidence audit, not independent human G7. The retained breadth is insufficient for a formal external experiment, so G8 is intentionally deferred until rejected oracle families are repaired and re-reviewed.", "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
