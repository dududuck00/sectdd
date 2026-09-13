#!/usr/bin/env python3
"""Analyze one validated protocol-v2 feedback development run."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "M")
FEEDBACK_METHODS = ("B4", "B5", "M")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser.parse_args()


def state(item: dict) -> str:
    hidden = item["final_hidden"]
    functional = hidden["functional"]["all_passed"]
    secure = hidden["security"]["all_passed"]
    return f"F{'+' if functional else '-'}S{'+' if secure else '-'}"


def summarize(items: list[dict]) -> dict:
    n = len(items)
    hidden = [item["final_hidden"] for item in items]
    usage = [item["budget_usage"] for item in items]
    functional = sum(item["functional"]["all_passed"] for item in hidden)
    secure = sum(item["security"]["all_passed"] for item in hidden)
    joint = sum(item["joint_pass"] for item in hidden)
    visible_joint = sum(
        item["final_visible"]["summary"]["all_passed"] for item in items
    )
    visible_hidden_gap = sum(
        item["final_visible"]["summary"]["all_passed"]
        and not item["final_hidden"]["joint_pass"]
        for item in items
    )
    return {
        "n": n,
        "functional_successes": functional,
        "hidden_func_at_1": functional / n,
        "security_successes": secure,
        "hidden_secure_at_1": secure / n,
        "joint_successes": joint,
        "hidden_secure_pass_at_1": joint / n,
        "hidden_safe_at_1": sum(item["safe"] for item in hidden) / n,
        "security_given_functional": joint / functional if functional else None,
        "visible_joint_successes": visible_joint,
        "visible_joint_rate": visible_joint / n,
        "visible_pass_hidden_joint_fail": visible_hidden_gap,
        "states": dict(sorted(Counter(state(item) for item in items).items())),
        "cost": {
            key: {
                "total": sum(item[key] for item in usage),
                "mean": sum(item[key] for item in usage) / n,
            }
            for key in (
                "model_calls",
                "input_tokens",
                "output_tokens",
                "feedback_tokens",
                "visible_test_executions",
            )
        },
    }


def paired_feedback(
    index: dict[tuple[str, int, str], dict], method: str
) -> dict:
    rows = []
    for (task, seed, observed_method), final in sorted(index.items()):
        if observed_method != method:
            continue
        initial = index[(task, seed, "B0")]
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
                "calls": final["budget_usage"]["model_calls"],
                "transition": f"{state(initial)}->{state(final)}",
                "initial_joint": initial_hidden["joint_pass"],
                "final_joint": final_hidden["joint_pass"],
                "initial_vulnerable_functional": initial_f and not initial_s,
                "secure_repair_without_function_loss": (
                    initial_f and not initial_s and final_f and final_s
                ),
                "functionality_regression": initial_f and not final_f,
                "visible_pass_hidden_joint_fail": (
                    final["final_visible"]["summary"]["all_passed"]
                    and not final_hidden["joint_pass"]
                ),
                "safe_delta": final_hidden["safe"] - initial_hidden["safe"],
            }
        )
    vulnerable = sum(row["initial_vulnerable_functional"] for row in rows)
    repaired = sum(row["secure_repair_without_function_loss"] for row in rows)
    return {
        "reference": "B0",
        "n": len(rows),
        "triggered": sum(row["triggered"] for row in rows),
        "trigger_rate": sum(row["triggered"] for row in rows) / len(rows),
        "joint_improved": sum(
            not row["initial_joint"] and row["final_joint"] for row in rows
        ),
        "joint_regressed": sum(
            row["initial_joint"] and not row["final_joint"] for row in rows
        ),
        "joint_unchanged": sum(
            row["initial_joint"] == row["final_joint"] for row in rows
        ),
        "initial_f_plus_s_minus": vulnerable,
        "secure_repairs_without_function_loss": repaired,
        "fpsr": repaired / vulnerable if vulnerable else None,
        "functionality_regressions": sum(
            row["functionality_regression"] for row in rows
        ),
        "visible_pass_hidden_joint_fail": sum(
            row["visible_pass_hidden_joint_fail"] for row in rows
        ),
        "mean_safe_delta": sum(row["safe_delta"] for row in rows) / len(rows),
        "transitions": dict(
            sorted(Counter(row["transition"] for row in rows).items())
        ),
        "per_task": {
            task: {
                "n": len(task_rows),
                "triggered": sum(row["triggered"] for row in task_rows),
                "joint_improved": sum(
                    not row["initial_joint"] and row["final_joint"]
                    for row in task_rows
                ),
                "joint_regressed": sum(
                    row["initial_joint"] and not row["final_joint"]
                    for row in task_rows
                ),
                "final_joint_successes": sum(
                    row["final_joint"] for row in task_rows
                ),
            }
            for task, task_rows in sorted(
                _group_rows(rows, "task").items()
            )
        },
    }


def _group_rows(rows: list[dict], key: str) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{100 * value:.1f}%"


def markdown(report: dict) -> str:
    lines = [
        "# Protocol v2 九任务反馈开发实验",
        "",
        f"本报告包含 {report['model']} 的 9 tasks × 7 methods × 3 seeds，"
        "共 189 条协议有效轨迹。该运行用于开发和 Go/No-Go 判断，不是主实验"
        "效果估计。",
        "",
        "B4/B5/M 逐字复用同 task × seed 的 B0 首轮候选；分别在失败后提供"
        "固定原始、随机原始和安全优先结构化反馈。",
        "",
        "## 总体指标",
        "",
        "| 方法 | Func@1 | Secure@1 | Secure-Pass@1 | SAFE@1 | "
        "Visible Joint | Vis-pass/Hid-fail | 平均调用 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        row = report["methods"][method]
        lines.append(
            f"| {method} | {pct(row['hidden_func_at_1'])} | "
            f"{pct(row['hidden_secure_at_1'])} | "
            f"{pct(row['hidden_secure_pass_at_1'])} | "
            f"{pct(row['hidden_safe_at_1'])} | "
            f"{pct(row['visible_joint_rate'])} | "
            f"{row['visible_pass_hidden_joint_fail']}/{row['n']} | "
            f"{row['cost']['model_calls']['mean']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 相对共享 B0 首轮的反馈结果",
            "",
            "| 方法 | 触发反馈 | 联合改善 | 联合回退 | FPSR | 功能回退 | "
            "Vis-pass/Hid-fail |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in FEEDBACK_METHODS:
        row = report["paired_feedback"][method]
        lines.append(
            f"| {method} | {row['triggered']}/{row['n']} "
            f"({pct(row['trigger_rate'])}) | {row['joint_improved']} | "
            f"{row['joint_regressed']} | "
            f"{row['secure_repairs_without_function_loss']}/"
            f"{row['initial_f_plus_s_minus']} ({pct(row['fpsr'])}) | "
            f"{row['functionality_regressions']} | "
            f"{row['visible_pass_hidden_joint_fail']} |"
        )
    lines.extend(
        [
            "",
            "## 逐任务 Hidden Secure-Pass@1",
            "",
            "| 任务 | B0 | B1 | B2 | B3 | B4 | B5 | M |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for task in report["tasks"]:
        cells = [
            pct(report["tasks"][task][method]["hidden_secure_pass_at_1"])
            for method in METHODS
        ]
        lines.append(f"| {task} | " + " | ".join(cells) + " |")
    go = report["go_no_go"]
    lines.extend(
        [
            "",
            "## Go/No-Go",
            "",
            f"- 反馈轨迹触发率：{go['triggered']}/{go['feedback_trajectories']} "
            f"({pct(go['trigger_rate'])})；阈值 ≥30%："
            f"{'通过' if go['trigger_threshold_passed'] else '未通过'}。",
            f"- 至少存在一次隐藏联合改善："
            f"{'通过' if go['has_joint_improvement'] else '未通过'}。",
            f"- 至少存在一次联合或功能回退："
            f"{'通过' if go['has_regression'] else '未通过'}。",
            f"- 开发阶段判定：{'GO' if go['passed'] else 'NO-GO'}。",
            "",
            "## 解释边界",
            "",
            "该实验只有一个模型、每条件三个 seeds，不能支持方法优越性的统计"
            "结论。CWE-78 存在天花板效应，CWE-22/CWE-117 存在持续地板"
            "效应，CWE-643 呈现模型规模依赖；这些任务应保留用于失败分析，"
            "但主实验需扩大模型和重复次数。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    paths = sorted(run_dir.glob("trajectories/*/*/seed_*/trajectory.json"))
    trajectories = [json.loads(path.read_text()) for path in paths]
    if len(trajectories) != 189:
        raise AssertionError(f"Expected 189 trajectories, found {len(trajectories)}")
    by_method = defaultdict(list)
    by_task_method = defaultdict(lambda: defaultdict(list))
    index = {}
    for item in trajectories:
        by_method[item["method"]].append(item)
        by_task_method[item["task"]][item["method"]].append(item)
        index[(item["task"], item["generation_seed"], item["method"])] = item
    paired = {
        method: paired_feedback(index, method) for method in FEEDBACK_METHODS
    }
    triggered = sum(paired[method]["triggered"] for method in FEEDBACK_METHODS)
    feedback_n = sum(paired[method]["n"] for method in FEEDBACK_METHODS)
    has_improvement = any(
        paired[method]["joint_improved"] > 0 for method in FEEDBACK_METHODS
    )
    has_regression = any(
        paired[method]["joint_regressed"] > 0
        or paired[method]["functionality_regressions"] > 0
        for method in FEEDBACK_METHODS
    )
    report = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "model": manifest["model"],
        "oracle_set_id": manifest["oracle_set_id"],
        "trajectory_count": len(trajectories),
        "methods": {
            method: summarize(by_method[method]) for method in METHODS
        },
        "tasks": {
            task: {
                method: summarize(by_task_method[task][method])
                for method in METHODS
            }
            for task in sorted(by_task_method)
        },
        "paired_feedback": paired,
        "go_no_go": {
            "feedback_trajectories": feedback_n,
            "triggered": triggered,
            "trigger_rate": triggered / feedback_n,
            "trigger_threshold": 0.30,
            "trigger_threshold_passed": triggered / feedback_n >= 0.30,
            "has_joint_improvement": has_improvement,
            "has_regression": has_regression,
            "passed": (
                triggered / feedback_n >= 0.30
                and has_improvement
                and has_regression
            ),
        },
    }
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
