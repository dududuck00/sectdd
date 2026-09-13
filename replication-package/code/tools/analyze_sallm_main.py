#!/usr/bin/env python3
"""Analyze merged multi-model SALLM external-main runs."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


METHODS = ("B0", "B3", "B4", "M", "B6")
BASELINES = ("B0", "B3", "B4", "M")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260730)
    return parser.parse_args()


def load_run(path: Path) -> tuple[dict, list[dict]]:
    root = path.resolve()
    manifest = json.loads((root / "run_manifest.json").read_text())
    trajectories = [
        json.loads(item.read_text())
        for item in sorted(root.glob("trajectories/*/*/seed_*/trajectory.json"))
    ]
    if len(trajectories) != manifest["trajectory_count"]:
        raise RuntimeError(f"Trajectory count mismatch: {root}")
    return manifest, trajectories


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (
        position - lower
    )


def task_cluster_ci(
    records: list[dict],
    value,
    replicates: int,
    rng: random.Random,
) -> tuple[float, float]:
    by_task = defaultdict(list)
    for item in records:
        by_task[item["task"]].append(value(item))
    tasks = sorted(by_task)
    draws = []
    for _ in range(replicates):
        sampled = [rng.choice(tasks) for _ in tasks]
        draws.append(
            sum(sum(by_task[task]) / len(by_task[task]) for task in sampled)
            / len(sampled)
        )
    return percentile(draws, 0.025), percentile(draws, 0.975)


def pass_at_k(successes: int, samples: int, k: int) -> float:
    if successes <= 0:
        return 0.0
    if samples - successes < k:
        return 1.0
    return 1.0 - math.comb(samples - successes, k) / math.comb(samples, k)


def task_pass_at_k(records: list[dict], field, k: int) -> float:
    by_task = defaultdict(list)
    for item in records:
        by_task[item["task"]].append(bool(field(item)))
    values = [
        pass_at_k(sum(outcomes), len(outcomes), k)
        for outcomes in by_task.values()
    ]
    return sum(values) / len(values)


def exact_sign_flip(differences: list[float]) -> float:
    observed = abs(sum(differences) / len(differences))
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(differences)):
        statistic = abs(
            sum(sign * value for sign, value in zip(signs, differences))
            / len(differences)
        )
        extreme += statistic >= observed - 1e-15
        total += 1
    return extreme / total


def holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted = {}
    running = 0.0
    count = len(ordered)
    for rank, key in enumerate(ordered):
        current = min(1.0, (count - rank) * p_values[key])
        running = max(running, current)
        adjusted[key] = running
    return adjusted


def summarize_model(
    model: str,
    records: list[dict],
    replicates: int,
    seed: int,
) -> dict:
    by_method = defaultdict(list)
    for item in records:
        by_method[item["method"]].append(item)
    summary = {}
    value_fields = {
        "functional": lambda x: x["final_hidden"]["functional"]["all_passed"],
        "secure": lambda x: x["final_hidden"]["security"]["all_passed"],
        "joint": lambda x: x["final_hidden"]["joint_pass"],
        "safe": lambda x: x["final_hidden"]["safe"],
    }
    for method in METHODS:
        items = by_method[method]
        if not items:
            continue
        method_summary = {"trajectories": len(items)}
        for offset, (name, getter) in enumerate(value_fields.items()):
            mean = sum(getter(item) for item in items) / len(items)
            low, high = task_cluster_ci(
                items,
                getter,
                replicates,
                random.Random(seed + offset + 100 * METHODS.index(method)),
            )
            method_summary[name] = mean
            method_summary[f"{name}_ci95"] = [low, high]
        method_summary.update(
            {
                "mean_calls": sum(
                    item["budget_usage"]["model_calls"] for item in items
                )
                / len(items),
                "mean_input_tokens": sum(
                    item["budget_usage"]["input_tokens"] for item in items
                )
                / len(items),
                "mean_output_tokens": sum(
                    item["budget_usage"]["output_tokens"] for item in items
                )
                / len(items),
                "mean_feedback_tokens": sum(
                    item["budget_usage"]["feedback_tokens"] for item in items
                )
                / len(items),
                "at_k": {
                    str(k): {
                        "pass": task_pass_at_k(
                            items,
                            lambda x: x["final_hidden"]["functional"][
                                "all_passed"
                            ],
                            k,
                        ),
                        "secure": task_pass_at_k(
                            items,
                            lambda x: x["final_hidden"]["security"][
                                "all_passed"
                            ],
                            k,
                        ),
                        "joint": task_pass_at_k(
                            items,
                            lambda x: x["final_hidden"]["joint_pass"],
                            k,
                        ),
                    }
                    for k in (1, 3, 5)
                },
            }
        )
        summary[method] = method_summary

    by_key = {
        (item["method"], item["task"], item["generation_seed"]): item
        for item in records
    }
    comparisons = {}
    raw_p = {}
    for baseline in BASELINES:
        task_differences = []
        improved = regressed = function_regressed = 0
        for task in sorted({item["task"] for item in records}):
            seed_differences = []
            for generation_seed in sorted(
                {item["generation_seed"] for item in records}
            ):
                target = by_key[("B6", task, generation_seed)]
                reference = by_key[(baseline, task, generation_seed)]
                target_joint = target["final_hidden"]["joint_pass"]
                reference_joint = reference["final_hidden"]["joint_pass"]
                seed_differences.append(target_joint - reference_joint)
                improved += target_joint and not reference_joint
                regressed += reference_joint and not target_joint
                function_regressed += (
                    reference["final_hidden"]["functional"]["all_passed"]
                    and not target["final_hidden"]["functional"]["all_passed"]
                )
            task_differences.append(
                sum(seed_differences) / len(seed_differences)
            )
        comparison = f"B6_vs_{baseline}"
        p_value = exact_sign_flip(task_differences)
        raw_p[comparison] = p_value
        comparisons[comparison] = {
            "mean_joint_difference": sum(task_differences)
            / len(task_differences),
            "task_differences": task_differences,
            "exact_sign_flip_p": p_value,
            "trajectory_joint_improved": improved,
            "trajectory_joint_regressed": regressed,
            "trajectory_function_regressed": function_regressed,
        }
    adjusted = holm(raw_p)
    for comparison, value in adjusted.items():
        comparisons[comparison]["holm_adjusted_p"] = value
    return {
        "model": model,
        "methods": summary,
        "comparisons": comparisons,
    }


def percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def markdown(report: dict) -> str:
    lines = [
        "# SALLM 多模型外部确认性实验",
        "",
        (
            f"设计：{report['design']['models']} models × "
            f"{report['design']['tasks']} tasks × "
            f"{report['design']['methods']} methods × "
            f"{report['design']['seeds']} seeds，共 "
            f"{report['design']['trajectories']} 条轨迹。"
        ),
        "",
        "## 汇总",
        "",
        "| 模型 | 方法 | Func | Secure | Joint | SAFE | Calls |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model in report["models"]:
        for method in METHODS:
            item = model["methods"][method]
            lines.append(
                f"| {model['model']} | {method} | "
                f"{percent(item['functional'])} | "
                f"{percent(item['secure'])} | "
                f"{percent(item['joint'])} | "
                f"{percent(item['safe'])} | "
                f"{item['mean_calls']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## B6 配对比较",
            "",
            "| 模型 | 比较 | Δ Joint | exact p | Holm p | 改善/回退 | 功能回退 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model in report["models"]:
        for comparison, item in model["comparisons"].items():
            lines.append(
                f"| {model['model']} | {comparison} | "
                f"{percent(item['mean_joint_difference'])} | "
                f"{item['exact_sign_flip_p']:.4f} | "
                f"{item['holm_adjusted_p']:.4f} | "
                f"{item['trajectory_joint_improved']}/"
                f"{item['trajectory_joint_regressed']} | "
                f"{item['trajectory_function_regressed']} |"
            )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 推断单位为 task；seed 作为任务内重复，不作为独立样本。",
            "- SAFE 使用冻结实现；当前每个 hidden 功能分区只有一个 case，"
            "因此 SAFE@1 在数值上退化为严格 Joint@1。",
            "- Pass@K、Secure@K 与 Joint@K 使用 5 seeds 的无偏估计，"
            "记录在机器可读 JSON 中。",
            "- G6 独立语义复核仍为 pending，不能描述为最终人工双审 benchmark。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    loaded = [load_run(path) for path in args.runs]
    oracle_ids = {manifest["oracle_set_id"] for manifest, _ in loaded}
    if len(oracle_ids) != 1:
        raise RuntimeError("Oracle-set mismatch")
    models = []
    all_records = []
    for index, (manifest, records) in enumerate(loaded):
        models.append(
            summarize_model(
                manifest["model"],
                records,
                args.bootstrap_replicates,
                args.bootstrap_seed + index * 10000,
            )
        )
        all_records.extend(records)
    task_count = len({item["task"] for item in all_records})
    seed_count = len({item["generation_seed"] for item in all_records})
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_set_id": next(iter(oracle_ids)),
        "design": {
            "models": len(models),
            "tasks": task_count,
            "methods": len(METHODS),
            "seeds": seed_count,
            "trajectories": len(all_records),
            "bootstrap_replicates": args.bootstrap_replicates,
        },
        "models": models,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(f"Wrote {args.markdown_output} and {args.json_output}")


if __name__ == "__main__":
    main()
