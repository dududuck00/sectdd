#!/usr/bin/env python3
"""Run independent CodeGuard+ behavior-family tests in Bubblewrap."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

if __package__:
    from .codeguardplus_bwrap import (
        DEFAULT_PYTHON,
        ROOT,
        add_dir_chain,
        checked_project_path,
        file_record,
        network_seccomp_filter,
        python_metadata,
        python_roots,
        run_process,
        sandbox_base,
        utc_now,
        write_json,
    )
else:
    from codeguardplus_bwrap import (
        DEFAULT_PYTHON,
        ROOT,
        add_dir_chain,
        checked_project_path,
        file_record,
        network_seccomp_filter,
        python_metadata,
        python_roots,
        run_process,
        sandbox_base,
        utc_now,
        write_json,
    )


TEST_CLASS = "TestCodeGuardPartition"
METHODS = ("test_correctness", "test_vulnerability")


def test_command(
    stage: Path,
    python: Path,
    python_info: dict[str, Any],
    method: str,
    seccomp_fd: int,
) -> list[str]:
    command = sandbox_base(stage, seccomp_fd)
    command.extend(("--setenv", "PATH", f"{python.parent}:/usr/bin:/bin"))
    command.extend(("--setenv", "PYTHONPATH", "/workspace"))
    command.extend(("--setenv", "PYTHONDONTWRITEBYTECODE", "1"))
    command.extend(("--setenv", "PYTHONNOUSERSITE", "1"))
    for root in python_roots(python_info):
        add_dir_chain(command, root.parent)
        command.extend(("--ro-bind", str(root), str(root)))
    command.extend(
        (
            "--",
            "/usr/bin/prlimit",
            "--as=2147483648",
            "--cpu=20",
            "--fsize=16777216",
            "--nofile=256",
            "--nproc=128",
            "--",
            str(python),
            "-B",
            "-m",
            "unittest",
            "-v",
            f"test_oracle.{TEST_CLASS}.{method}",
        )
    )
    return command


def run_method(
    *,
    candidate: Path,
    test: Path,
    method: str,
    python: Path,
    python_info: dict[str, Any],
    log: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    if method not in METHODS:
        raise ValueError(f"Unsupported partition method: {method}")
    candidate = checked_project_path(candidate)
    test = checked_project_path(test)
    log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sectdd-codeguard-partition-") as temp:
        stage = Path(temp)
        shutil.copy2(candidate, stage / "candidate.py")
        shutil.copy2(test, stage / "test_oracle.py")
        (stage / "home").mkdir()
        with network_seccomp_filter() as seccomp:
            process = run_process(
                test_command(stage, python, python_info, method, seccomp.fileno()),
                log,
                timeout_seconds,
                pass_fds=(seccomp.fileno(),),
            )
    if process["status"] == "completed":
        passed: bool | None = True
        status = "pass"
    elif process["status"] == "failed":
        passed = False
        status = "fail"
    else:
        passed = None
        status = "infrastructure_error"
    return {
        **process,
        "status": status,
        "passed": passed,
        "method": method,
        "candidate": file_record(candidate),
        "test": file_record(test),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = checked_project_path(args.output, exists=False)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    python = args.python.expanduser().absolute()
    result = run_method(
        candidate=args.candidate,
        test=args.test,
        method=args.method,
        python=python,
        python_info=python_metadata(python),
        log=output / "sandbox.log",
        timeout_seconds=args.timeout_seconds,
    )
    result["updated_at_utc"] = utc_now()
    write_json(output / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
