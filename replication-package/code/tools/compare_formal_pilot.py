#!/usr/bin/env python3
"""Compare validated formal-pilot runs and emit JSON plus Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "M")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser.parse_args()


def load_run(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    trajectories = [
        json.loads(path.read_text())
        for path in sorted((run_dir / "trajectories").glob("*/*/*/trajectory.json"))
    ]
    if len(trajectories) != manifest["trajectory_count"]:
        raise AssertionError(f"{run_dir}: trajectory count mismatch")
    return manifest, trajectories


def state(item: dict) -> str:
    functional = item["final_hidden"]["functional"]["all_passed"]
    secure = item["final_hidden"]["security"]["all_passed"]
    return f"F{'+' if functional else '-'}S{'+' if secure else '-'}"


def response_hash(item: dict) -> str:
    return hashlib.sha256(item["rounds"][0]["response"].encode()).hexdigest()


def summarize(items: list[dict]) -> dict:
    count = len(items)
    hidden = [item["final_hidden"] for item in items]
    usage = [item["budget_usage"] for item in items]
    joint_successes = sum(item["joint_pass"] for item in hidden)
    functional_successes = sum(
        item["functional"]["all_passed"] for item in hidden
    )
    security_successes = sum(
        item["security"]["all_passed"] for item in hidden
    )
    return {
        "n": count,
        "functional_successes": functional_successes,
        "hidden_func_at_1": functional_successes / count,
        "security_successes": security_successes,
        "hidden_secure_at_1": security_successes / count,
        "joint_successes": joint_successes,
        "hidden_secure_pass_at_1": joint_successes / count,
        "security_given_functional": (
            joint_successes / functional_successes
            if functional_successes
            else None
        ),
        "hidden_safe_at_1": sum(item["safe"] for item in hidden) / count,
        "mean_functional_case_fraction": sum(
            item["functional"]["fraction"] for item in hidden
        )
        / count,
        "mean_security_case_fraction": sum(
            item["security"]["fraction"] for item in hidden
        )
        / count,
        "states": dict(sorted(Counter(state(item) for item in items).items())),
        "cost": {
            key: {
                "total": sum(item[key] for item in usage),
                "mean": sum(item[key] for item in usage) / count,
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


def paired_summary(
    index: dict[tuple[str, int, str], dict],
    method: str,
    reference: str,
) -> dict:
    pairs = []
    for task, seed, candidate_method in sorted(index):
        if candidate_method != method:
            continue
        candidate = index[(task, seed, method)]
        baseline = index[(task, seed, reference)]
        pairs.append((baseline, candidate))
    transitions = Counter(f"{state(a)}->{state(b)}" for a, b in pairs)
    joint_delta = [
        int(b["final_hidden"]["joint_pass"])
        - int(a["final_hidden"]["joint_pass"])
        for a, b in pairs
    ]
    return {
        "reference": reference,
        "n": len(pairs),
        "transitions": dict(sorted(transitions.items())),
        "joint_improved": sum(delta > 0 for delta in joint_delta),
        "joint_regressed": sum(delta < 0 for delta in joint_delta),
        "joint_unchanged": sum(delta == 0 for delta in joint_delta),
        "mean_safe_delta": sum(
            b["final_hidden"]["safe"] - a["final_hidden"]["safe"]
            for a, b in pairs
        )
        / len(pairs),
    }


def iterative_diagnostics(
    index: dict[tuple[str, int, str], dict],
) -> dict:
    diagnostics = {}
    for method in ("B4", "B5", "M"):
        rows = []
        for task, seed, candidate_method in sorted(index):
            if candidate_method != method:
                continue
            initial = index[(task, seed, "B3")]
            final = index[(task, seed, method)]
            same_initial = response_hash(initial) == response_hash(final)
            rows.append(
                {
                    "task": task,
                    "seed": seed,
                    "same_initial_response_as_B3": same_initial,
                    "model_calls": final["budget_usage"]["model_calls"],
                    "initial_state_via_B3": state(initial),
                    "final_state": state(final),
                    "transition": f"{state(initial)}->{state(final)}",
                    "joint_delta": int(final["final_hidden"]["joint_pass"])
                    - int(initial["final_hidden"]["joint_pass"]),
                    "safe_delta": final["final_hidden"]["safe"]
                    - initial["final_hidden"]["safe"],
                }
            )
        diagnostics[method] = {
            "n": len(rows),
            "same_initial_response_count": sum(
                row["same_initial_response_as_B3"] for row in rows
            ),
            "trajectories_with_revision": sum(
                row["model_calls"] > 1 for row in rows
            ),
            "joint_improved": sum(row["joint_delta"] > 0 for row in rows),
            "joint_regressed": sum(row["joint_delta"] < 0 for row in rows),
            "joint_unchanged": sum(row["joint_delta"] == 0 for row in rows),
            "transitions": dict(
                sorted(Counter(row["transition"] for row in rows).items())
            ),
            "changed_cases": [
                row
                for row in rows
                if row["model_calls"] > 1 or row["joint_delta"] != 0
            ],
        }
    return diagnostics


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{100 * value:.1f}%"


def markdown_report(report: dict) -> str:
    lines = [
        "# Formal pilot：3 tasks × 3 seeds",
        "",
        "本报告汇总两个模型、B0–B5 与 M 的 126 条协议有效轨迹。"
        "每个模型/方法只有 9 条轨迹，因此结果是描述性 pre-experiment，"
        "不能作为总体优越性的统计结论。",
        "",
        "主指标为隐藏 Secure-Pass@1；Func@1、Secure@1、SAFE@1 和"
        "条件安全率为分解/补充指标。这里的 SAFE@1 使用项目 protocol 中"
        "针对 CWEval 动态安全 oracle 的适配定义。",
        "",
        "为严格比较反馈策略，B4/B5/M 复用同任务同 seed 的 B3 首轮候选；"
        "成本表按独立部署时的一次逻辑模型调用计量。校验器要求首轮消息、"
        "seed、响应和 usage 完全一致。",
        "",
    ]
    for model, model_report in report["models"].items():
        lines.extend(
            [
                f"## {model}",
                "",
                "| 方法 | Func@1 | Secure@1 | Secure-Pass@1 | SAFE@1 | "
                "P(S|F) | 调用 | 输入 token | 输出 token |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for method in METHODS:
            row = model_report["methods"][method]
            lines.append(
                f"| {method} | {pct(row['hidden_func_at_1'])} | "
                f"{pct(row['hidden_secure_at_1'])} | "
                f"{pct(row['hidden_secure_pass_at_1'])} | "
                f"{pct(row['hidden_safe_at_1'])} | "
                f"{pct(row['security_given_functional'])} | "
                f"{row['cost']['model_calls']['mean']:.2f} | "
                f"{row['cost']['input_tokens']['mean']:.1f} | "
                f"{row['cost']['output_tokens']['mean']:.1f} |"
            )
        lines.extend(["", "逐任务 Hidden Secure-Pass@1：", ""])
        lines.extend(
            [
                "| 方法 | CWE-20 | CWE-78 | CWE-79 |",
                "|---|---:|---:|---:|",
            ]
        )
        for method in METHODS:
            task_rows = model_report["tasks"][method]
            lines.append(
                f"| {method} | "
                f"{pct(task_rows['cwe_020_0']['hidden_secure_pass_at_1'])} | "
                f"{pct(task_rows['cwe_078_0']['hidden_secure_pass_at_1'])} | "
                f"{pct(task_rows['cwe_079_0']['hidden_secure_pass_at_1'])} |"
            )
        lines.extend(["", "迭代相对共享首轮 B3 候选的诊断：", ""])
        for method in ("B4", "B5", "M"):
            diag = model_report["iterative_vs_B3"][method]
            lines.append(
                f"- {method}: 首轮响应一致 {diag['same_initial_response_count']}/"
                f"{diag['n']}；实际发生修订 {diag['trajectories_with_revision']}；"
                f"联合改善/回归/不变 = {diag['joint_improved']}/"
                f"{diag['joint_regressed']}/{diag['joint_unchanged']}。"
            )
        lines.append("")
    lines.extend(
        [
            "## 关键观察",
            "",
            "- 7B：B0 的 Secure-Pass@1 为 44.4%，B1 为 66.7%；"
            "B2–B5/M 均为 100%。",
            "- 14B：B0 为 66.7%，B1/B3 为 100%；B2 降至 44.4%，"
            "说明仅功能测试不能替代安全规格。",
            "- 14B B2 的 SAFE@1 为 48.6%，比严格 Secure-Pass@1 的 44.4% "
            "高 4.2 个百分点，捕获了安全但仅部分功能正确的候选。",
            "- 两个模型的 B3/B4/B5/M 均为 100%，且所有共享首轮候选都直接"
            "通过可见测试；本轮没有触发反馈修订，不能区分 B4/B5/M。",
            "- CWE-78 对所有方法和模型均饱和为 100%，当前三任务集合存在"
            "明显天花板效应。",
            "",
            "## 解释边界",
            "",
            "当前只有 3 个任务、每方法每模型 9 条轨迹；B3/B4/B5/M 全部"
            "轨迹首轮即通过，因此无法区分反馈选择策略。下一阶段应扩展"
            "行为族 oracle 覆盖和任务数，并增加会触发多轮修复的困难样本。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    report = {
        "schema_version": 1,
        "scope": {
            "models": len(args.run_dirs),
            "tasks_per_model": 3,
            "methods": list(METHODS),
            "seeds": [11, 22, 33],
            "expected_trajectories": 126,
            "interpretation": "descriptive_pre_experiment",
        },
        "models": {},
    }
    total = 0
    for run_dir in args.run_dirs:
        manifest, trajectories = load_run(run_dir.resolve())
        total += len(trajectories)
        index = {
            (item["task"], item["generation_seed"], item["method"]): item
            for item in trajectories
        }
        by_method = defaultdict(list)
        by_method_task = defaultdict(lambda: defaultdict(list))
        for item in trajectories:
            by_method[item["method"]].append(item)
            by_method_task[item["method"]][item["task"]].append(item)
        model = manifest["model"]
        report["models"][model] = {
            "run_dir": str(run_dir.resolve()),
            "input_sha256": manifest["input_sha256"],
            "methods": {
                method: summarize(by_method[method]) for method in METHODS
            },
            "tasks": {
                method: {
                    task: summarize(items)
                    for task, items in sorted(by_method_task[method].items())
                }
                for method in METHODS
            },
            "paired_vs_B0": {
                method: paired_summary(index, method, "B0")
                for method in METHODS
            },
            "iterative_vs_B3": iterative_diagnostics(index),
        }
    report["scope"]["observed_trajectories"] = total
    if total != report["scope"]["expected_trajectories"]:
        raise AssertionError(f"Expected 126 trajectories, found {total}")
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    args.markdown_output.write_text(markdown_report(report))
    print(f"JSON: {args.json_output.resolve()}")
    print(f"Markdown: {args.markdown_output.resolve()}")


if __name__ == "__main__":
    main()
