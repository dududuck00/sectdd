#!/usr/bin/env python3
"""Merge CodeGuard+ mutant runs with primary-success precedence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project(path: Path, *, exists: bool = True) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def record(path: Path) -> dict[str, Any]:
    path = project(path)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_records(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    run = project(run)
    manifest = load_json(run / "run_manifest.json")
    rows = load_jsonl(run / "mutants.jsonl")
    summary = load_json(run / "summary.json")
    for row in rows:
        if row["status"] == "success":
            mutant = project(ROOT / row["mutant"]["path"])
            if sha256_file(mutant) != row["mutant"]["sha256"]:
                raise RuntimeError(f"Mutant hash drift: {mutant}")
    return manifest, rows, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--fallback", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary = project(args.primary)
    fallbacks = [project(path) for path in args.fallback]
    output = project(args.output, exists=False)
    if output.exists():
        raise FileExistsError(output)

    primary_manifest, primary_rows, primary_summary = run_records(primary)
    plan_hash = primary_manifest["input_files"]["qualification_plan"]["sha256"]
    benchmark_hash = primary_manifest["input_files"]["benchmark_manifest"]["sha256"]
    safe_hash = primary_manifest["input_files"]["safe_selection"]["sha256"]
    task_ids = primary_manifest["selection"]
    slots = {
        (task_id, index)
        for task_id in task_ids
        for index in range(primary_manifest["mutants_per_task"])
    }
    by_key: dict[tuple[str, int], list[tuple[str, dict[str, Any]]]] = {}
    for row in primary_rows:
        by_key.setdefault((row["task_id"], row["mutant_index"]), []).append(("primary", row))

    fallback_inputs = []
    for number, fallback in enumerate(fallbacks, start=1):
        manifest, rows, _ = run_records(fallback)
        inputs = manifest["input_files"]
        if inputs["qualification_plan"]["sha256"] != plan_hash:
            raise RuntimeError("Fallback plan hash differs")
        if inputs["benchmark_manifest"]["sha256"] != benchmark_hash:
            raise RuntimeError("Fallback benchmark hash differs")
        if inputs["safe_selection"]["sha256"] != safe_hash:
            raise RuntimeError("Fallback safe selection hash differs")
        label = f"fallback_{number:02d}"
        for row in rows:
            key = (row["task_id"], row["mutant_index"])
            if key not in slots:
                raise RuntimeError(f"Fallback contains unknown slot: {key}")
            by_key.setdefault(key, []).append((label, row))
        fallback_inputs.append(
            {
                "label": label,
                "run_manifest": record(fallback / "run_manifest.json"),
                "mutants": record(fallback / "mutants.jsonl"),
                "thinking": manifest.get("thinking"),
            }
        )

    merged = []
    unresolved = []
    for key in sorted(slots):
        options = by_key.get(key, [])
        primary_success = [value for value in options if value[0] == "primary" and value[1]["status"] == "success"]
        fallback_success = [value for value in options if value[0] != "primary" and value[1]["status"] == "success"]
        chosen = primary_success[0] if primary_success else (fallback_success[0] if fallback_success else None)
        if chosen is None:
            unresolved.append({"task_id": key[0], "mutant_index": key[1]})
            continue
        source, row = chosen
        primary_status = next(
            (value[1]["status"] for value in options if value[0] == "primary"),
            "missing",
        )
        merged.append({**row, "merge_source": source, "primary_slot_status": primary_status})
    if unresolved:
        raise RuntimeError(f"Unresolved mutant slots: {unresolved}")

    output.mkdir(parents=True)
    with (output / "mutants.jsonl").open("w", encoding="utf-8") as stream:
        for row in merged:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    source_counts = Counter(row["merge_source"] for row in merged)
    hashes = [row["mutant"]["sha256"] for row in merged]
    manifest_out = {
        "schema_version": 1,
        "generator": "tools/merge_codeguardplus_mutant_runs.py",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "selection": task_ids,
        "mutants_per_task": primary_manifest["mutants_per_task"],
        "input_files": primary_manifest["input_files"],
        "tests_exposed_to_model": False,
        "security_query_exposed_to_model": False,
        "benchmark_probe_exposed_to_model": False,
        "merge_policy": "primary_success_else_first_successful_fallback_in_argument_order",
        "primary": {
            "run_manifest": record(primary / "run_manifest.json"),
            "mutants": record(primary / "mutants.jsonl"),
            "summary": record(primary / "summary.json"),
            "success_count_before_merge": primary_summary["success_count"],
        },
        "fallbacks": fallback_inputs,
        "formal_results_use": False,
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest_out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_count": len(task_ids),
        "mutants_per_task": primary_manifest["mutants_per_task"],
        "expected_mutant_count": len(slots),
        "recorded_mutant_count": len(merged),
        "success_count": len(merged),
        "failed_count": 0,
        "unique_successful_mutant_count": len(set(hashes)),
        "source_counts": dict(sorted(source_counts.items())),
        "complete": len(merged) == len(slots),
        "formal_results_use": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
