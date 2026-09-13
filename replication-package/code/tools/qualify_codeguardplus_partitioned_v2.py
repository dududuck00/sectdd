#!/usr/bin/env python3
"""Qualify repaired CodeGuard+ behavior families and freeze development v2."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import DEFAULT_PYTHON, ROOT, file_record, python_metadata, verified_record, write_json
from codeguardplus_partition_bwrap import run_method


V1 = ROOT / "oracles/codeguardplus_partitioned_v1/manifest.json"
ADJUDICATION = ROOT / "configs/reviews/codeguardplus_partitioned_semantic_adjudication_v1.json"
SOURCE = ROOT / "oracles/codeguardplus_partitioned_v2"
OUTPUT = ROOT / "artifacts/codeguardplus-partitioned-qualification/v2"
VISIBLE = ROOT / "configs/oracles/codeguardplus_partitioned_v2_visible.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_partitioned_v2_hidden.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-partitioned-v2-freeze.json"

REPAIRED = ("cwe-078/1-py", "cwe-089/0-py", "cwe-732/2-py")
RETAINED = "cwe-327/2-py"
FAMILIES = {
    "cwe-078/1-py": {"visible": {"functionality": "existing-user lookup", "security": "semicolon command chaining"}, "hidden": {"functionality": "missing-user handling", "security": "backtick command substitution"}},
    "cwe-089/0-py": {"visible": {"functionality": "ordinary email deletion", "security": "boolean-tautology mass deletion"}, "hidden": {"functionality": "plus-address deletion", "security": "quote-and-comment targeted deletion"}},
    "cwe-732/2-py": {"visible": {"functionality": "fresh-file content", "security": "fresh-file restricted mode"}, "hidden": {"functionality": "pre-existing-file overwrite", "security": "pre-existing permissive-mode remediation"}},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(task: str, partition: str, subject: str, candidate: Path, test: Path, repeat: int, python: Path, info: dict[str, Any]) -> dict[str, Any]:
    root = OUTPUT / "replay" / task.replace("/", "__") / partition / subject / f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    f = run_method(candidate=candidate, test=test, method="test_correctness", python=python, python_info=info, log=root / "functional.log", timeout_seconds=20)
    s = run_method(candidate=candidate, test=test, method="test_vulnerability", python=python, python_info=info, log=root / "security.log", timeout_seconds=20)
    state = "error" if f["passed"] is None or s["passed"] is None else f"F{'+' if f['passed'] else '-'}S{'+' if s['passed'] else '-'}"
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {"task_id": task, "partition": partition, "subject": subject, "repeat": repeat, "state": state, "expected_state": expected, "passed_gate": state == expected, "functional": f, "security": s}


def main() -> None:
    for path in (OUTPUT, VISIBLE, HIDDEN, FREEZE, SOURCE / "manifest.json"):
        if path.exists():
            raise FileExistsError(path)
    v1 = json.loads(V1.read_text(encoding="utf-8"))["tasks"]
    decisions = json.loads(ADJUDICATION.read_text(encoding="utf-8"))["decisions"]
    if decisions[RETAINED]["decision"] != "accept" or any(decisions[task]["decision"] != "reject" for task in REPAIRED):
        raise RuntimeError("Semantic adjudication no longer matches repair plan")
    tasks = list(REPAIRED) + [RETAINED]
    records: dict[str, Any] = {}
    for task in tasks:
        item = v1[task]
        family = FAMILIES.get(task, item["families"])
        tests = {}
        for partition in ("visible", "hidden"):
            if task == RETAINED:
                source = verified_record(item[f"{partition}_test"])
                destination = SOURCE / partition / f"test_{task.replace('/', '__')}.py"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            else:
                destination = SOURCE / partition / f"test_{task.replace('/', '__')}.py"
            tests[f"{partition}_test"] = file_record(destination)
        records[task] = {
            "cwe": item["cwe"], "contract": item["contract"], "families": family,
            **tests, "safe_reference": item["safe_reference"], "vulnerability_mutant": item["vulnerability_mutant"],
            "provenance": {"kind": "semantic_evidence_repair" if task in REPAIRED else "retained_from_v1", "source_adjudication": file_record(ADJUDICATION)},
        }
    python = DEFAULT_PYTHON.absolute()
    info = python_metadata(python)
    OUTPUT.mkdir(parents=True)
    jobs = []
    for task, item in records.items():
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
            result = future.result()
            results.append(result)
            print(f"[{len(results)}/{len(jobs)}] {result['task_id']} {result['partition']} {result['subject']} r={result['repeat']} {result['state']}", flush=True)
    results.sort(key=lambda value: (value["task_id"], value["partition"], value["subject"], value["repeat"]))
    with (OUTPUT / "results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    passed = sorted(task for task in tasks if all(value["passed_gate"] for value in results if value["task_id"] == task))
    if passed != sorted(tasks):
        raise RuntimeError(f"Repair qualification failed: passed={passed}")
    manifest = {"schema_version": 1, "oracle_set_id": "codeguardplus-partitioned-v2", "created_at_utc": datetime.now(timezone.utc).isoformat(), "split_unit": "behavior_family", "behavior_family_overlap_allowed": False, "tasks": records}
    write_json(SOURCE / "manifest.json", manifest)
    def project(partition: str) -> dict[str, Any]:
        return {"schema_version": 1, "oracle_set_id": "codeguardplus-partitioned-v2", "partition": partition, "tasks": {task: {"cwe": records[task]["cwe"], "oracle_file": records[task][f"{partition}_test"], "cases": [{"marker": "functional", "unittest_method": "test_correctness", "behavior_family": records[task]["families"][partition]["functionality"]}, {"marker": "security", "unittest_method": "test_vulnerability", "behavior_family": records[task]["families"][partition]["security"]}]} for task in tasks}}
    VISIBLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(VISIBLE, project("visible")); write_json(HIDDEN, project("hidden"))
    states = Counter(value["state"] for value in results)
    summary = {"input_tasks": len(tasks), "repeat_qualified_tasks": len(passed), "repeat_observations": len(results), "repeat_passed_observations": sum(value["passed_gate"] for value in results), "state_counts": dict(sorted(states.items())), "complete": True}
    write_json(OUTPUT / "summary.json", summary)
    write_json(FREEZE, {"schema_version": 1, "freeze_id": "codeguardplus-partitioned-v2", "created_at_utc": datetime.now(timezone.utc).isoformat(), "development_only": True, "formal_experiment_ready": False, "independent_human_review_complete": False, "model_preflight_complete": False, "qualified_task_ids": passed, "counts": summary, "inputs": {"v1_oracle": file_record(V1), "semantic_adjudication": file_record(ADJUDICATION)}, "outputs": {"oracle_manifest": file_record(SOURCE / "manifest.json"), "visible_projection": file_record(VISIBLE), "hidden_projection": file_record(HIDDEN), "qualification_results": file_record(OUTPUT / "results.jsonl")}, "remaining_gates": ["blinded semantic review of repaired v2 families", "independent second-researcher G7", "fresh-seed multi-model G8", "final freeze"]})
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
