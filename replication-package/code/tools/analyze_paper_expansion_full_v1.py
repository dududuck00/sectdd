#!/usr/bin/env python3
"""Validate and summarize the complete paper-expansion experiment grid."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sectdd.orchestrator import normalize_python_response


RUN_ROOT = ROOT / "artifacts/paper-expansion-full-v1"
REPORT_JSON = ROOT / "artifacts/reports/paper-expansion-full-v1.json"
REPORT_MD = ROOT / "docs/paper-expansion-full-v1.md"
FREEZE = ROOT / "benchmarks/manifests/paper-expansion-full-v1-results-freeze.json"
BENCHMARKS = ("cweval", "sallm", "codeguardplus")
MODELS = ("qwen25-coder-7b", "qwen25-coder-14b", "qwen36-27b", "deepseek-v4-flash")
PAIRS = (("B1", "B0"), ("B2", "B0"), ("B3", "B0"), ("B4", "B0"), ("B5", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4"), ("M", "B5"))


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def outcome(row: dict[str, Any]) -> tuple[int, int, int, float]:
    hidden = row["final_hidden"]
    functional = int(hidden["functional"]["all_passed"])
    security = int(hidden["security"]["all_passed"])
    joint = int(hidden["joint_pass"])
    safe = hidden.get("safe")
    if not isinstance(safe, (int, float)):
        safe = float(joint)
    return functional, security, joint, float(safe)


def visible_joint(row: dict[str, Any]) -> bool:
    visible = row["final_visible"]
    cases = visible.get("cases", [])
    if cases:
        functional = [
            case
            for case in cases
            if case.get("marker") in {"functional", "functionality"}
        ]
        security = [case for case in cases if case.get("marker") == "security"]
        return bool(functional and security) and all(
            case.get("passed") for case in functional + security
        )
    return bool(visible["summary"]["all_passed"])


def validate_candidate(
    benchmark: str, row: dict[str, Any], round_value: dict[str, Any]
) -> None:
    """Validate the benchmark-specific persisted candidate representation."""

    record = round_value.get("candidate")
    if record is not None:
        candidate = ROOT / record["path"]
        if not candidate.is_file() or sha(candidate) != record["sha256"]:
            raise RuntimeError(f"Candidate hash mismatch: {candidate}")
        return
    if benchmark != "cweval":
        raise RuntimeError(
            f"Candidate record missing: {benchmark}/{row['model']}/"
            f"{row['task']}/{row['method']}"
        )
    # CWEval persists an evaluation tree rather than a candidate record.  Its
    # raw candidate must exactly match the canonicalized model response.
    command = round_value.get("visible_execution", {}).get("command", [])
    try:
        eval_root = Path(command[command.index("--eval-path") + 1]).resolve()
    except (ValueError, IndexError) as error:
        raise RuntimeError("CWEval candidate eval path missing") from error
    eval_root.relative_to(ROOT)
    candidate = (
        eval_root
        / "generated_0"
        / "core"
        / "py"
        / f"{row['task']}_raw.py"
    )
    if not candidate.is_file() or candidate.read_text(encoding="utf-8") != (
        normalize_python_response(round_value["response"])
    ):
        raise RuntimeError(f"CWEval candidate content mismatch: {candidate}")


def state(row: dict[str, Any]) -> str:
    functional, security, _, _ = outcome(row)
    return f"F{'+' if functional else '-'}S{'+' if security else '-'}"


def pass_at_k(successes: int, samples: int, k: int) -> float:
    if samples < k:
        raise ValueError(f"Cannot compute @{k} from {samples} samples")
    if successes <= 0:
        return 0.0
    if samples - successes < k:
        return 1.0
    return 1.0 - math.comb(samples - successes, k) / math.comb(samples, k)


def at_k(rows: list[dict[str, Any]], k: int) -> dict[str, float]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row)
    values = defaultdict(list)
    for samples in by_task.values():
        outcomes = [outcome(row) for row in samples]
        values["pass"].append(pass_at_k(sum(item[0] for item in outcomes), len(samples), k))
        values["secure"].append(pass_at_k(sum(item[1] for item in outcomes), len(samples), k))
        values["joint"].append(pass_at_k(sum(item[2] for item in outcomes), len(samples), k))
        # SAFE@k follows the adopted paper protocol: the mean continuous SAFE
        # utility over independent samples (equivalently, over size-k subsets).
        values["safe"].append(mean(item[3] for item in outcomes))
    return {name: mean(items) for name, items in values.items()}


def first_visible_pass_round(row: dict[str, Any]) -> int | None:
    for round_value in row["rounds"]:
        visible = round_value["visible_result"]
        if visible.get("summary", {}).get("all_passed"):
            return int(round_value["round"])
    return None


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    index = min(len(values) - 1, max(0, round((len(values) - 1) * fraction)))
    return values[index]


def task_bootstrap(deltas: dict[str, list[float]], seed: int, repeats: int = 10000) -> dict[str, float]:
    tasks = sorted(deltas)
    observed = mean(mean(deltas[task]) for task in tasks)
    rng = random.Random(seed)
    samples = []
    for _ in range(repeats):
        chosen = [rng.choice(tasks) for _ in tasks]
        samples.append(mean(mean(deltas[task]) for task in chosen))
    return {"mean_delta": observed, "ci95_low": percentile(samples, 0.025), "ci95_high": percentile(samples, 0.975), "task_clusters": len(tasks), "bootstrap_replicates": repeats}


def main() -> None:
    all_rows: list[dict[str, Any]] = []
    run_records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int]] = set()
    for benchmark in BENCHMARKS:
        config_path = ROOT / f"configs/experiments/{benchmark}_paper_expansion_full_v1.json"
        config = load(config_path)
        expected_per_model = len(config["tasks"]) * len(config["methods"]) * len(config["generation_seeds"])
        for model in MODELS:
            run = RUN_ROOT / benchmark / model
            manifest_path = run / "run_manifest.json"
            if not manifest_path.is_file():
                raise FileNotFoundError(f"Incomplete matrix: {manifest_path}")
            manifest = load(manifest_path)
            if manifest.get("trajectory_count") != expected_per_model:
                raise RuntimeError(f"Trajectory manifest count mismatch: {run}")
            if manifest.get("tasks") != config["tasks"] or manifest.get("methods") != list(config["methods"]) or manifest.get("seeds") != config["generation_seeds"]:
                raise RuntimeError(f"Frozen grid mismatch: {run}")
            for key, path in (
                ("config", config_path),
                ("visible_projection", ROOT / manifest["visible_projection"]),
                ("hidden_projection", ROOT / manifest["hidden_projection"]),
            ):
                if manifest.get("input_sha256", {}).get(key) != sha(path):
                    raise RuntimeError(f"Frozen input hash mismatch ({key}): {run}")
            paths = sorted((run / "trajectories").glob("*/*/seed_*/trajectory.json"))
            if len(paths) != expected_per_model:
                raise RuntimeError(f"Trajectory file count mismatch: {run}: {len(paths)}/{expected_per_model}")
            provider = config["models"][model].get("provider", "local")
            if manifest.get("provider", "local") != provider:
                raise RuntimeError(f"Provider drift: {run}")
            for path in paths:
                row = load(path)
                identity = (benchmark, row["model"], row["method"], row["task"], int(row["generation_seed"]))
                if identity in seen:
                    raise RuntimeError(f"Duplicate trajectory: {identity}")
                seen.add(identity)
                if row["model"] != model or row["task"] not in config["tasks"] or row["method"] not in config["methods"] or row["generation_seed"] not in config["generation_seeds"]:
                    raise RuntimeError(f"Trajectory identity drift: {path}")
                audit = row.get("hidden_leak_audit", {})
                if not audit.get("passed") or audit.get("hidden_evaluation_count") != 1 or audit.get("hidden_feedback_used"):
                    raise RuntimeError(f"Hidden-isolation failure: {path}")
                for round_value in row["rounds"]:
                    validate_candidate(benchmark, row, round_value)
                row["_benchmark"] = benchmark
                all_rows.append(row)
            run_records.append({"benchmark": benchmark, "model": model, "provider": provider, "tasks": len(config["tasks"]), "methods": len(config["methods"]), "repeats": len(config["generation_seeds"]), "trajectories": expected_per_model, "manifest": rec(manifest_path)})

    by_key = {(row["_benchmark"], row["model"], row["task"], int(row["generation_seed"]), row["method"]): row for row in all_rows}
    shared_checks = 0
    for row in all_rows:
        reference = row["method_config"].get("shared_initial_from")
        if reference is None:
            continue
        other = by_key[(row["_benchmark"], row["model"], row["task"], int(row["generation_seed"]), reference)]
        left, right = row["rounds"][0], other["rounds"][0]
        for field in ("messages", "request_seed", "response", "usage"):
            if left[field] != right[field]:
                raise RuntimeError(f"Shared initial candidate mismatch: {row['_benchmark']}/{row['model']}/{row['task']}/{row['method']}")
        if not left.get("generation_reused"):
            raise RuntimeError(f"Shared initial candidate not marked reused: {row['_benchmark']}/{row['model']}/{row['task']}/{row['method']}")
        shared_checks += 1

    aggregates = []
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[(row["_benchmark"], row["model"], row["method"])].append(row)
    for (benchmark, model, method), rows in sorted(grouped.items()):
        values = [outcome(row) for row in rows]
        functional_successes = sum(item[0] for item in values)
        joint_successes = sum(item[2] for item in values)
        visible_passes = [row for row in rows if visible_joint(row)]
        first_passes = [value for row in rows if (value := first_visible_pass_round(row)) is not None]
        aggregates.append({
            "benchmark": benchmark,
            "model": model,
            "method": method,
            "trajectories": len(rows),
            "functional_rate": mean(item[0] for item in values),
            "security_rate": mean(item[1] for item in values),
            "joint_rate": mean(item[2] for item in values),
            "safe_mean": mean(item[3] for item in values),
            "security_given_functional": joint_successes / functional_successes if functional_successes else None,
            "visible_joint_rate": len(visible_passes) / len(rows),
            "tfor": {
                "numerator": sum(not row["final_hidden"]["joint_pass"] for row in visible_passes),
                "denominator": len(visible_passes),
                "rate": (sum(not row["final_hidden"]["joint_pass"] for row in visible_passes) / len(visible_passes)) if visible_passes else None,
            },
            "states": dict(sorted(Counter(state(row) for row in rows).items())),
            "at_k": {str(k): at_k(rows, k) for k in (1, 3, 5)},
            "mean_first_visible_pass_round": mean(first_passes) if first_passes else None,
            "cost": {
                key: {
                    "total": sum(float(row["budget_usage"][key]) for row in rows),
                    "mean": mean(float(row["budget_usage"][key]) for row in rows),
                }
                for key in ("model_calls", "input_tokens", "output_tokens", "feedback_tokens", "visible_test_executions")
            },
        })

    comparisons = []
    for treatment, control in PAIRS:
        delta_by_task: dict[str, list[float]] = defaultdict(list)
        transitions = defaultdict(int)
        feedback_triggered = function_regressed = security_regressed = security_only_repaired = 0
        call_deltas: list[float] = []
        feedback_token_deltas: list[float] = []
        for benchmark in BENCHMARKS:
            for model in MODELS:
                config = load(ROOT / f"configs/experiments/{benchmark}_paper_expansion_full_v1.json")
                for task in config["tasks"]:
                    cluster = f"{benchmark}:{task}"
                    for seed in config["generation_seeds"]:
                        treated = outcome(by_key[(benchmark, model, task, seed, treatment)])[2]
                        baseline = outcome(by_key[(benchmark, model, task, seed, control)])[2]
                        treated_row = by_key[(benchmark, model, task, seed, treatment)]
                        baseline_row = by_key[(benchmark, model, task, seed, control)]
                        delta_by_task[cluster].append(treated - baseline)
                        transitions[f"{baseline}->{treated}"] += 1
                        feedback_triggered += int(len(treated_row["rounds"]) > 1)
                        bf, bs, _, _ = outcome(baseline_row)
                        tf, ts, tj, _ = outcome(treated_row)
                        function_regressed += int(bf and not tf)
                        security_regressed += int(bs and not ts)
                        security_only_repaired += int(bf and not bs and tj)
                        call_deltas.append(treated_row["budget_usage"]["model_calls"] - baseline_row["budget_usage"]["model_calls"])
                        feedback_token_deltas.append(treated_row["budget_usage"]["feedback_tokens"] - baseline_row["budget_usage"]["feedback_tokens"])
        comparison = {
            "treatment": treatment,
            "control": control,
            **task_bootstrap(delta_by_task, 20261101 + len(comparisons)),
            "wins": transitions["0->1"],
            "losses": transitions["1->0"],
            "ties": transitions["0->0"] + transitions["1->1"],
            "feedback_trigger_count": feedback_triggered,
            "repair_per_trigger": transitions["0->1"] / feedback_triggered if feedback_triggered else None,
            "joint_regression_per_trigger": transitions["1->0"] / feedback_triggered if feedback_triggered else None,
            "function_regression_count": function_regressed,
            "security_regression_count": security_regressed,
            "security_only_repair_count": security_only_repaired,
            "mean_call_delta": mean(call_deltas),
            "mean_feedback_token_delta": mean(feedback_token_deltas),
            "state_transitions": dict(sorted(transitions.items())),
        }
        comparisons.append(comparison)

    report = {
        "schema_version": 1,
        "report_id": "paper-expansion-full-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": True,
        "inference_unit": "task",
        "trajectory_count": len(all_rows),
        "task_instance_count": sum(record["tasks"] for record in run_records if record["model"] == MODELS[0]),
        "benchmark_count": len(BENCHMARKS),
        "model_count": len(MODELS),
        "method_count": len(grouped) // (len(BENCHMARKS) * len(MODELS)),
        "shared_initial_candidate_checks": shared_checks,
        "runs": run_records,
        "aggregates": aggregates,
        "paired_joint_comparisons": comparisons,
        "interpretation_boundary": "Expansion tasks were selected and semantically qualified without B0--B6/M or G8 outcome filtering; repeated trajectories are not treated as independent task samples.",
    }
    write(REPORT_JSON, report)
    lines = ["# Paper expansion full matrix v1", "", f"- Tasks: {report['task_instance_count']}", f"- Trajectories: {report['trajectory_count']}", f"- Methods: {report['method_count']}", f"- Models: {report['model_count']}", "", "## Condition outcomes", "", "| Benchmark | Model | Method | Func | Secure | Joint | SAFE | SGF | TFOR | Calls |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    def pct(value: float | None) -> str:
        return "--" if value is None else f"{100 * value:.1f}%"
    for item in aggregates:
        lines.append(f"| {item['benchmark']} | {item['model']} | {item['method']} | {pct(item['functional_rate'])} | {pct(item['security_rate'])} | {pct(item['joint_rate'])} | {pct(item['safe_mean'])} | {pct(item['security_given_functional'])} | {pct(item['tfor']['rate'])} | {item['cost']['model_calls']['mean']:.2f} |")
    lines.extend(["", "## Paired hidden-joint comparisons", "", "| Comparison | Delta | 95% task-bootstrap CI | Wins | Losses | Repair/trigger | Function regressions |", "|---|---:|---:|---:|---:|---:|---:|"])
    for item in comparisons:
        lines.append(f"| {item['treatment']} - {item['control']} | {100*item['mean_delta']:.2f} pp | [{100*item['ci95_low']:.2f}, {100*item['ci95_high']:.2f}] | {item['wins']} | {item['losses']} | {pct(item['repair_per_trigger'])} | {item['function_regression_count']} |")
    lines.extend(["", report["interpretation_boundary"], ""])
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    write(FREEZE, {"schema_version": 1, "freeze_id": "paper-expansion-full-v1-results", "complete": True, "formal_results_use": True, "task_instance_count": report["task_instance_count"], "trajectory_count": report["trajectory_count"], "inputs": {f"{item['benchmark']}:{item['model']}": item["manifest"] for item in run_records}, "outputs": {"json_report": rec(REPORT_JSON), "markdown_report": rec(REPORT_MD)}})
    print(json.dumps({"tasks": report["task_instance_count"], "trajectories": report["trajectory_count"], "models": report["model_count"], "methods": report["method_count"], "complete": True}, indent=2))


if __name__ == "__main__":
    main()
