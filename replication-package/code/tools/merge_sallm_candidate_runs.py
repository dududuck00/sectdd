#!/usr/bin/env python3
"""Merge compatible SALLM candidate runs by task and candidate index."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument(
        "--fallback",
        type=Path,
        action="append",
        default=[],
        help="Fallback runs in preference order",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def read_run(root: Path) -> dict[str, Any]:
    resolved = root.expanduser().resolve()
    manifest_path = resolved / "run_manifest.json"
    index_path = resolved / "candidate_index.jsonl"
    if not manifest_path.is_file() or not index_path.is_file():
        raise FileNotFoundError(f"Candidate run is incomplete: {resolved}")
    manifest = load_json(manifest_path)
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    by_slot = {
        (row["task_id"], row["candidate_index"]): row for row in rows
    }
    if len(by_slot) != len(rows):
        raise ValueError(f"Duplicate task/index records in {index_path}")
    return {
        "root": resolved,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "index_path": index_path,
        "by_slot": by_slot,
    }


def validate_compatibility(primary: dict[str, Any], other: dict[str, Any]) -> None:
    left = primary["manifest"]
    right = other["manifest"]
    for key in ("provider", "model", "base_seed", "candidates_per_task"):
        if left.get(key) != right.get(key):
            raise ValueError(
                f"Incompatible {key}: {left.get(key)!r} != {right.get(key)!r}"
            )
    if not set(right["selection"]).issubset(left["selection"]):
        raise ValueError("Fallback selection is not a subset of primary selection")
    for name in ("qualification", "benchmark_manifest", "overlay"):
        left_hash = left["input_files"][name]["sha256"]
        right_hash = right["input_files"][name]["sha256"]
        if left_hash != right_hash:
            raise ValueError(f"Incompatible input hash for {name}")


def source_candidate(
    run: dict[str, Any], task_id: str, candidate_index: int
) -> tuple[dict[str, Any], Path] | None:
    metadata = run["by_slot"].get((task_id, candidate_index))
    if not metadata or metadata.get("status") != "success":
        return None
    source = (
        run["root"]
        / "tasks"
        / Path(task_id).stem
        / f"candidate_{candidate_index:03d}"
        / "candidate.py"
    )
    if not source.is_file():
        raise FileNotFoundError(f"Successful candidate file is absent: {source}")
    actual_hash = sha256_file(source)
    if actual_hash != metadata["candidate_sha256"]:
        raise ValueError(f"Candidate hash mismatch: {source}")
    return metadata, source


def main() -> None:
    args = parse_args()
    runs = [read_run(args.primary), *[read_run(path) for path in args.fallback]]
    primary = runs[0]
    for run in runs[1:]:
        validate_compatibility(primary, run)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.mkdir(parents=True)

    manifest = primary["manifest"]
    rows: list[dict[str, Any]] = []
    canonical_by_task_hash: dict[tuple[str, str], int] = {}
    for task_id in manifest["selection"]:
        for candidate_index in range(manifest["candidates_per_task"]):
            selected = None
            selected_run = None
            for run in runs:
                candidate = source_candidate(run, task_id, candidate_index)
                if candidate is not None:
                    selected = candidate
                    selected_run = run
                    break
            if selected is None:
                rows.append(
                    {
                        "task_id": task_id,
                        "candidate_index": candidate_index,
                        "status": "missing",
                    }
                )
                continue
            metadata, source = selected
            destination = (
                output
                / "slots"
                / f"candidate_{candidate_index:03d}"
                / task_id
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            candidate_hash = metadata["candidate_sha256"]
            duplicate_key = (task_id, candidate_hash)
            duplicate_of = canonical_by_task_hash.get(duplicate_key)
            if duplicate_of is None:
                canonical_by_task_hash[duplicate_key] = candidate_index
            merged_metadata = {
                    "task_id": task_id,
                    "target_cwe": metadata["target_cwe"],
                    "candidate_index": candidate_index,
                    "status": "success",
                    "candidate_sha256": candidate_hash,
                    "duplicate_of_candidate_index": duplicate_of,
                    "source_run": relative(selected_run["root"]),
                    "source_max_tokens": selected_run["manifest"]["max_tokens"],
                    "source_metadata": relative(
                        selected_run["root"]
                        / "tasks"
                        / Path(task_id).stem
                        / f"candidate_{candidate_index:03d}"
                        / "metadata.json"
                    ),
                    "candidate_path": relative(destination),
                }
            rows.append(merged_metadata)
            standard_directory = (
                output
                / "tasks"
                / Path(task_id).stem
                / f"candidate_{candidate_index:03d}"
            )
            standard_directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, standard_directory / "candidate.py")
            write_json(standard_directory / "metadata.json", merged_metadata)

    index_path = output / "candidate_index.jsonl"
    index_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    successful = [row for row in rows if row["status"] == "success"]
    summary = {
        "task_count": len(manifest["selection"]),
        "expected_candidate_count": len(rows),
        "successful_candidate_count": len(successful),
        "missing_candidate_count": sum(
            row["status"] == "missing" for row in rows
        ),
        "unique_candidate_count": sum(
            row.get("duplicate_of_candidate_index") is None
            for row in successful
        ),
        "duplicate_candidate_count": sum(
            row.get("duplicate_of_candidate_index") is not None
            for row in successful
        ),
        "complete": len(successful) == len(rows),
    }
    write_json(output / "summary.json", summary)
    write_json(
        output / "run_manifest.json",
        {
            "schema_version": 1,
            "manifest_type": "sallm_candidate_run_merge",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "selection": manifest["selection"],
            "candidates_per_task": manifest["candidates_per_task"],
            "source_runs": [
                {
                    "path": relative(run["root"]),
                    "run_manifest_sha256": sha256_file(run["manifest_path"]),
                    "candidate_index_sha256": sha256_file(run["index_path"]),
                    "max_tokens": run["manifest"]["max_tokens"],
                }
                for run in runs
            ],
            "selection_policy": (
                "For each task/index, use the first successful candidate in "
                "primary-then-fallback order; preserve duplicates but mark "
                "their canonical candidate index."
            ),
            "summary": summary,
            "candidate_index_sha256": sha256_file(index_path),
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
