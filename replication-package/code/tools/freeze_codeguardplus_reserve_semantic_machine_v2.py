#!/usr/bin/env python3
"""Replay and freeze the machine-semantic-qualified CodeGuard+ reserve v2 set."""

from __future__ import annotations

import concurrent.futures
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import DEFAULT_PYTHON, ROOT, file_record, python_metadata, verified_record, write_json
from codeguardplus_partition_bwrap import run_method


SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-partitioned-v2-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_reserve_partitioned_v2/manifest.json"
PANEL = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/semantic-review-v2/report.json"
PACKETS = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/semantic-review-v2/packet_manifest.json"
OUTPUT = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/semantic-machine-v2"
TASKS = ROOT / "configs/benchmarks/codeguardplus_reserve_semantic_machine_qualified_v2.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_reserve_semantic_machine_visible_v2.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_reserve_semantic_machine_hidden_v2.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-semantic-machine-v2-freeze.json"
REPORT = ROOT / "docs/codeguardplus-reserve-semantic-machine-v2.md"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    task: str,
    partition: str,
    subject: str,
    candidate: Path,
    test: Path,
    repeat: int,
    python: Path,
    python_info: dict[str, Any],
) -> dict[str, Any]:
    root = OUTPUT / "replay" / task.replace("/", "__") / partition / subject / f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    functional = run_method(
        candidate=candidate,
        test=test,
        method="test_correctness",
        python=python,
        python_info=python_info,
        log=root / "functional.log",
        timeout_seconds=20,
    )
    security = run_method(
        candidate=candidate,
        test=test,
        method="test_vulnerability",
        python=python,
        python_info=python_info,
        log=root / "security.log",
        timeout_seconds=20,
    )
    if functional["passed"] is None or security["passed"] is None:
        state = "infrastructure_or_oracle_error"
    else:
        state = f"F{'+' if functional['passed'] else '-'}S{'+' if security['passed'] else '-'}"
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {
        "task_id": task,
        "partition": partition,
        "subject": subject,
        "repeat": repeat,
        "state": state,
        "expected_state": expected,
        "passed_gate": state == expected,
        "functional": functional,
        "security": security,
    }


def projection(oracle: dict[str, Any], task_ids: list[str], partition: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-reserve-semantic-machine-v2",
        "oracle_status": "machine_semantic_review_complete_human_g7_pending",
        "partition": partition,
        "canonical_freeze": {"path": FREEZE.relative_to(ROOT).as_posix()},
        "tasks": {
            task: {
                "cwe": oracle[task]["cwe"],
                "oracle_file": oracle[task][f"{partition}_test"],
                "cases": [
                    {
                        "case_id": f"{task.replace('/', '__')}-{partition}-f",
                        "marker": "functional",
                        "unittest_method": "test_correctness",
                        "behavior_family": oracle[task]["families"][partition]["functionality"],
                    },
                    {
                        "case_id": f"{task.replace('/', '__')}-{partition}-s",
                        "marker": "security",
                        "unittest_method": "test_vulnerability",
                        "behavior_family": oracle[task]["families"][partition]["security"],
                    },
                ],
            }
            for task in task_ids
        },
    }


