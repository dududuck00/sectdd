#!/usr/bin/env python3
"""Adjudicate, replay, and freeze wave4 machine-semantic evidence."""

from __future__ import annotations

import concurrent.futures
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codeguardplus_bwrap import DEFAULT_PYTHON, ROOT, file_record, python_metadata, verified_record, write_json
from codeguardplus_partition_bwrap import run_method


SOURCE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-freeze.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_reserve_breadth_wave4/manifest.json"
PANEL = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-review/report.json"
DISPUTE_FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-dispute-v1.json"
DISPUTE_PACKETS = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-dispute-review/packet_manifest.json"
TIEBREAK = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-dispute-review/reviews/qwen3-32b/cwe-117__2-py.json"
OUTPUT = ROOT / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-machine-v1"
TASKS = ROOT / "configs/benchmarks/codeguardplus_reserve_breadth_wave4_semantic_machine_v1.json"
VISIBLE = ROOT / "configs/oracles/codeguardplus_reserve_breadth_wave4_semantic_machine_visible_v1.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_reserve_breadth_wave4_semantic_machine_hidden_v1.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-machine-v1-freeze.json"
REPORT = ROOT / "docs/codeguardplus-reserve-breadth-wave4-semantic-machine-v1.md"
TASK_IDS = ["cwe-327/0-py", "cwe-117/2-py"]
DISPUTED = "cwe-117/2-py"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(task: str, partition: str, subject: str, candidate: Path, test: Path, repeat: int, python: Path, info: dict[str, Any]) -> dict[str, Any]:
    root = OUTPUT / "replay" / task.replace("/", "__") / partition / subject / f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    functional = run_method(candidate=candidate, test=test, method="test_correctness", python=python, python_info=info, log=root / "functional.log", timeout_seconds=20)
    security = run_method(candidate=candidate, test=test, method="test_vulnerability", python=python, python_info=info, log=root / "security.log", timeout_seconds=20)
    state = "infrastructure_or_oracle_error" if functional["passed"] is None or security["passed"] is None else f"F{'+' if functional['passed'] else '-'}S{'+' if security['passed'] else '-'}"
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {"task_id": task, "partition": partition, "subject": subject, "repeat": repeat, "state": state, "expected_state": expected, "passed_gate": state == expected, "functional": functional, "security": security}


def projection(oracle: dict[str, Any], partition: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-reserve-breadth-wave4-semantic-machine-v1",
        "oracle_status": "machine_semantic_review_complete_human_g7_and_g8_pending",
        "partition": partition,
        "canonical_freeze": {"path": FREEZE.relative_to(ROOT).as_posix()},
        "tasks": {
            task: {
                "cwe": oracle[task]["cwe"],
                "oracle_file": oracle[task][f"{partition}_test"],
                "cases": [
                    {"marker": "functional", "unittest_method": "test_correctness", "behavior_family": oracle[task]["families"][partition]["functionality"]},
                    {"marker": "security", "unittest_method": "test_vulnerability", "behavior_family": oracle[task]["families"][partition]["security"]},
                ],
            }
            for task in TASK_IDS
        },
    }


