#!/usr/bin/env python3
"""Validate and analyze the 2x2 visible-test upfront factorial addendum."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
NEW_ROOT = ROOT / "artifacts/security-only-upfront-ablation-v1"
PRIMARY_ROOT = ROOT / "artifacts/paper-expansion-full-v1"
FREEZE = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-input-freeze.json"
REPORT = ROOT / "artifacts/reports/security-only-upfront-ablation-v1.json"
ACCOUNTING_AUDIT = ROOT / "artifacts/reports/security-only-upfront-ablation-v1-accounting-audit.json"
MARKDOWN = ROOT / "docs/security-only-upfront-ablation-v1-results.md"
RESULT_FREEZE = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-results-freeze.json"
RELOCATION = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-checkpoint-relocation.json"
QWEN36_RELOCATION = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-qwen36-checkpoint-relocation.json"
PAPER_EVIDENCE_FREEZE = ROOT / "benchmarks/manifests/paper-evidence-v4-results-freeze.json"
PAPER_EVIDENCE_REPORT = ROOT / "artifacts/reports/unified-paper-evidence-v4.json"
BENCHMARKS = ("sallm", "codeguardplus")
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b", "qwen36-27b", "deepseek-v4-flash")
METHODS = ("B0", "B2", "B7", "B3")
METHOD_LABELS = {
    "B0": "Requirement only",
    "B2": "Functional tests only",
    "B7": "Security tests only",
    "B3": "Functional + security tests",
}
METRICS = ("functional", "security", "joint", "safe")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def file_set_record(paths: list[Path]) -> dict[str, Any]:
    files = [file_record(path) for path in sorted(paths)]
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "file_count": len(files),
        "canonical_manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": files,
    }


def identity_set_sha256(items: set[tuple[str, str, str, int, str]]) -> str:
    canonical = json.dumps(sorted(items), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_phase_identities(
    evidence_report: dict[str, Any], phase: str
) -> tuple[set[tuple[str, str, str, int, str]], set[tuple[str, str]], list[dict[str, Any]]]:
    benchmark_names = {
        "CWEval": "cweval",
        "SALLM": "sallm",
        "CodeGuard+": "codeguardplus",
    }
    identities: set[tuple[str, str, str, int, str]] = set()
    tasks: set[tuple[str, str]] = set()
    runs = []
    for run in evidence_report["runs"]:
        if run.get("evidence_phase") != phase:
            continue
        benchmark = benchmark_names[run["benchmark"]]
        manifest_record = run["manifest"]
        manifest_path = ROOT / manifest_record["path"]
        if sha(manifest_path) != manifest_record["sha256"]:
            raise RuntimeError(f"Prior evidence manifest hash mismatch: {manifest_path}")
        paths = sorted((manifest_path.parent / "trajectories").rglob("trajectory.json"))
        if len(paths) != run["trajectories"]:
            raise RuntimeError(f"Prior evidence trajectory count mismatch: {manifest_path.parent}")
        run_ids = set()
        for path in paths:
            row = load(path)
            item = identity(benchmark, row)
            if item in identities or item in run_ids:
                raise RuntimeError(f"Duplicate canonical trajectory identity: {item}")
            run_ids.add(item)
            tasks.add((benchmark, row["task"]))
        identities.update(run_ids)
        runs.append({
            "benchmark": benchmark,
            "model": run["model"],
            "manifest": file_record(manifest_path),
            "trajectory_count": len(paths),
            "identity_set_sha256": identity_set_sha256(run_ids),
        })
    return identities, tasks, runs


def trajectory_paths(run: Path, method: str) -> list[Path]:
    return sorted((run / "trajectories" / method).glob("*/seed_*/trajectory.json"))


def values(row: dict[str, Any]) -> dict[str, float]:
    hidden = row["final_hidden"]
    joint = float(bool(hidden["joint_pass"]))
    safe = hidden.get("safe", joint)
    if not isinstance(safe, (int, float)):
        safe = joint
    return {
        "functional": float(bool(hidden["functional"]["all_passed"])),
        "security": float(bool(hidden["security"]["all_passed"])),
        "joint": joint,
        "safe": float(safe),
    }


def state(row: dict[str, Any]) -> str:
    result = values(row)
    return f"F{'+' if result['functional'] else '-'}S{'+' if result['security'] else '-'}"


def identity(benchmark: str, row: dict[str, Any]) -> tuple[str, str, str, int, str]:
    return benchmark, row["model"], row["task"], int(row["generation_seed"]), row["method"]


def percentile(items: list[float], fraction: float) -> float:
    ordered = sorted(items)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def bootstrap(
    by_task: dict[str, list[float]], seed: int, repeats: int = 10_000
) -> dict[str, Any]:
    tasks = sorted(by_task)
    observed = mean(mean(by_task[task]) for task in tasks)
    rng = random.Random(seed)
    samples = []
    for _ in range(repeats):
        chosen = [rng.choice(tasks) for _ in tasks]
        samples.append(mean(mean(by_task[task]) for task in chosen))
    return {
        "estimate": observed,
        "ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "task_clusters": len(tasks),
        "bootstrap_replicates": repeats,
    }


def contrast(
    index: dict[tuple[str, str, str, int, str], dict[str, Any]],
    name: str,
    weights: dict[str, float],
    seed: int,
) -> dict[str, Any]:
    by_metric: dict[str, dict[str, list[float]]] = {
        metric: defaultdict(list) for metric in METRICS
    }
    cells = 0
    wins = losses = ties = 0
    for benchmark in BENCHMARKS:
        config = load(ROOT / f"configs/experiments/{benchmark}_security_only_upfront_ablation_v1.json")
        for task in config["tasks"]:
            cluster = f"{benchmark}:{task}"
            for model in MODELS:
                for slot in config["generation_seeds"]:
                    rows = {
                        method: index[(benchmark, model, task, int(slot), method)]
                        for method in weights
                    }
                    for metric in METRICS:
                        delta = sum(weight * values(rows[method])[metric] for method, weight in weights.items())
                        by_metric[metric][cluster].append(delta)
                    if set(weights.values()) == {1.0, -1.0} and len(weights) == 2:
                        delta = sum(weight * values(rows[method])["joint"] for method, weight in weights.items())
                        wins += int(delta > 0)
                        losses += int(delta < 0)
                        ties += int(delta == 0)
                    cells += 1
    return {
        "name": name,
        "weights": weights,
        "eligible_cells": cells,
        "metrics": {
            metric: bootstrap(by_metric[metric], seed + offset)
            for offset, metric in enumerate(METRICS)
        },
        "joint_wins": wins if len(weights) == 2 else None,
        "joint_losses": losses if len(weights) == 2 else None,
        "joint_ties": ties if len(weights) == 2 else None,
    }


def stratified_contrast(
    index: dict[tuple[str, str, str, int, str], dict[str, Any]],
    benchmark: str,
    model: str,
    name: str,
    weights: dict[str, float],
    seed: int,
) -> dict[str, Any]:
    config = load(ROOT / f"configs/experiments/{benchmark}_security_only_upfront_ablation_v1.json")
    by_metric: dict[str, dict[str, list[float]]] = {
        metric: defaultdict(list) for metric in METRICS
    }
    wins = losses = ties = 0
    for task in config["tasks"]:
        cluster = f"{benchmark}:{task}"
        for slot in config["generation_seeds"]:
            rows = {
                method: index[(benchmark, model, task, int(slot), method)]
                for method in weights
            }
            for metric in METRICS:
                delta = sum(
                    weight * values(rows[method])[metric]
                    for method, weight in weights.items()
                )
                by_metric[metric][cluster].append(delta)
            joint_delta = sum(
                weight * values(rows[method])["joint"]
                for method, weight in weights.items()
            )
            wins += int(joint_delta > 0)
            losses += int(joint_delta < 0)
            ties += int(joint_delta == 0)
    return {
        "benchmark": benchmark,
        "model": model,
        "name": name,
        "weights": weights,
        "eligible_cells": len(config["tasks"]) * len(config["generation_seeds"]),
        "metrics": {
            metric: bootstrap(by_metric[metric], seed + offset)
            for offset, metric in enumerate(METRICS)
        },
        "joint_wins": wins,
        "joint_losses": losses,
        "joint_ties": ties,
    }


def audit_b7_prompt(benchmark: str, row: dict[str, Any], visible: dict[str, Any]) -> None:
    if row["method"] != "B7" or row["method_config"].get("upfront_tests") != "security":
        raise RuntimeError(f"B7 method drift: {identity(benchmark, row)}")
    if len(row["rounds"]) != 1 or row["budget_usage"]["model_calls"] != 1:
        raise RuntimeError(f"B7 must be one-shot: {identity(benchmark, row)}")
    prompt = "\n".join(message["content"] for message in row["rounds"][0]["messages"])
    cases = visible["tasks"][row["task"]]["cases"]
    security = [case for case in cases if case.get("marker") == "security"]
    functional = [case for case in cases if case.get("marker") in {"functional", "functionality"}]
    for case in security:
        if case["case_id"] not in prompt:
            raise RuntimeError(f"Security case absent from B7 prompt: {case['case_id']}")
    for case in functional:
        identifiers = [case["case_id"], case.get("test_name"), case.get("test_method")]
        if any(identifier and identifier in prompt for identifier in identifiers):
            raise RuntimeError(f"Functional test leaked into B7 prompt: {case['case_id']}")


def main() -> None:
    freeze = load(FREEZE)
    relocation = load(RELOCATION)
    qwen36_relocation = load(QWEN36_RELOCATION)
    paper_evidence_freeze = load(PAPER_EVIDENCE_FREEZE)
    paper_evidence_report = load(PAPER_EVIDENCE_REPORT)
    if not freeze.get("complete") or freeze["scope"]["new_trajectory_count"] != 240:
        raise RuntimeError("Input freeze is incomplete")
    evidence_summary = paper_evidence_freeze.get("summary", {})
    expected_prior_counts = {
        "legacy_trajectories": 2705,
        "expansion_trajectories": 3200,
        "combined_trajectories": 5905,
    }
    if any(evidence_summary.get(key) != value for key, value in expected_prior_counts.items()):
        raise RuntimeError("Prior paper-evidence accounting changed")
    if sha(PAPER_EVIDENCE_REPORT) != paper_evidence_freeze["outputs"]["report"]["sha256"]:
        raise RuntimeError("Prior paper-evidence report does not match its result freeze")
    records: list[tuple[str, dict[str, Any]]] = []
    run_records = []
    for benchmark in BENCHMARKS:
        new_config_path = ROOT / f"configs/experiments/{benchmark}_security_only_upfront_ablation_v1.json"
        old_config_path = ROOT / f"configs/experiments/{benchmark}_paper_expansion_full_v1.json"
        config = load(new_config_path)
        old_config = load(old_config_path)
        frozen = freeze["configs"][benchmark]
        if frozen["ablation_config"]["sha256"] != relocation["original_frozen_config_sha256"][benchmark]:
            raise RuntimeError(f"{benchmark}: relocation source does not match input freeze")
        if relocation["relocated_config_sha256"][benchmark] != qwen36_relocation["original_config_sha256"][benchmark]:
            raise RuntimeError(f"{benchmark}: Qwen3.6 relocation source does not match the first relocation")
        if sha(new_config_path) != qwen36_relocation["relocated_config_sha256"][benchmark]:
            raise RuntimeError(f"Frozen ablation config changed: {new_config_path}")
        if sha(old_config_path) != frozen["base_config"]["sha256"]:
            raise RuntimeError(f"Frozen base config changed: {old_config_path}")
        for key in ("tasks", "generation_seeds", "generation", "budgets", "oracle_set_id"):
            if config[key] != old_config[key]:
                raise RuntimeError(f"{benchmark}: ablation changed frozen {key}")
        for model in MODELS:
            current_model = dict(config["models"][model])
            archived_model = dict(old_config["models"][model])
            current_model.pop("checkpoint", None)
            current_model.pop("tokenizer_proxy", None)
            archived_model.pop("checkpoint", None)
            archived_model.pop("tokenizer_proxy", None)
            if current_model != archived_model:
                raise RuntimeError(f"{benchmark}/{model}: model metadata changed beyond path relocation")
        visible_path = ROOT / frozen["visible_projection"]["path"]
        hidden_path = ROOT / frozen["hidden_projection"]["path"]
        if sha(visible_path) != frozen["visible_projection"]["sha256"] or sha(hidden_path) != frozen["hidden_projection"]["sha256"]:
            raise RuntimeError(f"{benchmark}: frozen oracle projection changed")
        visible = load(visible_path)
        expected_new = len(config["tasks"]) * len(config["generation_seeds"])
        for model in MODELS:
            new_run = NEW_ROOT / benchmark / model
            manifest_path = new_run / "run_manifest.json"
            if not manifest_path.is_file():
                raise FileNotFoundError(f"Pending ablation run: {manifest_path}")
            manifest = load(manifest_path)
            if (
                manifest.get("model") != model
                or manifest.get("tasks") != config["tasks"]
                or manifest.get("methods") != ["B7"]
                or manifest.get("seeds") != config["generation_seeds"]
                or manifest.get("trajectory_count") != expected_new
            ):
                raise RuntimeError(f"New run grid mismatch: {new_run}")
            run_config_sha256 = (
                relocation["relocated_config_sha256"][benchmark]
                if model in {"qwen25-coder-7b", "qwen25-coder-14b"}
                else qwen36_relocation["relocated_config_sha256"][benchmark]
            )
            expected_hashes = {
                "config": run_config_sha256,
                "visible_projection": sha(visible_path),
                "hidden_projection": sha(hidden_path),
            }
            if manifest.get("input_sha256") != expected_hashes:
                raise RuntimeError(f"New run input hash mismatch: {new_run}")
            paths = trajectory_paths(new_run, "B7")
            if len(paths) != expected_new:
                raise RuntimeError(f"Incomplete B7 run: {new_run}")
            for path in paths:
                row = load(path)
                audit = row.get("hidden_leak_audit", {})
                if not audit.get("passed") or audit.get("hidden_evaluation_count") != 1 or audit.get("hidden_feedback_used"):
                    raise RuntimeError(f"Hidden isolation failure: {path}")
                audit_b7_prompt(benchmark, row, visible)
                records.append((benchmark, row))
            old_run = PRIMARY_ROOT / benchmark / model
            old_manifest = load(old_run / "run_manifest.json")
            if old_manifest.get("tasks") != config["tasks"] or old_manifest.get("seeds") != config["generation_seeds"]:
                raise RuntimeError(f"Archived primary grid mismatch: {old_run}")
            for method in ("B0", "B2", "B3"):
                old_paths = trajectory_paths(old_run, method)
                if len(old_paths) != expected_new:
                    raise RuntimeError(f"Incomplete archived {method}: {old_run}")
                records.extend((benchmark, load(path)) for path in old_paths)
            run_records.append({
                "benchmark": benchmark,
                "model": model,
                "new_b7_run_manifest": file_record(manifest_path),
                "new_b7_trajectory_files": file_set_record(paths),
                "archived_primary_run_manifest": file_record(old_run / "run_manifest.json"),
                "new_trajectories": expected_new,
                "factorial_trajectories": expected_new * 4,
            })

    index = {identity(benchmark, row): row for benchmark, row in records}
    if len(records) != 960 or len(index) != 960:
        raise RuntimeError(f"Expected 960 unique factorial records, got {len(records)}/{len(index)}")
    new_ids = {key for key in index if key[-1] == "B7"}
    archived_ids = {key for key in index if key[-1] in {"B0", "B2", "B3"}}
    if len(new_ids) != 240 or len(archived_ids) != 720 or new_ids & archived_ids:
        raise RuntimeError("B7/archived trajectory identity accounting failed")
    balanced_ids, balanced_tasks, balanced_runs = evidence_phase_identities(
        paper_evidence_report, "balanced_expansion_20"
    )
    legacy_ids, legacy_tasks, legacy_runs = evidence_phase_identities(
        paper_evidence_report, "legacy_heterogeneous_31"
    )
    new_tasks = {(benchmark, row["task"]) for benchmark, row in records if row["method"] == "B7"}
    if (
        len(balanced_ids) != 3200
        or len(legacy_ids) != 2705
        or not archived_ids < balanced_ids
        or new_ids & balanced_ids
        or new_ids & legacy_ids
        or balanced_ids & legacy_ids
        or not new_tasks <= balanced_tasks
        or new_tasks & legacy_tasks
        or balanced_tasks & legacy_tasks
    ):
        raise RuntimeError("Cross-study trajectory/task overlap accounting failed")
    accounting_audit = {
        "schema_version": 1,
        "audit_id": "security-only-upfront-ablation-v1-accounting",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": True,
        "canonical_identity_fields": ["benchmark", "model", "task", "request_slot", "method"],
        "counts": {
            "legacy_supporting": len(legacy_ids),
            "balanced_primary": len(balanced_ids),
            "archived_B0_B2_B3_reused": len(archived_ids),
            "new_B7": len(new_ids),
            "factorial_analysis": len(archived_ids | new_ids),
            "primary_source_plus_addendum": len(balanced_ids | new_ids),
            "all_unique_frozen_evidence_after_addendum": len(legacy_ids | balanced_ids | new_ids),
        },
        "identity_set_sha256": {
            "legacy_supporting": identity_set_sha256(legacy_ids),
            "balanced_primary": identity_set_sha256(balanced_ids),
            "archived_B0_B2_B3_reused": identity_set_sha256(archived_ids),
            "new_B7": identity_set_sha256(new_ids),
        },
        "identity_overlap_counts": {
            "legacy_vs_balanced": len(legacy_ids & balanced_ids),
            "legacy_vs_new_B7": len(legacy_ids & new_ids),
            "balanced_vs_new_B7": len(balanced_ids & new_ids),
            "archived_B0_B2_B3_vs_new_B7": len(archived_ids & new_ids),
        },
        "task_overlap_counts": {
            "legacy_vs_balanced": len(legacy_tasks & balanced_tasks),
            "legacy_vs_new_B7": len(legacy_tasks & new_tasks),
            "new_B7_tasks_outside_balanced_primary": len(new_tasks - balanced_tasks),
        },
        "subset_checks": {
            "archived_B0_B2_B3_are_strict_subset_of_balanced_primary": archived_ids < balanced_ids,
            "new_B7_tasks_are_subset_of_balanced_primary_tasks": new_tasks <= balanced_tasks,
        },
        "source": {
            "paper_evidence_freeze": file_record(PAPER_EVIDENCE_FREEZE),
            "paper_evidence_report": file_record(PAPER_EVIDENCE_REPORT),
            "balanced_runs": balanced_runs,
            "legacy_runs": legacy_runs,
        },
    }
    ACCOUNTING_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNTING_AUDIT.write_text(
        json.dumps(accounting_audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summaries = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    pooled: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for benchmark, row in records:
        grouped[(benchmark, row["model"], row["method"])].append(row)
        pooled[row["method"]].append(row)
    for (benchmark, model, method), rows in sorted(grouped.items()):
        outcome = [values(row) for row in rows]
        summaries.append({
            "benchmark": benchmark,
            "model": model,
            "method": method,
            "n": len(rows),
            **{metric: mean(item[metric] for item in outcome) for metric in METRICS},
            "states": dict(sorted(Counter(state(row) for row in rows).items())),
        })
    pooled_summaries = {}
    for method in METHODS:
        outcome = [values(row) for row in pooled[method]]
        pooled_summaries[method] = {
            "label": METHOD_LABELS[method],
            "n": len(outcome),
            **{metric: mean(item[metric] for item in outcome) for metric in METRICS},
            "states": dict(sorted(Counter(state(row) for row in pooled[method]).items())),
        }

    specs = (
        ("functional_only_minus_requirement", {"B2": 1.0, "B0": -1.0}),
        ("security_only_minus_requirement", {"B7": 1.0, "B0": -1.0}),
        ("both_minus_requirement", {"B3": 1.0, "B0": -1.0}),
        ("security_increment_given_functional", {"B3": 1.0, "B2": -1.0}),
        ("functional_increment_given_security", {"B3": 1.0, "B7": -1.0}),
        ("functional_tests_main_effect", {"B2": 0.5, "B0": -0.5, "B3": 0.5, "B7": -0.5}),
        ("security_tests_main_effect", {"B7": 0.5, "B0": -0.5, "B3": 0.5, "B2": -0.5}),
        ("functional_x_security_interaction", {"B3": 1.0, "B2": -1.0, "B7": -1.0, "B0": 1.0}),
    )
    contrasts = [contrast(index, name, weights, 20260829 + offset * 10) for offset, (name, weights) in enumerate(specs)]
    stratified_specs = (
        ("functional_only_minus_requirement", {"B2": 1.0, "B0": -1.0}),
        ("security_only_minus_requirement", {"B7": 1.0, "B0": -1.0}),
        ("both_minus_requirement", {"B3": 1.0, "B0": -1.0}),
        ("security_increment_given_functional", {"B3": 1.0, "B2": -1.0}),
    )
    stratified_contrasts = []
    stratum_seed = 20260930
    for benchmark in BENCHMARKS:
        for model in MODELS:
            for name, weights in stratified_specs:
                stratified_contrasts.append(
                    stratified_contrast(
                        index,
                        benchmark,
                        model,
                        name,
                        weights,
                        stratum_seed,
                    )
                )
                stratum_seed += 10
    stratified_direction_counts = {}
    for name, _ in stratified_specs:
        estimates = [
            item["metrics"]["joint"]["estimate"]
            for item in stratified_contrasts
            if item["name"] == name
        ]
        stratified_direction_counts[name] = {
            "positive": sum(value > 0 for value in estimates),
            "zero": sum(value == 0 for value in estimates),
            "negative": sum(value < 0 for value in estimates),
            "strata": len(estimates),
        }
    report = {
        "schema_version": 1,
        "report_id": "security-only-upfront-ablation-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": True,
        "post_primary_addendum": True,
        "new_b7_trajectory_count": 240,
        "factorial_trajectory_count": 960,
        "task_count": 12,
        "model_count": 4,
        "repetitions_per_cell": 5,
        "inference": {
            "unit": "task",
            "cluster_key": "benchmark:task",
            "pooled_task_cluster_count": 12,
            "bootstrap_replicates": 10000,
            "pooled_bootstrap_seed_base": 20260829,
            "pooled_bootstrap_seed_step_by_contrast": 10,
            "stratified_bootstrap_seed_base": 20260930,
            "stratified_bootstrap_seed_step": 10,
            "models_and_request_slots_are_within_task_repetitions": True,
        },
        "trajectory_accounting": {
            "identity_key": ["benchmark", "model", "task", "request_slot", "method"],
            "archived_B0_B2_B3_from_balanced_primary": 720,
            "new_B7": 240,
            "identity_overlap_between_archived_and_new": 0,
            "factorial_analysis_records": 960,
            "prior_balanced_primary_unique_trajectories": 3200,
            "prior_legacy_disjoint_unique_trajectories": 2705,
            "prior_combined_unique_trajectories": 5905,
            "combined_unique_trajectories_after_addendum": 6145,
            "primary_source_plus_post_primary_addendum_unique_trajectories": 3440,
            "accounting_rule": "Only the 240 B7 trajectories are new; the 720 B0/B2/B3 records are reused from the 3,200-trajectory balanced primary experiment.",
            "accounting_audit": file_record(ACCOUNTING_AUDIT),
        },
        "new_B7_counts_by_model": {
            model: {
                "sallm": 40,
                "codeguardplus": 20,
                "total": 60,
            }
            for model in MODELS
        },
        "methods": METHOD_LABELS,
        "runs": run_records,
        "condition_summaries": summaries,
        "task_pooled_summaries": pooled_summaries,
        "contrasts": contrasts,
        "stratified_contrasts": stratified_contrasts,
        "stratified_joint_direction_counts": stratified_direction_counts,
        "interpretation_boundary": freeze["interpretation_boundary"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def pct(value: float) -> str:
        return f"{100 * value:.2f}%"

    lines = [
        "# Security-only upfront ablation v1 results",
        "",
        "Post-primary hypothesis-driven 2x2 factorial over the 12 SALLM/CodeGuard+ primary tasks.",
        "",
        "## Completeness and trajectory accounting",
        "",
        "| Model | SALLM B7 | CodeGuard+ B7 | New B7 total |",
        "|---|---:|---:|---:|",
    ]
    for model in MODELS:
        counts = report["new_B7_counts_by_model"][model]
        lines.append(
            f"| {model} | {counts['sallm']} | {counts['codeguardplus']} | {counts['total']} |"
        )
    lines.extend([
        "| **All four models** | **160** | **80** | **240** |",
        "",
        "Only B7 contributes new trajectories. The 720 B0/B2/B3 records are reused from the "
        "3,200-trajectory balanced primary experiment: 720 archived + 240 new = 960 records in "
        "this factorial analysis. The prior 2,705 trajectories are a disjoint legacy evidence set, "
        "so the repository-wide unique count changes from 5,905 to 6,145, not to 3,665.",
        "",
        "All confidence intervals resample the 12 `benchmark:task` clusters 10,000 times. Models and "
        "five request slots are within-task repetitions, never independent inference units.",
        "",
        "## Task-balanced outcomes",
        "",
        "| Condition | Functional | Security | Joint | SAFE |",
        "|---|---:|---:|---:|---:|",
    ])
    for method in METHODS:
        item = pooled_summaries[method]
        lines.append(f"| {item['label']} | {pct(item['functional'])} | {pct(item['security'])} | {pct(item['joint'])} | {pct(item['safe'])} |")
    lines.extend(["", "## Planned hidden-joint contrasts", "", "| Contrast | Estimate | 95% task-bootstrap CI | Wins | Losses |", "|---|---:|---:|---:|---:|"])
    for item in contrasts:
        joint = item["metrics"]["joint"]
        lines.append(
            f"| {item['name']} | {100*joint['estimate']:.2f} pp | "
            f"[{100*joint['ci95'][0]:.2f}, {100*joint['ci95'][1]:.2f}] | "
            f"{item['joint_wins'] if item['joint_wins'] is not None else '--'} | "
            f"{item['joint_losses'] if item['joint_losses'] is not None else '--'} |"
        )
    incremental = next(
        item for item in contrasts if item["name"] == "security_increment_given_functional"
    )
    lines.extend([
        "",
        "## Direct incremental value of security tests given functional tests (B3 - B2)",
        "",
        "| Metric | Estimate | 95% task-cluster bootstrap CI |",
        "|---|---:|---:|",
    ])
    for metric in ("functional", "security", "joint"):
        value = incremental["metrics"][metric]
        lines.append(
            f"| {metric.capitalize()} | {100*value['estimate']:.2f} pp | "
            f"[{100*value['ci95'][0]:.2f}, {100*value['ci95'][1]:.2f}] |"
        )
    summary_index = {
        (item["benchmark"], item["model"], item["method"]): item
        for item in summaries
    }
    stratum_index = {
        (item["benchmark"], item["model"], item["name"]): item
        for item in stratified_contrasts
    }
    lines.extend([
        "",
        "## Benchmark-model stratified hidden-joint results",
        "",
        "| Benchmark | Model | B0 | B2 | B7 | B3 | B7-B0 [95% CI] | B3-B2 [95% CI] |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for benchmark in BENCHMARKS:
        for model in MODELS:
            outcomes = {
                method: summary_index[(benchmark, model, method)]["joint"]
                for method in METHODS
            }
            b7 = stratum_index[(benchmark, model, "security_only_minus_requirement")]["metrics"]["joint"]
            b3_b2 = stratum_index[(benchmark, model, "security_increment_given_functional")]["metrics"]["joint"]
            lines.append(
                f"| {benchmark} | {model} | {pct(outcomes['B0'])} | {pct(outcomes['B2'])} | "
                f"{pct(outcomes['B7'])} | {pct(outcomes['B3'])} | "
                f"{100*b7['estimate']:.2f} [{100*b7['ci95'][0]:.2f}, {100*b7['ci95'][1]:.2f}] | "
                f"{100*b3_b2['estimate']:.2f} [{100*b3_b2['ci95'][0]:.2f}, {100*b3_b2['ci95'][1]:.2f}] |"
            )
    lines.extend([
        "",
        "Stratified intervals contain only eight SALLM or four CodeGuard+ task clusters and are "
        "therefore diagnostic. They are not multiplicity-adjusted, and pooled task-cluster contrasts "
        "remain the inferential results. B3-B2 has no negative joint point estimate across the eight "
        "strata (six positive, two zero). B7-B0 reverses for SALLM/qwen25-coder-7b on joint success "
        "(-5.00 pp); its security component also reverses for SALLM qwen25-coder-7b and 14b "
        "(-2.50 pp each), so the effect remains model- and benchmark-dependent.",
    ])
    lines.extend(["", report["interpretation_boundary"], ""])
    MARKDOWN.write_text("\n".join(lines), encoding="utf-8")
    result_freeze = {
        "schema_version": 1,
        "freeze_id": "security-only-upfront-ablation-v1-results",
        "complete": True,
        "formal_results_use": True,
        "post_primary_addendum": True,
        "inputs": {
            "analysis_program": file_record(Path(__file__).resolve()),
            "input_freeze": file_record(FREEZE),
            "qwen25_checkpoint_relocation": file_record(RELOCATION),
            "qwen36_checkpoint_relocation": file_record(QWEN36_RELOCATION),
            "prior_paper_evidence_freeze": file_record(PAPER_EVIDENCE_FREEZE),
        },
        "outputs": {
            "accounting_audit": file_record(ACCOUNTING_AUDIT),
            "json_report": file_record(REPORT),
            "markdown_report": file_record(MARKDOWN),
        },
        "new_b7_trajectory_count": 240,
        "factorial_trajectory_count": 960,
    }
    RESULT_FREEZE.write_text(json.dumps(result_freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "complete": True,
        "new_b7_trajectories": 240,
        "factorial_trajectories": 960,
        "tasks": 12,
        "report": REPORT.relative_to(ROOT).as_posix(),
    }, indent=2))


if __name__ == "__main__":
    main()
