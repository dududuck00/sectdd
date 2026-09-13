#!/usr/bin/env python3
"""Verify the frozen SALLM expansion wave-2 candidate-generation bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "configs/benchmarks/sallm_expansion_candidates_v2.json",
    )
    parser.add_argument(
        "--wave1-plan",
        type=Path,
        default=ROOT / "configs/benchmarks/sallm_expansion_candidates_v1.json",
    )
    parser.add_argument(
        "--merged-run",
        type=Path,
        default=ROOT
        / "artifacts/sallm-secure-reference/deepseek-v4-flash-expansion-v2-merged",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/sallm-expansion-wave2-generation-audit.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_recorded_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def record(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any) -> None:
    checks.append({"check": name, "passed": passed, "detail": detail})


def main() -> None:
    args = parse_args()
    plan = load_json(args.plan.resolve())
    wave1 = load_json(args.wave1_plan.resolve())
    merged = args.merged_run.resolve()
    manifest = load_json(merged / "run_manifest.json")
    summary = load_json(merged / "summary.json")
    rows = load_jsonl(merged / "candidate_index.jsonl")
    checks: list[dict[str, Any]] = []

    tasks = plan["tasks"]
    task_set = set(tasks)
    selected_records = {item["task_id"]: item for item in plan["selected_candidates"]}
    wave1_tasks = set(wave1["tasks"])
    slots = {(row["task_id"], row["candidate_index"]) for row in rows}
    expected_slots = {(task_id, index) for task_id in tasks for index in range(3)}

    record(checks, "wave2_task_count", len(tasks) == 24, len(tasks))
    record(checks, "wave2_task_ids_unique", len(task_set) == len(tasks), len(task_set))
    record(
        checks,
        "plan_records_match_tasks",
        set(selected_records) == task_set,
        len(selected_records),
    )
    record(
        checks,
        "wave1_wave2_disjoint",
        not (task_set & wave1_tasks),
        sorted(task_set & wave1_tasks),
    )
    record(
        checks,
        "merged_selection_matches_plan",
        manifest.get("selection") == tasks,
        len(manifest.get("selection", [])),
    )
    record(checks, "all_72_slots_present", slots == expected_slots, len(slots))
    record(
        checks,
        "all_rows_successful",
        len(rows) == 72 and all(row.get("status") == "success" for row in rows),
        len(rows),
    )
    expected_summary = {
        "task_count": 24,
        "expected_candidate_count": 72,
        "successful_candidate_count": 72,
        "missing_candidate_count": 0,
        "complete": True,
    }
    record(
        checks,
        "merged_summary_complete",
        all(summary.get(key) == value for key, value in expected_summary.items()),
        summary,
    )

    bad_candidate_hashes: list[str] = []
    bad_metadata: list[str] = []
    bad_prompts: list[str] = []
    source_runs: set[Path] = set()
    for row in rows:
        slot_label = f"{row['task_id']}#{row['candidate_index']}"
        candidate = resolve_recorded_path(row["candidate_path"])
        if not candidate.is_file() or sha256_file(candidate) != row["candidate_sha256"]:
            bad_candidate_hashes.append(slot_label)

        metadata_path = resolve_recorded_path(row["source_metadata"])
        if not metadata_path.is_file():
            bad_metadata.append(slot_label)
        else:
            metadata = load_json(metadata_path)
            if not (
                metadata.get("status") == "success"
                and metadata.get("task_id") == row["task_id"]
                and metadata.get("candidate_index") == row["candidate_index"]
                and metadata.get("candidate_sha256") == row["candidate_sha256"]
            ):
                bad_metadata.append(slot_label)

        source_run = resolve_recorded_path(row["source_run"])
        source_runs.add(source_run)
        prompt_path = source_run / "tasks" / Path(row["task_id"]).stem / "prompt.json"
        if not prompt_path.is_file():
            bad_prompts.append(slot_label + ":missing")
            continue
        prompt = load_json(prompt_path)
        context = prompt.get("context", {})
        serialized = json.dumps(prompt, ensure_ascii=False)
        test_path = resolve_recorded_path(
            selected_records[row["task_id"]]["tests"]["entrypoint"]["path"]
        )
        test_source = test_path.read_text(encoding="utf-8")
        context_test_keys = [key for key in context if "test" in key.lower()]
        if (
            prompt.get("tests_included") is not False
            or context_test_keys
            or str(test_path.relative_to(ROOT)) in serialized
            or test_path.name in serialized
            or test_source in serialized
            or "sallm_partitioned_oracle" in serialized
        ):
            bad_prompts.append(slot_label)

    record(checks, "candidate_hashes_match", not bad_candidate_hashes, bad_candidate_hashes)
    record(checks, "source_metadata_match", not bad_metadata, bad_metadata)
    record(checks, "prompts_exclude_tests_and_oracles", not bad_prompts, bad_prompts)

    bad_source_manifests: list[str] = []
    for source_run in sorted(source_runs):
        source_manifest_path = source_run / "run_manifest.json"
        if not source_manifest_path.is_file():
            bad_source_manifests.append(str(source_run) + ":missing")
            continue
        source_manifest = load_json(source_manifest_path)
        if (
            source_manifest.get("api_key_persisted") is not False
            or source_manifest.get("hidden_tests_exposed_to_model") is not False
            or source_manifest.get("provider") != "deepseek"
            or source_manifest.get("model") != "deepseek-v4-flash"
        ):
            bad_source_manifests.append(str(source_run))
            continue
        for input_record in source_manifest.get("input_files", {}).values():
            input_path = resolve_recorded_path(input_record["path"])
            if not input_path.is_file() or sha256_file(input_path) != input_record["sha256"]:
                bad_source_manifests.append(str(source_run) + ":input-hash")
                break
    record(
        checks,
        "source_manifests_and_input_hashes_valid",
        not bad_source_manifests,
        bad_source_manifests,
    )

    unique_count = sum(row.get("duplicate_of_candidate_index") is None for row in rows)
    duplicate_count = len(rows) - unique_count
    record(
        checks,
        "dedup_counts_match",
        summary.get("unique_candidate_count") == unique_count
        and summary.get("duplicate_candidate_count") == duplicate_count,
        {"unique": unique_count, "duplicate": duplicate_count},
    )

    passed = all(item["passed"] for item in checks)
    report = {
        "schema_version": 1,
        "audit": "sallm_expansion_wave2_candidate_generation",
        "passed": passed,
        "formal_experiment_ready": False,
        "formal_readiness_blocker": (
            "Candidates have not yet passed original-oracle qualification, repeated "
            "sandbox audits, visible/hidden partitioning, semantic review, or preflight."
        ),
        "summary": {
            "task_count": len(tasks),
            "cwe_count": len({item["cwe"] for item in selected_records.values()}),
            "candidate_slot_count": len(rows),
            "unique_candidate_count": unique_count,
            "duplicate_candidate_count": duplicate_count,
            "source_run_count": len(source_runs),
        },
        "checks": checks,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
