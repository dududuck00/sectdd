#!/usr/bin/env python3
"""Verify the anonymous review artifact, including the post-primary B7 study.

This file is intentionally self-contained.  The anonymous-repository synchronizer
copies it to ``scripts/verify_artifact.py``; it must therefore depend only on the
Python standard library and files included in the review artifact.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

GROUPS = {
    "primary": {
        "path": "data/primary-trajectories.jsonl.gz",
        "records": 3_200,
        "tasks": 20,
        "phase": "balanced-primary-20",
    },
    "legacy": {
        "path": "data/legacy-trajectories.jsonl.gz",
        "records": 2_705,
        "tasks": 31,
        "phase": "legacy-support-31",
    },
    "security_only_upfront": {
        "path": "data/security-only-upfront-trajectories.jsonl.gz",
        "records": 240,
        "tasks": 12,
        "phase": "post-primary-b7-12",
    },
}

B7_MODELS = {
    "qwen25-coder-7b",
    "qwen25-coder-14b",
    "qwen36-27b",
    "deepseek-v4-flash",
}
B7_BENCHMARK_COUNTS = {"sallm": 160, "codeguardplus": 80}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object: {path.relative_to(ROOT)}")
    return payload


def verify_integrity_manifest() -> None:
    manifest = ROOT / "MANIFEST.sha256"
    if not manifest.is_file():
        raise RuntimeError("MANIFEST.sha256 is absent")

    listed: set[str] = set()
    for line_number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RuntimeError(
                f"Malformed MANIFEST.sha256 entry on line {line_number}"
            ) from exc
        if not SHA256_PATTERN.fullmatch(expected):
            raise RuntimeError(
                f"Malformed SHA-256 on MANIFEST.sha256 line {line_number}"
            )
        if relative in listed:
            raise RuntimeError(f"Duplicate manifest entry: {relative}")
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Artifact hash mismatch: {relative}")
        listed.add(relative)

    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name != "MANIFEST.sha256"
        and ".git" not in path.relative_to(ROOT).parts
        and "reproduced" not in path.relative_to(ROOT).parts
        and "__pycache__" not in path.relative_to(ROOT).parts
        and path.suffix != ".pyc"
    }
    if listed != actual:
        raise RuntimeError(
            "Manifest membership mismatch: "
            f"missing={sorted(actual - listed)}, stale={sorted(listed - actual)}"
        )


def verify_hidden_isolation(row: dict[str, Any], identity: tuple[Any, ...]) -> None:
    audit = row.get("hidden_leak_audit")
    if not isinstance(audit, dict):
        raise RuntimeError(f"Hidden-test audit is absent: {identity}")
    if (
        audit.get("passed") is not True
        or audit.get("hidden_feedback_used") is not False
        or audit.get("hidden_projection_loaded_after_candidate_frozen") is not True
        or audit.get("hidden_evaluation_count") != 1
        or audit.get("leaked_terms") not in ([], None)
    ):
        raise RuntimeError(f"Hidden-test isolation failure: {identity}")


def load_group(
    index: dict[str, Any], group: str, global_identities: set[tuple[Any, ...]]
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    expected = GROUPS[group]
    entry = index.get(group)
    if not isinstance(entry, dict):
        raise RuntimeError(f"data/index.json has no {group!r} object")
    if entry.get("path") != expected["path"]:
        raise RuntimeError(
            f"Unexpected {group} path: {entry.get('path')!r}; "
            f"expected {expected['path']!r}"
        )

    path = ROOT / expected["path"]
    if not path.is_file():
        raise RuntimeError(f"Exported trajectory file is absent: {expected['path']}")
    if entry.get("sha256") != sha256(path):
        raise RuntimeError(f"data/index.json SHA-256 mismatch for {group}")
    if entry.get("compressed_bytes") != path.stat().st_size:
        raise RuntimeError(f"data/index.json byte count mismatch for {group}")

    rows: list[dict[str, Any]] = []
    tasks: set[tuple[str, str]] = set()
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Malformed JSON in {expected['path']} on line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"Non-object trajectory in {expected['path']} on line {line_number}"
                )
            artifact = row.get("_artifact")
            if not isinstance(artifact, dict):
                raise RuntimeError(
                    f"Anonymous-export metadata is absent in {group} line {line_number}"
                )
            benchmark = artifact.get("benchmark")
            if benchmark not in {"cweval", "sallm", "codeguardplus"}:
                raise RuntimeError(
                    f"Unexpected benchmark in {group} line {line_number}: {benchmark!r}"
                )
            if artifact.get("evidence_phase") != expected["phase"]:
                raise RuntimeError(
                    f"Unexpected evidence phase in {group} line {line_number}: "
                    f"{artifact.get('evidence_phase')!r}"
                )
            source_hash = artifact.get("source_record_sha256")
            if not isinstance(source_hash, str) or not SHA256_PATTERN.fullmatch(source_hash):
                raise RuntimeError(
                    f"Source-record hash is absent or malformed in {group} line {line_number}"
                )

            try:
                seed = int(row["generation_seed"])
                identity = (
                    artifact["evidence_phase"],
                    benchmark,
                    row["model"],
                    row["task"],
                    seed,
                    row["method"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Incomplete trajectory identity in {group} line {line_number}"
                ) from exc
            if identity in global_identities:
                raise RuntimeError(f"Duplicate exported trajectory: {identity}")
            global_identities.add(identity)
            verify_hidden_isolation(row, identity)
            tasks.add((benchmark, str(row["task"])))
            rows.append(row)

    if len(rows) != expected["records"] or entry.get("records") != expected["records"]:
        raise RuntimeError(
            f"Unexpected {group} count: file={len(rows)}, "
            f"index={entry.get('records')}, expected={expected['records']}"
        )
    if len(tasks) != expected["tasks"] or entry.get("task_instances") != expected["tasks"]:
        raise RuntimeError(
            f"Unexpected {group} task count: file={len(tasks)}, "
            f"index={entry.get('task_instances')}, expected={expected['tasks']}"
        )
    return rows, tasks


def trajectory_cell(row: dict[str, Any]) -> tuple[str, str, str, int]:
    artifact = row["_artifact"]
    return (
        str(artifact["benchmark"]),
        str(row["model"]),
        str(row["task"]),
        int(row["generation_seed"]),
    )


def verify_b7_grid(
    primary_rows: list[dict[str, Any]],
    primary_tasks: set[tuple[str, str]],
    b7_rows: list[dict[str, Any]],
    b7_tasks: set[tuple[str, str]],
    index: dict[str, Any],
) -> None:
    if any(row.get("method") != "B7" for row in b7_rows):
        raise RuntimeError("The security-only-upfront export contains a non-B7 method")
    if any(row.get("method") == "B7" for row in primary_rows):
        raise RuntimeError("B7 records must be new post-primary evidence, not primary records")
    if not b7_tasks.issubset(primary_tasks):
        raise RuntimeError("B7 task membership is not a subset of the balanced primary study")

    benchmark_counts = Counter(row["_artifact"]["benchmark"] for row in b7_rows)
    if dict(benchmark_counts) != B7_BENCHMARK_COUNTS:
        raise RuntimeError(
            f"Unexpected B7 benchmark counts: {dict(sorted(benchmark_counts.items()))}"
        )
    model_counts = Counter(str(row.get("model")) for row in b7_rows)
    if set(model_counts) != B7_MODELS or any(count != 60 for count in model_counts.values()):
        raise RuntimeError(
            f"Unexpected B7 model counts: {dict(sorted(model_counts.items()))}"
        )

    benchmark_model_counts = Counter(
        (row["_artifact"]["benchmark"], str(row["model"])) for row in b7_rows
    )
    expected_benchmark_model_counts = {
        **{("sallm", model): 40 for model in B7_MODELS},
        **{("codeguardplus", model): 20 for model in B7_MODELS},
    }
    if dict(benchmark_model_counts) != expected_benchmark_model_counts:
        raise RuntimeError("The B7 benchmark-by-model grid is incomplete")

    b7_cells = [trajectory_cell(row) for row in b7_rows]
    if len(set(b7_cells)) != 240:
        raise RuntimeError("B7 does not contain exactly 240 distinct task/model/seed cells")
    seeds_by_task_model: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for benchmark, model, task, seed in b7_cells:
        seeds_by_task_model[(benchmark, model, task)].add(seed)
    if len(seeds_by_task_model) != 48 or any(
        len(seeds) != 5 for seeds in seeds_by_task_model.values()
    ):
        raise RuntimeError("B7 does not contain five seeds for every task/model cell")

    primary_cell_methods = {
        (*trajectory_cell(row), str(row["method"])) for row in primary_rows
    }
    required_reused = {
        (*cell, method)
        for cell in set(b7_cells)
        for method in ("B0", "B2", "B3")
    }
    missing = required_reused - primary_cell_methods
    if missing:
        preview = sorted(missing)[:5]
        raise RuntimeError(
            f"The 720 reused B0/B2/B3 primary cells are incomplete; examples={preview}"
        )
    if len(required_reused) != 720:
        raise RuntimeError("Internal error while reconstructing the 720 reused cells")

    factorial = index.get("factorial_ablation")
    expected_accounting = {
        "records": 960,
        "reused_primary_records": 720,
        "new_security_only_records": 240,
    }
    if not isinstance(factorial, dict) or any(
        factorial.get(key) != value for key, value in expected_accounting.items()
    ):
        raise RuntimeError(
            "Factorial accounting must record 960 observations = "
            "720 reused primary B0/B2/B3 + 240 new B7"
        )


def verify_input_link(link: Any, label: str) -> None:
    """Validate a source hash and, when exported, the sanitized-artifact hash."""

    if not isinstance(link, dict):
        raise RuntimeError(f"Test-input binding has no {label} link")
    relative_value = link.get("path")
    source_digest = link.get("sha256")
    if not isinstance(relative_value, str) or not isinstance(source_digest, str):
        raise RuntimeError(f"Test-input binding has an incomplete {label} link")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Test-input binding has an unsafe {label} path")
    if not SHA256_PATTERN.fullmatch(source_digest):
        raise RuntimeError(f"Test-input binding has an invalid {label} source hash")
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"Test-input binding target is absent: {relative_value}")

    artifact_digest = link.get("artifact_sha256")
    if artifact_digest is not None:
        if (
            not isinstance(artifact_digest, str)
            or not SHA256_PATTERN.fullmatch(artifact_digest)
            or artifact_digest != sha256(path)
        ):
            raise RuntimeError(
                f"Test-input binding artifact hash mismatch: {relative_value}"
            )


def verify_test_inputs(expected_b7_tasks: set[tuple[str, str]]) -> None:
    """Check frozen task membership and source/exported file bindings."""
    bindings = read_json(ROOT / "benchmarks/manifests/test-input-bindings-v1.json")
    benchmarks = bindings.get("benchmarks")
    if not isinstance(benchmarks, dict) or set(benchmarks) != {"sallm", "codeguardplus"}:
        raise RuntimeError("Test-input bindings must cover SALLM and CodeGuard+")
    expected_tasks: set[tuple[str, str]] = set()
    recorded_tasks: set[tuple[str, str]] = set()
    for benchmark in ("sallm", "codeguardplus"):
        freeze = read_json(
            ROOT / f"benchmarks/manifests/{benchmark}-paper-expansion-v1-semantic-machine-freeze.json"
        )
        expected_tasks.update((benchmark, str(task)) for task in freeze["qualified_tasks"])
        record = benchmarks[benchmark]
        if not isinstance(record, dict) or not isinstance(record.get("tasks"), list):
            raise RuntimeError(f"Test-input binding has no task list for {benchmark}")
        recorded_tasks.update((benchmark, str(task)) for task in record["tasks"])
        for field in ("source_machine_freeze", "visible_projection", "hidden_projection"):
            verify_input_link(record.get(field), f"{benchmark}.{field}")
    verify_input_link(bindings.get("balanced_primary_input_freeze"), "balanced_primary_input_freeze")
    if recorded_tasks != expected_tasks or expected_b7_tasks != expected_tasks:
        raise RuntimeError("Frozen test-input tasks and the archived factorial cohort differ")


def verify_index_totals(
    index: dict[str, Any], group_tasks: dict[str, set[tuple[str, str]]]
) -> None:
    combined = index.get("combined")
    all_tasks = set().union(*group_tasks.values())
    if (
        not isinstance(combined, dict)
        or combined.get("records") != 6_145
        or combined.get("task_instances") != 51
        or combined.get("distinct_cwes") != 24
        or len(all_tasks) != 51
    ):
        raise RuntimeError(
            "Combined accounting must contain 6,145 unique trajectories over "
            "51 task instances and 24 CWEs"
        )


def main() -> None:
    verify_integrity_manifest()
    index = read_json(ROOT / "data/index.json")
    if index.get("anonymous_review_artifact") is not True:
        raise RuntimeError("data/index.json is not marked as an anonymous review artifact")

    identities: set[tuple[Any, ...]] = set()
    rows: dict[str, list[dict[str, Any]]] = {}
    tasks: dict[str, set[tuple[str, str]]] = {}
    for group in GROUPS:
        rows[group], tasks[group] = load_group(index, group, identities)

    if sum(len(group_rows) for group_rows in rows.values()) != 6_145:
        raise RuntimeError("Combined trajectory count is not 6,145")
    verify_index_totals(index, tasks)
    verify_b7_grid(
        rows["primary"],
        tasks["primary"],
        rows["security_only_upfront"],
        tasks["security_only_upfront"],
        index,
    )
    verify_test_inputs(tasks["security_only_upfront"])

    subprocess.run(
        [sys.executable, str(ROOT / "scripts/audit_anonymity.py")], check=True
    )
    print(
        "OK: 6,145 unique trajectories verified "
        "(3,200 primary + 2,705 legacy + 240 new B7); "
        "the 960-cell factorial reuses 720 primary observations."
    )


if __name__ == "__main__":
    main()
