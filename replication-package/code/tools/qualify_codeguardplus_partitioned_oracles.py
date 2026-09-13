#!/usr/bin/env python3
"""Qualify and freeze CodeGuard+ visible/hidden behavior-family oracle candidates."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .codeguardplus_bwrap import (
        DEFAULT_PYTHON,
        ROOT,
        checked_project_path,
        file_record,
        python_metadata,
        sha256_file,
        utc_now,
        verified_record,
        write_json,
    )
    from .codeguardplus_partition_bwrap import run_method
else:
    from codeguardplus_bwrap import (
        DEFAULT_PYTHON,
        ROOT,
        checked_project_path,
        file_record,
        python_metadata,
        sha256_file,
        utc_now,
        verified_record,
        write_json,
    )
    from codeguardplus_partition_bwrap import run_method


GENERATION = ROOT / "artifacts/codeguardplus-partitioned-generation/qwen36-27b-pairs-v3"
PAIRS = ROOT / "benchmarks/manifests/codeguardplus-oracle-pairs-v1.json"
OUTPUT = ROOT / "artifacts/codeguardplus-partitioned-qualification/v1"
ORACLE_ROOT = ROOT / "oracles/codeguardplus_partitioned_v1"
VISIBLE = ROOT / "configs/oracles/codeguardplus_partitioned_v1_visible.json"
HIDDEN = ROOT / "configs/oracles/codeguardplus_partitioned_v1_hidden.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-partitioned-v1-freeze.json"
REPORT = ROOT / "docs/codeguardplus-partitioned-v1.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-run", type=Path, default=GENERATION)
    parser.add_argument("--pairs", type=Path, default=PAIRS)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--oracle-root", type=Path, default=ORACLE_ROOT)
    parser.add_argument("--visible-projection", type=Path, default=VISIBLE)
    parser.add_argument("--hidden-projection", type=Path, default=HIDDEN)
    parser.add_argument("--freeze", type=Path, default=FREEZE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--oracle-set-id", default="codeguardplus-partitioned-v1")
    parser.add_argument("--freeze-id", default="codeguardplus-partitioned-v1")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--num-workers", type=int, default=8)
    return parser.parse_args()


def project(path: Path, *, exists: bool = True) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def slug(task_id: str) -> str:
    return task_id.replace("/", "__")


def state(functional: bool | None, security: bool | None) -> str:
    if functional is None or security is None:
        return "infrastructure_or_oracle_error"
    return f"F{'+' if functional else '-'}S{'+' if security else '-'}"


def evaluate(
    *,
    task_id: str,
    subject: str,
    candidate: Path,
    partition: str,
    test: Path,
    python: Path,
    python_info: dict[str, Any],
    log_root: Path,
    timeout: float,
    repeat: int | None = None,
) -> dict[str, Any]:
    root = log_root / slug(task_id) / partition / subject
    if repeat is not None:
        root /= f"repeat-{repeat}"
    root.mkdir(parents=True, exist_ok=True)
    functional = run_method(candidate=candidate, test=test, method="test_correctness", python=python, python_info=python_info, log=root / "functional.log", timeout_seconds=timeout)
    security = run_method(candidate=candidate, test=test, method="test_vulnerability", python=python, python_info=python_info, log=root / "security.log", timeout_seconds=timeout)
    observed = state(functional["passed"], security["passed"])
    expected = "F+S+" if subject == "safe_reference" else "F+S-"
    return {
        "task_id": task_id,
        "partition": partition,
        "subject": subject,
        "repeat": repeat,
        "state": observed,
        "expected_state": expected,
        "passed_gate": observed == expected,
        "functional": functional,
        "security": security,
    }


def main() -> None:
    args = parse_args()
    if not args.oracle_set_id or not args.freeze_id:
        raise ValueError("Oracle/freeze identifiers must be non-empty")
    if args.repeats != 3 or args.num_workers < 1 or args.num_workers > 16:
        raise ValueError("Qualification requires three repeats and 1-16 workers")
    generation = project(args.generation_run)
    pair_path = project(args.pairs)
    output = project(args.output, exists=False)
    oracle_root = project(args.oracle_root, exists=False)
    visible_path = project(args.visible_projection, exists=False)
    hidden_path = project(args.hidden_projection, exists=False)
    freeze_path = project(args.freeze, exists=False)
    report_path = project(args.report, exists=False)
    for path in (output, oracle_root, visible_path, hidden_path, freeze_path, report_path):
        if path.exists():
            raise FileExistsError(path)

    generation_manifest = load_json(generation / "run_manifest.json")
    generation_summary = load_json(generation / "summary.json")
    candidates = load_jsonl(generation / "oracles.jsonl")
    pairs = load_json(pair_path)
    if generation_manifest["input_files"]["oracle_pairs"]["sha256"] != sha256_file(pair_path):
        raise RuntimeError("Generation used different oracle pairs")
    if not generation_summary["complete"]:
        raise RuntimeError("Oracle generation grid is incomplete")
    if (
        generation_manifest.get("benchmark_tests_exposed_to_model") is not False
        or generation_manifest.get("codeql_query_exposed_to_model") is not False
        or generation_manifest.get("benchmark_probe_exposed_to_model") is not False
    ):
        raise RuntimeError("Oracle generation was not benchmark-oracle blind")
    pair_by_id = {item["task_id"]: item for item in pairs["tasks"]}
    successful = [item for item in candidates if item["status"] == "success"]
    for item in successful:
        pair = pair_by_id[item["task_id"]]
        if item["safe_reference"]["sha256"] != pair["safe_reference"]["sha256"]:
            raise RuntimeError(f"Safe-reference drift in generation: {item['task_id']}")
        if item["vulnerability_mutant"]["sha256"] != pair["vulnerability_mutant"]["sha256"]:
            raise RuntimeError(f"Mutant drift in generation: {item['task_id']}")
        for partition in ("visible", "hidden"):
            verified_record(item[f"{partition}_test"])

    output.mkdir(parents=True)
    python = args.python.expanduser().absolute()
    py_info = python_metadata(python)
    write_json(
        output / "run_manifest.json",
        {
            "schema_version": 1,
            "created_at_utc": utc_now(),
            "study_phase": "codeguardplus_partitioned_oracle_construction",
            "development_only": True,
            "formal_results_use": False,
            "generation_manifest": file_record(generation / "run_manifest.json"),
            "generation_candidates": file_record(generation / "oracles.jsonl"),
            "oracle_pairs": file_record(pair_path),
            "python_environment": py_info,
            "candidate_imported_in_parent": False,
            "ephemeral_workspace_per_test_method": True,
            "network_unshared_and_socket_denied": True,
        },
    )

    audit_jobs = []
    for item in successful:
        pair = pair_by_id[item["task_id"]]
        subjects = {
            "safe_reference": verified_record(pair["safe_reference"]),
            "vulnerability_mutant": verified_record(pair["vulnerability_mutant"]),
        }
        for partition in ("visible", "hidden"):
            test = verified_record(item[f"{partition}_test"])
            for subject, candidate in subjects.items():
                audit_jobs.append((item, partition, subject, candidate, test))
    audit_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = {
            pool.submit(
                evaluate,
                task_id=item["task_id"],
                subject=subject,
                candidate=candidate,
                partition=partition,
                test=test,
                python=python,
                python_info=py_info,
                log_root=output / "candidate-audit" / f"attempt-{item['attempt_index']:03d}",
                timeout=args.timeout_seconds,
            ): (item, partition, subject)
            for item, partition, subject, candidate, test in audit_jobs
        }
        for future in concurrent.futures.as_completed(futures):
            item, partition, subject = futures[future]
            result = future.result()
            result["attempt_index"] = item["attempt_index"]
            audit_results.append(result)
            print(f"[audit {len(audit_results)}/{len(audit_jobs)}] {item['task_id']} a={item['attempt_index']} {partition} {subject} {result['state']}", flush=True)
    audit_results.sort(key=lambda item: (item["task_id"], item["attempt_index"], item["partition"], item["subject"]))
    with (output / "candidate_audit.jsonl").open("w", encoding="utf-8") as stream:
        for item in audit_results:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    audit_by_attempt: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in audit_results:
        audit_by_attempt.setdefault((item["task_id"], item["attempt_index"]), []).append(item)
    metadata_by_attempt = {(item["task_id"], item["attempt_index"]): item for item in successful}
    selected: dict[str, dict[str, Any]] = {}
    for task_id in pairs["qualified_task_ids"]:
        for index in sorted(key[1] for key in audit_by_attempt if key[0] == task_id):
            observations = audit_by_attempt[(task_id, index)]
            if len(observations) == 4 and all(item["passed_gate"] for item in observations):
                selected[task_id] = metadata_by_attempt[(task_id, index)]
                break

    visible_root = oracle_root / "visible"
    hidden_root = oracle_root / "hidden"
    visible_root.mkdir(parents=True)
    hidden_root.mkdir(parents=True)
    selected_records = {}
    for task_id, item in sorted(selected.items()):
        selected_records[task_id] = {"attempt_index": item["attempt_index"], "families": item["families"], "contract": item["contract"]}
        for partition, root in (("visible", visible_root), ("hidden", hidden_root)):
            source = verified_record(item[f"{partition}_test"])
            destination = root / f"test_{slug(task_id)}.py"
            shutil.copy2(source, destination)
            selected_records[task_id][f"{partition}_test"] = file_record(destination)

    repeat_jobs = []
    for task_id, item in sorted(selected.items()):
        pair = pair_by_id[task_id]
        subjects = {
            "safe_reference": verified_record(pair["safe_reference"]),
            "vulnerability_mutant": verified_record(pair["vulnerability_mutant"]),
        }
        for partition, root in (("visible", visible_root), ("hidden", hidden_root)):
            test = root / f"test_{slug(task_id)}.py"
            for subject, candidate in subjects.items():
                for repeat in range(1, args.repeats + 1):
                    repeat_jobs.append((task_id, partition, subject, candidate, test, repeat))
    repeat_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = {
            pool.submit(
                evaluate,
                task_id=task_id,
                subject=subject,
                candidate=candidate,
                partition=partition,
                test=test,
                python=python,
                python_info=py_info,
                log_root=output / "repeat-audit",
                timeout=args.timeout_seconds,
                repeat=repeat,
            ): (task_id, partition, subject, repeat)
            for task_id, partition, subject, candidate, test, repeat in repeat_jobs
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            repeat_results.append(result)
            print(f"[repeat {len(repeat_results)}/{len(repeat_jobs)}] {result['task_id']} {result['partition']} {result['subject']} r={result['repeat']} {result['state']}", flush=True)
    repeat_results.sort(key=lambda item: (item["task_id"], item["partition"], item["subject"], item["repeat"]))
    with (output / "repeat_results.jsonl").open("w", encoding="utf-8") as stream:
        for item in repeat_results:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    final_ids = []
    for task_id in selected:
        observations = [item for item in repeat_results if item["task_id"] == task_id]
        if len(observations) == 12 and all(item["passed_gate"] for item in observations):
            final_ids.append(task_id)
    rejected = []
    for task_id in pairs["qualified_task_ids"]:
        if task_id in final_ids:
            continue
        reason = "no_generated_candidate" if not any(item["task_id"] == task_id for item in successful) else ("no_candidate_passed_construction_gate" if task_id not in selected else "failed_three_repeat_gate")
        rejected.append({"task_id": task_id, "cwe": pair_by_id[task_id]["cwe"], "reason": reason})

    def projection(partition: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "oracle_set_id": args.oracle_set_id,
            "partition": partition,
            "canonical_freeze": {"path": freeze_path.relative_to(ROOT).as_posix()},
            "tasks": {
                task_id: {
                    "cwe": pair_by_id[task_id]["cwe"],
                    "oracle_file": selected_records[task_id][f"{partition}_test"],
                    "cases": [
                        {"case_id": f"{slug(task_id)}-{partition}-f", "marker": "functional", "unittest_method": "test_correctness", "behavior_family": selected_records[task_id]["families"][partition]["functionality"]},
                        {"case_id": f"{slug(task_id)}-{partition}-s", "marker": "security", "unittest_method": "test_vulnerability", "behavior_family": selected_records[task_id]["families"][partition]["security"]},
                    ],
                }
                for task_id in final_ids
            },
        }

    visible_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(visible_path, projection("visible"))
    write_json(hidden_path, projection("hidden"))
    oracle_manifest = {
        "schema_version": 1,
        "oracle_set_id": args.oracle_set_id,
        "created_at_utc": utc_now(),
        "split_unit": "behavior_family",
        "behavior_family_overlap_allowed": False,
        "tasks": {task_id: {**selected_records[task_id], "cwe": pair_by_id[task_id]["cwe"], "safe_reference": pair_by_id[task_id]["safe_reference"], "vulnerability_mutant": pair_by_id[task_id]["vulnerability_mutant"]} for task_id in final_ids},
    }
    write_json(oracle_root / "manifest.json", oracle_manifest)
    states = Counter(item["state"] for item in repeat_results)
    freeze = {
        "schema_version": 1,
        "freeze_type": "codeguardplus_partitioned_oracle_machine_freeze",
        "freeze_id": args.freeze_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "formal_experiment_ready": False,
        "inputs": {"oracle_pairs": file_record(pair_path), "generation_manifest": file_record(generation / "run_manifest.json"), "generation_candidates": file_record(generation / "oracles.jsonl"), "qualification_manifest": file_record(output / "run_manifest.json")},
        "outputs": {"oracle_manifest": file_record(oracle_root / "manifest.json"), "visible_projection": file_record(visible_path), "hidden_projection": file_record(hidden_path), "candidate_audit": file_record(output / "candidate_audit.jsonl"), "repeat_results": file_record(output / "repeat_results.jsonl")},
        "counts": {"input_tasks": len(pairs["qualified_task_ids"]), "generated_successful_candidates": len(successful), "construction_gate_tasks": len(selected), "repeat_qualified_tasks": len(final_ids), "rejected_tasks": len(rejected), "repeat_observations": len(repeat_results), "repeat_state_counts": dict(sorted(states.items()))},
        "qualified_task_ids": final_ids,
        "rejected": rejected,
        "remaining_gates": ["independent semantic review", "fresh-seed multi-model G8 preflight", "final prompt/oracle/budget freeze"],
    }
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(freeze_path, freeze)
    summary = {**freeze["counts"], "complete": True, "formal_results_use": False, "updated_at_utc": utc_now()}
    write_json(output / "summary.json", summary)

    lines = [
        f"# CodeGuard+ visible/hidden 行为族：{args.oracle_set_id}",
        "",
        f"候选测试由 {generation_manifest['provider']}/{generation_manifest['model']} 在不读取 benchmark tests、CodeQL 查询或 probe 的条件下生成。",
        "每个候选必须让 safe 在 visible/hidden 都为 F+S+，让 mutant 都为 F+S-；入选后再独立复验三次。",
        "",
        f"- 输入 machine-qualified pairs：{len(pairs['qualified_task_ids'])}",
        f"- 结构有效候选：{len(successful)}",
        f"- 通过构建 gate：{len(selected)}",
        f"- 三次复验资格化：{len(final_ids)}",
        f"- repeat observations：{len(repeat_results)}，状态 {dict(sorted(states.items()))}",
        "",
        "| Task | CWE | selected attempt | result |",
        "|---|---|---:|---|",
    ]
    for task_id in pairs["qualified_task_ids"]:
        attempt = selected_records.get(task_id, {}).get("attempt_index", "-")
        result = "qualified" if task_id in final_ids else next(item["reason"] for item in rejected if item["task_id"] == task_id)
        lines.append(f"| {task_id} | {pair_by_id[task_id]['cwe']} | {attempt} | {result} |")
    lines.extend(["", "该冻结仍是 development-only。独立语义审查和全新 seed 多模型 G8 之前，不得用于正式方法效果比较。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
