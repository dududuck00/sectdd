#!/usr/bin/env python3
"""Run CWEval-generated Python code in a Bubblewrap isolation boundary."""

from __future__ import annotations

import argparse
import os
import resource
import signal
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CWEVAL_ROOT = PROJECT_ROOT / "third_party" / "CWEval"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
LOG_ROOT = PROJECT_ROOT / "artifacts" / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-path", type=Path, required=True)
    parser.add_argument("--num-proc", type=int, default=1)
    parser.add_argument("--timeout-per-test", type=float, default=20.0)
    parser.add_argument("--wall-timeout", type=int, default=300)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Parse generations but do not execute them.",
    )
    return parser.parse_args()


def checked_eval_path(raw_path: Path) -> Path:
    eval_path = raw_path.expanduser().resolve()
    if not eval_path.is_dir():
        raise FileNotFoundError(eval_path)
    try:
        eval_path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"Evaluation path must be beneath project root {PROJECT_ROOT}"
        ) from exc
    return eval_path


def run_cweval_method(method: str, eval_path: Path, num_proc: int) -> None:
    subprocess.run(
        [
            str(VENV_PYTHON),
            "-m",
            "cweval.evaluate",
            method,
            "--eval_path",
            str(eval_path),
            "--num_proc",
            str(num_proc),
        ],
        cwd=CWEVAL_ROOT,
        check=True,
    )


def has_compilable_source(eval_path: Path) -> bool:
    return any(
        path.suffix in {".c", ".cpp", ".go"}
        for path in eval_path.rglob("*_task.*")
    )


def install_pytest_config(eval_path: Path) -> None:
    shutil.copy2(CWEVAL_ROOT / "benchmark" / "pytest.ini", eval_path / "pytest.ini")


def copy_test_files(eval_path: Path, num_proc: int) -> None:
    previous_cwd = Path.cwd()
    sys.path.insert(0, str(CWEVAL_ROOT))
    try:
        os.chdir(CWEVAL_ROOT)
        from cweval.evaluate import Evaler

        Evaler(eval_path=str(eval_path), num_proc=num_proc)._copy_test_files()
    finally:
        os.chdir(previous_cwd)


def add_dir_chain(args: list[str], path: Path) -> None:
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        args.extend(("--dir", str(current)))


def sandbox_command(
    eval_path: Path,
    num_proc: int,
    timeout_per_test: float,
    inner_command: list[str] | None = None,
    masked_paths: list[Path] | None = None,
    project_bind_paths: list[Path] | None = None,
    working_directory: Path | None = None,
) -> list[str]:
    python_target = Path(os.readlink(VENV_PYTHON))
    base_env_target = python_target.parents[1]
    base_env_source = VENV_PYTHON.resolve().parents[1]

    command = [
        "/usr/bin/bwrap",
        # Avoid --unshare-all: this host rejects creation of a cgroup
        # namespace, while these namespaces are available and sufficient for
        # the Python pilot.
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--hostname",
        "cweval-sandbox",
        "--clearenv",
        "--setenv",
        "HOME",
        "/sandbox-home",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "PATH",
        f"{PROJECT_ROOT}/.venv/bin:/usr/bin:/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/sandbox-home",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--symlink",
        "usr/sbin",
        "/sbin",
        "--ro-bind",
        "/etc",
        "/etc",
    ]

    if project_bind_paths is None:
        add_dir_chain(command, PROJECT_ROOT.parent)
        command.extend(("--ro-bind", str(PROJECT_ROOT), str(PROJECT_ROOT)))
    else:
        for bind_path in project_bind_paths:
            resolved_bind = bind_path.resolve()
            try:
                resolved_bind.relative_to(PROJECT_ROOT)
            except ValueError as exc:
                raise ValueError(
                    f"Project bind must be beneath {PROJECT_ROOT}: "
                    f"{resolved_bind}"
                ) from exc
            if not resolved_bind.exists():
                raise FileNotFoundError(resolved_bind)
            add_dir_chain(command, resolved_bind.parent)
            command.extend(
                ("--ro-bind", str(resolved_bind), str(resolved_bind))
            )
        add_dir_chain(command, eval_path.parent)
    command.extend(("--bind", str(eval_path), str(eval_path)))
    for masked_path in masked_paths or []:
        resolved_mask = masked_path.resolve()
        try:
            resolved_mask.relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise ValueError(
                f"Masked path must be beneath {PROJECT_ROOT}: {resolved_mask}"
            ) from exc
        if resolved_mask == eval_path or resolved_mask in eval_path.parents:
            raise ValueError(f"Cannot mask evaluation path: {resolved_mask}")
        if resolved_mask.is_dir():
            command.extend(("--tmpfs", str(resolved_mask)))
        elif resolved_mask.is_file():
            command.extend(("--ro-bind", "/dev/null", str(resolved_mask)))
        else:
            raise FileNotFoundError(resolved_mask)

    for destination in (base_env_source, base_env_target):
        add_dir_chain(command, destination.parent)
        command.extend(("--ro-bind", str(base_env_source), str(destination)))

    if inner_command is None:
        inner_command = [
            str(VENV_PYTHON),
            str(PROJECT_ROOT / "tools" / "run_cweval_detailed.py"),
            "--eval-path",
            str(eval_path),
            "--num-proc",
            str(num_proc),
            "--timeout-per-test",
            str(timeout_per_test),
        ]

    command.extend(
        (
            "--chdir",
            str((working_directory or CWEVAL_ROOT).resolve()),
            "--",
            # Applying RLIMIT_NPROC before bwrap makes clone(2) fail on this
            # host. Apply it after namespace creation and before Python.
            "/usr/bin/prlimit",
            "--nproc=256",
            "--",
            *inner_command,
        )
    )
    return command


