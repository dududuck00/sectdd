#!/usr/bin/env python3
"""Combine the frozen 31-task evidence with the balanced 20-task expansion."""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from analyze_paper_evidence_v3 import (  # noqa: E402
    METHODS,
    condition_summaries,
    load_records as load_legacy_records,
    paired,
    rq4,
)


EXPANSION_ROOT = ROOT / "artifacts/paper-expansion-full-v1"
EXPANSION_REPORT = ROOT / "artifacts/reports/paper-expansion-full-v1.json"
EXPANSION_FREEZE = (
    ROOT / "benchmarks/manifests/paper-expansion-full-v1-results-freeze.json"
)
LEGACY_REPORT = ROOT / "artifacts/reports/unified-paper-evidence-v3.json"
LEGACY_FREEZE = ROOT / "benchmarks/manifests/paper-evidence-v3-results-freeze.json"
OUTPUT = ROOT / "artifacts/reports/unified-paper-evidence-v4.json"
MARKDOWN = ROOT / "docs/unified-paper-evidence-v4.md"
FREEZE = ROOT / "benchmarks/manifests/paper-evidence-v4-results-freeze.json"
BENCHMARKS = {
    "cweval": "CWEval",
    "sallm": "SALLM",
    "codeguardplus": "CodeGuard+",
}
MODELS = (
    "qwen25-coder-7b",
    "qwen25-coder-14b",
    "qwen36-27b",
    "deepseek-v4-flash",
)
PAIRS = (
    ("B3", "B0"),
    ("B4", "B0"),
    ("M", "B0"),
    ("B6", "B3"),
    ("M", "B4"),
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def grid_hash(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def check_frozen_output(freeze: dict, name: str, path: Path) -> None:
    record = freeze["outputs"][name]
    if record["path"] != path.relative_to(ROOT).as_posix():
        raise RuntimeError(f"Frozen output path mismatch: {path}")
    if record["sha256"] != sha256(path):
        raise RuntimeError(f"Frozen output changed: {path}")


def load_expansion_records() -> tuple[list[dict], list[dict]]:
    freeze = load(EXPANSION_FREEZE)
    check_frozen_output(freeze, "json_report", EXPANSION_REPORT)
    report = load(EXPANSION_REPORT)
    if not report.get("complete") or report.get("trajectory_count") != 3200:
        raise RuntimeError("Balanced expansion report is incomplete")
    records: list[dict] = []
    runs: list[dict] = []
    frozen_manifests = freeze["inputs"]
    for slug, benchmark in BENCHMARKS.items():
        config = load(ROOT / f"configs/experiments/{slug}_paper_expansion_full_v1.json")
        expected = (
            len(config["tasks"])
            * len(config["methods"])
            * len(config["generation_seeds"])
        )
        for model in MODELS:
            run = EXPANSION_ROOT / slug / model
            manifest_path = run / "run_manifest.json"
            frozen = frozen_manifests[f"{slug}:{model}"]
            if frozen["sha256"] != sha256(manifest_path):
                raise RuntimeError(f"Expansion manifest changed: {manifest_path}")
            manifest = load(manifest_path)
            paths = sorted(run.glob("trajectories/*/*/seed_*/trajectory.json"))
            if len(paths) != expected or manifest["trajectory_count"] != expected:
                raise RuntimeError(f"Expansion grid incomplete: {run}")
            if (
                manifest["tasks"] != config["tasks"]
                or manifest["methods"] != list(config["methods"])
                or manifest["seeds"] != config["generation_seeds"]
            ):
                raise RuntimeError(f"Expansion condition drift: {run}")
            for path in paths:
                item = load(path)
                item["_benchmark"] = benchmark
                item["_family"] = (
                    "DeepSeek" if model == "deepseek-v4-flash" else "Qwen"
                )
                item["_trajectory_path"] = path.relative_to(ROOT).as_posix()
                item["_evidence_phase"] = "balanced_expansion_20"
                records.append(item)
            runs.append(
                {
                    "evidence_phase": "balanced_expansion_20",
                    "benchmark": benchmark,
                    "family": "DeepSeek" if model == "deepseek-v4-flash" else "Qwen",
                    "model": model,
                    "tasks": len(config["tasks"]),
                    "methods": len(config["methods"]),
                    "repetitions": len(config["generation_seeds"]),
                    "trajectories": expected,
                    "manifest": file_record(manifest_path),
                    "trajectory_grid_sha256": grid_hash(run, paths),
                }
            )
    if len(records) != 3200:
        raise RuntimeError("Expected 3,200 balanced expansion trajectories")
    return records, runs


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def clustered_comparison(
    records: list[dict], target: str, reference: str, seed: int
) -> dict[str, Any]:
    index = {
        (
            item["_benchmark"],
            item["model"],
            item["task"],
            item["generation_seed"],
            item["method"],
        ): item
        for item in records
    }
    deltas: dict[str, list[int]] = defaultdict(list)
    wins = losses = ties = 0
    for key, current in index.items():
        benchmark, model, task, slot, method = key
        if method != target:
            continue
        baseline = index.get((benchmark, model, task, slot, reference))
        if baseline is None:
            continue
        current_joint = int(current["final_hidden"]["joint_pass"])
        baseline_joint = int(baseline["final_hidden"]["joint_pass"])
        delta = current_joint - baseline_joint
        deltas[f"{benchmark}:{task}"].append(delta)
        wins += int(delta > 0)
        losses += int(delta < 0)
        ties += int(delta == 0)
    tasks = sorted(deltas)
    observed = mean(mean(deltas[task]) for task in tasks)
    rng = random.Random(seed)
    samples = []
    for _ in range(10000):
        chosen = [rng.choice(tasks) for _ in tasks]
        samples.append(mean(mean(deltas[task]) for task in chosen))
    return {
        "target": target,
        "reference": reference,
        "eligible_task_clusters": len(tasks),
        "eligible_trajectory_pairs": wins + losses + ties,
        "task_macro_joint_delta": observed,
        "task_bootstrap_ci95": [
            percentile(samples, 0.025),
            percentile(samples, 0.975),
        ],
        "bootstrap_replicates": 10000,
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }


def pct(value: float | None) -> str:
    return "--" if value is None else f"{100 * value:.2f}%"


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Unified paper evidence v4",
        "",
        "The 20-task balanced expansion is the primary confirmatory matrix; the earlier 31-task heterogeneous grid is retained as supporting coverage evidence.",
        "",
        "## Scope",
        "",
        "| Evidence phase | Tasks | Trajectories | Role |",
        "|---|---:|---:|---|",
        f"| Legacy heterogeneous evidence | 31 | {report['scope']['legacy_trajectories']:,} | Supporting/sensitivity |",
        f"| Balanced expansion | 20 | {report['scope']['expansion_trajectories']:,} | Primary confirmatory |",
        f"| Combined coverage | 51 | {report['scope']['combined_trajectories']:,} | Descriptive only |",
        "",
        "Task instances by benchmark: "
        + ", ".join(
            f"{key}={value}" for key, value in report["scope"]["tasks_by_benchmark"].items()
        )
        + ".",
        "",
        "## Combined paired outcome audit",
        "",
        "| Comparison | Task clusters | Pairs | Joint delta | 95% task-bootstrap CI | Wins | Losses |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["combined_task_cluster_comparisons"]:
        low, high = item["task_bootstrap_ci95"]
        lines.append(
            f"| {item['target']} - {item['reference']} | {item['eligible_task_clusters']} | "
            f"{item['eligible_trajectory_pairs']} | {pct(item['task_macro_joint_delta'])} | "
            f"[{pct(low)}, {pct(high)}] | {item['wins']} | {item['losses']} |"
        )
    lines += [
        "",
        "The combined rows are robustness summaries over an unbalanced historical grid. They must not replace the balanced 20-task estimates for model or method ranking.",
        "",
        "## Interpretation boundary",
        "",
        report["interpretation_boundary"],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    legacy_freeze = load(LEGACY_FREEZE)
    check_frozen_output(legacy_freeze, "report", LEGACY_REPORT)
    legacy, legacy_runs = load_legacy_records()
    for item in legacy:
        item["_evidence_phase"] = "legacy_heterogeneous_31"
    expansion, expansion_runs = load_expansion_records()
    all_records = legacy + expansion
    identities = [
        (
            item["_benchmark"],
            item["model"],
            item["task"],
            item["generation_seed"],
            item["method"],
        )
        for item in all_records
    ]
    if len(identities) != len(set(identities)):
        raise RuntimeError("Legacy and expansion trajectory identities overlap")
    legacy_tasks = {(item["_benchmark"], item["task"]) for item in legacy}
    expansion_tasks = {(item["_benchmark"], item["task"]) for item in expansion}
    if legacy_tasks & expansion_tasks:
        raise RuntimeError("Legacy and expansion task sets overlap")
    tasks = legacy_tasks | expansion_tasks
    if len(legacy_tasks) != 31 or len(expansion_tasks) != 20 or len(tasks) != 51:
        raise RuntimeError("Expected disjoint 31 + 20 = 51 task instances")
    by_benchmark = defaultdict(set)
    cwes = set()
    for benchmark, task in tasks:
        by_benchmark[benchmark].add(task)
        match = re.search(r"cwe[-_]?(\d+)", task, re.IGNORECASE)
        if not match:
            raise RuntimeError(f"Cannot infer CWE from frozen task identifier: {task}")
        cwes.add(int(match.group(1)))
    conditions = condition_summaries(all_records)
    report = {
        "schema_version": 4,
        "report_id": "unified-paper-evidence-v4",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": False,
        "scope": {
            "legacy_tasks": len(legacy_tasks),
            "expansion_tasks": len(expansion_tasks),
            "combined_tasks": len(tasks),
            "legacy_trajectories": len(legacy),
            "expansion_trajectories": len(expansion),
            "combined_trajectories": len(all_records),
            "distinct_cwe_count": len(cwes),
            "tasks_by_benchmark": {
                key: len(value) for key, value in sorted(by_benchmark.items())
            },
            "major_model_families": ["Qwen", "DeepSeek"],
            "named_model_configurations": sorted({item["model"] for item in all_records}),
        },
        "evidence_roles": {
            "primary_confirmatory": "balanced_expansion_20",
            "supporting_sensitivity": "legacy_heterogeneous_31",
            "combined_coverage": "descriptive_only",
        },
        "runs": [
            {**run, "evidence_phase": "legacy_heterogeneous_31"}
            for run in legacy_runs
        ] + expansion_runs,
        "condition_methods": conditions,
        "shared_candidate_feedback": {
            f"{target}_vs_{reference}": paired(all_records, target, reference)
            for target, reference in (("B4", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4"))
        },
        "visible_to_hidden_overfitting": rq4(all_records),
        "combined_task_cluster_comparisons": [
            clustered_comparison(all_records, target, reference, 20261201 + index)
            for index, (target, reference) in enumerate(PAIRS)
        ],
        "source_freezes": {
            "legacy_31": file_record(LEGACY_FREEZE),
            "balanced_expansion_20": file_record(EXPANSION_FREEZE),
        },
        "interpretation_boundary": (
            "The balanced 20-task, four-model, eight-method matrix is the primary "
            "confirmatory evidence. The combined 51-task/5,905-trajectory view is "
            "unbalanced and mixes legacy machine-qualified evidence, so it is used "
            "only for coverage and robustness; task is the inference unit."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN.write_text(markdown(report), encoding="utf-8")
    freeze = {
        "schema_version": 1,
        "freeze_id": "paper-evidence-v4-results",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": False,
        "summary": report["scope"],
        "inputs": report["source_freezes"],
        "outputs": {
            "report": file_record(OUTPUT),
            "markdown": file_record(MARKDOWN),
        },
        "interpretation_boundary": report["interpretation_boundary"],
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "tasks": len(tasks),
                "trajectories": len(all_records),
                "legacy_tasks": len(legacy_tasks),
                "balanced_expansion_tasks": len(expansion_tasks),
                "complete": True,
                "formal_results_use": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
