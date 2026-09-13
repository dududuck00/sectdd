#!/usr/bin/env python3
"""Build deterministic inventory manifests for external security benchmarks.

The manifests produced here describe only the material present in the pinned
third-party repositories.  They do not claim that a task's oracle is valid:
reference execution and oracle qualification happen in a later stage.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "external_benchmark_manifest.schema.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "benchmarks" / "manifests"
SALLM_DEFAULT_ROOT = PROJECT_ROOT / "third_party" / "SALLM"
CODEGUARDPLUS_DEFAULT_ROOT = PROJECT_ROOT / "third_party" / "CodeGuardPlus"

SALLM_FUNCTIONAL_METHODS = {"test_correctness", "test_functionality"}
SALLM_SECURITY_METHODS = {"test_vulnerability", "test_security"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic SALLM and CodeGuard+ benchmark "
            "inventory manifests."
        )
    )
    parser.add_argument("--sallm-root", type=Path, default=SALLM_DEFAULT_ROOT)
    parser.add_argument(
        "--codeguardplus-root",
        type=Path,
        default=CODEGUARDPLUS_DEFAULT_ROOT,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if checked-in manifests differ from freshly generated data.",
    )
    return parser.parse_args()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_text(content: str) -> str:
    return sha256_bytes(content.encode("utf-8"))


def project_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def file_record(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": project_relative(path),
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
    }


def optional_file_record(path: Path) -> dict[str, Any] | None:
    return file_record(path) if path.is_file() else None


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def repository_record(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        raise FileNotFoundError(f"Not a Git checkout: {root}")
    dirty_entries = [
        line
        for line in git_output(root, "status", "--porcelain").splitlines()
        if line
    ]
    if dirty_entries:
        raise RuntimeError(
            f"Third-party repository must be clean: {root}\n"
            + "\n".join(dirty_entries)
        )
    return {
        "path": project_relative(root),
        "remote_url": git_output(root, "remote", "get-url", "origin"),
        "commit": git_output(root, "rev-parse", "HEAD"),
        "commit_date": git_output(root, "show", "-s", "--format=%cI", "HEAD"),
        "dirty": False,
    }


def normalize_cwe(value: str) -> str:
    match = re.search(r"(?i)cwe[-_]?(\d+)", value)
    if not match:
        raise ValueError(f"Cannot extract CWE from: {value}")
    number = int(match.group(1))
    return f"CWE-{number}"


def requirement_items(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def docker_base_image(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*FROM\s+(\S+)", line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def unittest_methods(path: Path) -> tuple[list[dict[str, str]], str | None]:
    if not path.is_file():
        return [], None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [], f"{exc.__class__.__name__}: {exc}"

    methods = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                child.name.startswith("test_")
            ):
                methods.append(
                    {
                        "class_name": node.name,
                        "method": child.name,
                        "unittest_target": f"{node.name}.{child.name}",
                    }
                )
    return sorted(
        methods,
        key=lambda item: (item["class_name"], item["method"]),
    ), None


def render_json(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def build_sallm_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    dataset_path = root / "Dataset" / "dataset.jsonl"
    rows = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tasks: list[dict[str, Any]] = []

    for line_number, row in enumerate(rows, start=1):
        task_id = row["id"]
        technique = row["technique"]
        origin = row["source"]
        prefix = f"{technique}_{origin}_"
        issues: list[str] = []
        if not task_id.startswith(prefix):
            raise ValueError(
                f"{dataset_path}:{line_number}: id {task_id!r} does not "
                f"start with {prefix!r}"
            )

        source_name = task_id[len(prefix) :]
        source_path = root / "Dataset" / technique / origin / source_name
        stem = Path(source_name).stem
        task_dir = source_path.parent
        test_path = task_dir / f"test_{source_name}"
        requirements_path = task_dir / f"{stem}_requirements.txt"
        dockerfile_path = task_dir / f"{stem}_Dockerfile"

        try:
            cwe = normalize_cwe(stem)
        except ValueError:
            cwe = None
            issues.append("missing_cwe")

        if not source_path.is_file():
            issues.append("missing_reference_source")
        if not requirements_path.is_file():
            issues.append("missing_requirements_file")
        if not dockerfile_path.is_file():
            issues.append("missing_environment_spec")
        if not test_path.is_file():
            issues.append("missing_test_file")

        discovered_methods, parse_error = unittest_methods(test_path)
        if parse_error:
            issues.append("test_syntax_error")
        functional_methods = [
            item
            for item in discovered_methods
            if item["method"] in SALLM_FUNCTIONAL_METHODS
        ]
        security_methods = [
            item
            for item in discovered_methods
            if item["method"] in SALLM_SECURITY_METHODS
        ]
        unclassified_methods = [
            item
            for item in discovered_methods
            if item["method"]
            not in SALLM_FUNCTIONAL_METHODS | SALLM_SECURITY_METHODS
        ]
        if test_path.is_file() and not functional_methods:
            issues.append("missing_functional_test_method")
        if test_path.is_file() and not security_methods:
            issues.append("missing_security_test_method")
        if unclassified_methods:
            issues.append("unclassified_test_method")

        source_record = optional_file_record(source_path)
        source_matches_dataset = (
            source_path.read_text(encoding="utf-8") == row["insecure_code"]
            if source_path.is_file()
            else False
        )
        if source_path.is_file() and not source_matches_dataset:
            issues.append("reference_source_differs_from_dataset")

        inventory_complete = all(
            path.is_file()
            for path in (source_path, requirements_path, dockerfile_path)
        )
        has_joint_tests = bool(
            test_path.is_file() and functional_methods and security_methods
        )

        tasks.append(
            {
                "task_id": task_id,
                "cwe": cwe,
                "language": "python",
                "source": {
                    "dataset": file_record(dataset_path),
                    "dataset_line": line_number,
                    "technique": technique,
                    "origin": origin,
                    "prompt_sha256": sha256_text(row["prompt"]),
                    "insecure_code_sha256": sha256_text(row["insecure_code"]),
                    "reference_file": source_record,
                    "reference_matches_dataset": source_matches_dataset,
                },
                "tests": {
                    "framework": "unittest",
                    "entrypoint": optional_file_record(test_path),
                    "functional": functional_methods,
                    "security": security_methods,
                    "unclassified": unclassified_methods,
                    "parse_error": parse_error,
                },
                "dependencies": {
                    "requirement_file": optional_file_record(requirements_path),
                    "python_requirements": requirement_items(requirements_path),
                    "environment_spec": optional_file_record(dockerfile_path),
                    "declared_base_image": docker_base_image(dockerfile_path),
                },
                "eligibility": {
                    "inventory_complete": inventory_complete,
                    "has_joint_tests": has_joint_tests,
                    "candidate_for_oracle_audit": (
                        inventory_complete and has_joint_tests
                    ),
                    "issues": sorted(set(issues)),
                },
            }
        )

    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("SALLM contains duplicate task IDs")

    eligible = [
        task
        for task in tasks
        if task["eligibility"]["candidate_for_oracle_audit"]
    ]
    issue_counts = Counter(
        issue
        for task in tasks
        for issue in task["eligibility"]["issues"]
    )
    return {
        "$schema": project_relative(SCHEMA_PATH),
        "schema_version": 1,
        "manifest_type": "external_benchmark_inventory",
        "benchmark": {
            "name": "SALLM",
            "version_label": "git-pinned-main",
            "evaluation_scope": (
                "Dynamic functional and security unittest inventory"
            ),
        },
        "repository": repository_record(root),
        "generator": {
            "path": project_relative(Path(__file__)),
            "policy_version": 1,
            "deterministic": True,
        },
        "status": "inventory_only",
        "summary": {
            "task_count": len(tasks),
            "cwe_count": len({task["cwe"] for task in tasks if task["cwe"]}),
            "language_counts": dict(
                sorted(Counter(task["language"] for task in tasks).items())
            ),
            "tasks_with_joint_tests": sum(
                task["eligibility"]["has_joint_tests"] for task in tasks
            ),
            "candidate_for_oracle_audit_count": len(eligible),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "tasks": sorted(tasks, key=lambda task: task["task_id"]),
    }


def codeql_query_record(
    root: Path, declared_path: str | None
) -> dict[str, Any] | None:
    if not declared_path:
        return None
    bundle_prefix = "~/codeql/codeql-repo/"
    if declared_path.startswith(bundle_prefix):
        return {
            "evaluator": "codeql",
            "source_type": "codeql_standard_bundle",
            "declared_path": declared_path,
            "bundle_relative_path": declared_path[len(bundle_prefix) :],
            "resolved_file": None,
        }

    resolved = root / declared_path
    return {
        "evaluator": "codeql",
        "source_type": "benchmark_repository",
        "declared_path": declared_path,
        "bundle_relative_path": None,
        "resolved_file": optional_file_record(resolved),
    }


def build_codeguardplus_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    data_root = root / "data" / "base"
    test_root = root / "unit_test"
    global_requirements = root / "requirements.txt"
    common_requirements = requirement_items(global_requirements)
    tasks: list[dict[str, Any]] = []

    for info_path in sorted(data_root.glob("*/*/info.json")):
        task_dir = info_path.parent
        task_id = task_dir.relative_to(data_root).as_posix()
        info = json.loads(info_path.read_text(encoding="utf-8"))
        language_code = info["language"]
        language = {"py": "python", "c": "c"}.get(
            language_code, language_code
        )
        issues: list[str] = []

        directory_cwe = normalize_cwe(task_dir.parent.name)
        try:
            declared_cwe = normalize_cwe(info["cwe"])
        except (KeyError, ValueError):
            declared_cwe = None
            issues.append("missing_cwe")
        cwe = declared_cwe or directory_cwe
        if declared_cwe and declared_cwe != directory_cwe:
            issues.append("cwe_directory_mismatch")

        file_context = task_dir / f"file_context.{language_code}"
        function_context = task_dir / f"func_context.{language_code}"
        unit_dir = test_root / task_id
        functional_entrypoint = unit_dir / "functional.py"
        if not file_context.is_file():
            issues.append("missing_file_context")
        if not function_context.is_file():
            issues.append("missing_function_context")
        if not functional_entrypoint.is_file():
            issues.append("missing_functional_test")

        methods, parse_error = unittest_methods(functional_entrypoint)
        if parse_error:
            issues.append("functional_test_syntax_error")

        support_files = (
            [
                file_record(path)
                for path in sorted(unit_dir.rglob("*"))
                if path.is_file() and path != functional_entrypoint
            ]
            if unit_dir.is_dir()
            else []
        )

        query = codeql_query_record(root, info.get("check_ql"))
        if query is None:
            issues.append("missing_security_query")
        elif (
            query["source_type"] == "benchmark_repository"
            and query["resolved_file"] is None
        ):
            issues.append("missing_repository_security_query")

        dependency_set_ids = ["codeguardplus-python-runtime"]
        if language in {"c", "cpp"}:
            dependency_set_ids.append("codeguardplus-c-toolchain")
        if query is not None:
            dependency_set_ids.append("codeguardplus-codeql")

        inventory_complete = all(
            path.is_file()
            for path in (
                info_path,
                file_context,
                function_context,
                functional_entrypoint,
            )
        )
        has_security_oracle = query is not None and not (
            query["source_type"] == "benchmark_repository"
            and query["resolved_file"] is None
        )

        tasks.append(
            {
                "task_id": task_id,
                "cwe": cwe,
                "language": language,
                "source": {
                    "info": file_record(info_path),
                    "scenario": info.get("scenario"),
                    "file_context": optional_file_record(file_context),
                    "function_context": optional_file_record(function_context),
                },
                "tests": {
                    "functional": {
                        "framework": "benchmark_script",
                        "entrypoint": optional_file_record(
                            functional_entrypoint
                        ),
                        "discovered_unittest_methods": methods,
                        "parse_error": parse_error,
                        "support_files": support_files,
                    },
                    "security": query,
                },
                "dependencies": {
                    "dependency_set_ids": dependency_set_ids,
                },
                "eligibility": {
                    "inventory_complete": inventory_complete,
                    "has_functional_tests": functional_entrypoint.is_file(),
                    "has_security_oracle_declaration": has_security_oracle,
                    "candidate_for_oracle_audit": (
                        inventory_complete and has_security_oracle
                    ),
                    "issues": sorted(set(issues)),
                },
            }
        )

    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("CodeGuard+ contains duplicate task IDs")

    eligible = [
        task
        for task in tasks
        if task["eligibility"]["candidate_for_oracle_audit"]
    ]
    issue_counts = Counter(
        issue
        for task in tasks
        for issue in task["eligibility"]["issues"]
    )
    query_source_counts = Counter(
        task["tests"]["security"]["source_type"]
        if task["tests"]["security"]
        else "missing"
        for task in tasks
    )
    return {
        "$schema": project_relative(SCHEMA_PATH),
        "schema_version": 1,
        "manifest_type": "external_benchmark_inventory",
        "benchmark": {
            "name": "CodeGuard+",
            "version_label": "git-pinned-main",
            "evaluation_scope": (
                "Functional test scripts and declared CodeQL security queries"
            ),
        },
        "repository": repository_record(root),
        "generator": {
            "path": project_relative(Path(__file__)),
            "policy_version": 1,
            "deterministic": True,
        },
        "status": "inventory_only",
        "dependency_sets": {
            "codeguardplus-python-runtime": {
                "kind": "python_requirements",
                "requirement_file": file_record(global_requirements),
                "requirements": common_requirements,
            },
            "codeguardplus-c-toolchain": {
                "kind": "system_tools",
                "tools": ["gcc", "g++"],
                "version": "not_yet_frozen",
            },
            "codeguardplus-codeql": {
                "kind": "security_analyzer",
                "tools": ["codeql"],
                "version": "not_yet_installed_or_frozen",
            },
        },
        "summary": {
            "task_count": len(tasks),
            "cwe_count": len({task["cwe"] for task in tasks if task["cwe"]}),
            "language_counts": dict(
                sorted(Counter(task["language"] for task in tasks).items())
            ),
            "tasks_with_functional_tests": sum(
                task["eligibility"]["has_functional_tests"] for task in tasks
            ),
            "tasks_with_security_oracle_declaration": sum(
                task["eligibility"]["has_security_oracle_declaration"]
                for task in tasks
            ),
            "security_query_source_counts": dict(
                sorted(query_source_counts.items())
            ),
            "candidate_for_oracle_audit_count": len(eligible),
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "tasks": sorted(tasks, key=lambda task: task["task_id"]),
    }


def validate_basic_invariants(manifest: dict[str, Any]) -> None:
    tasks = manifest["tasks"]
    if manifest["summary"]["task_count"] != len(tasks):
        raise AssertionError("summary.task_count does not match tasks")
    task_ids = [task["task_id"] for task in tasks]
    if task_ids != sorted(task_ids):
        raise AssertionError("tasks are not sorted by task_id")
    if len(task_ids) != len(set(task_ids)):
        raise AssertionError("task IDs are not unique")
    commit = manifest["repository"]["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AssertionError(f"Invalid Git commit: {commit}")


def build_all(
    sallm_root: Path, codeguardplus_root: Path
) -> dict[str, dict[str, Any]]:
    manifests = {
        "sallm-v1.json": build_sallm_manifest(sallm_root),
        "codeguardplus-v1.json": build_codeguardplus_manifest(
            codeguardplus_root
        ),
    }
    for manifest in manifests.values():
        validate_basic_invariants(manifest)
    return manifests


def build_index(rendered: dict[str, bytes]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "manifest_type": "external_benchmark_inventory_index",
        "generator": project_relative(Path(__file__)),
        "manifests": [
            {
                "benchmark": name.removesuffix("-v1.json"),
                "path": (
                    Path("benchmarks") / "manifests" / name
                ).as_posix(),
                "sha256": sha256_bytes(content),
            }
            for name, content in sorted(rendered.items())
        ],
    }


def write_or_check(
    output_dir: Path,
    manifests: dict[str, dict[str, Any]],
    *,
    check: bool,
) -> None:
    rendered = {
        filename: render_json(manifest)
        for filename, manifest in manifests.items()
    }
    rendered["index-v1.json"] = render_json(build_index(rendered))

    if check:
        mismatches = []
        for filename, expected in rendered.items():
            path = output_dir / filename
            if not path.is_file() or path.read_bytes() != expected:
                mismatches.append(str(path))
        if mismatches:
            raise SystemExit(
                "Manifest check failed; regenerate these files:\n"
                + "\n".join(mismatches)
            )
        print(f"OK: {len(rendered)} manifest files are current")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in rendered.items():
        path = output_dir / filename
        path.write_bytes(content)
        print(f"Wrote {path}")


def main() -> None:
    args = parse_args()
    manifests = build_all(
        args.sallm_root.expanduser(),
        args.codeguardplus_root.expanduser(),
    )
    write_or_check(
        args.output_dir.expanduser().resolve(),
        manifests,
        check=args.check,
    )


if __name__ == "__main__":
    main()
