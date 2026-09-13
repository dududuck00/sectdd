#!/usr/bin/env python3
"""CWEval test runner that preserves per-test outcomes for SAFE@k."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CWEVAL_ROOT = PROJECT_ROOT / "third_party" / "CWEval"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--eval-path", type=Path)
    group.add_argument("--single-generated-path", type=Path)
    parser.add_argument("--num-proc", type=int, default=1)
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    return parser.parse_args()


def configure_imports() -> None:
    sys.path.insert(0, str(CWEVAL_ROOT))
    os.chdir(CWEVAL_ROOT)


def run_single(generated_path: Path, timeout_per_test: float) -> None:
    configure_imports()
    from cweval.run_tests import run_tests

    file_results = run_tests(
        str(generated_path.resolve()),
        timeout_per_test=timeout_per_test,
    )
    payload = {
        file_result.file: {
            "functional": file_result.functional,
            "secure": file_result.secure,
            "test_cases": [asdict(case) for case in file_result.test_cases],
        }
        for file_result in file_results
    }
    result_path = generated_path / "res.json"
    result_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Detailed results: {result_path}", flush=True)


def main() -> None:
    args = parse_args()
    if args.timeout_per_test <= 0:
        raise ValueError("--timeout-per-test must be positive")
    if args.single_generated_path is not None:
        run_single(args.single_generated_path, args.timeout_per_test)
        return

    eval_path = args.eval_path.resolve()
    configure_imports()
    from cweval.evaluate import Evaler

    evaluator = Evaler(eval_path=str(eval_path), num_proc=args.num_proc)
    evaluator._copy_test_files()
    for generated_path in evaluator.generated_paths:
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--single-generated-path",
                generated_path,
                "--timeout-per-test",
                str(args.timeout_per_test),
            ],
            check=True,
        )
    print(f"Detailed CWEval results written under {eval_path}", flush=True)


if __name__ == "__main__":
    main()
