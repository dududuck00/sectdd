#!/usr/bin/env python3
"""Freeze a result-blind CodeGuard+ Python oracle-qualification pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
SMOKE_CONFIG = ROOT / "configs/benchmarks/codeguardplus_python_smoke_v1.json"
OUTPUT = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
REPORT = ROOT / "docs/codeguardplus-qualification-candidates-v2.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--smoke-config", type=Path, default=SMOKE_CONFIG)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def checked(path: Path, *, exists: bool = True) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.is_file():
        raise FileNotFoundError(value)
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = checked(path)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def verified(record_value: dict[str, Any]) -> Path:
    path = checked(ROOT / record_value["path"])
    if sha256_file(path) != record_value["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if path.stat().st_size != record_value["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")
    return path


def render(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def cwe_number(value: str) -> int:
    return int(value.removeprefix("CWE-"))


def payload_probe_count(tasks: list[dict[str, Any]]) -> int:
    return sum(
        any(
            Path(item["path"]).name in {"test_case.py", "test_cases.py"}
            for item in task["tests"]["functional"]["support_files"]
        )
        for task in tasks
    )


def task_cost(task: dict[str, Any]) -> dict[str, Any]:
    source = task["source"]
    functional = task["tests"]["functional"]
    context_bytes = (
        source["file_context"]["size_bytes"]
        + source["function_context"]["size_bytes"]
        + source["info"]["size_bytes"]
    )
    probes = [
        item
        for item in functional["support_files"]
        if Path(item["path"]).name in {"test_case.py", "test_cases.py"}
    ]
    fixtures = [item for item in functional["support_files"] if item not in probes]
    return {
        "query_source_penalty": (
            0
            if task["tests"]["security"]["source_type"]
            == "codeql_standard_bundle"
            else 1
        ),
        "missing_benchmark_probe_penalty": 0 if probes else 1,
        "functional_test_bytes": functional["entrypoint"]["size_bytes"],
        "public_context_bytes": context_bytes,
        "benchmark_probe_bytes": sum(item["size_bytes"] for item in probes),
        "fixture_bytes": sum(item["size_bytes"] for item in fixtures),
    }


def cost_key(task: dict[str, Any]) -> tuple[Any, ...]:
    cost = task_cost(task)
    return (
        cost["query_source_penalty"],
        cost["missing_benchmark_probe_penalty"],
        cost["functional_test_bytes"],
        cost["public_context_bytes"],
        cost["benchmark_probe_bytes"],
        task["task_id"],
    )


def task_record(
    task: dict[str, Any], *, state: str, reason: str
) -> dict[str, Any]:
    for item in (
        task["source"]["file_context"],
        task["source"]["function_context"],
        task["source"]["info"],
        task["tests"]["functional"]["entrypoint"],
        *task["tests"]["functional"]["support_files"],
    ):
        verified(item)
    security = task["tests"]["security"]
    if security["source_type"] == "benchmark_repository":
        verified(security["resolved_file"])
    probes = [
        item
        for item in task["tests"]["functional"]["support_files"]
        if Path(item["path"]).name in {"test_case.py", "test_cases.py"}
    ]
    fixtures = [
        item
        for item in task["tests"]["functional"]["support_files"]
        if item not in probes
    ]
    return {
        "task_id": task["task_id"],
        "cwe": task["cwe"],
        "selection_state": state,
        "selection_reason": reason,
        "selection_cost": task_cost(task),
        "public_generation_inputs": {
            "file_context": task["source"]["file_context"],
            "function_context": task["source"]["function_context"],
            "info": task["source"]["info"],
            "benchmark_probe_exposed_to_model": False,
            "functional_test_exposed_to_model": False,
            "security_query_exposed_to_model": False,
        },
        "qualification_oracles": {
            "functional": task["tests"]["functional"],
            "security": security,
        },
        "benchmark_probe_candidates": probes,
        "benchmark_fixture_files": fixtures,
        "dependencies": task["dependencies"],
    }


def build_plan(
    manifest_path: Path, smoke_path: Path
) -> tuple[dict[str, Any], str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    if manifest["benchmark"]["name"] != "CodeGuard+":
        raise RuntimeError("Wrong benchmark manifest")
    repo = checked(ROOT / manifest["repository"]["path"], exists=False)
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != manifest["repository"]["commit"] or dirty:
        raise RuntimeError("CodeGuard+ checkout is not at the clean pinned commit")

    eligible = [
        task
        for task in manifest["tasks"]
        if task["language"] == "python"
        and task["eligibility"]["candidate_for_oracle_audit"]
    ]
    smoke_ids = {item["task_id"] for item in smoke["tasks"]}
    available = [task for task in eligible if task["task_id"] not in smoke_ids]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in available:
        grouped[task["cwe"]].append(task)

    selected: dict[str, str] = {}
    for cwe, tasks in grouped.items():
        winner = min(tasks, key=cost_key)
        selected[winner["task_id"]] = "lowest_static_cost_within_cwe"

    custom = [
        task
        for task in available
        if task["tests"]["security"]["source_type"] == "benchmark_repository"
    ]
    if custom and not any(task["task_id"] in selected for task in custom):
        winner = min(custom, key=cost_key)
        selected[winner["task_id"]] = "additional_custom_query_source_coverage"

    selected_tasks = sorted(
        (task for task in available if task["task_id"] in selected),
        key=lambda item: (cwe_number(item["cwe"]), item["task_id"]),
    )
    reserve_tasks = sorted(
        (task for task in available if task["task_id"] not in selected),
        key=lambda item: (cost_key(item), cwe_number(item["cwe"])),
    )
    excluded_tasks = sorted(
        (task for task in eligible if task["task_id"] in smoke_ids),
        key=lambda item: (cwe_number(item["cwe"]), item["task_id"]),
    )
    if len(selected_tasks) != 24 or len({task["cwe"] for task in selected_tasks}) != 23:
        raise RuntimeError("Expected 24 primary tasks spanning all 23 eligible CWEs")
    if len(selected_tasks) + len(reserve_tasks) + len(excluded_tasks) != 62:
        raise RuntimeError("Task partition is incomplete")

    tasks = [
        *(
            task_record(task, state="primary", reason=selected[task["task_id"]])
            for task in selected_tasks
        ),
        *(
            task_record(task, state="reserve", reason="not_selected_by_static_rank")
            for task in reserve_tasks
        ),
        *(
            task_record(
                task,
                state="development_excluded",
                reason="result_observed_in_infrastructure_smoke",
            )
            for task in excluded_tasks
        ),
    ]
    query_counts = Counter(
        item["qualification_oracles"]["security"]["source_type"]
        for item in tasks
        if item["selection_state"] == "primary"
    )
    payload = {
        "schema_version": 1,
        "plan_type": "codeguardplus_python_oracle_qualification_candidates",
        "plan_id": "codeguardplus-qualification-candidates-v2",
        "study_phase": "oracle_construction_development",
        "development_only": True,
        "formal_results_use": False,
        "selection_frozen_before_candidate_generation": True,
        "selection_reads_model_outputs": False,
        "selection_reads_oracle_outcomes": False,
        "inputs": {
            "benchmark_manifest": record(manifest_path),
            "infrastructure_smoke_config": record(smoke_path),
            "repository_commit": commit,
        },
        "selection_policy": {
            "eligible_population": (
                "All Python tasks marked candidate_for_oracle_audit in the pinned "
                "inventory manifest"
            ),
            "development_exclusion": (
                "Exclude the six tasks whose benchmark-probe outcomes were observed "
                "during infrastructure smoke"
            ),
            "primary_rule": (
                "Within each CWE select the minimum tuple of standard-query penalty, "
                "missing-benchmark-probe penalty, functional-test bytes, public-context "
                "bytes, benchmark-probe bytes, and task_id"
            ),
            "query_diversity_rule": (
                "Additionally select the lowest-cost benchmark-repository query when "
                "not already selected"
            ),
            "post_generation_replacement": (
                "Primary failures may only be replaced by the next pre-ranked reserve "
                "from the same CWE; observed results cannot alter the reserve order"
            ),
        },
        "counts": {
            "eligible": len(eligible),
            "primary": len(selected_tasks),
            "reserve": len(reserve_tasks),
            "development_excluded": len(excluded_tasks),
            "primary_cwes": len({task["cwe"] for task in selected_tasks}),
            "primary_query_sources": dict(sorted(query_counts.items())),
            "primary_with_benchmark_probe": sum(
                bool(task["tests"]["functional"]["support_files"])
                and any(
                    Path(item["path"]).name in {"test_case.py", "test_cases.py"}
                    for item in task["tests"]["functional"]["support_files"]
                )
                for task in selected_tasks
            ),
        },
        "primary_task_ids": [task["task_id"] for task in selected_tasks],
        "reserve_task_ids": [task["task_id"] for task in reserve_tasks],
        "development_excluded_task_ids": [task["task_id"] for task in excluded_tasks],
        "tasks": tasks,
        "next_gate": (
            "Generate three test-blind secure candidates per primary task, then "
            "evaluate benchmark probes and candidates without changing this selection."
        ),
    }

    lines = [
        "# CodeGuard+ qualification 候选池 v2",
        "",
        "该候选池在任何安全实现生成或资格运行前冻结。选择过程不读取模型输出、",
        "功能通过率或 CodeQL 结果；六个已用于基础设施 smoke 的任务全部排除。",
        "",
        "- 可审计 Python 总体：62",
        "- primary：24，覆盖 23 个 CWE",
        "- reserve：32",
        "- development-excluded：6",
        "- primary query：23 个标准查询、1 个 benchmark 自定义查询",
        f"- primary 中带 benchmark probe：{payload_probe_count(selected_tasks)}",
        "",
        "| Task | CWE | Query source | 选择原因 | functional bytes | context bytes |",
        "|---|---|---|---|---:|---:|",
    ]
    for task in selected_tasks:
        cost = task_cost(task)
        lines.append(
            f"| {task['task_id']} | {task['cwe']} | "
            f"{task['tests']['security']['source_type']} | "
            f"{selected[task['task_id']]} | {cost['functional_test_bytes']} | "
            f"{cost['public_context_bytes']} |"
        )
    lines.extend(
        [
            "",
            "后续 primary 任务失败时，只能按本计划中的 reserve 顺序取同 CWE 的",
            "下一题替换；不得根据已经观察到的结果重新排列 reserve。该阶段仍为",
            "oracle construction development，不构成方法效果证据。",
            "",
        ]
    )
    return payload, "\n".join(lines)


def main() -> None:
    args = parse_args()
    manifest = checked(args.manifest)
    smoke = checked(args.smoke_config)
    output = checked(args.output, exists=False)
    report = checked(args.report, exists=False)
    payload, markdown = build_plan(manifest, smoke)
    expected = {output: render(payload), report: markdown.encode()}
    if args.check:
        stale = [str(path) for path, content in expected.items() if not path.is_file() or path.read_bytes() != content]
        if stale:
            raise SystemExit("Stale CodeGuard+ qualification plan: " + ", ".join(stale))
        print("CodeGuard+ qualification plan is current")
        return
    for path, content in expected.items():
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(json.dumps(payload["counts"], indent=2))


if __name__ == "__main__":
    main()
