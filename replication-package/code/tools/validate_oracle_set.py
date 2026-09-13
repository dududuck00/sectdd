#!/usr/bin/env python3
"""Validate an oracle manifest and its reference/mutant discrimination matrix."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from tools.cweval_sandbox import (
    CWEVAL_ROOT,
    PROJECT_ROOT,
    VENV_PYTHON,
    install_pytest_config,
    run_in_sandbox,
)
from tools.oracle_manifest import (
    load_oracle_manifest,
    manifest_dependency_digest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=PROJECT_ROOT / "schemas" / "oracle_manifest.schema.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--wall-timeout", type=int, default=60)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_project_file(base: Path, raw_path: str) -> Path:
    path = (base / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Oracle path escapes project root: {path}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def pytest_test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def static_validate(manifest: dict, base: Path) -> dict[str, Path]:
    global_case_ids = set()
    resolved_files: dict[str, Path] = {}
    for task, task_data in manifest["tasks"].items():
        cases = task_data["cases"]
        case_ids = [case["case_id"] for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise AssertionError(f"{task}: duplicate case IDs")
        overlap = global_case_ids & set(case_ids)
        if overlap:
            raise AssertionError(f"Globally duplicate case IDs: {sorted(overlap)}")
        global_case_ids.update(case_ids)

        visible_families = {
            case["behavior_family"]
            for case in cases
            if case["partition"] == "visible"
        }
        hidden_families = {
            case["behavior_family"]
            for case in cases
            if case["partition"] == "hidden"
        }
        if visible_families & hidden_families:
            raise AssertionError(
                f"{task}: behavior families cross partitions: "
                f"{sorted(visible_families & hidden_families)}"
            )

        for partition in ("visible", "hidden"):
            partition_cases = [
                case for case in cases if case["partition"] == partition
            ]
            for marker in ("functionality", "security"):
                count = sum(
                    case["marker"] == marker for case in partition_cases
                )
                if count < 2:
                    raise AssertionError(
                        f"{task}/{partition}: requires >=2 {marker} cases"
                    )
            oracle_path = resolve_project_file(
                base, task_data["oracles"][partition]
            )
            resolved_files[f"{task}:oracle:{partition}"] = oracle_path
            declared_names = {
                case["test_name"] for case in partition_cases
            }
            actual_names = pytest_test_names(oracle_path)
            if declared_names != actual_names:
                raise AssertionError(
                    f"{task}/{partition}: manifest/test mismatch; "
                    f"missing={sorted(actual_names - declared_names)}, "
                    f"extra={sorted(declared_names - actual_names)}"
                )

        references = [
            subject
            for subject in task_data["subjects"]
            if subject["kind"] == "reference"
        ]
        if len(references) != 1:
            raise AssertionError(f"{task}: requires exactly one reference")
        if not any(
            subject["kind"] == "mutant"
            and subject["expected_visible"]
            and not subject["expected_hidden"]
            for subject in task_data["subjects"]
        ):
            raise AssertionError(
                f"{task}: requires a visible-passing, hidden-failing mutant"
            )
        for subject in task_data["subjects"]:
            subject_path = resolve_project_file(base, subject["source"])
            resolved_files[
                f"{task}:subject:{subject['subject_id']}"
            ] = subject_path
    return resolved_files


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def run_one(
    *,
    output: Path,
    task: str,
    subject: dict,
    subject_path: Path,
    partition: str,
    oracle_path: Path,
    expected_tests: int,
    repeat: int,
    wall_timeout: int,
) -> dict:
    eval_path = (
        output
        / "runs"
        / task
        / subject["subject_id"]
        / partition
        / f"repeat_{repeat}"
    )
    eval_path.mkdir(parents=True)
    shutil.copy2(subject_path, eval_path / "oracle_subject.py")
    shutil.copy2(oracle_path, eval_path / "test_oracle.py")
    install_pytest_config(eval_path)
    junit_path = eval_path / "junit.xml"
    command = [
        str(VENV_PYTHON),
        "-m",
        "pytest",
        str(eval_path / "test_oracle.py"),
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    return_code = 0
    try:
        log_path = run_in_sandbox(
            eval_path,
            1,
            20,
            wall_timeout,
            inner_command=command,
            log_name=(
                f"oracle.{task}.{subject['subject_id']}."
                f"{partition}.repeat_{repeat}.log"
            ),
        )
    except subprocess.CalledProcessError as error:
        return_code = error.returncode
        log_path = (
            PROJECT_ROOT
            / "artifacts"
            / "logs"
            / (
                f"oracle.{task}.{subject['subject_id']}."
                f"{partition}.repeat_{repeat}.log"
            )
        )
    if not junit_path.is_file():
        raise AssertionError(f"Missing JUnit report; see {log_path}")
    counts = junit_counts(junit_path)
    if counts["tests"] != expected_tests or counts["errors"]:
        raise AssertionError(
            f"{task}/{subject['subject_id']}/{partition}: "
            f"invalid execution {counts}; see {log_path}"
        )
    passed = return_code == 0 and counts["failures"] == 0
    if not passed and counts["failures"] == 0:
        raise AssertionError(
            f"{task}/{subject['subject_id']}/{partition}: "
            f"non-assertion pytest failure; see {log_path}"
        )
    return {
        "repeat": repeat,
        "passed": passed,
        "pytest_return_code": return_code,
        "junit": counts,
        "log": str(log_path),
    }


def main() -> None:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    manifest_path = args.manifest.expanduser().resolve()
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest, manifest_sources = load_oracle_manifest(manifest_path)
    schema = json.loads(args.schema.resolve().read_text(encoding="utf-8"))
    jsonschema.validate(raw_manifest, schema)
    resolved_files = static_validate(manifest, manifest_path.parent)

    output = (
        args.output.expanduser().resolve()
        if args.output
        else PROJECT_ROOT
        / "artifacts"
        / "oracle_validation"
        / manifest["oracle_set_id"]
    )
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; choose a new --output"
        )
    output.mkdir(parents=True)
    records = []
    for task, task_data in manifest["tasks"].items():
        for subject in task_data["subjects"]:
            for partition in ("visible", "hidden"):
                expected = subject[f"expected_{partition}"]
                partition_cases = [
                    case
                    for case in task_data["cases"]
                    if case["partition"] == partition
                ]
                executions = [
                    run_one(
                        output=output,
                        task=task,
                        subject=subject,
                        subject_path=resolved_files[
                            f"{task}:subject:{subject['subject_id']}"
                        ],
                        partition=partition,
                        oracle_path=resolved_files[
                            f"{task}:oracle:{partition}"
                        ],
                        expected_tests=len(partition_cases),
                        repeat=repeat,
                        wall_timeout=args.wall_timeout,
                    )
                    for repeat in range(args.repeats)
                ]
                observed = [execution["passed"] for execution in executions]
                if any(value != expected for value in observed):
                    raise AssertionError(
                        f"{task}/{subject['subject_id']}/{partition}: "
                        f"expected {expected}, observed {observed}"
                    )
                records.append(
                    {
                        "task": task,
                        "subject": subject["subject_id"],
                        "kind": subject["kind"],
                        "partition": partition,
                        "expected_pass": expected,
                        "observed_pass": observed,
                        "executions": executions,
                    }
                )
                print(
                    f"{task} {subject['subject_id']} {partition}: "
                    f"{observed}",
                    flush=True,
                )

    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_set_id": manifest["oracle_set_id"],
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_sources_sha256": manifest_sources,
        "manifest_dependency_digest": manifest_dependency_digest(
            manifest_sources
        ),
        "repeats": args.repeats,
        "files_sha256": {
            key: sha256_file(path)
            for key, path in sorted(resolved_files.items())
        },
        "records": records,
        "passed": True,
    }
    report_path = output / "validation_report.json"
    report_path.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Oracle validation passed: {report_path}")


if __name__ == "__main__":
    main()
