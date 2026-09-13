#!/usr/bin/env python3
"""Replay and freeze the CodeGuard+ v2 machine-semantic set."""

from __future__ import annotations

import concurrent.futures
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import DEFAULT_PYTHON, ROOT, file_record, python_metadata, verified_record, write_json
from codeguardplus_partition_bwrap import run_method


SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-partitioned-v2-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_partitioned_v2/manifest.json"
PANEL = ROOT / "artifacts/codeguardplus-semantic-review-v2/report.json"
ADJUDICATION = ROOT / "configs/reviews/codeguardplus_partitioned_semantic_adjudication_v2.json"
OUTPUT = ROOT / "artifacts/codeguardplus-semantic-machine-v2"
TASKS = ROOT / "configs/benchmarks/codeguardplus_semantic_machine_qualified_v2.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_semantic_machine_visible_v2.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_semantic_machine_hidden_v2.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-semantic-machine-v2-freeze.json"
REPORT = ROOT / "docs/codeguardplus-semantic-machine-v2.md"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(task: str, partition: str, subject: str, candidate: Path, test: Path, repeat: int, python: Path, info: dict[str, Any]) -> dict[str, Any]:
    root = OUTPUT / "replay" / task.replace("/", "__") / partition / subject / f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    f = run_method(candidate=candidate, test=test, method="test_correctness", python=python, python_info=info, log=root / "functional.log", timeout_seconds=20)
    s = run_method(candidate=candidate, test=test, method="test_vulnerability", python=python, python_info=info, log=root / "security.log", timeout_seconds=20)
    state = "error" if f["passed"] is None or s["passed"] is None else f"F{'+' if f['passed'] else '-'}S{'+' if s['passed'] else '-'}"
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {"task_id": task, "partition": partition, "subject": subject, "repeat": repeat, "state": state, "expected_state": expected, "passed_gate": state == expected, "functional": f, "security": s}


