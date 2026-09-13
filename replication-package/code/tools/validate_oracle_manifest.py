#!/usr/bin/env python3
"""Validate oracle schema, paths, behavior-family separation, and test mapping."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

import jsonschema


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "oracles" / "cweval_python_v1" / "manifest.json",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=PROJECT_ROOT / "schemas" / "oracle_draft_manifest.schema.json",
    )
    return parser.parse_args()


def project_path(raw_path: str) -> Path:
    path = (PROJECT_ROOT / raw_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise AssertionError(f"Path escapes project root: {raw_path}") from exc
    if not path.is_file():
        raise AssertionError(f"Missing file: {raw_path}")
    return path


def test_markers(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        markers = set()
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Attribute)
                and isinstance(decorator.value, ast.Attribute)
                and isinstance(decorator.value.value, ast.Name)
                and decorator.value.value.id == "pytest"
                and decorator.value.attr == "mark"
            ):
                markers.add(decorator.attr)
        if node.name.startswith("test_"):
            result[node.name] = markers
    return result


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    schema = json.loads(args.schema.resolve().read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)

    candidate_ids = set()
    mutants_by_task: dict[str, set[str]] = defaultdict(set)
    for candidate in manifest["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in candidate_ids:
            raise AssertionError(f"Duplicate candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        project_path(candidate["source"])
        if candidate["task"] not in manifest["tasks"]:
            raise AssertionError(f"Candidate has unknown task: {candidate_id}")
        if candidate["kind"] == "mutant":
            mutants_by_task[candidate["task"]].add(candidate_id)

    case_ids = set()
    node_keys = set()
    target_counts: dict[str, int] = defaultdict(int)
    total_cases = 0
    test_file_cache: dict[Path, dict[str, set[str]]] = {}
    for task, task_data in manifest["tasks"].items():
        project_path(task_data["source_task"])
        families = {"visible": set(), "hidden": set()}
        manifest_functions: dict[Path, set[str]] = defaultdict(set)
        for case in task_data["cases"]:
            total_cases += 1
            case_id = case["case_id"]
            if case_id in case_ids:
                raise AssertionError(f"Duplicate case_id: {case_id}")
            case_ids.add(case_id)
            partition = case["partition"]
            families[partition].add(case["behavior_family"])
            test_path = project_path(case["test_file"])
            if f"/{partition}/" not in test_path.as_posix():
                raise AssertionError(
                    f"{case_id}: file is not under its {partition} directory"
                )
            node_file, separator, function_name = case["pytest_nodeid"].partition(
                "::"
            )
            if not separator or node_file != test_path.name:
                raise AssertionError(f"{case_id}: invalid pytest_nodeid")
            node_key = (partition, task, case["pytest_nodeid"])
            if node_key in node_keys:
                raise AssertionError(f"Duplicate pytest node: {node_key}")
            node_keys.add(node_key)
            manifest_functions[test_path].add(function_name)
            if test_path not in test_file_cache:
                test_file_cache[test_path] = test_markers(test_path)
            markers = test_file_cache[test_path].get(function_name)
            if markers is None:
                raise AssertionError(
                    f"{case_id}: test function {function_name} not found"
                )
            if case["marker"] not in markers:
                raise AssertionError(
                    f"{case_id}: missing pytest.mark.{case['marker']}"
                )
            for mutant in case["target_mutants"]:
                if mutant not in mutants_by_task[task]:
                    raise AssertionError(
                        f"{case_id}: unknown mutant for {task}: {mutant}"
                    )
                target_counts[mutant] += 1
        overlap = families["visible"] & families["hidden"]
        if overlap:
            raise AssertionError(
                f"{task}: visible/hidden behavior families overlap: "
                f"{sorted(overlap)}"
            )
        for path, functions in manifest_functions.items():
            actual = set(test_file_cache[path])
            if actual != functions:
                raise AssertionError(
                    f"{path}: manifest/test function mismatch; "
                    f"missing={sorted(actual - functions)}, "
                    f"extra={sorted(functions - actual)}"
                )

    untargeted = sorted(
        mutant
        for mutants in mutants_by_task.values()
        for mutant in mutants
        if target_counts[mutant] == 0
    )
    if untargeted:
        raise AssertionError(f"Mutants not targeted by any case: {untargeted}")
    print(
        f"OK: {len(manifest['tasks'])} tasks, {total_cases} cases, "
        f"{len(candidate_ids)} candidates; schema, files, markers, mappings, "
        "and visible/hidden behavior-family separation verified."
    )


if __name__ == "__main__":
    main()
