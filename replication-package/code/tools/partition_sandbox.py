#!/usr/bin/env python3
"""Prepare a CWEval candidate and run one test partition in Bubblewrap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cweval_sandbox import (
    PROJECT_ROOT,
    VENV_PYTHON,
    checked_eval_path,
    copy_test_files,
    install_pytest_config,
    run_cweval_method,
    run_in_sandbox,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-path", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    parser.add_argument("--wall-timeout", type=int, default=300)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_path = checked_eval_path(args.eval_path)
    split_path = args.split.expanduser().resolve()
    try:
        split_path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("Split file must be beneath the project root") from exc
    split = json.loads(split_path.read_text(encoding="utf-8"))
    partition = split["partition"]

    run_cweval_method("parse_generated", eval_path, 1)
    install_pytest_config(eval_path)
    copy_test_files(eval_path, 1)
    generated_paths = sorted(eval_path.glob("generated_*"))
    if len(generated_paths) != 1:
        raise RuntimeError(
            "Partition runner currently requires exactly one generated sample"
        )

    output_path = eval_path / f"{partition}_result.json"
    task_names = sorted(
        path.name.removesuffix("_raw.py")
        for path in generated_paths[0].rglob("*_raw.py")
    )
    if not task_names:
        raise RuntimeError("No generated task files found")
    inner_command = [
        str(VENV_PYTHON),
        str(PROJECT_ROOT / "tools" / "run_partition_tests.py"),
        "--generated-path",
        str(generated_paths[0]),
        "--split",
        str(split_path),
        "--output",
        str(output_path),
        "--timeout-per-test",
        str(args.timeout_per_test),
    ]
    for task_name in task_names:
        inner_command.extend(("--task", task_name))
    log_path = run_in_sandbox(
        eval_path,
        1,
        args.timeout_per_test,
        args.wall_timeout,
        inner_command=inner_command,
        log_name=f"{eval_path.name}.{partition}.sandbox.log",
    )
    print(f"Partition result: {output_path}")
    print(f"Sandbox log: {log_path}")


if __name__ == "__main__":
    main()