def main() -> None:
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, ADJUDICATION):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT, TASKS, VISIBLE, HIDDEN, FREEZE, REPORT):
        if path.exists():
            raise FileExistsError(path)
    source_freeze, oracle, panel, adjudication = map(load, (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, ADJUDICATION))
    tasks = sorted(source_freeze["qualified_task_ids"])
    if set(tasks) != set(oracle["tasks"]) or set(tasks) != set(adjudication["decisions"]):
        raise RuntimeError("v2 semantic inputs have different task sets")
    if any(adjudication["decisions"][task]["decision"] != "accept" for task in tasks):
        raise RuntimeError("v2 contains a rejected semantic decision")
    if adjudication["formal_g7_complete"] is not False or panel["formal_g7_complete"] is not False:
        raise RuntimeError("Machine review cannot claim human G7")
    python = DEFAULT_PYTHON.absolute()
    info = python_metadata(python)
    OUTPUT.mkdir(parents=True)
    jobs = []
    for task in tasks:
        item = oracle["tasks"][task]
        for partition in ("visible", "hidden"):
            test = verified_record(item[f"{partition}_test"])
            for subject in ("safe_reference", "vulnerability_mutant"):
                candidate = verified_record(item[subject])
                for repeat in range(1, 4):
                    jobs.append((task, partition, subject, candidate, test, repeat))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(evaluate, *job, python, info) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result(); results.append(result)
            print(f"[{len(results)}/{len(jobs)}] {result['task_id']} {result['partition']} {result['subject']} r={result['repeat']} {result['state']}", flush=True)
    results.sort(key=lambda value: (value["task_id"], value["partition"], value["subject"], value["repeat"]))
    if not all(value["passed_gate"] for value in results):
        raise RuntimeError("Post-semantic replay mismatch")
    with (OUTPUT / "replay_results.jsonl").open("w", encoding="utf-8") as stream:
        for value in results:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    def projection(partition: str) -> dict[str, Any]:
        return {"schema_version": 1, "oracle_set_id": "codeguardplus-semantic-machine-v2", "oracle_status": "machine_semantic_review_complete_human_g7_pending", "partition": partition, "canonical_freeze": {"path": FREEZE.relative_to(ROOT).as_posix()}, "tasks": {task: {"cwe": oracle["tasks"][task]["cwe"], "oracle_file": oracle["tasks"][task][f"{partition}_test"], "cases": [{"marker": "functional", "unittest_method": "test_correctness", "behavior_family": oracle["tasks"][task]["families"][partition]["functionality"]}, {"marker": "security", "unittest_method": "test_vulnerability", "behavior_family": oracle["tasks"][task]["families"][partition]["security"]}]} for task in tasks}}
    VISIBLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(VISIBLE, projection("visible")); write_json(HIDDEN, projection("hidden"))
    write_json(TASKS, {"schema_version": 1, "oracle_set_id": "codeguardplus-semantic-machine-v2", "machine_semantic_review_complete": True, "independent_human_review_complete": False, "model_preflight_complete": False, "formal_experiment_ready": False, "tasks": tasks, "remaining_gates": ["independent second-researcher semantic review (G7)", "fresh-seed multi-model preflight (G8)", "final prompt/oracle/budget freeze"]})
    states = Counter(value["state"] for value in results)
    summary = {"task_count": len(tasks), "cwe_count": len({oracle['tasks'][task]['cwe'] for task in tasks}), "replay_observation_count": len(results), "replay_passed_observation_count": len(results), "repeat_count": 3, "partition_count": 2, "subject_count": 2, "state_counts": dict(sorted(states.items()))}
    write_json(OUTPUT / "summary.json", summary)
    write_json(OUTPUT / "run_manifest.json", {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(), "study_phase": "codeguardplus_v2_machine_semantic_replay", "python_environment": info, "candidate_imported_in_parent": False, "network_unshared_and_socket_denied": True, "results": file_record(OUTPUT / "replay_results.jsonl")})
    write_json(FREEZE, {"schema_version": 1, "freeze_id": "codeguardplus-semantic-machine-v2", "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "machine_semantic_review_complete_human_g7_and_g8_pending", "formal_experiment_ready": False, "machine_semantic_review_complete": True, "independent_human_review_complete": False, "model_preflight_complete": False, "qualified_task_ids": tasks, "summary": summary, "tasks": {task: {"decision": adjudication["decisions"][task], "oracle": oracle["tasks"][task]} for task in tasks}, "inputs": {"source_partition_freeze": file_record(SOURCE_FREEZE), "source_oracle_manifest": file_record(SOURCE_ORACLE), "semantic_machine_panel": file_record(PANEL), "semantic_evidence_adjudication": file_record(ADJUDICATION)}, "outputs": {"qualified_tasks": file_record(TASKS), "visible_projection": file_record(VISIBLE), "hidden_projection": file_record(HIDDEN), "replay_results": file_record(OUTPUT / "replay_results.jsonl"), "run_manifest": file_record(OUTPUT / "run_manifest.json")}, "formal_readiness_blockers": ["independent second-researcher semantic review (G7)", "fresh-seed multi-model preflight (G8)", "final prompt/oracle/budget freeze"]})
    rows = ["# CodeGuard+ machine semantic review v2", "", "## Outcome", "", "The repaired four-task/four-CWE slice passed code-level semantic adjudication. Qwen2.5-Coder-14B accepted 4/4; 7B accepted CWE-732 and produced confidence-0 template rejections for the other three, which were resolved from code rather than votes.", "", "## Replay", "", f"All {len(results)}/{len(results)} post-review safe/mutant observations matched their expected states across visible/hidden partitions and three fresh Bubblewrap repeats.", "", "## Boundary", "", "This freeze remains development-only: independent human G7 and fresh-seed multi-model G8 are pending. Four CWEs support a preflight slice, not a broad claim over all CodeGuard+.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True); REPORT.write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
