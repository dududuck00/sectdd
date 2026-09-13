#!/usr/bin/env python3
"""Validate reference implementations and mutants against draft oracles."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cweval_sandbox import (
    PROJECT_ROOT,
    VENV_PYTHON,
    install_pytest_config,
    run_in_sandbox,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "oracles" / "cweval_python_v1" / "manifest.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--wall-timeout", type=int, default=120)
    return parser.parse_args()


def project_file(raw_path: str) -> Path:
    path = (PROJECT_ROOT / raw_path).resolve()
    path.relative_to(PROJECT_ROOT)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    manifest_path = args.manifest.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.relative_to(PROJECT_ROOT)
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; choose a new path to preserve provenance"
        )
    subprocess.run(
        [
            str(VENV_PYTHON),
            str(PROJECT_ROOT / "tools" / "validate_oracle_manifest.py"),
            "--manifest",
            str(manifest_path),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True)

    test_files: dict[tuple[str, str], Path] = {}
    for task, task_data in manifest["tasks"].items():
        for case in task_data["cases"]:
            key = (task, case["partition"])
            path = project_file(case["test_file"])
            existing = test_files.setdefault(key, path)
            if existing != path:
                raise AssertionError(
                    f"{task} {case['partition']} uses multiple test files"
                )

    records = []
    total = len(manifest["candidates"]) * 2 * args.repeats
    completed = 0
    for candidate in manifest["candidates"]:
        task = candidate["task"]
        source = project_file(candidate["source"])
        for partition in ("visible", "hidden"):
            repeat_results = []
            for repeat in range(args.repeats):
                run_dir = (
                    output
                    / "runs"
                    / candidate["candidate_id"]
                    / partition
                    / f"repeat_{repeat}"
                )
                work_dir = run_dir / "work"
                work_dir.mkdir(parents=True)
                task_destination = work_dir / f"{task}_task.py"
                test_destination = work_dir / f"{task}_test.py"
                shutil.copy2(source, task_destination)
                shutil.copy2(test_files[(task, partition)], test_destination)
                install_pytest_config(run_dir)
                result_path = run_dir / "result.json"
                inner_command = [
                    str(VENV_PYTHON),
                    str(PROJECT_ROOT / "tools" / "run_oracle_pytest.py"),
                    "--test-file",
                    str(test_destination),
                    "--output",
                    str(result_path),
                ]
                log_path = run_in_sandbox(
                    run_dir,
                    1,
                    20,
                    args.wall_timeout,
                    inner_command=inner_command,
                    log_name=(
                        f"oracle.{candidate['candidate_id']}."
                        f"{partition}.{repeat}.log"
                    ),
                )
                result = json.loads(result_path.read_text(encoding="utf-8"))
                repeat_results.append(
                    {
                        "repeat": repeat,
                        "result": result,
                        "log": str(log_path),
                    }
                )
                completed += 1
                print(
                    f"[{completed}/{total}] {candidate['candidate_id']} "
                    f"{partition} repeat={repeat} "
                    f"passed={result['summary']['all_passed']}",
                    flush=True,
                )

            outcomes = {
                item["result"]["summary"]["all_passed"]
                for item in repeat_results
            }
            if len(outcomes) != 1:
                raise AssertionError(
                    f"Nondeterministic result: {candidate['candidate_id']} "
                    f"{partition}: {sorted(outcomes)}"
                )
            actual = "pass" if outcomes == {True} else "fail"
            expected = candidate["expected"][partition]
            matches = expected == "either" or actual == expected
            records.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "task": task,
                    "kind": candidate["kind"],
                    "partition": partition,
                    "expected": expected,
                    "actual": actual,
                    "matches_expected": matches,
                    "repeats": repeat_results,
                }
            )

    if not all(record["matches_expected"] for record in records):
        mismatches = [
            (record["candidate_id"], record["partition"])
            for record in records
            if not record["matches_expected"]
        ]
        raise AssertionError(f"Oracle outcomes differ from manifest: {mismatches}")
    summary = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "oracle_id": manifest["oracle_id"],
        "oracle_status": manifest["status"],
        "repeats": args.repeats,
        "candidate_count": len(manifest["candidates"]),
        "condition_count": len(records),
        "all_expected_outcomes_matched": True,
        "records": records,
    }
    summary_path = output / "validation_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