def main() -> None:
    for path in (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, DISPUTE_FREEZE, DISPUTE_PACKETS, TIEBREAK):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT, TASKS, VISIBLE, HIDDEN, FREEZE, REPORT):
        if path.exists():
            raise FileExistsError(path)
    source, oracle_manifest, panel, dispute, packets, tiebreak = map(load, (SOURCE_FREEZE, SOURCE_ORACLE, PANEL, DISPUTE_FREEZE, DISPUTE_PACKETS, TIEBREAK))
    oracle = oracle_manifest["tasks"]
    if source["qualified_task_ids"] != TASK_IDS or set(oracle) != set(TASK_IDS):
        raise RuntimeError("Wave4 construction task drift")
    if panel["unanimous_machine_accept_tasks"] != ["cwe-327/0-py"]:
        raise RuntimeError("Wave4 initial panel acceptance drift")
    if panel["task_audit"][DISPUTED]["reviewer_verdicts"] != {"qwen25-coder-14b": "reject", "qwen36-35b-a3b": "accept"}:
        raise RuntimeError("Unexpected CWE-117 initial split")
    if dispute["qualified_task_ids"] != [DISPUTED] or dispute["third_reviewer_packet_contains_prior_verdicts"] is not False:
        raise RuntimeError("Invalid CWE-117 dispute freeze")
    if packets.get("blinded") is not True or packets.get("task_count") != 1 or packets["task_file"]["sha256"] != file_record(DISPUTE_FREEZE)["sha256"]:
        raise RuntimeError("Invalid blinded tie-break packet")
    if tiebreak["reviewer"]["model"] != "qwen3-32b" or tiebreak["reviewer"]["provider"] != "local":
        raise RuntimeError("Unexpected tie-break reviewer")
    if tiebreak["review"]["verdict"] != "accept" or tiebreak["review"]["behavior_family_assessment"]["materially_distinct"] is not True:
        raise RuntimeError("CWE-117 tie-break did not accept semantic validity")
    if tiebreak["api"]["request_config"].get("thinking") != "disabled" or tiebreak["packet"]["sha256"] != packets["packets"][DISPUTED]["sha256"]:
        raise RuntimeError("Tie-break request or packet drift")

    python = DEFAULT_PYTHON.absolute()
    info = python_metadata(python)
    OUTPUT.mkdir(parents=True)
    jobs = []
    for task in TASK_IDS:
        for partition in ("visible", "hidden"):
            test = verified_record(oracle[task][f"{partition}_test"])
            for subject in ("safe_reference", "vulnerability_mutant"):
                candidate = verified_record(oracle[task][subject])
                for repeat in range(1, 4):
                    jobs.append((task, partition, subject, candidate, test, repeat))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(evaluate, *job, python, info) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result(); results.append(result)
            print(f"[{len(results)}/{len(jobs)}] {result['task_id']} {result['partition']} {result['subject']} r={result['repeat']} {result['state']}", flush=True)
    results.sort(key=lambda item: (item["task_id"], item["partition"], item["subject"], item["repeat"]))
    with (OUTPUT / "replay_results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    passed = sum(item["passed_gate"] for item in results)
    states = Counter(item["state"] for item in results)
    summary = {"construction_qualified_task_count": 2, "machine_semantic_accepted_task_count": 2, "semantic_rejected_task_count": 0, "cwe_count": 2, "repeat_count": 3, "partition_count": 2, "subject_count": 2, "replay_observation_count": len(results), "replay_passed_observation_count": passed, "state_counts": dict(sorted(states.items())), "complete": len(results) == 24 and passed == 24, "formal_results_use": False}
    write_json(OUTPUT / "summary.json", summary)
    if not summary["complete"]:
        raise RuntimeError(f"Post-semantic replay mismatch: {summary}")
    TASKS.parent.mkdir(parents=True, exist_ok=True)
    write_json(TASKS, {"schema_version": 1, "oracle_set_id": "codeguardplus-reserve-breadth-wave4-semantic-machine-v1", "machine_semantic_review_complete": True, "independent_human_review_complete": False, "model_preflight_complete": False, "formal_experiment_ready": False, "tasks": TASK_IDS, "cwes": [oracle[task]["cwe"] for task in TASK_IDS], "remaining_gates": ["independent second-researcher semantic review (G7)", "fresh-seed multi-model G8 preflight", "final prompt/oracle/budget freeze"]})
    VISIBLE.parent.mkdir(parents=True, exist_ok=True)
    write_json(VISIBLE, projection(oracle, "visible")); write_json(HIDDEN, projection(oracle, "hidden"))
    write_json(OUTPUT / "run_manifest.json", {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(), "study_phase": "codeguardplus_reserve_breadth_wave4_machine_semantic_replay", "development_only": True, "formal_results_use": False, "python_environment": info, "candidate_imported_in_parent": False, "ephemeral_workspace_per_test_method": True, "network_unshared_and_socket_denied": True, "results": file_record(OUTPUT / "replay_results.jsonl")})
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(["# CodeGuard+ reserve breadth-wave4 machine-semantic freeze v1", "", "CWE-327 was unanimously accepted by the initial panel. CWE-117 was accepted by a blinded Qwen3-32B tie-break, producing a 2/3 machine majority.", "", f"All {passed}/{len(results)} post-review observations matched expected safe F+S+ and mutant F+S- states.", "", "This remains machine-assisted evidence, not independent human G7. Fresh-seed G8 and final freeze are pending.", ""]), encoding="utf-8")
    write_json(FREEZE, {"schema_version": 1, "freeze_id": "codeguardplus-reserve-breadth-wave4-semantic-machine-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "machine_semantic_review_complete_human_g7_and_g8_pending", "development_only": True, "formal_results_use": False, "formal_experiment_ready": False, "machine_semantic_review_complete": True, "independent_human_review_complete": False, "model_preflight_complete": False, "qualified_task_ids": TASK_IDS, "semantic_adjudication": {"cwe-327/0-py": {"policy": "initial_panel_unanimous_accept"}, DISPUTED: {"policy": "blinded_third_reviewer_majority_accept", "initial_verdicts": panel["task_audit"][DISPUTED]["reviewer_verdicts"], "tiebreak_model": "qwen3-32b", "tiebreak_verdict": "accept"}}, "summary": summary, "inputs": {"source_partition_freeze": file_record(SOURCE_FREEZE), "source_oracle_manifest": file_record(SOURCE_ORACLE), "initial_semantic_panel": file_record(PANEL), "semantic_dispute_freeze": file_record(DISPUTE_FREEZE), "semantic_dispute_packet_manifest": file_record(DISPUTE_PACKETS), "tiebreak_review": file_record(TIEBREAK)}, "outputs": {"qualified_tasks": file_record(TASKS), "visible_projection": file_record(VISIBLE), "hidden_projection": file_record(HIDDEN), "replay_results": file_record(OUTPUT / "replay_results.jsonl"), "run_manifest": file_record(OUTPUT / "run_manifest.json"), "report": file_record(REPORT)}, "formal_readiness_blockers": ["independent second-researcher semantic review (G7)", "fresh-seed multi-model G8 preflight", "final prompt/oracle/budget freeze"]})
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
