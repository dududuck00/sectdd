#!/usr/bin/env python3
"""Parse one generation and run one projected paper oracle in a minimal sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from cweval_sandbox import (
    CWEVAL_ROOT,
    PROJECT_ROOT,
    VENV_PYTHON,
    checked_eval_path,
    install_pytest_config,
    run_cweval_method,
    run_in_sandbox,
)


RUNNER = PROJECT_ROOT / "tools" / "run_paper_oracle_tests.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-path", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    parser.add_argument("--wall-timeout", type=int, default=180)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_file(raw_path: str) -> Path:
    path = (PROJECT_ROOT / raw_path).resolve()
    path.relative_to(PROJECT_ROOT)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def main() -> None:
    args = parse_args()
    eval_path = checked_eval_path(args.eval_path)
    projection_path = args.projection.expanduser().resolve()
    projection_path.relative_to(PROJECT_ROOT)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    partition = projection["partition"]
    if args.task not in projection["tasks"]:
        raise ValueError(f"Task absent from projection: {args.task}")
    task_data = projection["tasks"][args.task]
    oracle_source = project_file(task_data["oracle_file"])
    if sha256_file(oracle_source) != task_data["oracle_sha256"]:
        raise AssertionError(f"Oracle source changed: {oracle_source}")

    run_cweval_method("parse_generated", eval_path, 1)
    parsed_task = (
        eval_path
        / "generated_0"
        / "core"
        / "py"
        / f"{args.task}_task.py"
    )
    if not parsed_task.is_file():
        raise FileNotFoundError(parsed_task)
    work_dir = eval_path / "paper_oracle" / partition
    work_dir.mkdir(parents=True, exist_ok=True)
    subject_path = work_dir / "oracle_subject.py"
    test_path = work_dir / "test_oracle.py"
    shutil.copy2(parsed_task, subject_path)
    shutil.copy2(oracle_source, test_path)
    install_pytest_config(eval_path)
    result_path = eval_path / f"{partition}_paper_result.json"
    inner_command = [
        str(VENV_PYTHON),
        str(RUNNER),
        "--test-file",
        str(test_path),
        "--projection",
        str(projection_path),
        "--task",
        args.task,
        "--output",
        str(result_path),
        "--timeout-per-test",
        str(args.timeout_per_test),
    ]
    minimal_project_paths = [
        PROJECT_ROOT / ".venv",
        CWEVAL_ROOT,
        RUNNER,
        projection_path,
    ]
    log_path = run_in_sandbox(
        eval_path,
        1,
        args.timeout_per_test,
        args.wall_timeout,
        inner_command=inner_command,
        log_name=f"{eval_path.name}.paper-{partition}.sandbox.log",
        project_bind_paths=minimal_project_paths,
        working_directory=eval_path,
    )
    print(f"Paper-oracle result: {result_path}")
    print(f"Sandbox log: {log_path}")


if __name__ == "__main__":
    main()
