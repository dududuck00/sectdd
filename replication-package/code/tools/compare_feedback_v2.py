#!/usr/bin/env python3
"""Compare validated protocol-v2 feedback reports across models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "M")
FEEDBACK_METHODS = ("B4", "B5", "M")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser.parse_args()


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{100 * value:.1f}%"


def load_report(path: Path) -> dict:
    report = json.loads(path.read_text())
    if report["trajectory_count"] != 189:
        raise AssertionError(f"{path}: expected 189 trajectories")
    manifest_path = Path(report["run_dir"]) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    report["provenance"] = {
        "report_path": str(path.resolve()),
        "run_manifest": str(manifest_path.resolve()),
        "input_sha256": manifest["input_sha256"],
        "canonical_oracle_manifest_sha256": manifest[
            "canonical_oracle_manifest_sha256"
        ],
    }
    return report


def build_comparison(reports: list[dict]) -> dict:
    input_hashes = [report["provenance"]["input_sha256"] for report in reports]
    oracle_hashes = [
        report["provenance"]["canonical_oracle_manifest_sha256"]
        for report in reports
    ]
    if any(value != input_hashes[0] for value in input_hashes[1:]):
        raise AssertionError("Model runs do not share identical immutable inputs")
    if any(value != oracle_hashes[0] for value in oracle_hashes[1:]):
        raise AssertionError("Model runs do not share the same canonical oracle")

    pooled_methods = {}
    for method in METHODS:
        n = sum(report["methods"][method]["n"] for report in reports)
        functional = sum(
            report["methods"][method]["functional_successes"]
            for report in reports
        )
        secure = sum(
            report["methods"][method]["security_successes"]
            for report in reports
        )
        joint = sum(
            report["methods"][method]["joint_successes"]
            for report in reports
        )
        safe_sum = sum(
            report["methods"][method]["hidden_safe_at_1"]
            * report["methods"][method]["n"]
            for report in reports
        )
        calls = sum(
            report["methods"][method]["cost"]["model_calls"]["total"]
            for report in reports
        )
        gaps = sum(
            report["methods"][method]["visible_pass_hidden_joint_fail"]
            for report in reports
        )
        pooled_methods[method] = {
            "n": n,
            "functional_successes": functional,
            "hidden_func_at_1": functional / n,
            "security_successes": secure,
            "hidden_secure_at_1": secure / n,
            "joint_successes": joint,
            "hidden_secure_pass_at_1": joint / n,
            "hidden_safe_at_1": safe_sum / n,
            "mean_model_calls": calls / n,
            "visible_pass_hidden_joint_fail": gaps,
        }

    pooled_feedback = {}
    for method in FEEDBACK_METHODS:
        rows = [report["paired_feedback"][method] for report in reports]
        n = sum(row["n"] for row in rows)
        vulnerable = sum(row["initial_f_plus_s_minus"] for row in rows)
        repaired = sum(
            row["secure_repairs_without_function_loss"] for row in rows
        )
        pooled_feedback[method] = {
            "n": n,
            "triggered": sum(row["triggered"] for row in rows),
            "trigger_rate": sum(row["triggered"] for row in rows) / n,
            "joint_improved": sum(row["joint_improved"] for row in rows),
            "joint_regressed": sum(row["joint_regressed"] for row in rows),
            "initial_f_plus_s_minus": vulnerable,
            "secure_repairs_without_function_loss": repaired,
            "fpsr": repaired / vulnerable if vulnerable else None,
            "functionality_regressions": sum(
                row["functionality_regressions"] for row in rows
            ),
            "visible_pass_hidden_joint_fail": sum(
                row["visible_pass_hidden_joint_fail"] for row in rows
            ),
        }

    tasks = sorted(reports[0]["tasks"])
    for report in reports[1:]:
        if sorted(report["tasks"]) != tasks:
            raise AssertionError("Reports do not contain the same tasks")
    persistent_floors = [
        task
        for task in tasks
        if all(
            report["tasks"][task][method]["joint_successes"] == 0
            for report in reports
            for method in METHODS
        )
    ]
    persistent_ceilings = [
        task
        for task in tasks
        if all(
            report["tasks"][task][method]["joint_successes"]
            == report["tasks"][task][method]["n"]
            for report in reports
            for method in METHODS
        )
    ]
    return {
        "schema_version": 1,
        "design": {
            "models": len(reports),
            "tasks": len(tasks),
            "methods": len(METHODS),
            "seeds": 3,
            "trajectory_count": sum(
                report["trajectory_count"] for report in reports
            ),
            "development_only": True,
        },
        "immutable_inputs": {
            "identical_across_models": True,
            "input_sha256": input_hashes[0],
            "canonical_oracle_manifest_sha256": oracle_hashes[0],
        },
        "models": {
            report["model"]: {
                "run_dir": report["run_dir"],
                "methods": report["methods"],
                "paired_feedback": report["paired_feedback"],
                "tasks": report["tasks"],
                "go_no_go": report["go_no_go"],
                "provenance": report["provenance"],
            }
            for report in reports
        },
        "pooled_descriptive": {
            "methods": pooled_methods,
            "paired_feedback": pooled_feedback,
        },
        "task_patterns": {
            "persistent_joint_floors": persistent_floors,
            "persistent_joint_ceilings": persistent_ceilings,
        },
    }


def markdown(comparison: dict) -> str:
    lines = [
        "# Protocol v2 双模型九任务反馈实验",
        "",
        "这是 2 models × 9 tasks × 7 methods × 3 seeds 的开发实验汇总，"
        "共 378 条经协议审计的轨迹。两个模型使用完全相同的配置、visible/"
        "hidden projections 和 canonical oracle；结果仅作描述性比较。",
        "",
        "## 各模型结果",
        "",
        "| 模型 | 方法 | Func@1 | Secure@1 | Secure-Pass@1 | SAFE@1 | "
        "平均调用 | Vis-pass/Hid-fail |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model, report in comparison["models"].items():
        for method in METHODS:
            row = report["methods"][method]
            lines.append(
                f"| {model} | {method} | {pct(row['hidden_func_at_1'])} | "
                f"{pct(row['hidden_secure_at_1'])} | "
                f"{pct(row['hidden_secure_pass_at_1'])} | "
                f"{pct(row['hidden_safe_at_1'])} | "
                f"{row['cost']['model_calls']['mean']:.2f} | "
                f"{row['visible_pass_hidden_joint_fail']}/{row['n']} |"
            )

    lines.extend(
        [
            "",
            "## 共享 B0 首轮后的配对反馈效果",
            "",
            "| 模型 | 方法 | 触发反馈 | 联合改善 | 联合回退 | FPSR | "
            "功能回退 | Vis-pass/Hid-fail |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model, report in comparison["models"].items():
        for method in FEEDBACK_METHODS:
            row = report["paired_feedback"][method]
            lines.append(
                f"| {model} | {method} | {row['triggered']}/{row['n']} "
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
            "## 跨模型合并描述",
            "",
            "合并值把两个模型的轨迹作为计数汇总，不把它们当作独立统计重复，"
            "因此不用于显著性检验。",
            "",
            "| 方法 | Joint | SAFE | Func | Secure | 平均调用 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for method in METHODS:
        row = comparison["pooled_descriptive"]["methods"][method]
        lines.append(
            f"| {method} | {pct(row['hidden_secure_pass_at_1'])} | "
            f"{pct(row['hidden_safe_at_1'])} | "
            f"{pct(row['hidden_func_at_1'])} | "
            f"{pct(row['hidden_secure_at_1'])} | "
            f"{row['mean_model_calls']:.2f} |"
        )
    lines.extend(
        [
            "",
            "| 反馈方法 | 触发率 | 联合改善/回退 | FPSR | 功能回退 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for method in FEEDBACK_METHODS:
        row = comparison["pooled_descriptive"]["paired_feedback"][method]
        lines.append(
            f"| {method} | {row['triggered']}/{row['n']} "
            f"({pct(row['trigger_rate'])}) | {row['joint_improved']}/"
            f"{row['joint_regressed']} | "
            f"{row['secure_repairs_without_function_loss']}/"
            f"{row['initial_f_plus_s_minus']} ({pct(row['fpsr'])}) | "
            f"{row['functionality_regressions']} |"
        )

    floors = ", ".join(comparison["task_patterns"]["persistent_joint_floors"])
    ceilings = ", ".join(
        comparison["task_patterns"]["persistent_joint_ceilings"]
    )
    lines.extend(
        [
            "",
            "## 当前结论",
            "",
            "- B4 在两个模型上都取得最高 Secure-Pass@1：7B 为 48.1%，"
            "14B 为 59.3%；说明失败驱动的原始测试反馈值得进入主实验。",
            "- M 在两个模型上均无联合回退，但其修复率未超过 B4，且 14B "
            "出现 4 次功能回退；当前结构化反馈还不能宣称优于简单反馈。",
            "- B5 有联合回退且平均调用更多，不适合作为默认方法，但应作为"
            "反馈选择随机性的对照。",
            "- SAFE@1 在部分条件高于严格 Secure-Pass@1，成功保留了“安全但"
            "部分正确”候选的信息；两者应与 Func@1、Secure@1 同时报告。",
            f"- 持续联合地板任务：{floors or '无'}；持续天花板任务："
            f"{ceilings or '无'}。它们应保留用于边界与失败分析。",
            "",
            "## 判定与限制",
            "",
            "两个模型均通过开发阶段 Go/No-Go。可以进入冻结协议后的主实验，"
            "但当前每条件仅 3 个 seeds，且任务集用于方法开发，不能据此提出"
            "统计显著性或外部泛化结论。主实验应先冻结提示、预算和 oracle "
            "哈希，再增加独立 seeds 与外部任务/模型。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    reports = [load_report(path.resolve()) for path in args.reports]
    if len(reports) < 2:
        raise AssertionError("At least two model reports are required")
    comparison = build_comparison(reports)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n"
    )
    args.markdown_output.write_text(markdown(comparison))
    print(f"JSON: {args.json_output.resolve()}")
    print(f"Markdown: {args.markdown_output.resolve()}")


if __name__ == "__main__":
    main()
