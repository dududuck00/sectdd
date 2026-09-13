#!/usr/bin/env python3
"""Evaluate CodeGuard+ qualification subjects with frozen functional/CodeQL oracles."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from .codeguardplus_bwrap import (
        DEFAULT_CODEQL_ROOT,
        DEFAULT_PYTHON,
        ROOT,
        checked_project_path,
        codeql_metadata,
        codeql_paths,
        file_record,
        git_output,
        python_metadata,
        run_codeql,
        run_functional,
        sha256_file,
        utc_now,
        verified_record,
        write_json,
    )
else:
    from codeguardplus_bwrap import (
        DEFAULT_CODEQL_ROOT,
        DEFAULT_PYTHON,
        ROOT,
        checked_project_path,
        codeql_metadata,
        codeql_paths,
        file_record,
        git_output,
        python_metadata,
        run_codeql,
        run_functional,
        sha256_file,
        utc_now,
        verified_record,
        write_json,
    )


DEFAULT_PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
DEFAULT_MANIFEST = ROOT / "benchmarks/manifests/codeguardplus-v1.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--generation-run", type=Path)
    parser.add_argument("--safe-selection", type=Path)
    parser.add_argument("--mutant-run", type=Path)
    parser.add_argument("--mutant-selection", type=Path)
    parser.add_argument("--include-benchmark-probes", action="store_true")
    parser.add_argument(
        "--selection-state", choices=("primary", "reserve"), default="primary"
    )
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--codeql-root", type=Path, default=DEFAULT_CODEQL_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--functional-timeout", type=float, default=30.0)
    parser.add_argument("--codeql-timeout", type=float, default=300.0)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_inputs(
    plan_path: Path,
    manifest_path: Path,
    requested: list[str] | None,
    selection_state: str = "primary",
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    plan_path = checked_project_path(plan_path)
    manifest_path = checked_project_path(manifest_path)
    plan = load_json(plan_path)
    manifest = load_json(manifest_path)
    if sha256_file(manifest_path) != plan["inputs"]["benchmark_manifest"]["sha256"]:
        raise RuntimeError("Plan and benchmark manifest hashes differ")
    repo = checked_project_path(ROOT / manifest["repository"]["path"])
    if git_output(repo, "rev-parse", "HEAD") != plan["inputs"]["repository_commit"]:
        raise RuntimeError("CodeGuard+ repository commit drift")
    if git_output(repo, "status", "--porcelain"):
        raise RuntimeError("CodeGuard+ repository is dirty")
    pool = {
        item["task_id"]: item
        for item in plan["tasks"]
        if item["selection_state"] == selection_state
    }
    manifest_tasks = {item["task_id"]: item for item in manifest["tasks"]}
    selected_ids = requested or plan[f"{selection_state}_task_ids"]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("Duplicate task selection")
    unknown = sorted(set(selected_ids) - set(pool))
    if unknown:
        raise ValueError(
            f"Tasks are absent from frozen {selection_state} pool: {unknown}"
        )
    result = []
    for task_id in selected_ids:
        task = manifest_tasks[task_id]
        plan_task = pool[task_id]
        for record in (
            task["source"]["file_context"],
            task["source"]["function_context"],
            task["source"]["info"],
            task["tests"]["functional"]["entrypoint"],
            *task["tests"]["functional"]["support_files"],
        ):
            verified_record(record)
        result.append({"benchmark": task, "plan": plan_task})
    return plan, manifest, result


def generation_subjects(
    run: Path, plan_path: Path, selected_ids: set[str]
) -> list[dict[str, Any]]:
    run = checked_project_path(run)
    manifest_path = run / "run_manifest.json"
    candidates_path = run / "candidates.jsonl"
    if not manifest_path.is_file() or not candidates_path.is_file():
        raise FileNotFoundError("Generation run is incomplete")
    run_manifest = load_json(manifest_path)
    if run_manifest["input_files"]["qualification_plan"]["sha256"] != sha256_file(plan_path):
        raise RuntimeError("Generation run used a different qualification plan")
    if run_manifest.get("tests_exposed_to_model") is not False or run_manifest.get("security_query_exposed_to_model") is not False:
        raise RuntimeError("Generation run is not test/query blind")
    subjects = []
    for item in load_jsonl(candidates_path):
        if item["task_id"] not in selected_ids or item["status"] != "success":
            continue
        candidate = verified_record(item["candidate"])
        subjects.append(
            {
                "task_id": item["task_id"],
                "subject_type": "generated_secure_candidate",
                "subject_id": f"candidate_{item['candidate_index']:03d}",
                "candidate_index": item["candidate_index"],
                "source_run": file_record(manifest_path),
                "file": file_record(candidate),
            }
        )
    return subjects


def mutant_subjects(run: Path, plan_path: Path, selected_ids: set[str]) -> list[dict[str, Any]]:
    run = checked_project_path(run)
    manifest_path = run / "run_manifest.json"
    mutants_path = run / "mutants.jsonl"
    if not manifest_path.is_file() or not mutants_path.is_file():
        raise FileNotFoundError("Mutant run is incomplete")
    run_manifest = load_json(manifest_path)
    if run_manifest["input_files"]["qualification_plan"]["sha256"] != sha256_file(plan_path):
        raise RuntimeError("Mutant run used a different qualification plan")
    if (
        run_manifest.get("tests_exposed_to_model") is not False
        or run_manifest.get("security_query_exposed_to_model") is not False
        or run_manifest.get("benchmark_probe_exposed_to_model") is not False
    ):
        raise RuntimeError("Mutant run is not test/query/probe blind")
    subjects = []
    for item in load_jsonl(mutants_path):
        if item["task_id"] not in selected_ids or item["status"] != "success":
            continue
        mutant = verified_record(item["mutant"])
        subjects.append(
            {
                "task_id": item["task_id"],
                "subject_type": "targeted_vulnerability_mutant",
                "subject_id": f"mutant_{item['mutant_index']:03d}",
                "mutant_index": item["mutant_index"],
                "source_run": file_record(manifest_path),
                "file": file_record(mutant),
            }
        )
    return subjects


def mutant_selection_subjects(
    selection_path: Path, plan_path: Path, selected_ids: set[str]
) -> list[dict[str, Any]]:
    selection_path = checked_project_path(selection_path)
    selection = load_json(selection_path)
    if selection["inputs"]["qualification_plan"]["sha256"] != sha256_file(plan_path):
        raise RuntimeError("Mutant selection used a different qualification plan")
    subjects = []
    for item in selection["selected"]:
        if item["task_id"] not in selected_ids:
            continue
        mutant = verified_record(item["mutant"])
        subjects.append(
            {
                "task_id": item["task_id"],
                "subject_type": "selected_vulnerability_mutant",
                "subject_id": f"selected_mutant_{item['mutant_index']:03d}",
                "mutant_index": item["mutant_index"],
                "source_run": file_record(selection_path),
                "file": file_record(mutant),
            }
        )
    return subjects


def safe_selection_subjects(
    selection_path: Path, plan_path: Path, selected_ids: set[str]
) -> list[dict[str, Any]]:
    selection_path = checked_project_path(selection_path)
    selection = load_json(selection_path)
    if selection["inputs"]["qualification_plan"]["sha256"] != sha256_file(plan_path):
        raise RuntimeError("Safe selection used a different qualification plan")
    subjects = []
    for item in selection["selected"]:
        if item["task_id"] not in selected_ids:
            continue
        candidate = verified_record(item["candidate"])
        subjects.append(
            {
                "task_id": item["task_id"],
                "subject_type": "selected_safe_reference",
                "subject_id": f"selected_candidate_{item['candidate_index']:03d}",
                "candidate_index": item["candidate_index"],
                "source_run": file_record(selection_path),
                "file": file_record(candidate),
            }
        )
    return subjects


def collect_subjects(
    args: argparse.Namespace,
    plan_path: Path,
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_ids = {item["benchmark"]["task_id"] for item in selected}
    subjects = []
    if args.include_benchmark_probes:
        for item in selected:
            task_id = item["benchmark"]["task_id"]
            for index, value in enumerate(item["plan"]["benchmark_probe_candidates"]):
                probe = verified_record(value)
                subjects.append(
                    {
                        "task_id": task_id,
                        "subject_type": "benchmark_probe",
                        "subject_id": f"benchmark_probe_{index:03d}",
                        "probe_index": index,
                        "file": file_record(probe),
                    }
                )
    if args.generation_run:
        subjects.extend(generation_subjects(args.generation_run, plan_path, selected_ids))
    if args.safe_selection:
        subjects.extend(safe_selection_subjects(args.safe_selection, plan_path, selected_ids))
    if args.mutant_run:
        subjects.extend(mutant_subjects(args.mutant_run, plan_path, selected_ids))
    if args.mutant_selection:
        subjects.extend(mutant_selection_subjects(args.mutant_selection, plan_path, selected_ids))
    if not subjects:
        raise ValueError("No subjects selected")
    subjects.sort(key=lambda item: (item["task_id"], item["subject_type"], item["subject_id"]))
    duplicates = Counter((item["task_id"], item["subject_type"], item["subject_id"]) for item in subjects)
    if any(count > 1 for count in duplicates.values()):
        raise RuntimeError("Duplicate qualification subject")
    return subjects


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    states: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    types: dict[str, Counter[str]] = {}
    for item in results:
        functional = item["functional"]["passed"]
        security = item["security"]["passed"]
        state = (
            "infrastructure_or_oracle_error"
            if functional is None or security is None
            else f"F{'+' if functional else '-'}S{'+' if security else '-'}"
        )
        states[state] += 1
        statuses[item["status"]] += 1
        types.setdefault(item["subject_type"], Counter())[state] += 1
    return {
        "result_count": len(results),
        "task_count": len({item["task_id"] for item in results}),
        "state_counts": dict(sorted(states.items())),
        "state_counts_by_subject_type": {key: dict(sorted(value.items())) for key, value in sorted(types.items())},
        "status_counts": dict(sorted(statuses.items())),
        "complete": bool(results) and not statuses.get("infrastructure_error"),
        "formal_results_use": False,
    }


def main() -> None:
    args = parse_args()
    if args.repeats < 1 or args.repeats > 3:
        raise ValueError("--repeats must be in [1, 3]")
    if args.num_workers < 1 or args.num_workers > 8:
        raise ValueError("--num-workers must be in [1, 8]")
    plan_path = checked_project_path(args.plan)
    manifest_path = checked_project_path(args.benchmark_manifest)
    plan, _, selected = validate_inputs(
        plan_path, manifest_path, args.tasks, args.selection_state
    )
    python = args.python.expanduser().absolute()
    py_info = python_metadata(python)
    paths = codeql_paths(args.codeql_root, "2.17.5")
    cq_info = codeql_metadata(paths, "2.17.5")
    subjects = collect_subjects(args, plan_path, selected)
    output = checked_project_path(args.output, exists=False)
    manifest_payload = {
            "schema_version": 1,
            "created_at_utc": utc_now(),
            "study_phase": "codeguardplus_oracle_qualification_development",
            "development_only": True,
            "formal_results_use": False,
            "qualification_plan": file_record(plan_path),
            "benchmark_manifest": file_record(manifest_path),
            "repository_commit": plan["inputs"]["repository_commit"],
            "selection_state": args.selection_state,
            "task_ids": [item["benchmark"]["task_id"] for item in selected],
            "subject_count": len(subjects),
            "subjects": subjects,
            "repeats": args.repeats,
            "num_workers": args.num_workers,
            "python_environment": py_info,
            "codeql_environment": cq_info,
            "candidate_imported_in_parent": False,
            "ephemeral_workspace_per_oracle": True,
            "network_unshared_and_socket_denied": True,
        }
    if args.resume:
        if not output.is_dir():
            raise FileNotFoundError(output)
        observed_manifest = load_json(output / "run_manifest.json")
        for field in (
            "qualification_plan",
            "benchmark_manifest",
            "repository_commit",
            "selection_state",
            "task_ids",
            "subjects",
            "repeats",
            "python_environment",
            "codeql_environment",
        ):
            if observed_manifest.get(field) != manifest_payload[field]:
                raise RuntimeError(f"Resume configuration mismatch: {field}")
    else:
        if output.exists():
            raise FileExistsError(output)
        output.mkdir(parents=True)
        write_json(output / "run_manifest.json", manifest_payload)
    logs = output / "logs"
    logs.mkdir(exist_ok=True)
    tasks = {item["benchmark"]["task_id"]: item["benchmark"] for item in selected}
    total = len(subjects) * args.repeats
    results_path = output / "results.jsonl"
    results: list[dict[str, Any]] = load_jsonl(results_path) if args.resume and results_path.is_file() else []
    valid_keys = {
        (subject["task_id"], subject["subject_type"], subject["subject_id"], repeat)
        for subject in subjects
        for repeat in range(1, args.repeats + 1)
    }
    results = [item for item in results if item["status"] == "completed"]
    result_keys = [
        (item["task_id"], item["subject_type"], item["subject_id"], item["repeat"])
        for item in results
    ]
    if len(result_keys) != len(set(result_keys)) or set(result_keys) - valid_keys:
        raise RuntimeError("Resume results contain duplicate or unexpected observations")
    if args.resume:
        with results_path.open("w", encoding="utf-8") as stream:
            for item in results:
                stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    def evaluate(subject: dict[str, Any], repeat: int) -> dict[str, Any]:
        task = tasks[subject["task_id"]]
        candidate = verified_record(subject["file"])
        slug = re.sub(r"[^A-Za-z0-9_.-]", "_", subject["task_id"])
        result_root = logs / slug / subject["subject_type"] / subject["subject_id"] / f"repeat-{repeat}"
        result_root.mkdir(parents=True, exist_ok=True)
        functional = run_functional(task, candidate, python, py_info, result_root / "functional.log", args.functional_timeout)
        security = run_codeql(task, candidate, paths, result_root, args.codeql_timeout)
        status = "completed" if functional["passed"] is not None and security["passed"] is not None else "infrastructure_error"
        return {
            "task_id": subject["task_id"],
            "cwe": task["cwe"],
            "subject_type": subject["subject_type"],
            "subject_id": subject["subject_id"],
            "repeat": repeat,
            "status": status,
            "candidate": file_record(candidate),
            "functional": functional,
            "security": security,
            "joint_pass": functional["passed"] and security["passed"] if status == "completed" else None,
        }

    completed_keys = set(result_keys)
    jobs = [
        (subject, repeat)
        for subject in subjects
        for repeat in range(1, args.repeats + 1)
        if (subject["task_id"], subject["subject_type"], subject["subject_id"], repeat)
        not in completed_keys
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = {pool.submit(evaluate, subject, repeat): (subject, repeat) for subject, repeat in jobs}
        for future in concurrent.futures.as_completed(futures):
            subject, repeat = futures[future]
            try:
                item = future.result()
            except Exception as error:
                task = tasks[subject["task_id"]]
                candidate = verified_record(subject["file"])
                failure = {
                    "passed": None,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                item = {
                    "task_id": subject["task_id"],
                    "cwe": task["cwe"],
                    "subject_type": subject["subject_type"],
                    "subject_id": subject["subject_id"],
                    "repeat": repeat,
                    "status": "infrastructure_error",
                    "candidate": file_record(candidate),
                    "functional": {**failure, "stage": "worker_exception"},
                    "security": {**failure, "stage": "worker_exception"},
                    "joint_pass": None,
                    "worker_traceback": "".join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    ),
                }
            results.append(item)
            with results_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            print(
                f"[{len(results)}/{total}] {item['task_id']} {item['subject_id']} "
                f"repeat={item['repeat']} F={item['functional']['passed']} "
                f"S={item['security']['passed']}",
                flush=True,
            )
    results.sort(key=lambda item: (item["task_id"], item["subject_type"], item["subject_id"], item["repeat"]))
    with results_path.open("w", encoding="utf-8") as stream:
        for item in results:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    summary = summarize(results)
    summary["expected_result_count"] = total
    summary["complete"] = summary["complete"] and len(results) == total
    summary["updated_at_utc"] = utc_now()
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
