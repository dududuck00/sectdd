#!/usr/bin/env python3
"""Analyze the paired B3 versus B6 internal hybrid-development experiment."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import defaultdict
from pathlib import Path

from analyze_feedback_v2 import pct, state, summarize


METHODS = ("B3", "B6")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260729)
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


def task_joint_values(items: list[dict]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for item in items:
        grouped[item["task"]].append(
            float(item["final_hidden"]["joint_pass"])
        )
    return {
        task: mean(values) for task, values in sorted(grouped.items())
    }


def paired_bootstrap_ci(
    differences: dict[str, float],
    replicates: int,
    rng: random.Random,
) -> dict:
    tasks = list(differences)
    samples = [
        mean([differences[rng.choice(tasks)] for _ in tasks])
        for _ in range(replicates)
    ]
    return {
        "estimate": mean(list(differences.values())),
        "lower": quantile(samples, 0.025),
        "upper": quantile(samples, 0.975),
        "clusters": len(tasks),
        "replicates": replicates,
    }


def exact_sign_flip_pvalue(differences: list[float]) -> float:
    observed = abs(mean(differences))
    extreme = 0
    total = 0
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
        if permuted + 1e-12 >= observed:
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
    expected = (
        len(manifest["tasks"])
        * len(manifest["methods"])
        * len(manifest["seeds"])
    )
    if manifest["methods"] != list(METHODS):
        raise AssertionError(f"{resolved}: expected methods {METHODS}")
    if len(trajectories) != expected == manifest["trajectory_count"]:
        raise AssertionError(f"{resolved}: incomplete condition grid")
    return {
        "run_dir": str(resolved),
        "manifest": manifest,
        "trajectories": trajectories,
    }


def paired_feedback(index: dict[tuple[str, int, str], dict]) -> dict:
    rows = []
    for (task, seed, method), final in sorted(index.items()):
        if method != "B6":
            continue
        initial = index[(task, seed, "B3")]
        initial_hidden = initial["final_hidden"]
        final_hidden = final["final_hidden"]
        initial_f = initial_hidden["functional"]["all_passed"]
        initial_s = initial_hidden["security"]["all_passed"]
        final_f = final_hidden["functional"]["all_passed"]
        final_s = final_hidden["security"]["all_passed"]
        rows.append(
            {
                "task": task,
                "seed": seed,
                "triggered": final["budget_usage"]["model_calls"] > 1,
                "transition": f"{state(initial)}->{state(final)}",
                "initial_joint": initial_hidden["joint_pass"],
                "final_joint": final_hidden["joint_pass"],
                "initial_vulnerable_functional": initial_f and not initial_s,
                "secure_repair_without_function_loss": (
                    initial_f and not initial_s and final_f and final_s
                ),
                "functionality_regression": initial_f and not final_f,
                "visible_hidden_gap": (
                    final["final_visible"]["summary"]["all_passed"]
                    and not final_hidden["joint_pass"]
                ),
            }
        )
    vulnerable = sum(row["initial_vulnerable_functional"] for row in rows)
    repaired = sum(
        row["secure_repair_without_function_loss"] for row in rows
    )
    return {
        "reference": "B3",
        "n": len(rows),
        "triggered": sum(row["triggered"] for row in rows),
        "trigger_rate": mean([float(row["triggered"]) for row in rows]),
        "joint_improved": sum(
            not row["initial_joint"] and row["final_joint"] for row in rows
        ),
        "joint_regressed": sum(
            row["initial_joint"] and not row["final_joint"] for row in rows
        ),
        "initial_f_plus_s_minus": vulnerable,
        "secure_repairs_without_function_loss": repaired,
        "fpsr": repaired / vulnerable if vulnerable else None,
        "functionality_regressions": sum(
            row["functionality_regression"] for row in rows
        ),
        "visible_pass_hidden_joint_fail": sum(
            row["visible_hidden_gap"] for row in rows
        ),
        "per_task": {
            task: {
                "b3_joint": sum(
                    row["initial_joint"] for row in rows if row["task"] == task
                ),
                "b6_joint": sum(
                    row["final_joint"] for row in rows if row["task"] == task
                ),
                "improved": sum(
                    not row["initial_joint"] and row["final_joint"]
                    for row in rows
                    if row["task"] == task
                ),
                "regressed": sum(
                    row["initial_joint"] and not row["final_joint"]
                    for row in rows
                    if row["task"] == task
                ),
            }
            for task in sorted({row["task"] for row in rows})
        },
    }


def analyze_model(run: dict, replicates: int, rng: random.Random) -> dict:
    by_method: dict[str, list[dict]] = defaultdict(list)
    index = {}
    for item in run["trajectories"]:
        by_method[item["method"]].append(item)
        index[(item["task"], item["generation_seed"], item["method"])] = item
    b3 = task_joint_values(by_method["B3"])
    b6 = task_joint_values(by_method["B6"])
    differences = {task: b6[task] - b3[task] for task in sorted(b3)}
    return {
        "run_dir": run["run_dir"],
        "manifest": run["manifest"],
        "methods": {
            method: summarize(by_method[method]) for method in METHODS
        },
        "comparison": {
            "method": "B6",
            "baseline": "B3",
            "absolute_difference": mean(list(differences.values())),
            "task_clustered_ci": paired_bootstrap_ci(
                differences, replicates, rng
            ),
            "exact_sign_flip_pvalue": exact_sign_flip_pvalue(
                list(differences.values())
            ),
            "task_differences": differences,
        },
        "paired_feedback": paired_feedback(index),
    }


def build_markdown(report: dict) -> str:
    lines = [
        "# B3 + SecTDD 混合方法内部开发实验",
        "",
        "B6 与 B3 共享完全相同的初始候选；B6 仅在此基础上增加结构化"
        "反馈。任务参与过方法开发，因此该结果只用于方法筛选。",
        "",
        "## 结果",
        "",
        "| 模型 | 方法 | Secure-Pass@1 | SAFE@1 | Func@1 | Secure@1 | 平均调用 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model, model_result in report["models"].items():
        for method in METHODS:
            row = model_result["methods"][method]
            lines.append(
                f"| {model} | {method} | "
                f"{pct(row['hidden_secure_pass_at_1'])} | "
                f"{pct(row['hidden_safe_at_1'])} | "
                f"{pct(row['hidden_func_at_1'])} | "
                f"{pct(row['hidden_secure_at_1'])} | "
                f"{row['cost']['model_calls']['mean']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## B6 − B3 配对比较",
            "",
            "| 模型 | 差值 (95% CI) | exact p | Holm p | 改善/回退 | 功能回退 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model, result in report["models"].items():
        comparison = result["comparison"]
        ci = comparison["task_clustered_ci"]
        feedback = result["paired_feedback"]
        lines.append(
            f"| {model} | {pct(comparison['absolute_difference'])} "
            f"[{pct(ci['lower'])}, {pct(ci['upper'])}] | "
            f"{comparison['exact_sign_flip_pvalue']:.4f} | "
            f"{comparison['holm_adjusted_pvalue']:.4f} | "
            f"{feedback['joint_improved']}/{feedback['joint_regressed']} | "
            f"{feedback['functionality_regressions']} |"
        )
    lines.extend(
        [
            "",
            "## 任务级差值",
            "",
            "| 模型 | " + " | ".join(report["design"]["tasks"]) + " |",
            "|---|" + "---:|" * len(report["design"]["tasks"]),
        ]
    )
    for model, result in report["models"].items():
        differences = result["comparison"]["task_differences"]
        lines.append(
            f"| {model} | "
            + " | ".join(pct(differences[task]) for task in report["design"]["tasks"])
            + " |"
        )
    lines.extend(
        [
            "",
            "## 判定规则",
            "",
            "B6 只有在多数模型上提高 Secure-Pass@1、没有明显增加功能回退，"
            "且收益足以解释额外调用成本时，才进入新的外部任务确认实验。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    runs = [load_run(path) for path in args.run_dirs]
    config_hashes = [run["manifest"]["input_sha256"] for run in runs]
    if any(value != config_hashes[0] for value in config_hashes[1:]):
        raise AssertionError("Runs do not share frozen inputs")
    rng = random.Random(args.bootstrap_seed)
    models = {
        run["manifest"]["model"]: analyze_model(
            run, args.bootstrap_replicates, rng
        )
        for run in runs
    }
    raw_pvalues = {
        model: result["comparison"]["exact_sign_flip_pvalue"]
        for model, result in models.items()
    }
    adjusted = holm_adjust(raw_pvalues)
    for model, value in adjusted.items():
        models[model]["comparison"]["holm_adjusted_pvalue"] = value
    first = runs[0]["manifest"]
    report = {
        "schema_version": 1,
        "study_phase": "hybrid_b3m_internal_development",
        "development_results_only": True,
        "primary_metric": "hidden_secure_pass_at_1",
        "design": {
            "models": len(models),
            "tasks": first["tasks"],
            "methods": list(METHODS),
            "seeds": first["seeds"],
            "trajectory_count": sum(
                run["manifest"]["trajectory_count"] for run in runs
            ),
        },
        "statistics": {
            "inference_unit": "task",
            "bootstrap_replicates": args.bootstrap_replicates,
            "bootstrap_seed": args.bootstrap_seed,
            "paired_test": "exact_sign_flip_permutation",
            "multiple_comparison_correction": "holm_across_models",
        },
        "models": models,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(
        build_markdown(report), encoding="utf-8"
    )
    print(f"JSON report: {args.json_output}")
    print(f"Markdown report: {args.markdown_output}")


if __name__ == "__main__":
    main()
