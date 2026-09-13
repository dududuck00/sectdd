#!/usr/bin/env python3
"""Run CodeGuard+ Python functionality and CodeQL oracles without Docker.

Candidate code is never imported by the parent process. Functional tests and
CodeQL run in separate ephemeral Bubblewrap workspaces with no network.
"""

from __future__ import annotations

import argparse
import csv
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/benchmarks/codeguardplus_python_smoke_v1.json"
DEFAULT_PYTHON = ROOT / ".venv-codeguardplus/bin/python"
DEFAULT_CODEQL_ROOT = ROOT / ".tools/codeguardplus"
BWRAP = Path("/usr/bin/bwrap")
SECCOMP_ACTION_ALLOW = 0x7FFF0000
SECCOMP_ACTION_ERRNO = 0x00050000
REQUIRED_IMPORTS = (
    "argon2",
    "boto3",
    "Crypto",
    "cryptography",
    "defusedxml",
    "django",
    "flask",
    "func_timeout",
    "jinja2",
    "jose",
    "jwt",
    "libcst",
    "lxml",
    "paramiko",
    "yaml",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--codeql-root", type=Path, default=DEFAULT_CODEQL_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--functional-timeout", type=float, default=30.0)
    parser.add_argument("--codeql-timeout", type=float, default=300.0)
    parser.add_argument("--doctor", action="store_true")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def checked_project_path(path: Path, *, exists: bool = True) -> Path:
    resolved = path.expanduser().resolve()
    resolved.relative_to(ROOT)
    if exists and not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def verified_record(record: dict[str, Any]) -> Path:
    path = checked_project_path(ROOT / record["path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256_file(path) != record["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if "size_bytes" in record and path.stat().st_size != record["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")
    return path


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_inputs(config_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config_path = checked_project_path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("config_id") != "codeguardplus-python-smoke-v1":
        raise ValueError("Unsupported CodeGuard+ audit config")
    manifest_path = verified_record(config["benchmark_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("benchmark", {}).get("name") != "CodeGuard+":
        raise ValueError("Selected manifest is not CodeGuard+")
    if manifest.get("status") != "inventory_only":
        raise ValueError("Unexpected CodeGuard+ inventory status")
    repo = checked_project_path(ROOT / manifest["repository"]["path"])
    commit = git_output(repo, "rev-parse", "HEAD")
    if commit != config["repository_commit"] or commit != manifest["repository"]["commit"]:
        raise RuntimeError("CodeGuard+ repository commit mismatch")
    if git_output(repo, "status", "--porcelain"):
        raise RuntimeError("CodeGuard+ repository is dirty")
    return config, manifest, config_path


def python_metadata(python: Path) -> dict[str, Any]:
    python = python.expanduser().absolute()
    if not python.is_file():
        raise FileNotFoundError(python)
    probe = (
        "import hashlib,json,sqlite3,sys; "
        "from importlib.metadata import distributions; "
        "p=sorted(f'{d.metadata.get(\"Name\",\"UNKNOWN\")}=={d.version}' "
        "for d in distributions()); "
        "print(json.dumps({'version':sys.version,'version_info':list(sys.version_info[:3]),"
        "'prefix':sys.prefix,'base_prefix':sys.base_prefix,'executable':sys.executable,"
        "'sqlite_version':sqlite3.sqlite_version,'packages':p,"
        "'packages_sha256':hashlib.sha256(('\\n'.join(p)+'\\n').encode()).hexdigest()}))"
    )
    payload = json.loads(
        subprocess.run(
            [str(python), "-c", probe], check=True, capture_output=True, text=True
        ).stdout
    )
    payload["requested_executable"] = str(python)
    payload["resolved_executable"] = str(python.resolve())
    if payload["version_info"][:2] != [3, 10]:
        raise RuntimeError("CodeGuard+ audit environment must use Python 3.10")
    missing = []
    for module in REQUIRED_IMPORTS:
        result = subprocess.run(
            [str(python), "-c", f"import {module}"], capture_output=True, text=True
        )
        if result.returncode != 0:
            missing.append(module)
    if missing:
        raise RuntimeError(f"Missing CodeGuard+ Python imports: {missing}")
    return payload


def codeql_paths(root: Path, expected_version: str) -> dict[str, Path]:
    root = root.expanduser().resolve()
    cli_root = root / f"codeql-cli-{expected_version}/codeql"
    query_root = root / f"codeql-repo-{expected_version}"
    home = root / "home"
    packages = home / ".codeql/packages"
    result = {
        "root": root,
        "cli_root": cli_root,
        "binary": cli_root / "codeql",
        "query_root": query_root,
        "home": home,
        "packages": packages,
    }
    for name in ("binary", "query_root", "packages"):
        if not result[name].exists():
            raise FileNotFoundError(result[name])
    return result


def codeql_metadata(paths: dict[str, Path], expected_version: str) -> dict[str, Any]:
    version_text = subprocess.run(
        [str(paths["binary"]), "version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if expected_version not in version_text:
        raise RuntimeError(f"Unexpected CodeQL version: {version_text}")
    commit = git_output(paths["query_root"], "rev-parse", "HEAD")
    if git_output(paths["query_root"], "status", "--porcelain"):
        raise RuntimeError("CodeQL query repository is dirty")
    archive_hash_path = paths["cli_root"].parent / "download.sha256"
    archive_url_path = paths["cli_root"].parent / "download.url"
    return {
        "version": expected_version,
        "version_output": version_text,
        "binary": str(paths["binary"]),
        "binary_sha256": sha256_file(paths["binary"]),
        "query_repository": str(paths["query_root"]),
        "query_repository_commit": commit,
        "package_root": str(paths["packages"]),
        "archive_sha256": (
            archive_hash_path.read_text(encoding="utf-8").split()[0]
            if archive_hash_path.is_file()
            else None
        ),
        "archive_url": (
            archive_url_path.read_text(encoding="utf-8").strip()
            if archive_url_path.is_file()
            else None
        ),
    }


def network_seccomp_filter() -> Any:
    library_path = ctypes.util.find_library("seccomp")
    if not library_path:
        raise RuntimeError("libseccomp is required")
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
        deny = SECCOMP_ACTION_ERRNO | errno.EPERM
        for name in (b"socket", b"socketpair"):
            syscall = library.seccomp_syscall_resolve_name(name)
            if syscall < 0 or library.seccomp_rule_add(context, deny, syscall, 0) != 0:
                raise RuntimeError(f"Cannot deny {name.decode()}")
        if library.seccomp_export_bpf(context, output.fileno()) != 0:
            raise RuntimeError("Cannot export seccomp filter")
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise
    finally:
        library.seccomp_release(context)


def add_dir_chain(command: list[str], path: Path) -> None:
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        command.extend(("--dir", str(current)))


def python_roots(info: dict[str, Any]) -> list[Path]:
    roots = {Path(info["prefix"]), Path(info["base_prefix"])}
    return sorted(
        (p for p in roots if p != Path("/usr") and Path("/usr") not in p.parents),
        key=lambda p: (len(p.parts), str(p)),
    )


def sandbox_base(stage: Path, seccomp_fd: int) -> list[str]:
    return [
        str(BWRAP),
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--die-with-parent",
        "--new-session",
        "--hostname",
        "codeguardplus-sandbox",
        "--clearenv",
        "--setenv",
        "HOME",
        "/workspace/home",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/etc",
        "/etc",
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
        "--seccomp",
        str(seccomp_fd),
        "--dir",
        "/workspace",
        "--bind",
        str(stage),
        "/workspace",
        "--chdir",
        "/workspace",
    ]


def run_process(
    command: list[str], log: Path, timeout: float, *, pass_fds: tuple[int, ...]
) -> dict[str, Any]:
    started = time.monotonic()
    with log.open("wb") as stream:
        process = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=pass_fds,
            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)),
        )
        try:
            return_code = process.wait(timeout=timeout)
            status = "completed" if return_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return_code = None
            status = "timeout"
    prefix = log.read_bytes()[:4096]
    if prefix.startswith(b"bwrap:") or prefix.startswith(b"prlimit:"):
        status = "infrastructure_error"
    return {
        "status": status,
        "return_code": return_code,
        "wall_seconds": round(time.monotonic() - started, 6),
        "log": file_record(log),
    }


def select_tasks(
    config: dict[str, Any], manifest: dict[str, Any], requested: list[str] | None
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    manifest_tasks = {task["task_id"]: task for task in manifest["tasks"]}
    configured = {item["task_id"]: item for item in config["tasks"]}
    selected_ids = requested or list(configured)
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("Duplicate task selection")
    unknown = set(selected_ids) - set(configured)
    if unknown:
        raise ValueError(f"Tasks absent from frozen smoke config: {sorted(unknown)}")
    result = []
    for task_id in selected_ids:
        task = manifest_tasks[task_id]
        if task["language"] != "python":
            raise ValueError(f"Non-Python smoke task: {task_id}")
        if not task["eligibility"]["candidate_for_oracle_audit"]:
            raise ValueError(f"Ineligible inventory task: {task_id}")
        verified_record(task["tests"]["functional"]["entrypoint"])
        for support in task["tests"]["functional"]["support_files"]:
            verified_record(support)
        verified_record(task["source"]["file_context"])
        verified_record(task["source"]["function_context"])
        verified_record(configured[task_id]["candidate"])
        result.append((task, configured[task_id]))
    return result


def prepare_functional_stage(
    stage: Path, task: dict[str, Any], candidate: Path
) -> tuple[Path, Path]:
    candidate_dir = stage / "candidates"
    candidate_dir.mkdir(parents=True)
    shutil.copy2(candidate, candidate_dir / "candidate.py")
    unit_root = stage / "unit_test"
    task_test_dir = ROOT / "third_party/CodeGuardPlus/unit_test" / task["task_id"]
    shutil.copytree(task_test_dir, unit_root / task["task_id"])
    shutil.copy2(
        ROOT / "third_party/CodeGuardPlus/unit_test/test_utils.py",
        unit_root / "test_utils.py",
    )
    (stage / "home").mkdir()
    write_json(stage / "stat.json", {"candidate.py": {"functional": None}})
    return unit_root / task["task_id"] / "functional.py", candidate_dir


def functional_command(
    stage: Path,
    python: Path,
    info: dict[str, Any],
    script: Path,
    candidate_dir: Path,
    seccomp_fd: int,
) -> list[str]:
    command = sandbox_base(stage, seccomp_fd)
    command.extend(("--setenv", "PATH", f"{python.parent}:/usr/bin:/bin"))
    command.extend(("--setenv", "PYTHONDONTWRITEBYTECODE", "1"))
    command.extend(("--setenv", "PYTHONNOUSERSITE", "1"))
    for root in python_roots(info):
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
            "/workspace/" + script.relative_to(stage).as_posix(),
            "--path",
            "/workspace/" + candidate_dir.relative_to(stage).as_posix(),
        )
    )
    return command


def run_functional(
    task: dict[str, Any],
    candidate: Path,
    python: Path,
    python_info: dict[str, Any],
    log: Path,
    timeout: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sectdd-codeguard-func-") as temp:
        stage = Path(temp)
        script, candidate_dir = prepare_functional_stage(stage, task, candidate)
        with network_seccomp_filter() as seccomp:
            process = run_process(
                functional_command(
                    stage, python, python_info, script, candidate_dir, seccomp.fileno()
                ),
                log,
                timeout,
                pass_fds=(seccomp.fileno(),),
            )
        stat_path = stage / "stat.json"
        stat = json.loads(stat_path.read_text()) if stat_path.is_file() else None
        observed = stat.get("candidate.py", {}).get("functional") if stat else None
    decision_source = "benchmark_stat_json"
    if process["status"] in {"timeout", "infrastructure_error"}:
        status = process["status"]
        passed = None
    elif observed is True:
        status = "pass"
        passed = True
    elif observed is False:
        status = "fail"
        passed = False
    else:
        # Some upstream TestWrapper tests use subTest. unittest suppresses the
        # exception inside that context, so the benchmark's outer exception
        # handler never appends a result and stat.json remains null. Preserve
        # the benchmark test outcome by parsing unittest's own final marker.
        output = log.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?m)^FAILED \(", output):
            status = "fail"
            passed = False
            decision_source = "unittest_final_marker_fallback"
        elif re.search(r"(?m)^OK(?: \(|$)", output):
            status = "pass"
            passed = True
            decision_source = "unittest_final_marker_fallback"
        else:
            status = "oracle_error"
            passed = None
            decision_source = "unresolved"
    return {
        **process,
        "status": status,
        "passed": passed,
        "stat": stat,
        "decision_source": decision_source,
    }


def resolve_query(
    task: dict[str, Any], paths: dict[str, Path]
) -> tuple[Path, str]:
    security = task["tests"]["security"]
    if security["source_type"] == "codeql_standard_bundle":
        query = paths["query_root"] / security["bundle_relative_path"]
        source_type = "codeql_standard_bundle"
    elif security["source_type"] == "benchmark_repository":
        query = verified_record(security["resolved_file"])
        source_type = "benchmark_repository"
    else:
        raise RuntimeError(f"No runnable security query for {task['task_id']}")
    if not query.is_file():
        raise FileNotFoundError(query)
    return query, source_type


def codeql_command(
    stage: Path,
    paths: dict[str, Path],
    args: list[str],
    seccomp_fd: int,
) -> list[str]:
    command = sandbox_base(stage, seccomp_fd)
    command.extend(("--dir", "/opt", "--ro-bind", str(paths["cli_root"]), "/opt/codeql"))
    command.extend(("--ro-bind", str(paths["query_root"]), "/opt/codeql-repo"))
    command.extend(("--ro-bind", str(paths["packages"]), "/opt/codeql-packages"))
    command.extend(("--setenv", "PATH", "/opt/codeql:/usr/bin:/bin"))
    # JAVA_TOOL_OPTIONS also reaches CodeQL subprocesses such as the YAML
    # indexer spawned during Python database finalization.
    command.extend(
        (
            "--setenv",
            "JAVA_TOOL_OPTIONS",
            "-XX:ActiveProcessorCount=2 -XX:+UseSerialGC -Xmx4096m",
        )
    )
    command.extend(
        (
            "--",
            "/usr/bin/prlimit",
            "--as=8589934592",
            "--cpu=300",
            "--fsize=2147483648",
            "--nofile=1024",
            # CodeQL's JVM otherwise sizes its GC/thread pools from every host
            # core. RLIMIT_NPROC is per real UID, so a low limit also counts
            # unrelated processes owned by the researcher on a shared server.
            "--nproc=4096",
            "--",
            "/opt/codeql/codeql",
            *args[:2],
            "-J=-XX:ActiveProcessorCount=2",
            "-J=-XX:+UseSerialGC",
            "-J=-Xmx4096m",
            *args[2:],
        )
    )
    return command


def cwe78_false_positive(row: list[str], candidate: Path) -> bool:
    """Reproduce the benchmark's list-argument suppression for CWE-78."""
    if len(row) < 9:
        return False
    try:
        import libcst as cst
        from libcst.metadata import PositionProvider
        from libcst._position import CodePosition
    except ImportError as exc:
        raise RuntimeError("libcst is required for CWE-78 filtering") from exc

    start = CodePosition(int(row[-4]), int(row[-3]) - 1)
    end = CodePosition(int(row[-2]), int(row[-1]))

    class Visitor(cst.CSTVisitor):
        METADATA_DEPENDENCIES = (PositionProvider,)

        def __init__(self) -> None:
            self.list_vars: set[str] = set()
            self.fp = False

        def visit_Assign(self, node: Any) -> None:
            if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name):
                return
            name = node.targets[0].target.value
            if isinstance(node.value, cst.List):
                if node.value.elements and isinstance(node.value.elements[0].value, cst.BaseString):
                    self.list_vars.add(name)
            elif isinstance(node.value, cst.Name) and node.value.value in self.list_vars:
                self.list_vars.add(name)
            elif isinstance(node.value, cst.BinaryOperation):
                for side in (node.value.left, node.value.right):
                    if isinstance(side, cst.List) or (
                        isinstance(side, cst.Name) and side.value in self.list_vars
                    ):
                        self.list_vars.add(name)

        def visit_Name(self, node: Any) -> None:
            position = self.get_metadata(PositionProvider, node)
            if (
                position.start.line == start.line
                and position.start.column == start.column
                and position.end.line == end.line
                and position.end.column == end.column
                and node.value in self.list_vars
            ):
                self.fp = True

    visitor = Visitor()
    cst.MetadataWrapper(cst.parse_module(candidate.read_text())).visit(visitor)
    return visitor.fp


def run_codeql(
    task: dict[str, Any],
    candidate: Path,
    paths: dict[str, Path],
    log_root: Path,
    timeout: float,
) -> dict[str, Any]:
    query, source_type = resolve_query(task, paths)
    query_record = {
        "input_path": str(query),
        "sha256": sha256_file(query),
        "size_bytes": query.stat().st_size,
        "source_type": source_type,
    }
    with tempfile.TemporaryDirectory(prefix="sectdd-codeguard-codeql-") as temp:
        stage = Path(temp)
        source = stage / "source"
        source.mkdir()
        shutil.copy2(candidate, source / "candidate.py")
        (stage / "home").mkdir()
        if source_type == "benchmark_repository":
            shutil.copytree(query.parent, stage / "custom-query")
            inner_query = "/workspace/custom-query/" + query.name
        else:
            inner_query = "/opt/codeql-repo/" + query.relative_to(paths["query_root"]).as_posix()
        create_log = log_root / "codeql-create.log"
        with network_seccomp_filter() as seccomp:
            create = run_process(
                codeql_command(
                    stage,
                    paths,
                    [
                        "database",
                        "create",
                        "/workspace/database",
                        "--language=python",
                        "--source-root=/workspace/source",
                        "--overwrite",
                        "--threads=2",
                        "--ram=4096",
                        "--quiet",
                    ],
                    seccomp.fileno(),
                ),
                create_log,
                timeout,
                pass_fds=(seccomp.fileno(),),
            )
        if create["status"] != "completed":
            return {
                "status": "infrastructure_error",
                "passed": None,
                "query": query_record,
                "database_create": create,
                "database_analyze": None,
                "raw_finding_count": None,
                "filtered_finding_count": None,
            }
        analyze_log = log_root / "codeql-analyze.log"
        with network_seccomp_filter() as seccomp:
            analyze = run_process(
                codeql_command(
                    stage,
                    paths,
                    [
                        "database",
                        "analyze",
                        "/workspace/database",
                        inner_query,
                        "--format=csv",
                        "--output=/workspace/codeql.csv",
                        "--rerun",
                        "--threads=2",
                        "--ram=4096",
                        "--quiet",
                        "--additional-packs=/opt/codeql-packages",
                    ],
                    seccomp.fileno(),
                ),
                analyze_log,
                timeout,
                pass_fds=(seccomp.fileno(),),
            )
        csv_path = stage / "codeql.csv"
        rows = []
        if analyze["status"] == "completed" and csv_path.is_file():
            with csv_path.open(newline="", encoding="utf-8") as stream:
                rows = [row for row in csv.reader(stream) if len(row) >= 5]
        raw_count = len(rows)
        if analyze["status"] != "completed" or not csv_path.is_file():
            return {
                "status": "oracle_error",
                "passed": None,
                "query": query_record,
                "database_create": create,
                "database_analyze": analyze,
                "raw_finding_count": None,
                "filtered_finding_count": None,
            }
        filtered = rows
        suppressed = 0
        if task["cwe"] == "CWE-78":
            filtered = []
            for row in rows:
                if cwe78_false_positive(row, candidate):
                    suppressed += 1
                else:
                    filtered.append(row)
        copied_csv = log_root / "codeql.csv"
        shutil.copy2(csv_path, copied_csv)
    return {
        "status": "pass" if not filtered else "fail",
        "passed": not filtered,
        "query": query_record,
        "database_create": create,
        "database_analyze": analyze,
        "raw_finding_count": raw_count,
        "suppressed_cwe78_false_positives": suppressed,
        "filtered_finding_count": len(filtered),
        "csv": file_record(copied_csv),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    states = Counter()
    statuses = Counter()
    for item in results:
        functional = item["functional"]["passed"]
        security = item["security"]["passed"]
        if functional is None or security is None:
            state = "infrastructure_or_oracle_error"
        else:
            state = f"F{'+' if functional else '-'}S{'+' if security else '-'}"
        states[state] += 1
        statuses[item["status"]] += 1
    return {
        "result_count": len(results),
        "task_count": len({item["task_id"] for item in results}),
        "state_counts": dict(sorted(states.items())),
        "status_counts": dict(sorted(statuses.items())),
        "complete": bool(results) and not statuses.get("infrastructure_error"),
        "formal_results_use": False,
    }


def main() -> None:
    args = parse_args()
    if args.repeats < 1 or args.repeats > 5:
        raise ValueError("--repeats must be between 1 and 5")
    config, manifest, config_path = load_inputs(args.config)
    python = args.python.expanduser().absolute()
    py_info = python_metadata(python)
    paths = codeql_paths(args.codeql_root, config["codeql"]["cli_version"])
    cq_info = codeql_metadata(paths, config["codeql"]["cli_version"])
    selected = select_tasks(config, manifest, args.tasks)
    if args.doctor:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "python": py_info,
                    "codeql": cq_info,
                    "tasks": [task["task_id"] for task, _ in selected],
                    "bubblewrap": str(BWRAP),
                },
                indent=2,
            )
        )
        return
    if args.output is None:
        raise ValueError("--output is required unless --doctor is used")
    output = checked_project_path(args.output, exists=False)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    logs = output / "logs"
    logs.mkdir()
    manifest_out = {
        "schema_version": 1,
        "created_at_utc": utc_now(),
        "study_phase": "codeguardplus_python_infrastructure_smoke",
        "development_only": True,
        "formal_results_use": False,
        "config": file_record(config_path),
        "benchmark_manifest": file_record(verified_record(config["benchmark_manifest"])),
        "repository_commit": config["repository_commit"],
        "tasks": [task["task_id"] for task, _ in selected],
        "repeats": args.repeats,
        "python_environment": py_info,
        "codeql_environment": cq_info,
        "sandbox": {
            "bubblewrap": str(BWRAP),
            "unshare_network": True,
            "seccomp_denied_syscalls": ["socket", "socketpair"],
            "candidate_imported_in_parent": False,
            "ephemeral_workspace_per_oracle": True,
        },
    }
    write_json(output / "run_manifest.json", manifest_out)
    results = []
    results_path = output / "results.jsonl"
    for task, selection in selected:
        candidate = verified_record(selection["candidate"])
        for repeat in range(1, args.repeats + 1):
            result_root = logs / re.sub(r"[^A-Za-z0-9_.-]", "_", task["task_id"]) / f"repeat-{repeat}"
            result_root.mkdir(parents=True)
            functional = run_functional(
                task,
                candidate,
                python,
                py_info,
                result_root / "functional.log",
                args.functional_timeout,
            )
            security = run_codeql(task, candidate, paths, result_root, args.codeql_timeout)
            status = (
                "completed"
                if functional["passed"] is not None and security["passed"] is not None
                else "infrastructure_error"
            )
            item = {
                "task_id": task["task_id"],
                "cwe": task["cwe"],
                "repeat": repeat,
                "status": status,
                "candidate": file_record(candidate),
                "functional": functional,
                "security": security,
                "joint_pass": (
                    functional["passed"] and security["passed"]
                    if status == "completed"
                    else None
                ),
            }
            results.append(item)
            with results_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            print(
                f"[{len(results)}/{len(selected) * args.repeats}] {task['task_id']} "
                f"repeat={repeat} F={functional['passed']} S={security['passed']}",
                flush=True,
            )
    summary = summarize(results)
    summary["updated_at_utc"] = utc_now()
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