def set_resource_limits() -> None:
    gib = 1024**3
    mib = 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (8 * gib, 8 * gib))
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * mib, 64 * mib))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_in_sandbox(
    eval_path: Path,
    num_proc: int,
    timeout_per_test: float,
    wall_timeout: int,
    inner_command: list[str] | None = None,
    log_name: str | None = None,
    masked_paths: list[Path] | None = None,
    project_bind_paths: list[Path] | None = None,
    working_directory: Path | None = None,
) -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / (log_name or f"{eval_path.name}.sandbox.log")
    command = sandbox_command(
        eval_path,
        num_proc,
        timeout_per_test,
        inner_command=inner_command,
        masked_paths=masked_paths,
        project_bind_paths=project_bind_paths,
        working_directory=working_directory,
    )
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=set_resource_limits,
            start_new_session=True,
            text=True,
        )
        try:
            return_code = process.wait(timeout=wall_timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise TimeoutError(
                f"CWEval exceeded {wall_timeout}s; see {log_path}"
            )
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
    return log_path


def main() -> None:
    args = parse_args()
    eval_path = checked_eval_path(args.eval_path)
    if args.num_proc < 1:
        raise ValueError("--num-proc must be positive")
    if args.timeout_per_test <= 0:
        raise ValueError("--timeout-per-test must be positive")

    run_cweval_method("parse_generated", eval_path, args.num_proc)
    # CWEval checks all three compiler toolchains even when the compilation
    # list is empty. Avoid that check for this Python-only pilot.
    if has_compilable_source(eval_path):
        run_cweval_method("compile_parsed", eval_path, args.num_proc)
    install_pytest_config(eval_path)
    if args.prepare_only:
        print(f"Prepared {eval_path}; generated code was not executed")
        return

    log_path = run_in_sandbox(
        eval_path,
        args.num_proc,
        args.timeout_per_test,
        args.wall_timeout,
    )
    run_cweval_method("_merge_results", eval_path, args.num_proc)
    run_cweval_method("report_pass_at_k", eval_path, args.num_proc)
    sample_count = len(list(eval_path.glob("generated_*")))
    for k in sorted({1, sample_count}):
        subprocess.run(
            [
                str(VENV_PYTHON),
                str(PROJECT_ROOT / "tools" / "summarize_cweval.py"),
                "--eval-path",
                str(eval_path),
                "--k",
                str(k),
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )
    print(f"Sandbox log: {log_path}")
    print(f"Merged results: {eval_path / 'res_all.json'}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}", file=sys.stderr)
        raise
