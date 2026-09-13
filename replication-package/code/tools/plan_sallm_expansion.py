#!/usr/bin/env python3
"""Create a provenance-checked SALLM secure-reference expansion wave.

The output deliberately remains a candidate plan.  Passing the original
reference audit is evidence that a task can expose a functional/security
trade-off, but it does not qualify a new safe implementation or partitioned
visible/hidden oracle for a formal experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = PROJECT_ROOT / "benchmarks/manifests/sallm-v1.json"
DEFAULT_QUALIFICATION = (
    PROJECT_ROOT / "benchmarks/manifests/sallm-reference-qualified-v1.json"
)
DEFAULT_AUDIT = (
    PROJECT_ROOT / "artifacts/sallm-audit/reference-overlay-v1-001/results.jsonl"
)
DEFAULT_OVERLAY = PROJECT_ROOT / "configs/benchmarks/sallm_audit_overlay_v1.json"
DEFAULT_CURRENT = (
    PROJECT_ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "configs/benchmarks/sallm_expansion_candidates_v1.json"
)
DEFAULT_REPORT = PROJECT_ROOT / "docs/sallm-expansion-candidates-v1.md"
SCHEMA = PROJECT_ROOT / "schemas/sallm_expansion_plan.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--qualification", type=Path, default=DEFAULT_QUALIFICATION)
    parser.add_argument("--audit-results", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--current-oracle", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-selected", type=int, default=24)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def resolve(path: Path, *, must_exist: bool = True) -> Path:
    value = path.expanduser().resolve()
    try:
        value.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path must be inside {PROJECT_ROOT}: {value}") from exc
    if must_exist and not value.is_file():
        raise FileNotFoundError(value)
    return value


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def render_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def cwe_number(cwe: str) -> int:
    return int(cwe.removeprefix("CWE-"))


def file_ref(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def verify_inputs(
    benchmark_path: Path,
    qualification_path: Path,
    audit_path: Path,
    overlay_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    benchmark = load_json(benchmark_path)
    qualification = load_json(qualification_path)
    audit = load_jsonl(audit_path)

    inputs = qualification.get("inputs", {})
    expected = {
        "benchmark": (
            inputs.get("benchmark_manifest", {}).get("sha256"),
            sha256_file(benchmark_path),
        ),
        "audit results": (
            inputs.get("results", {}).get("sha256"), sha256_file(audit_path)
        ),
        "overlay": (
            inputs.get("overlay", {}).get("sha256"), sha256_file(overlay_path)
        ),
    }
    for label, (recorded, actual) in expected.items():
        if recorded != actual:
            raise RuntimeError(
                f"Qualification {label} hash is stale: recorded={recorded}, actual={actual}"
            )

    manifest_ids = [task["task_id"] for task in benchmark["tasks"]]
    audit_ids = [row["task_id"] for row in audit]
    qualification_ids = [task["task_id"] for task in qualification["tasks"]]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise RuntimeError("Benchmark contains duplicate task IDs")
    if manifest_ids != audit_ids or manifest_ids != qualification_ids:
        raise RuntimeError("Benchmark, audit, and qualification task order differ")
    return benchmark, qualification, audit


def candidate_record(
    task: dict[str, Any],
    result: dict[str, Any],
    fixture_count: int,
) -> dict[str, Any]:
    methods = result["method_results"]
    return {
        "task_id": task["task_id"],
        "cwe": task["cwe"],
        "selection_state": "reserve",
        "selection_reason": "not_yet_ranked",
        "source": {
            "technique": task["source"]["technique"],
            "origin": task["source"]["origin"],
            "reference_file": task["source"]["reference_file"],
        },
        "tests": {
            "entrypoint": task["tests"]["entrypoint"],
            "functional_method_count": len(task["tests"]["functional"]),
            "security_method_count": len(task["tests"]["security"]),
        },
        "execution_cost": {
            "declared_python_requirement_count": len(
                task["dependencies"].get("python_requirements", [])
            ),
            "fixture_count": fixture_count,
            "source_and_test_size_bytes": (
                task["source"]["reference_file"]["size_bytes"]
                + task["tests"]["entrypoint"]["size_bytes"]
            ),
            "reference_audit_wall_seconds": round(
                sum(float(method["wall_seconds"]) for method in methods), 6
            ),
        },
        "reference_audit": {
            "execution_status": result["status"],
            "functional_pass": result["functional_pass"],
            "security_pass": result["security_pass"],
            "joint_pass": result["joint_pass"],
            "candidate_sha256": result["candidate"]["sha256"],
            "method_logs": [
                {
                    "category": method["category"],
                    "method": method["method"],
                    "status": method["status"],
                    "sha256": method["log"]["sha256"],
                }
                for method in methods
            ],
        },
    }


def cost_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    cost = candidate["execution_cost"]
    return (
        cost["fixture_count"],
        cost["declared_python_requirement_count"],
        cost["reference_audit_wall_seconds"],
        cost["source_and_test_size_bytes"],
        candidate["task_id"],
    )


def build_plan(
    benchmark: dict[str, Any],
    qualification: dict[str, Any],
    audit: list[dict[str, Any]],
    overlay: dict[str, Any],
    current: dict[str, Any],
    paths: dict[str, Path],
    max_selected: int,
) -> dict[str, Any]:
    if max_selected < 1:
        raise ValueError("--max-selected must be positive")

    tasks_by_id = {task["task_id"]: task for task in benchmark["tasks"]}
    results_by_id = {result["task_id"]: result for result in audit}
    qualified = {
        task["task_id"]
        for task in qualification["tasks"]
        if task["decision"] == "candidate"
    }
    current_tasks = set(current["tasks"])
    current_cwes = {value["cwe"] for value in current["tasks"].values()}
    fixtures = overlay.get("fixtures", {})

    candidates = []
    for task_id in sorted(qualified - current_tasks):
        result = results_by_id[task_id]
        if not (
            result["status"] == "completed"
            and result["functional_pass"] is True
            and result["security_pass"] is False
        ):
            raise RuntimeError(f"Qualification evidence drifted for {task_id}")
        candidates.append(
            candidate_record(tasks_by_id[task_id], result, len(fixtures.get(task_id, [])))
        )

    novel_by_cwe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate["cwe"] not in current_cwes:
            novel_by_cwe[candidate["cwe"]].append(candidate)

    representatives = [
        min(group, key=cost_key) for group in novel_by_cwe.values()
    ]
    representatives.sort(key=lambda item: (cost_key(item), cwe_number(item["cwe"])))
    selected_ids = {
        candidate["task_id"] for candidate in representatives[:max_selected]
    }
    selected_cwe_ids = {
        candidate["cwe"]
        for candidate in candidates
        if candidate["task_id"] in selected_ids
    }

    selected = []
    reserve = []
    for candidate in candidates:
        if candidate["task_id"] in selected_ids:
            candidate["selection_state"] = "selected"
            candidate["selection_reason"] = (
                "lowest_execution_cost_representative_for_new_cwe"
            )
            selected.append(candidate)
        else:
            if candidate["cwe"] in current_cwes:
                reason = "existing_formal_cwe_replication_reserve"
            elif candidate["cwe"] in selected_cwe_ids:
                reason = "alternate_task_for_selected_new_cwe"
            else:
                reason = "new_cwe_representative_beyond_wave_cap"
            candidate["selection_reason"] = reason
            reserve.append(candidate)

    selected.sort(key=lambda item: cwe_number(item["cwe"]))
    reserve.sort(
        key=lambda item: (
            item["selection_reason"], cwe_number(item["cwe"]), cost_key(item)
        )
    )
    selected_cwes = {item["cwe"] for item in selected}
    reserve_reasons = Counter(item["selection_reason"] for item in reserve)

    return {
        "$schema": rel(SCHEMA),
        "schema_version": 1,
        "plan_id": "sallm-expansion-candidates-v1",
        "status": "secure_reference_generation_ready",
        "formal_experiment_ready": False,
        "remaining_work": (
            "Selected tasks require repeated unsafe/safe/mutant audits, "
            "partitioned oracle construction, semantic review, and model preflight."
        ),
        "selection_policy": {
            "policy_version": 1,
            "candidate_gate": (
                "not in the current v3 oracle; completed reference audit; "
                "functional pass; security fail"
            ),
            "coverage_goal": "one representative for every CWE absent from v3",
            "representative_order": [
                "fewest overlay fixtures",
                "fewest declared Python requirements",
                "shortest reference audit wall time",
                "smallest combined source and test size",
                "lexicographic task ID tie-break",
            ],
            "max_selected": max_selected,
            "model_outputs_used_for_selection": False,
        },
        "qualification_gates": [
            {
                "gate": "G1",
                "state": "passed",
                "requirement": "single audited reference run is functional-pass/security-fail",
            },
            {
                "gate": "G2",
                "state": "pending",
                "requirement": "unsafe reference is functional-pass/security-fail in three fresh sandboxes",
            },
            {
                "gate": "G3",
                "state": "pending",
                "requirement": "safe reference is functional-pass/security-pass in three fresh sandboxes",
            },
            {
                "gate": "G4",
                "state": "pending",
                "requirement": "targeted mutant is functional-pass/security-fail in three fresh sandboxes",
            },
            {
                "gate": "G5",
                "state": "pending",
                "requirement": "visible and hidden tests use disjoint behavior families",
            },
            {
                "gate": "G6",
                "state": "pending",
                "requirement": "hash/provenance checks and no benchmark-test exposure during generation",
            },
            {
                "gate": "G7",
                "state": "pending",
                "requirement": "independent semantic review of contract, safe implementation, and mutant",
            },
            {
                "gate": "G8",
                "state": "pending",
                "requirement": "model preflight rejects ceiling/floor tasks and measures security-only feedback triggers",
            },
        ],
        "inputs": {name: file_ref(path) for name, path in paths.items()},
        "repository_commit": benchmark["repository"]["commit"],
        "summary": {
            "benchmark_task_count": len(benchmark["tasks"]),
            "reference_qualified_task_count": len(qualified),
            "current_formal_task_count": len(current_tasks),
            "current_formal_cwe_count": len(current_cwes),
            "remaining_candidate_count": len(candidates),
            "remaining_candidate_cwe_count": len({c["cwe"] for c in candidates}),
            "novel_cwe_count": len(novel_by_cwe),
            "selected_task_count": len(selected),
            "selected_cwe_count": len(selected_cwes),
            "projected_cwe_count_if_all_selected_qualify": len(current_cwes | selected_cwes),
            "reserve_task_count": len(reserve),
            "reserve_reason_counts": dict(sorted(reserve_reasons.items())),
        },
        # Kept as a plain list for direct compatibility with
        # generate_sallm_secure_candidates.py --task-file.
        "tasks": [candidate["task_id"] for candidate in selected],
        "selected_candidates": selected,
        "reserve_candidates": reserve,
    }


def render_report(plan: dict[str, Any]) -> bytes:
    summary = plan["summary"]
    lines = [
        "# SALLM expansion candidates v1",
        "",
        "## Outcome",
        "",
        (
            f"The frozen reference audit yields {summary['remaining_candidate_count']} "
            f"candidates after removing the {summary['current_formal_task_count']} current "
            f"formal tasks. This wave selects {summary['selected_task_count']} tasks, one "
            f"low-cost representative for each of {summary['selected_cwe_count']} CWEs not "
            "present in the v3 oracle."
        ),
        "",
        (
            f"If every selected task passes the remaining gates, SALLM coverage grows from "
            f"{summary['current_formal_cwe_count']} to "
            f"{summary['projected_cwe_count_if_all_selected_qualify']} CWEs. This file is a "
            "construction plan, not evidence that the tasks are formal-experiment ready."
        ),
        "",
        "## Selected secure-reference wave",
        "",
        "| CWE | Task | Technique | Origin | Fixtures | Bytes | Audit s |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for candidate in plan["selected_candidates"]:
        cost = candidate["execution_cost"]
        source = candidate["source"]
        lines.append(
            f"| {candidate['cwe']} | `{candidate['task_id']}` | "
            f"{source['technique']} | {source['origin']} | {cost['fixture_count']} | "
            f"{cost['source_and_test_size_bytes']} | "
            f"{cost['reference_audit_wall_seconds']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Qualification gates",
            "",
            "Only G1 is currently satisfied. A task may enter the formal benchmark only after all gates pass.",
            "",
        ]
    )
    for gate in plan["qualification_gates"]:
        lines.append(
            f"- **{gate['gate']} ({gate['state']}):** {gate['requirement']}."
        )
    lines.extend(
        [
            "",
            "## Selection interpretation",
            "",
            "The wave deliberately maximizes CWE breadth before adding same-CWE replicas. "
            "Within each new CWE, the representative is selected using only execution-cost "
            "metadata; no model-generation result influences selection. The remaining tasks "
            "stay in the machine-readable reserve list and can replace a candidate that fails "
            "G2–G8.",
            "",
            "## Next executable stage",
            "",
            "Use the JSON plan directly as `--task-file` for secure-reference candidate "
            "generation. Generate multiple candidates, audit them without exposing tests to "
            "the model, retain the first independently valid safe implementation, then build "
            "a targeted unsafe mutant and partitioned visible/hidden tests.",
            "",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {
        "benchmark_manifest": resolve(args.benchmark),
        "reference_qualification": resolve(args.qualification),
        "reference_audit_results": resolve(args.audit_results),
        "execution_overlay": resolve(args.overlay),
        "current_hidden_oracle": resolve(args.current_oracle),
    }
    output = resolve(args.output, must_exist=False)
    report = resolve(args.report, must_exist=False)
    benchmark, qualification, audit = verify_inputs(
        paths["benchmark_manifest"],
        paths["reference_qualification"],
        paths["reference_audit_results"],
        paths["execution_overlay"],
    )
    plan = build_plan(
        benchmark,
        qualification,
        audit,
        load_json(paths["execution_overlay"]),
        load_json(paths["current_hidden_oracle"]),
        paths,
        args.max_selected,
    )
    output_bytes = render_json(plan)
    report_bytes = render_report(plan)
    if args.check:
        stale = []
        if not output.is_file() or output.read_bytes() != output_bytes:
            stale.append(str(output))
        if not report.is_file() or report.read_bytes() != report_bytes:
            stale.append(str(report))
        if stale:
            raise SystemExit("Stale SALLM expansion outputs: " + ", ".join(stale))
        print(f"OK: {output}")
        print(f"OK: {report}")
        return

    for destination, content in ((output, output_bytes), (report, report_bytes)):
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        print(f"Wrote {destination}")
    print(json.dumps(plan["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
