#!/usr/bin/env python3
"""Paired task/CWE error analysis for merged SALLM formal runs."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
METHODS = ("B0", "B3", "B4", "M", "B6")
PAIRS = (
    ("B0_to_B3", "B0", "B3", "visible tests upfront"),
    ("B0_to_B4", "B0", "B4", "fixed raw visible feedback"),
    ("B0_to_M", "B0", "M", "SecTDD structured feedback"),
    ("B3_to_B6", "B3", "B6", "upfront tests plus SecTDD feedback"),
    ("B4_to_M", "B4", "M", "structured versus raw feedback"),
)
STATE_ORDER = ("F+S+", "F+S-", "F-S+", "F-S-")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument(
        "--hidden-projection",
        type=Path,
        default=ROOT
        / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json",
    )
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--examples-per-direction", type=int, default=3)
    return parser.parse_args()


def load_run(path: Path) -> tuple[dict, list[dict]]:
    root = path.resolve()
    manifest = json.loads((root / "run_manifest.json").read_text())
    records = []
    for item in sorted(root.glob("trajectories/*/*/seed_*/trajectory.json")):
        record = json.loads(item.read_text())
        record["_trajectory_file"] = item.relative_to(ROOT).as_posix()
        records.append(record)
    if len(records) != manifest["trajectory_count"]:
        raise RuntimeError(f"Trajectory count mismatch: {root}")
    if len(records) != 275:
        raise RuntimeError(f"Expected 275 trajectories: {root}")
    return manifest, records


def outcome(record: dict) -> dict[str, Any]:
    functional = bool(record["final_hidden"]["functional"]["all_passed"])
    secure = bool(record["final_hidden"]["security"]["all_passed"])
    return {
        "functional": functional,
        "secure": secure,
        "joint": functional and secure,
        "state": f"F{'+' if functional else '-'}S{'+' if secure else '-'}",
    }


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def percent(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def cwe_number(value: str) -> int:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 10**9


def failed_hidden_cases(record: dict) -> list[dict]:
    return [
        {
            "marker": case["marker"],
            "behavior_family": case["behavior_family"],
            "description": case["description"],
        }
        for case in record["final_hidden"]["raw"]["cases"]
        if not case["passed"]
    ]


def initial_visible_failure_pattern(record: dict) -> str:
    failed = sorted(
        case["marker"]
        for case in record["rounds"][0]["visible_result"]["cases"]
        if not case["passed"]
    )
    return "+".join(failed) if failed else "none"


def final_candidate(record: dict) -> tuple[str, str]:
    item = record["rounds"][-1]["candidate"]
    return item["path"], item["sha256"]


def diff_stat(before_path: str, after_path: str) -> dict[str, int]:
    before = (ROOT / before_path).read_text(encoding="utf-8").splitlines()
    after = (ROOT / after_path).read_text(encoding="utf-8").splitlines()
    changes = list(difflib.ndiff(before, after))
    return {
        "added_lines": sum(line.startswith("+ ") for line in changes),
        "removed_lines": sum(line.startswith("- ") for line in changes),
    }


def example_record(
    model: str,
    metadata: dict,
    reference: dict,
    target: dict,
    reference_method: str,
    target_method: str,
) -> dict:
    before_path, before_sha = final_candidate(reference)
    after_path, after_sha = final_candidate(target)
    first_before = reference["rounds"][0]["candidate"]["sha256"]
    first_after = target["rounds"][0]["candidate"]["sha256"]
    return {
        "model": model,
        "task": target["task"],
        "cwe": metadata["cwe"],
        "seed": target["generation_seed"],
        "reference_method": reference_method,
        "target_method": target_method,
        "reference_outcome": outcome(reference),
        "target_outcome": outcome(target),
        "target_calls": target["budget_usage"]["model_calls"],
        "target_feedback_case_ids": sorted(
            {
                case
                for round_record in target["rounds"]
                for case in round_record["feedback_case_ids"]
            }
        ),
        "shared_initial_candidate": first_before == first_after,
        "reference_hidden_failures": failed_hidden_cases(reference),
        "target_hidden_failures": failed_hidden_cases(target),
        "reference_candidate": {
            "path": before_path,
            "sha256": before_sha,
        },
        "target_candidate": {"path": after_path, "sha256": after_sha},
        "diff": diff_stat(before_path, after_path),
        "reference_trajectory": reference["_trajectory_file"],
        "target_trajectory": target["_trajectory_file"],
    }


def summarize_pair(
    model: str,
    records: list[dict],
    task_metadata: dict,
    reference_method: str,
    target_method: str,
    examples_per_direction: int,
) -> dict:
    index = {
        (item["method"], item["task"], item["generation_seed"]): item
        for item in records
    }
    tasks = sorted({item["task"] for item in records})
    seeds = sorted({item["generation_seed"] for item in records})
    totals = Counter()
    transitions = Counter()
    visible_patterns = Counter()
    repairs_by_visible_pattern = Counter()
    by_task = {}
    repairs = []
    regressions = []

    for task in tasks:
        task_totals = Counter()
        task_transitions = Counter()
        for seed in seeds:
            reference = index[(reference_method, task, seed)]
            target = index[(target_method, task, seed)]
            before = outcome(reference)
            after = outcome(target)
            transitions[f"{before['state']}->{after['state']}"] += 1
            task_transitions[f"{before['state']}->{after['state']}"] += 1
            totals["pairs"] += 1
            task_totals["pairs"] += 1
            for metric in ("joint", "functional", "secure"):
                totals[f"reference_{metric}_pass"] += before[metric]
                totals[f"target_{metric}_pass"] += after[metric]
                task_totals[f"reference_{metric}_pass"] += before[metric]
                task_totals[f"target_{metric}_pass"] += after[metric]
                totals[f"{metric}_repair_eligible"] += not before[metric]
                task_totals[f"{metric}_repair_eligible"] += not before[metric]
                totals[f"{metric}_repaired"] += (
                    not before[metric] and after[metric]
                )
                task_totals[f"{metric}_repaired"] += (
                    not before[metric] and after[metric]
                )
                totals[f"{metric}_regressed"] += (
                    before[metric] and not after[metric]
                )
                task_totals[f"{metric}_regressed"] += (
                    before[metric] and not after[metric]
                )
            triggered = target["budget_usage"]["model_calls"] > 1
            visible_pattern = initial_visible_failure_pattern(target)
            visible_patterns[visible_pattern] += 1
            totals["feedback_triggered"] += triggered
            task_totals["feedback_triggered"] += triggered
            totals["triggered_joint_repaired"] += (
                triggered and not before["joint"] and after["joint"]
            )
            totals["triggered_joint_regressed"] += (
                triggered and before["joint"] and not after["joint"]
            )
            if not before["joint"] and after["joint"]:
                repairs_by_visible_pattern[visible_pattern] += 1
                repairs.append(
                    example_record(
                        model,
                        task_metadata[task],
                        reference,
                        target,
                        reference_method,
                        target_method,
                    )
                )
            elif before["joint"] and not after["joint"]:
                regressions.append(
                    example_record(
                        model,
                        task_metadata[task],
                        reference,
                        target,
                        reference_method,
                        target_method,
                    )
                )
        by_task[task] = {
            "cwe": task_metadata[task]["cwe"],
            **dict(task_totals),
            "joint_repair_rate": rate(
                task_totals["joint_repaired"],
                task_totals["joint_repair_eligible"],
            ),
            "state_transitions": dict(sorted(task_transitions.items())),
        }

    return {
        "reference_method": reference_method,
        "target_method": target_method,
        **dict(totals),
        "joint_repair_rate": rate(
            totals["joint_repaired"], totals["joint_repair_eligible"]
        ),
        "functional_repair_rate": rate(
            totals["functional_repaired"],
            totals["functional_repair_eligible"],
        ),
        "security_repair_rate": rate(
            totals["secure_repaired"], totals["secure_repair_eligible"]
        ),
        "state_transitions": dict(sorted(transitions.items())),
        "initial_visible_failure_patterns": dict(
            sorted(visible_patterns.items())
        ),
        "joint_repairs_by_initial_visible_failure_pattern": dict(
            sorted(repairs_by_visible_pattern.items())
        ),
        "by_task": by_task,
        "examples": {
            "joint_repairs": repairs[:examples_per_direction],
            "joint_regressions": regressions[:examples_per_direction],
        },
    }


def method_task_summary(records: list[dict], metadata: dict) -> dict:
    grouped = defaultdict(list)
    for item in records:
        grouped[(item["task"], item["method"])].append(item)
    result = {}
    for task in sorted({item["task"] for item in records}):
        task_result = {
            "cwe": metadata[task]["cwe"],
            "hidden_behaviors": [
                {
                    "marker": case["marker"],
                    "behavior_family": case["behavior_family"],
                    "description": case["description"],
                }
                for case in metadata[task]["cases"]
            ],
            "methods": {},
        }
        for method in METHODS:
            items = grouped[(task, method)]
            states = Counter(outcome(item)["state"] for item in items)
            task_result["methods"][method] = {
                "seeds": len(items),
                "functional": sum(
                    outcome(item)["functional"] for item in items
                )
                / len(items),
                "secure": sum(outcome(item)["secure"] for item in items)
                / len(items),
                "joint": sum(outcome(item)["joint"] for item in items)
                / len(items),
                "states": {state: states[state] for state in STATE_ORDER},
                "mean_calls": sum(
                    item["budget_usage"]["model_calls"] for item in items
                )
                / len(items),
            }
        result[task] = task_result
    return result


def model_state_summary(records: list[dict]) -> dict:
    result = {}
    for method in METHODS:
        items = [item for item in records if item["method"] == method]
        states = Counter(outcome(item)["state"] for item in items)
        result[method] = {state: states[state] for state in STATE_ORDER}
    return result


def behavior_failure_summary(
    all_records: list[dict], task_metadata: dict
) -> list[dict]:
    grouped = defaultdict(lambda: Counter(total=0, failed=0))
    for item in all_records:
        cases = item["final_hidden"]["raw"]["cases"]
        for case in cases:
            key = (
                item["method"],
                case["marker"],
                case["behavior_family"],
                item["task"],
            )
            grouped[key]["total"] += 1
            grouped[key]["failed"] += not case["passed"]
    rows = []
    for (method, marker, family, task), counts in grouped.items():
        rows.append(
            {
                "method": method,
                "marker": marker,
                "behavior_family": family,
                "task": task,
                "cwe": task_metadata[task]["cwe"],
                "failed": counts["failed"],
                "total": counts["total"],
                "failure_rate": counts["failed"] / counts["total"],
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            -item["failure_rate"],
            -item["failed"],
            item["method"],
            item["cwe"],
        ),
    )


def identifiability_summary(models: list[dict]) -> dict:
    counts = Counter()
    cells = []
    for model in models:
        for task, item in model["tasks"].items():
            values = {
                method: item["methods"][method]["joint"]
                for method in METHODS
            }
            if all(value == 1.0 for value in values.values()):
                category = "ceiling"
            elif all(value == 0.0 for value in values.values()):
                category = "floor"
            else:
                category = "informative"
            counts[category] += 1
            cells.append(
                {
                    "model": model["model"],
                    "task": task,
                    "cwe": item["cwe"],
                    "category": category,
                    "joint_by_method": values,
                }
            )
    total = len(cells)
    return {
        "task_model_cells": total,
        "ceiling": counts["ceiling"],
        "floor": counts["floor"],
        "informative": counts["informative"],
        "informative_fraction": counts["informative"] / total,
        "cells": cells,
    }


def link(path: str, label: str) -> str:
    return f"[{label}]({ROOT / path})"


def render_example(item: dict) -> str:
    before = item["reference_outcome"]["state"]
    after = item["target_outcome"]["state"]
    feedback = ", ".join(item["target_feedback_case_ids"]) or "none"
    files = (
        f"{link(item['reference_candidate']['path'], 'before')} / "
        f"{link(item['target_candidate']['path'], 'after')} / "
        f"{link(item['target_trajectory'], 'trajectory')}"
    )
    return (
        f"- `{item['model']}` · `{item['cwe']}` · seed "
        f"`{item['seed']}`: {before} → {after}; calls="
        f"{item['target_calls']}; feedback=`{feedback}`; diff="
        f"+{item['diff']['added_lines']}/-{item['diff']['removed_lines']}; "
        f"{files}"
    )


def markdown(report: dict) -> str:
    lines = [
        "# SALLM main-002 逐题/CWE 误差分析",
        "",
        (
            f"输入：{report['design']['models']} models × "
            f"{report['design']['tasks']} tasks × "
            f"{report['design']['methods']} methods × "
            f"{report['design']['seeds']} seeds，共 "
            f"{report['design']['trajectories']} 条已校验轨迹。"
        ),
        "",
        "状态记号：`F+S+` 同时通过隐藏功能/安全测试；`F+S-` 仅功能通过；"
        "`F-S+` 仅安全通过；`F-S-` 均失败。",
        "",
        "## 最终状态分布",
        "",
        "| 模型 | 方法 | F+S+ | F+S- | F-S+ | F-S- |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model in report["models"]:
        for method in METHODS:
            states = model["state_summary"][method]
            lines.append(
                f"| {model['model']} | {method} | "
                + " | ".join(str(states[state]) for state in STATE_ORDER)
                + " |"
            )

    identifiability = report["identifiability"]
    lines.extend(
        [
            "",
            "## 方法可识别性诊断",
            "",
            (
                f"共 {identifiability['task_model_cells']} 个 task × model "
                f"单元：{identifiability['ceiling']} 个所有方法均为 100% 的"
                f"天花板单元，{identifiability['floor']} 个所有方法均为 0% 的"
                f"地板单元，只有 {identifiability['informative']} 个"
                f"（{percent(identifiability['informative_fraction'])}）能够"
                "区分方法。"
            ),
            "",
            "| 模型 | 类别 | CWE |",
            "|---|---|---|",
        ]
    )
    grouped_cells = defaultdict(list)
    for cell in identifiability["cells"]:
        if cell["category"] != "informative":
            grouped_cells[(cell["model"], cell["category"])].append(
                cell["cwe"]
            )
    for (model, category), cwes in sorted(grouped_cells.items()):
        lines.append(
            f"| {model} | {category} | {', '.join(sorted(cwes, key=cwe_number))} |"
        )

    lines.extend(["", "## 配对修复与回退", ""])
    for pair_id, _, _, description in PAIRS:
        lines.extend(
            [
                f"### {pair_id}: {description}",
                "",
                "| 模型 | 可修复 | Joint 修复 | 修复率 | Joint 回退 | "
                "功能修复/回退 | 安全修复/回退 | 触发反馈 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for model in report["models"]:
            item = model["paired"][pair_id]
            lines.append(
                f"| {model['model']} | {item['joint_repair_eligible']} | "
                f"{item['joint_repaired']} | "
                f"{percent(item['joint_repair_rate'])} | "
                f"{item['joint_regressed']} | "
                f"{item['functional_repaired']}/{item['functional_regressed']} | "
                f"{item['secure_repaired']}/{item['secure_regressed']} | "
                f"{item['feedback_triggered']} |"
            )
        lines.append("")

    lines.extend(
        [
            "## 反馈触发类型与 Joint 修复来源",
            "",
            "`none` 表示首轮已通过 visible tests，因而不会触发反馈。",
            "",
            "| 模型 | 比较 | 首轮 visible 失败类型 | 轨迹数 | Joint 修复 |",
            "|---|---|---|---:|---:|",
        ]
    )
    for pair_id in ("B0_to_B4", "B0_to_M", "B3_to_B6"):
        for model in report["models"]:
            item = model["paired"][pair_id]
            patterns = item["initial_visible_failure_patterns"]
            repairs = item[
                "joint_repairs_by_initial_visible_failure_pattern"
            ]
            for pattern in ("functionality", "security", "functionality+security", "none"):
                if pattern not in patterns:
                    continue
                lines.append(
                    f"| {model['model']} | {pair_id} | `{pattern}` | "
                    f"{patterns[pattern]} | {repairs.get(pattern, 0)} |"
                )
    lines.append("")

    lines.extend(["## 逐模型、逐 CWE 的 Joint@1", ""])
    for model in report["models"]:
        lines.extend(
            [
                f"### {model['model']}",
                "",
                "| CWE | Task | B0 | B3 | B4 | M | B6 |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        tasks = sorted(
            model["tasks"].items(),
            key=lambda item: cwe_number(item[1]["cwe"]),
        )
        for task, item in tasks:
            values = [percent(item["methods"][m]["joint"]) for m in METHODS]
            lines.append(
                f"| {item['cwe']} | `{task}` | " + " | ".join(values) + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## 高频隐藏行为失败",
            "",
            "以下按三个模型合并统计；每个 method × behavior 有 15 个样本。",
            "",
            "| 方法 | 类型 | CWE | 隐藏行为族 | 失败 |",
            "|---|---|---|---|---:|",
        ]
    )
    hardest = [
        item
        for item in report["behavior_failures"]
        if item["method"] in {"M", "B6"} and item["failed"] > 0
    ][:20]
    for item in hardest:
        lines.append(
            f"| {item['method']} | {item['marker']} | {item['cwe']} | "
            f"`{item['behavior_family']}` | {item['failed']}/{item['total']} |"
        )

    lines.extend(["", "## 代表性配对案例", ""])
    for pair_id, _, _, description in PAIRS:
        lines.extend([f"### {pair_id}: {description}", ""])
        any_example = False
        for model in report["models"]:
            examples = model["paired"][pair_id]["examples"]
            for direction in ("joint_repairs", "joint_regressions"):
                for item in examples[direction]:
                    any_example = True
                    lines.append(render_example(item))
        if not any_example:
            lines.append("- 无 Joint 状态变化。")
        lines.append("")

    lines.extend(
        [
            "## 解释边界",
            "",
            "- seed 是任务内重复；逐题百分比步长为 20%，不能视为 5 个独立任务。",
            "- 每个 CWE 当前只有一个任务，CWE 差异与题目差异完全混杂。",
            "- 动态测试只能证明冻结行为族上的通过，不能证明不存在其他漏洞。",
            "- G6 独立语义复核仍为 pending，本报告属于 machine-qualified 分析。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    projection = json.loads(args.hidden_projection.resolve().read_text())
    task_metadata = projection["tasks"]
    loaded = [load_run(path) for path in args.runs]
    oracle_ids = {manifest["oracle_set_id"] for manifest, _ in loaded}
    if oracle_ids != {projection["oracle_set_id"]}:
        raise RuntimeError("Run/projection oracle mismatch")

    models = []
    all_records = []
    for manifest, records in loaded:
        expected = {
            (method, task, seed)
            for method in METHODS
            for task in manifest["tasks"]
            for seed in manifest["seeds"]
        }
        observed = {
            (item["method"], item["task"], item["generation_seed"])
            for item in records
        }
        if observed != expected:
            raise RuntimeError(f"Incomplete grid: {manifest['model']}")
        paired = {}
        for pair_id, reference, target, _ in PAIRS:
            paired[pair_id] = summarize_pair(
                manifest["model"],
                records,
                task_metadata,
                reference,
                target,
                args.examples_per_direction,
            )
        models.append(
            {
                "model": manifest["model"],
                "state_summary": model_state_summary(records),
                "tasks": method_task_summary(records, task_metadata),
                "paired": paired,
            }
        )
        all_records.extend(records)

    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_set_id": projection["oracle_set_id"],
        "design": {
            "models": len(models),
            "tasks": len(task_metadata),
            "methods": len(METHODS),
            "seeds": len({item["generation_seed"] for item in all_records}),
            "trajectories": len(all_records),
        },
        "models": models,
        "identifiability": identifiability_summary(models),
        "behavior_failures": behavior_failure_summary(
            all_records, task_metadata
        ),
        "limitations": {
            "one_task_per_cwe": True,
            "seed_is_within_task_repeat": True,
            "g6_independent_semantic_review": "pending",
        },
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
