#!/usr/bin/env python3
"""Execute SALLM unittest oracles in per-method Bubblewrap sandboxes.

The executor consumes the frozen SALLM inventory manifest.  It deliberately
does not import or execute candidate code in the parent process.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "benchmarks" / "manifests" / "sallm-v1.json"
)
DEFAULT_OVERLAY = (
    PROJECT_ROOT / "configs" / "benchmarks" / "sallm_audit_overlay_v1.json"
)
DEFAULT_PYTHON = PROJECT_ROOT / ".venv-sallm" / "bin" / "python"
RESULT_SCHEMA = PROJECT_ROOT / "schemas" / "sallm_execution.schema.json"
BWRAP = Path("/usr/bin/bwrap")
SECCOMP_ACTION_ALLOW = 0x7FFF0000
SECCOMP_ACTION_ERRNO = 0x00050000

REQUIRED_IMPORTS = (
    "flask",
    "flask_sqlalchemy",
    "Crypto",
    "requests",
    "canvasapi",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run SALLM functional and security unittests in isolated "
            "Bubblewrap sandboxes."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--overlay",
        type=Path,
        help="Optional audited fixture/dependency/exclusion overlay.",
    )
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument(
        "--output",
        type=Path,
        help="New output directory beneath the SecTDD project root.",
    )
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="Exact SALLM task ID; repeat to select multiple tasks.",
    )
    parser.add_argument(
        "--candidate-root",
        type=Path,
        help=(
            "Use generated candidates from this directory instead of the "
            "manifest's reference files."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--cpu-seconds", type=int, default=15)
    parser.add_argument("--memory-mib", type=int, default=2048)
    parser.add_argument("--max-log-mib", type=int, default=8)
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check Python dependencies and Bubblewrap without running tasks.",
    )
    parser.add_argument(
        "--allow-python-version-mismatch",
        action="store_true",
        help="Allow a Python version other than the declared Python 3.10.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.write_bytes(json_bytes(payload))


def checked_project_path(
    raw_path: Path,
    *,
    must_exist: bool,
    kind: str,
) -> Path:
    path = raw_path.expanduser().resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"{kind} must be beneath project root {PROJECT_ROOT}: {path}"
        ) from exc
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    manifest = json.loads(content)
    if manifest.get("manifest_type") != "external_benchmark_inventory":
        raise ValueError(f"Unexpected manifest_type in {path}")
    if manifest.get("benchmark", {}).get("name") != "SALLM":
        raise ValueError(f"Not a SALLM manifest: {path}")
    if manifest.get("status") != "inventory_only":
        raise ValueError(f"Unexpected SALLM manifest status in {path}")
    return manifest, sha256_bytes(content)


def load_overlay(
    path: Path,
    *,
    manifest_hash: str,
    repository_commit: str,
    task_ids: set[str],
) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    overlay = json.loads(content)
    if overlay.get("schema_version") != 1:
        raise ValueError(f"Unsupported overlay schema in {path}")
    if overlay.get("overlay_type") != "sallm_execution_audit_overlay":
        raise ValueError(f"Not a SALLM execution overlay: {path}")
    if overlay.get("benchmark_manifest_sha256") != manifest_hash:
        raise RuntimeError(
            "Overlay benchmark manifest hash does not match selected manifest"
        )
    if overlay.get("repository_commit") != repository_commit:
        raise RuntimeError(
            "Overlay repository commit does not match selected manifest"
        )
    referenced_tasks = (
        set(overlay.get("fixtures", {}))
        | set(overlay.get("exclusions", {}))
        | set(overlay.get("test_overrides", {}))
    )
    unknown = sorted(referenced_tasks - task_ids)
    if unknown:
        raise ValueError(f"Overlay references unknown task IDs: {unknown}")
    overlap = (
        set(overlay.get("fixtures", {}))
        | set(overlay.get("test_overrides", {}))
    ) & set(overlay.get("exclusions", {}))
    if overlap:
        raise ValueError(
            f"Overlay cannot both stage and exclude tasks: {sorted(overlap)}"
        )
    return overlay, sha256_bytes(content)


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_repository(manifest: dict[str, Any]) -> Path:
    repository = manifest["repository"]
    root = checked_project_path(
        PROJECT_ROOT / repository["path"],
        must_exist=True,
        kind="SALLM repository",
    )
    actual_commit = git_output(root, "rev-parse", "HEAD")
    if actual_commit != repository["commit"]:
        raise RuntimeError(
            "SALLM commit does not match manifest: "
            f"{actual_commit} != {repository['commit']}"
        )
    dirty = git_output(root, "status", "--porcelain")
    if dirty:
        raise RuntimeError(
            "SALLM repository is dirty; regenerate/freeze the manifest first:\n"
            + dirty
        )
    return root


def resolve_record(record: dict[str, Any] | None) -> Path | None:
    if record is None:
        return None
    path = checked_project_path(
        PROJECT_ROOT / record["path"],
        must_exist=True,
        kind="Manifest input",
    )
    actual = sha256_file(path)
    if actual != record["sha256"]:
        raise RuntimeError(
            f"Manifest hash mismatch for {path}: {actual} != "
            f"{record['sha256']}"
        )
    if path.stat().st_size != record["size_bytes"]:
        raise RuntimeError(f"Manifest size mismatch for {path}")
    return path


def select_tasks(
    manifest: dict[str, Any], requested: list[str] | None
) -> list[dict[str, Any]]:
    tasks = manifest["tasks"]
    by_id = {task["task_id"]: task for task in tasks}
    if not requested:
        return tasks
    if len(requested) != len(set(requested)):
        raise ValueError("--task values must be unique")
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown SALLM task IDs: {unknown}")
    return [by_id[task_id] for task_id in requested]


def normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_overlay_environment(
    overlay: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> None:
    if overlay is None:
        return
    installed = {}
    for item in metadata["installed_distributions"]:
        name, separator, version = item.partition("==")
        if separator:
            installed[normalized_distribution_name(name)] = version
    mismatches = []
    for dependency in overlay.get("supplemental_dependencies", []):
        name = dependency["distribution"]
        expected = dependency["version"]
        actual = installed.get(normalized_distribution_name(name))
        if actual != expected:
            mismatches.append(f"{name}: expected {expected}, found {actual}")
    if mismatches:
        raise RuntimeError(
            "Python environment does not match SALLM overlay:\n"
            + "\n".join(mismatches)
            + "\nRerun scripts/bootstrap_sallm_env.sh."
        )


def python_metadata(python: Path) -> dict[str, Any]:
    if not python.is_file():
        raise FileNotFoundError(
            f"Python environment not found: {python}. "
            "Create .venv-sallm as documented."
        )
    probe = (
        "import json,sys; from importlib.metadata import distributions; "
        "packages=sorted("
        "f'{d.metadata.get(\"Name\", \"UNKNOWN\")}=={d.version}' "
        "for d in distributions()); "
        "print(json.dumps({"
        "'version':sys.version,'version_info':list(sys.version_info[:3]),"
        "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'executable':sys.executable,"
        "'installed_distributions':packages}))"
    )
    result = subprocess.run(
        [str(python), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(result.stdout)
    metadata["requested_executable"] = str(python)
    metadata["resolved_executable"] = str(python.resolve())
    metadata["installed_distributions_sha256"] = sha256_bytes(
        (
            "\n".join(metadata["installed_distributions"]) + "\n"
        ).encode("utf-8")
    )
    return metadata


def validate_python_version(
    metadata: dict[str, Any], allow_mismatch: bool
) -> None:
    major, minor = metadata["version_info"][:2]
    if (major, minor) != (3, 10) and not allow_mismatch:
        raise RuntimeError(
            "SALLM declares python:3.10-slim, but selected interpreter is "
            f"{major}.{minor}. Use .venv-sallm or explicitly pass "
            "--allow-python-version-mismatch for a non-comparable audit."
        )


def add_dir_chain(command: list[str], path: Path) -> None:
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        command.extend(("--dir", str(current)))


def covered_by_system_mount(path: Path) -> bool:
    return path == Path("/usr") or Path("/usr") in path.parents


def python_bind_roots(metadata: dict[str, Any]) -> list[Path]:
    roots = {
        Path(metadata["prefix"]).absolute(),
        Path(metadata["base_prefix"]).absolute(),
    }
    executable = Path(metadata["resolved_executable"])
    if not covered_by_system_mount(executable):
        roots.add(Path(metadata["base_prefix"]).absolute())
    return sorted(
        (root for root in roots if not covered_by_system_mount(root)),
        key=lambda item: (len(item.parts), str(item)),
    )


def network_seccomp_filter() -> Any:
    library_path = ctypes.util.find_library("seccomp")
    if not library_path:
        raise RuntimeError("libseccomp is required for network isolation")
    library = ctypes.CDLL(library_path, use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_export_bpf.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]

    context = library.seccomp_init(SECCOMP_ACTION_ALLOW)
    if not context:
        raise OSError(ctypes.get_errno(), "seccomp_init failed")
    output = tempfile.TemporaryFile()
    try:
        deny_action = SECCOMP_ACTION_ERRNO | errno.EPERM
        for name in (b"socket", b"socketpair"):
            syscall = library.seccomp_syscall_resolve_name(name)
            if syscall < 0:
                raise RuntimeError(
                    f"Cannot resolve seccomp syscall {name.decode()}"
                )
            result = library.seccomp_rule_add(
                context, deny_action, syscall, 0
            )
            if result != 0:
                raise OSError(-result, f"Cannot deny {name.decode()}")
        result = library.seccomp_export_bpf(context, output.fileno())
        if result != 0:
            raise OSError(-result, "seccomp_export_bpf failed")
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise
    finally:
        library.seccomp_release(context)


def sandbox_command(
    stage: Path,
    python: Path,
    metadata: dict[str, Any],
    inner_args: list[str],
    *,
    cpu_seconds: int,
    memory_mib: int,
    max_log_mib: int,
    seccomp_fd: int,
) -> list[str]:
    command = [
        str(BWRAP),
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--hostname",
        "sallm-sandbox",
        "--clearenv",
        "--setenv",
        "HOME",
        "/sandbox-home",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "PATH",
        f"{python.parent}:/usr/bin:/bin",
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
        "--seccomp",
        str(seccomp_fd),
    ]
    for root in python_bind_roots(metadata):
        if not root.is_dir():
            raise FileNotFoundError(f"Python prefix does not exist: {root}")
        add_dir_chain(command, root.parent)
        command.extend(("--ro-bind", str(root), str(root)))
    command.extend(
        (
            "--dir",
            "/workspace",
            "--bind",
            str(stage),
            "/workspace",
            "--chdir",
            "/workspace",
            "--",
            "/usr/bin/prlimit",
            f"--as={memory_mib * 1024 * 1024}",
            f"--cpu={cpu_seconds}",
            f"--fsize={max_log_mib * 1024 * 1024}",
            "--nofile=256",
            "--nproc=128",
            "--",
            str(python),
            "-B",
            *inner_args,
        )
    )
    return command


def set_parent_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_process(
    command: list[str],
    log_path: Path,
    timeout_seconds: float,
    *,
    pass_fds: tuple[int, ...] = (),
) -> tuple[str, int | None, float]:
    started = time.monotonic()
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            preexec_fn=set_parent_limits,
            start_new_session=True,
            pass_fds=pass_fds,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return "timeout", None, time.monotonic() - started
    duration = time.monotonic() - started
    if return_code == 0:
        return "pass", return_code, duration
    prefix = log_path.read_bytes()[:4096]
    if prefix.startswith(b"bwrap:") or prefix.startswith(b"prlimit:"):
        return "infrastructure_error", return_code, duration
    if return_code < 0:
        return "resource_or_signal_failure", return_code, duration
    return "fail", return_code, duration


def task_slug(task_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
    if not slug or slug in {".", ".."}:
        raise ValueError(f"Cannot form output name for task {task_id!r}")
    return slug


def candidate_for_task(
    task: dict[str, Any],
    candidate_root: Path | None,
    reference_path: Path,
) -> tuple[Path, str]:
    if candidate_root is None:
        return reference_path, "manifest_reference"
    candidates = [
        candidate_root / task["task_id"],
        candidate_root / reference_path.name,
    ]
    existing = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in existing:
            existing.append(candidate)
    if not existing:
        raise FileNotFoundError(
            f"No candidate for {task['task_id']}; expected one of "
            f"{[str(path) for path in candidates]}"
        )
    if len(existing) > 1:
        hashes = {sha256_file(path) for path in existing}
        if len(hashes) > 1:
            raise RuntimeError(
                f"Ambiguous candidates with different content for "
                f"{task['task_id']}: {existing}"
            )
    return existing[0], "candidate_root"


def preflight_tasks(
    tasks: list[dict[str, Any]],
    candidate_root: Path | None,
    overlay: dict[str, Any] | None,
) -> None:
    for task in tasks:
        task_id = task["task_id"]
        if overlay and task_id in overlay.get("exclusions", {}):
            continue
        reference_path = resolve_record(task["source"]["reference_file"])
        test_record = (
            overlay.get("test_overrides", {}).get(task_id)
            if overlay
            else None
        ) or task["tests"]["entrypoint"]
        test_path = resolve_record(test_record)
        resolve_record(task["dependencies"]["requirement_file"])
        resolve_record(task["dependencies"]["environment_spec"])
        for fixture in (
            overlay.get("fixtures", {}).get(task_id, [])
            if overlay
            else []
        ):
            resolve_record(fixture["source"])
            destination = Path(fixture["destination"])
            if destination.is_absolute() or ".." in destination.parts:
                raise ValueError(
                    f"Unsafe overlay destination for {task_id}: {destination}"
                )
        if reference_path is not None and test_path is not None:
            candidate_for_task(task, candidate_root, reference_path)


def prepare_stage(
    stage: Path,
    candidate: Path,
    reference_path: Path,
    test_path: Path,
    requirement_path: Path | None,
    fixtures: list[dict[str, Any]],
) -> None:
    shutil.copy2(candidate, stage / reference_path.name)
    shutil.copy2(test_path, stage / test_path.name)
    if requirement_path is not None:
        shutil.copy2(requirement_path, stage / requirement_path.name)
    for fixture in fixtures:
        source = resolve_record(fixture["source"])
        if source is None:
            raise AssertionError("Overlay fixture source cannot be null")
        destination = stage / fixture["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def run_method(
    task: dict[str, Any],
    category: str,
    method: dict[str, str],
    *,
    candidate: Path,
    reference_path: Path,
    test_path: Path,
    requirement_path: Path | None,
    python: Path,
    python_info: dict[str, Any],
    log_path: Path,
    timeout_seconds: float,
    cpu_seconds: int,
    memory_mib: int,
    max_log_mib: int,
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sectdd-sallm-") as temp:
        stage = Path(temp)
        prepare_stage(
            stage,
            candidate,
            reference_path,
            test_path,
            requirement_path,
            fixtures,
        )
        test_module = test_path.stem
        target = (
            f"{test_module}.{method['class_name']}.{method['method']}"
        )
        with network_seccomp_filter() as seccomp:
            command = sandbox_command(
                stage,
                python,
                python_info,
                ["-m", "unittest", "-v", target],
                cpu_seconds=cpu_seconds,
                memory_mib=memory_mib,
                max_log_mib=max_log_mib,
                seccomp_fd=seccomp.fileno(),
            )
            status, return_code, duration = run_process(
                command,
                log_path,
                timeout_seconds,
                pass_fds=(seccomp.fileno(),),
            )
    return {
        "category": category,
        "class_name": method["class_name"],
        "method": method["method"],
        "unittest_target": target,
        "status": status,
        "passed": (
            None if status == "infrastructure_error" else status == "pass"
        ),
        "return_code": return_code,
        "wall_seconds": round(duration, 6),
        "log": {
            "path": log_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        },
    }


def category_pass(
    method_results: list[dict[str, Any]], category: str
) -> bool | None:
    selected = [
        result for result in method_results if result["category"] == category
    ]
    if not selected:
        return None
    if any(result["passed"] is None for result in selected):
        return None
    return all(result["passed"] for result in selected)


def run_task(
    task: dict[str, Any],
    *,
    candidate_root: Path | None,
    python: Path,
    python_info: dict[str, Any],
    log_root: Path,
    timeout_seconds: float,
    cpu_seconds: int,
    memory_mib: int,
    max_log_mib: int,
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    task_id = task["task_id"]
    exclusion = (
        overlay.get("exclusions", {}).get(task_id) if overlay else None
    )
    if exclusion is not None:
        return {
            "task_id": task_id,
            "cwe": task["cwe"],
            "status": "excluded_by_overlay",
            "reason": exclusion["reason_code"],
            "exclusion": exclusion,
            "method_results": [],
            "functional_pass": None,
            "security_pass": None,
            "joint_pass": None,
        }
    reference_path = resolve_record(task["source"]["reference_file"])
    if reference_path is None:
        return {
            "task_id": task["task_id"],
            "cwe": task["cwe"],
            "status": "not_runnable",
            "reason": "missing_reference_source",
            "method_results": [],
            "functional_pass": None,
            "security_pass": None,
            "joint_pass": None,
        }
    test_record = (
        overlay.get("test_overrides", {}).get(task_id)
        if overlay
        else None
    ) or task["tests"]["entrypoint"]
    test_path = resolve_record(test_record)
    if test_path is None:
        return {
            "task_id": task["task_id"],
            "cwe": task["cwe"],
            "status": "not_runnable",
            "reason": "missing_test_file",
            "method_results": [],
            "functional_pass": None,
            "security_pass": None,
            "joint_pass": None,
        }
    requirement_path = resolve_record(
        task["dependencies"]["requirement_file"]
    )
    resolve_record(task["dependencies"]["environment_spec"])
    candidate, source_type = candidate_for_task(
        task, candidate_root, reference_path
    )
    candidate_hash = sha256_file(candidate)
    fixtures = (
        overlay.get("fixtures", {}).get(task_id, []) if overlay else []
    )

    task_log_root = log_root / task_slug(task["task_id"])
    task_log_root.mkdir(parents=True)
    method_results = []
    for category in ("functional", "security"):
        methods = task["tests"][category]
        for index, method in enumerate(methods):
            log_path = (
                task_log_root
                / f"{category}-{index}-{method['method']}.log"
            )
            method_results.append(
                run_method(
                    task,
                    category,
                    method,
                    candidate=candidate,
                    reference_path=reference_path,
                    test_path=test_path,
                    requirement_path=requirement_path,
                    python=python,
                    python_info=python_info,
                    log_path=log_path,
                    timeout_seconds=timeout_seconds,
                    cpu_seconds=cpu_seconds,
                    memory_mib=memory_mib,
                    max_log_mib=max_log_mib,
                    fixtures=fixtures,
                )
            )
    functional_pass = category_pass(method_results, "functional")
    security_pass = category_pass(method_results, "security")
    task_status = (
        "infrastructure_error"
        if any(
            result["status"] == "infrastructure_error"
            for result in method_results
        )
        else "completed"
    )
    return {
        "task_id": task["task_id"],
        "cwe": task["cwe"],
        "status": task_status,
        "reason": None,
        "candidate": {
            "source_type": source_type,
            "input_path": str(candidate),
            "staged_filename": reference_path.name,
            "sha256": candidate_hash,
            "matches_manifest_reference": (
                candidate_hash == task["source"]["reference_file"]["sha256"]
            ),
        },
        "overlay_fixture_count": len(fixtures),
        "test_source": {
            "source_type": (
                "overlay_override"
                if overlay
                and task_id in overlay.get("test_overrides", {})
                else "manifest_entrypoint"
            ),
            "input_path": str(test_path),
            "staged_filename": test_path.name,
            "sha256": sha256_file(test_path),
        },
        "method_results": method_results,
        "functional_pass": functional_pass,
        "security_pass": security_pass,
        "joint_pass": (
            functional_pass and security_pass
            if functional_pass is not None and security_pass is not None
            else None
        ),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    runnable = [item for item in results if item["status"] == "completed"]
    method_statuses = Counter(
        method["status"]
        for item in runnable
        for method in item["method_results"]
    )

    def count(field: str, value: bool) -> int:
        return sum(item[field] is value for item in runnable)

    return {
        "task_count": len(results),
        "completed_task_count": len(runnable),
        "not_runnable_task_count": sum(
            item["status"] == "not_runnable" for item in results
        ),
        "excluded_by_overlay_task_count": sum(
            item["status"] == "excluded_by_overlay" for item in results
        ),
        "infrastructure_error_task_count": sum(
            item["status"] == "infrastructure_error" for item in results
        ),
        "functional_pass_count": count("functional_pass", True),
        "functional_fail_count": count("functional_pass", False),
        "security_pass_count": count("security_pass", True),
        "security_fail_count": count("security_pass", False),
        "joint_pass_count": count("joint_pass", True),
        "joint_fail_count": count("joint_pass", False),
        "method_status_counts": dict(sorted(method_statuses.items())),
    }


def doctor(
    python: Path,
    python_info: dict[str, Any],
    *,
    cpu_seconds: int,
    memory_mib: int,
    max_log_mib: int,
    required_imports: tuple[str, ...] = REQUIRED_IMPORTS,
) -> None:
    imports = "; ".join(f"import {name}" for name in required_imports)
    script = (
        f"{imports}; "
        "import errno, json, socket, sys; "
        "network='unexpectedly_allowed'; "
        "\ntry: socket.socket()\n"
        "except PermissionError as exc:\n"
        " assert exc.errno == errno.EPERM\n"
        " network='denied_by_seccomp'\n"
        "print(json.dumps({"
        "'python':sys.version,"
        "'imports':'ok',"
        "'network_socket_syscall':network"
        "}))"
    )
    with tempfile.TemporaryDirectory(prefix="sectdd-sallm-doctor-") as temp:
        stage = Path(temp)
        log_path = stage / "doctor.log"
        with network_seccomp_filter() as seccomp:
            command = sandbox_command(
                stage,
                python,
                python_info,
                ["-c", script],
                cpu_seconds=cpu_seconds,
                memory_mib=memory_mib,
                max_log_mib=max_log_mib,
                seccomp_fd=seccomp.fileno(),
            )
            status, return_code, _ = run_process(
                command,
                log_path,
                30,
                pass_fds=(seccomp.fileno(),),
            )
        output = log_path.read_text(encoding="utf-8", errors="replace")
    if status != "pass":
        raise RuntimeError(
            "SALLM sandbox doctor failed. Install "
            "requirements/sallm-oracle.txt into the selected Python "
            f"environment. Return code: {return_code}\n{output}"
        )
    print(f"Bubblewrap: {subprocess.check_output([BWRAP, '--version'], text=True).strip()}")
    print(f"Python: {python_info['version'].splitlines()[0]}")
    print("SALLM dependencies: OK")
    print("Network: socket/socketpair syscalls denied by seccomp")


def validate_limits(args: argparse.Namespace) -> None:
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.cpu_seconds <= 0:
        raise ValueError("--cpu-seconds must be positive")
    if args.memory_mib < 256:
        raise ValueError("--memory-mib must be at least 256")
    if args.max_log_mib < 1:
        raise ValueError("--max-log-mib must be positive")


def main() -> None:
    args = parse_args()
    validate_limits(args)
    if not BWRAP.is_file():
        raise FileNotFoundError(BWRAP)
    python = args.python.expanduser().absolute()
    python_info = python_metadata(python)
    validate_python_version(
        python_info, args.allow_python_version_mismatch
    )
    if args.doctor:
        required_imports = REQUIRED_IMPORTS
        if args.overlay is not None:
            manifest_path = checked_project_path(
                args.manifest,
                must_exist=True,
                kind="Manifest",
            )
            manifest, manifest_hash = load_manifest(manifest_path)
            verify_repository(manifest)
            overlay_path = checked_project_path(
                args.overlay,
                must_exist=True,
                kind="Overlay",
            )
            overlay, _ = load_overlay(
                overlay_path,
                manifest_hash=manifest_hash,
                repository_commit=manifest["repository"]["commit"],
                task_ids={task["task_id"] for task in manifest["tasks"]},
            )
            validate_overlay_environment(overlay, python_info)
            required_imports = tuple(
                dict.fromkeys(
                    [*REQUIRED_IMPORTS, *overlay["required_imports"]]
                )
            )
        doctor(
            python,
            python_info,
            cpu_seconds=args.cpu_seconds,
            memory_mib=args.memory_mib,
            max_log_mib=args.max_log_mib,
            required_imports=required_imports,
        )
        return
    if args.output is None:
        raise ValueError("--output is required unless --doctor is used")

    manifest_path = checked_project_path(
        args.manifest,
        must_exist=True,
        kind="Manifest",
    )
    manifest, manifest_hash = load_manifest(manifest_path)
    verify_repository(manifest)
    overlay = None
    overlay_hash = None
    overlay_path = None
    if args.overlay is not None:
        overlay_path = checked_project_path(
            args.overlay,
            must_exist=True,
            kind="Overlay",
        )
        overlay, overlay_hash = load_overlay(
            overlay_path,
            manifest_hash=manifest_hash,
            repository_commit=manifest["repository"]["commit"],
            task_ids={task["task_id"] for task in manifest["tasks"]},
        )
        validate_overlay_environment(overlay, python_info)
    selected_tasks = select_tasks(manifest, args.tasks)
    candidate_root = None
    if args.candidate_root is not None:
        candidate_root = checked_project_path(
            args.candidate_root,
            must_exist=True,
            kind="Candidate root",
        )
        if not candidate_root.is_dir():
            raise NotADirectoryError(candidate_root)
    preflight_tasks(selected_tasks, candidate_root, overlay)
    required_imports = tuple(
        dict.fromkeys(
            [
                *REQUIRED_IMPORTS,
                *(
                    overlay.get("required_imports", [])
                    if overlay
                    else []
                ),
            ]
        )
    )
    doctor(
        python,
        python_info,
        cpu_seconds=args.cpu_seconds,
        memory_mib=args.memory_mib,
        max_log_mib=args.max_log_mib,
        required_imports=required_imports,
    )

    output = checked_project_path(
        args.output,
        must_exist=False,
        kind="Output",
    )
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; use a new run tag to preserve provenance"
        )
    output.mkdir(parents=True)
    log_root = output / "logs"
    log_root.mkdir()
    results_path = output / "results.jsonl"

    run_manifest = {
        "$schema": RESULT_SCHEMA.relative_to(PROJECT_ROOT).as_posix(),
        "schema_version": 1,
        "run_type": "sallm_bubblewrap_execution",
        "status": "running",
        "started_at_utc": utc_now(),
        "completed_at_utc": None,
        "benchmark_manifest": {
            "path": manifest_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": manifest_hash,
            "repository_commit": manifest["repository"]["commit"],
        },
        "overlay": (
            {
                "path": overlay_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": overlay_hash,
                "overlay_id": overlay["overlay_id"],
            }
            if overlay and overlay_path and overlay_hash
            else None
        ),
        "executor": {
            "path": Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
            "bubblewrap_version": subprocess.check_output(
                [BWRAP, "--version"], text=True
            ).strip(),
            "network": "socket_and_socketpair_denied_by_seccomp",
            "workspace_policy": "fresh_per_test_method",
        },
        "python": python_info,
        "source_mode": (
            "candidate_root" if candidate_root else "manifest_reference"
        ),
        "candidate_root": str(candidate_root) if candidate_root else None,
        "task_ids": [task["task_id"] for task in selected_tasks],
        "limits": {
            "wall_seconds_per_method": args.timeout_seconds,
            "cpu_seconds_per_method": args.cpu_seconds,
            "memory_mib_per_method": args.memory_mib,
            "max_log_mib_per_method": args.max_log_mib,
            "processes_per_method": 128,
            "open_files_per_method": 256,
        },
    }
    write_json(output / "run_manifest.json", run_manifest)

    results = []
    with results_path.open("a", encoding="utf-8") as stream:
        for index, task in enumerate(selected_tasks, start=1):
            result = run_task(
                task,
                candidate_root=candidate_root,
                python=python,
                python_info=python_info,
                log_root=log_root,
                timeout_seconds=args.timeout_seconds,
                cpu_seconds=args.cpu_seconds,
                memory_mib=args.memory_mib,
                max_log_mib=args.max_log_mib,
                overlay=overlay,
            )
            results.append(result)
            stream.write(json.dumps(result, sort_keys=True) + "\n")
            stream.flush()
            print(
                f"[{index}/{len(selected_tasks)}] {task['task_id']} "
                f"status={result['status']} "
                f"functional={result['functional_pass']} "
                f"security={result['security_pass']}",
                flush=True,
            )

    summary = summarize(results)
    write_json(output / "summary.json", summary)
    run_manifest["status"] = "completed"
    run_manifest["completed_at_utc"] = utc_now()
    run_manifest["results"] = {
        "path": results_path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": sha256_file(results_path),
        "summary_path": (output / "summary.json")
        .relative_to(PROJECT_ROOT)
        .as_posix(),
    }
    write_json(output / "run_manifest.json", run_manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["infrastructure_error_task_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