def main() -> None:
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, PACKETS):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT, TASKS, VISIBLE, HIDDEN, FREEZE, REPORT):
        if path.exists():
            raise FileExistsError(path)

    source_freeze = load(SOURCE_FREEZE)
    oracle_manifest = load(SOURCE_ORACLE)
    oracle = oracle_manifest["tasks"]
    panel = load(PANEL)
    packets = load(PACKETS)
    task_ids = source_freeze["qualified_task_ids"]

    if source_freeze["outputs"]["oracle_manifest"]["sha256"] != file_record(SOURCE_ORACLE)["sha256"]:
        raise RuntimeError("The v2 oracle drifted after qualification")
    if panel["report_id"] != "codeguardplus-reserve-partitioned-semantic-machine-panel-v2":
        raise RuntimeError("Unexpected semantic panel identity")
    if panel["inputs"]["task_file"]["sha256"] != file_record(SOURCE_FREEZE)["sha256"]:
        raise RuntimeError("The partition freeze drifted after semantic review")
    if panel["inputs"]["oracle_manifest"]["sha256"] != file_record(SOURCE_ORACLE)["sha256"]:
        raise RuntimeError("The oracle manifest drifted after semantic review")
    if packets.get("report_id") != panel["report_id"] or packets.get("blinded") is not True:
        raise RuntimeError("The semantic packet manifest is not the frozen blinded v2 set")
    if set(task_ids) != set(oracle) or set(task_ids) != set(panel["task_audit"]):
        raise RuntimeError("Machine-semantic inputs have different task sets")
    if panel["summary"] != {
        "machine_reject_or_escalate_count": 0,
        "reviewer_count": 2,
        "task_count": len(task_ids),
        "unanimous_machine_accept_count": len(task_ids),
    }:
        raise RuntimeError("The v2 machine panel is not a unanimous two-reviewer acceptance")
    reviewer_models = {item["model"] for item in panel["reviewers"]}
    reviewer_providers = {item["provider"] for item in panel["reviewers"]}
    if len(reviewer_models) != 2 or reviewer_providers != {"deepseek", "local"}:
        raise RuntimeError("The semantic panel lacks the frozen cross-provider reviewers")
    for task in task_ids:
        audit = panel["task_audit"][task]
        if (
            audit["machine_panel_verdict"] != "accept"
            or set(audit["reviewer_verdicts"]) != reviewer_models
            or set(audit["reviewer_verdicts"].values()) != {"accept"}
        ):
            raise RuntimeError(f"Task lacks unanimous machine acceptance: {task}")
        for review_record in audit["reviews"].values():
            verified_record(review_record)
        for field in ("safe_reference", "vulnerability_mutant", "visible_test", "hidden_test"):
            verified_record(oracle[task][field])
    if panel["formal_g7_complete"] is not False or panel["independent_human_review_complete"] is not False:
        raise RuntimeError("Machine review cannot claim independent human G7")

    python = DEFAULT_PYTHON.absolute()
    python_info = python_metadata(python)
    OUTPUT.mkdir(parents=True)
    jobs = []
    for task in task_ids:
        for partition in ("visible", "hidden"):
            test = verified_record(oracle[task][f"{partition}_test"])
            for subject in ("safe_reference", "vulnerability_mutant"):
                candidate = verified_record(oracle[task][subject])
                for repeat in range(1, 4):
                    jobs.append((task, partition, subject, candidate, test, repeat))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(evaluate, *job, python, python_info) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"[{len(results)}/{len(jobs)}] {result['task_id']} {result['partition']} "
                f"{result['subject']} r={result['repeat']} {result['state']}",
                flush=True,
            )
    results.sort(key=lambda item: (item["task_id"], item["partition"], item["subject"], item["repeat"]))
    with (OUTPUT / "replay_results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")

    states = Counter(item["state"] for item in results)
    passed_count = sum(item["passed_gate"] for item in results)
    summary = {
        "task_count": len(task_ids),
        "cwe_count": len({oracle[task]["cwe"] for task in task_ids}),
        "reviewer_count": 2,
        "repeat_count": 3,
        "partition_count": 2,
        "subject_count": 2,
        "replay_observation_count": len(results),
        "replay_passed_observation_count": passed_count,
        "state_counts": dict(sorted(states.items())),
        "complete": len(results) == 24 and passed_count == 24,
        "formal_results_use": False,
    }
    write_json(OUTPUT / "summary.json", summary)
    if not summary["complete"]:
        raise RuntimeError(f"Post-semantic replay mismatch: {summary}")

    write_json(
        OUTPUT / "run_manifest.json",
        {
            "schema_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "study_phase": "codeguardplus_reserve_v2_machine_semantic_replay",
            "development_only": True,
            "formal_results_use": False,
            "python_environment": python_info,
            "candidate_imported_in_parent": False,
            "ephemeral_workspace_per_test_method": True,
            "network_unshared_and_socket_denied": True,
            "source_partition_freeze": file_record(SOURCE_FREEZE),
            "source_oracle_manifest": file_record(SOURCE_ORACLE),
            "semantic_machine_panel": file_record(PANEL),
            "results": file_record(OUTPUT / "replay_results.jsonl"),
        },
    )
    write_json(
        TASKS,
        {
            "schema_version": 1,
            "oracle_set_id": "codeguardplus-reserve-semantic-machine-v2",
            "machine_semantic_review_complete": True,
            "independent_human_review_complete": False,
            "model_preflight_complete": False,
            "formal_experiment_ready": False,
            "tasks": task_ids,
            "cwes": sorted({oracle[task]["cwe"] for task in task_ids}),
            "remaining_gates": [
                "independent second-researcher semantic review (G7)",
                "fresh-seed multi-model G8 preflight",
                "final prompt/oracle/budget freeze",
            ],
        },
    )
    VISIBLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(VISIBLE, projection(oracle, task_ids, "visible"))
    write_json(HIDDEN, projection(oracle, task_ids, "hidden"))
    report_lines = [
        "# CodeGuard+ reserve machine-semantic freeze v2",
        "",
        "## Outcome",
        "",
        "Qwen2.5-Coder-14B and DeepSeek-V4-Flash unanimously accepted both blinded v2 packets.",
        "The CWE-295 repair is retained alongside the unanimously accepted CWE-89 task.",
        "",
        "## Post-review replay",
        "",
        f"All {len(results)}/{len(results)} safe/mutant observations matched their expected states across visible/hidden partitions and three fresh Bubblewrap repeats.",
        "",
        "## Boundary",
        "",
        "This freeze remains development-only. Independent human G7, fresh-seed multi-model G8, and the final experiment freeze are pending.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")
    write_json(
        FREEZE,
        {
            "schema_version": 1,
            "freeze_id": "codeguardplus-reserve-semantic-machine-v2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "machine_semantic_review_complete_human_g7_and_g8_pending",
            "development_only": True,
            "formal_results_use": False,
            "formal_experiment_ready": False,
            "machine_semantic_review_complete": True,
            "independent_human_review_complete": False,
            "model_preflight_complete": False,
            "qualified_task_ids": task_ids,
            "summary": summary,
            "inputs": {
                "source_partition_freeze": file_record(SOURCE_FREEZE),
                "source_oracle_manifest": file_record(SOURCE_ORACLE),
                "semantic_packet_manifest": file_record(PACKETS),
                "semantic_machine_panel": file_record(PANEL),
            },
            "outputs": {
                "qualified_tasks": file_record(TASKS),
                "visible_projection": file_record(VISIBLE),
                "hidden_projection": file_record(HIDDEN),
                "replay_results": file_record(OUTPUT / "replay_results.jsonl"),
                "run_manifest": file_record(OUTPUT / "run_manifest.json"),
                "report": file_record(REPORT),
            },
            "formal_readiness_blockers": [
                "independent second-researcher semantic review (G7)",
                "fresh-seed multi-model G8 preflight",
                "final prompt/oracle/budget freeze",
            ],
        },
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
