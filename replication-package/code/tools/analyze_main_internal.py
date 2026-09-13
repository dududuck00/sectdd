#!/usr/bin/env python3
"""Analyze frozen protocol-v2 internal confirmatory main runs."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import defaultdict
from pathlib import Path

from analyze_feedback_v2 import (
    FEEDBACK_METHODS,
    METHODS,
    paired_feedback,
    pct,
    summarize,
)


METRICS = {
    "hidden_secure_pass_at_1": lambda item: float(
        item["final_hidden"]["joint_pass"]
    ),
    "hidden_safe_at_1": lambda item: float(item["final_hidden"]["safe"]),
    "hidden_func_at_1": lambda item: float(
        item["final_hidden"]["functional"]["all_passed"]
    ),
    "hidden_secure_at_1": lambda item: float(
        item["final_hidden"]["security"]["all_passed"]
    ),
}
CONFIRMATORY_BASELINES = ("B0", "B3", "B4", "B5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260728)
    return parser.parse_args()


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def task_values(items: list[dict], metric: str) -> dict[str, float]:
    grouped = defaultdict(list)
    extract = METRICS[metric]
    for item in items:
        grouped[item["task"]].append(extract(item))
    return {
        task: mean(values) for task, values in sorted(grouped.items())
    }


def clustered_ci(
    values: dict[str, float],
    replicates: int,
    rng: random.Random,
) -> dict:
    tasks = list(values)
    observed = mean(list(values.values()))
    samples = []
    for _ in range(replicates):
        samples.append(
            mean([values[rng.choice(tasks)] for _ in range(len(tasks))])
        )
    return {
        "estimate": observed,
        "lower": quantile(samples, 0.025),
        "upper": quantile(samples, 0.975),
        "clusters": len(tasks),
        "replicates": replicates,
    }


def exact_sign_flip_pvalue(differences: list[float]) -> float:
    observed = abs(mean(differences))
    extreme = 0
    total = 0
    epsilon = 1e-12
    for signs in itertools.product((-1.0, 1.0), repeat=len(differences)):
        permuted = abs(
            mean(
                [
                    difference * sign
                    for difference, sign in zip(differences, signs)
                ]
            )
        )
        total += 1
        if permuted + epsilon >= observed:
            extreme += 1
    return extreme / total


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues, key=pvalues.get)
    adjusted = {}
    running = 0.0
    count = len(ordered)
    for rank, key in enumerate(ordered):
        candidate = min(1.0, (count - rank) * pvalues[key])
        running = max(running, candidate)
        adjusted[key] = running
    return adjusted


def load_run(run_dir: Path) -> dict:
    resolved = run_dir.expanduser().resolve()
    manifest = json.loads((resolved / "run_manifest.json").read_text())
    paths = sorted(
        resolved.glob("trajectories/*/*/seed_*/trajectory.json")
    )
    trajectories = [json.loads(path.read_text()) for path in paths]
    if len(trajectories) != manifest["trajectory_count"]:
        raise AssertionError(f"{resolved}: trajectory count mismatch")
    expected = (
        len(manifest["tasks"])
        * len(manifest["methods"])
        * len(manifest["seeds"])
    )
    if len(trajectories) != expected:
        raise AssertionError(f"{resolved}: incomplete condition grid")
    return {
        "run_dir": str(resolved),
        "manifest": manifest,
        "trajectories": trajectories,
    }


def analyze_model(
    run: dict,
    replicates: int,
    rng: random.Random,
) -> dict:
    trajectories = run["trajectories"]
    by_method = defaultdict(list)
    index = {}
    for item in trajectories:
        by_method[item["method"]].append(item)
        index[(item["task"], item["generation_seed"], item["method"])] = item

    methods = {}
    task_metric_values = {}
    for method in METHODS:
        methods[method] = summarize(by_method[method])
        task_metric_values[method] = {}
        methods[method]["task_clustered_ci"] = {}
        for metric in METRICS:
            values = task_values(by_method[method], metric)
            task_metric_values[method][metric] = values
            methods[method]["task_clustered_ci"][metric] = clustered_ci(
                values, replicates, rng
            )

    comparisons = {}
    raw_pvalues = {}
    for baseline in CONFIRMATORY_BASELINES:
        label = f"M_vs_{baseline}"
        m_values = task_metric_values["M"]["hidden_secure_pass_at_1"]
        b_values = task_metric_values[baseline][
            "hidden_secure_pass_at_1"
        ]
        differences = [
            m_values[task] - b_values[task] for task in sorted(m_values)
        ]
        ci = clustered_ci(
            {
                task: m_values[task] - b_values[task]
                for task in sorted(m_values)
            },
            replicates,
            rng,
        )
        pvalue = exact_sign_flip_pvalue(differences)
        raw_pvalues[label] = pvalue
        comparisons[label] = {
            "method": "M",
            "baseline": baseline,
            "absolute_difference": mean(differences),
            "task_clustered_ci": ci,
            "exact_sign_flip_pvalue": pvalue,
            "task_differences": {
                task: m_values[task] - b_values[task]
                for task in sorted(m_values)
            },
        }
    adjusted = holm_adjust(raw_pvalues)
    for label, value in adjusted.items():
        comparisons[label]["holm_adjusted_pvalue"] = value

    return {
        "run_dir": run["run_dir"],
        "manifest": run["manifest"],
        "methods": methods,
        "paired_feedback": {
            method: paired_feedback(index, method)
            for method in FEEDBACK_METHODS
        },
        "confirmatory_comparisons": comparisons,
    }


def build_report(
    runs: list[dict],
    replicates: int,
    bootstrap_seed: int,
) -> dict:
    config_hashes = [run["manifest"]["input_sha256"] for run in runs]
    oracle_hashes = [
        run["manifest"]["canonical_oracle_manifest_sha256"] for run in runs
    ]
    seeds = [run["manifest"]["seeds"] for run in runs]
    if any(value != config_hashes[0] for value in config_hashes[1:]):
        raise AssertionError("Runs do not share identical frozen inputs")
    if any(value != oracle_hashes[0] for value in oracle_hashes[1:]):
        raise AssertionError("Runs do not share canonical oracle")
    if any(value != seeds[0] for value in seeds[1:]):
        raise AssertionError("Runs do not share generation seeds")
    rng = random.Random(bootstrap_seed)
    models = {
        run["manifest"]["model"]: analyze_model(run, replicates, rng)
        for run in runs
    }
    return {
        "schema_version": 1,
        "study_phase": "main_internal_confirmatory",
        "primary_metric": "hidden_secure_pass_at_1",
        "development_results_included": False,
        "design": {
            "models": len(runs),
            "tasks": len(runs[0]["manifest"]["tasks"]),
            "methods": len(runs[0]["manifest"]["methods"]),
            "seeds": seeds[0],
            "trajectory_count": sum(
                run["manifest"]["trajectory_count"] for run in runs
            ),
        },
        "immutable_inputs": {
            "identical_across_models": True,
            "input_sha256": config_hashes[0],
            "canonical_oracle_manifest_sha256": oracle_hashes[0],
        },
        "statistics": {
            "inference_unit": "task",
            "bootstrap_replicates": replicates,
            "bootstrap_seed": bootstrap_seed,
            "confidence_level": 0.95,
            "paired_test": "exact_sign_flip_permutation",
            "multiple_comparison_correction": "holm_within_model",
        },
        "models": models,
    }


def ci_text(ci: dict) -> str:
    return (
        f"{pct(ci['estimate'])} "
        f"[{pct(ci['lower'])}, {pct(ci['upper'])}]"
    )


def markdown(report: dict) -> str:
    design = report["design"]
    lines = [
        "# Protocol v2 内部确认性主实验",
        "",
        f"冻结主分析包含 {design['models']} models × {design['tasks']} tasks × "
        f"{design['methods']} methods × {len(design['seeds'])} seeds，共 "
        f"{design['trajectory_count']} 条协议有效轨迹。开发 seeds 未并入分析。",
        "",
        "## 主结果",
        "",
        "括号为按 task 聚类 bootstrap 的 95% CI。",
        "",
        "| 模型 | 方法 | Secure-Pass@1 (95% CI) | SAFE@1 | Func@1 | "
        "Secure@1 | 平均调用 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model, result in report["models"].items():
        for method in METHODS:
            row = result["methods"][method]
            lines.append(
                f"| {model} | {method} | "
                f"{ci_text(row['task_clustered_ci']['hidden_secure_pass_at_1'])} | "
                f"{pct(row['hidden_safe_at_1'])} | "
                f"{pct(row['hidden_func_at_1'])} | "
                f"{pct(row['hidden_secure_at_1'])} | "
                f"{row['cost']['model_calls']['mean']:.2f} |"
            )

    lines.extend(
        [
            "",
            "## M 的确认性配对比较",
            "",
            "差值为 M − baseline 的 Secure-Pass@1 绝对百分点；p 值按每模型"
            "四项比较进行 Holm 校正。",
            "",
            "| 模型 | 比较 | 差值 (95% CI) | exact p | Holm p |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for model, result in report["models"].items():
        for label in (
            "M_vs_B0",
            "M_vs_B3",
            "M_vs_B4",
            "M_vs_B5",
        ):
            row = result["confirmatory_comparisons"][label]
            ci = row["task_clustered_ci"]
            lines.append(
                f"| {model} | {label} | {pct(row['absolute_difference'])} "
                f"[{pct(ci['lower'])}, {pct(ci['upper'])}] | "
                f"{row['exact_sign_flip_pvalue']:.4f} | "
                f"{row['holm_adjusted_pvalue']:.4f} |"
            )

    lines.extend(
        [
            "",
            "## 反馈修复与回退",
            "",
            "| 模型 | 方法 | 触发率 | FPSR | 联合改善/回退 | 功能回退 | "
            "Vis-pass/Hid-fail |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model, result in report["models"].items():
        for method in FEEDBACK_METHODS:
            row = result["paired_feedback"][method]
            lines.append(
                f"| {model} | {method} | {pct(row['trigger_rate'])} | "
                f"{row['secure_repairs_without_function_loss']}/"
                f"{row['initial_f_plus_s_minus']} ({pct(row['fpsr'])}) | "
                f"{row['joint_improved']}/{row['joint_regressed']} | "
                f"{row['functionality_regressions']} | "
                f"{row['visible_pass_hidden_joint_fail']} |"
            )

    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "该分析使用独立 generation seeds，并覆盖多个模型家族和规模，但九个"
            "任务参与过方法开发。因此结果可用于内部重复性与机制检验，不能替代"
            "未参与开发任务、外部 benchmark 或其他语言上的外部验证。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    runs = [load_run(path) for path in args.run_dirs]
    report = build_report(
        runs, args.bootstrap_replicates, args.bootstrap_seed
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    args.markdown_output.write_text(markdown(report))
    print(f"JSON: {args.json_output.resolve()}")
    print(f"Markdown: {args.markdown_output.resolve()}")


if __name__ == "__main__":
    main()
