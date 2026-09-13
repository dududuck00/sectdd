#!/usr/bin/env python3
"""Analyze no-G7 CodeGuard+ technical-confirmatory trajectories."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from analyze_sallm_main import METHODS, exact_sign_flip, holm, load_run, summarize_model


PAIRS = (("B4", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4"))


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260805)
    return parser.parse_args()


def paired(records: list[dict]) -> dict:
    by_key = {(x["method"], x["task"], x["generation_seed"]): x for x in records}
    tasks = sorted({x["task"] for x in records})
    seeds = sorted({x["generation_seed"] for x in records})
    result = {}
    raw_p = {}
    for target, reference in PAIRS:
        differences = []
        improved = regressed = security_repairs = function_regressions = triggers = 0
        for task in tasks:
            task_differences = []
            for seed in seeds:
                current, base = by_key[(target, task, seed)], by_key[(reference, task, seed)]
                cj, bj = current["final_hidden"]["joint_pass"], base["final_hidden"]["joint_pass"]
                task_differences.append(int(cj) - int(bj))
                improved += int(cj and not bj)
                regressed += int(bj and not cj)
                security_repairs += int(base["final_hidden"]["functional"]["all_passed"] and not base["final_hidden"]["security"]["all_passed"] and cj)
                function_regressions += int(base["final_hidden"]["functional"]["all_passed"] and not current["final_hidden"]["functional"]["all_passed"])
                triggers += int(len(current["rounds"]) > 1)
            differences.append(sum(task_differences) / len(task_differences))
        name = f"{target}_vs_{reference}"
        p = exact_sign_flip(differences)
        raw_p[name] = p
        result[name] = {"mean_joint_difference": sum(differences) / len(differences), "task_differences": differences, "feedback_trigger_count": triggers, "joint_improvement_count": improved, "joint_regression_count": regressed, "security_only_repair_count": security_repairs, "function_regression_count": function_regressions, "exact_sign_flip_p": p}
    adjusted = holm(raw_p)
    for name, value in adjusted.items():
        result[name]["holm_adjusted_p"] = value
    return result


def markdown(report: dict) -> str:
    lines = [
        "# CodeGuard+ technical confirmatory experiment (human G7 skipped)", "",
        f"Design: {report['design']['models']} models × {report['design']['tasks']} tasks × {report['design']['methods']} methods × {report['design']['seeds']} seeds = {report['design']['trajectories']} trajectories.", "",
        "| Model | Method | Func | Secure | Joint | SAFE | Calls |", "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model in report["models"]:
        for method in METHODS:
            item = model["methods"][method]
            lines.append(f"| {model['model']} | {method} | {item['functional']:.3f} | {item['secure']:.3f} | {item['joint']:.3f} | {item['safe']:.3f} | {item['mean_calls']:.2f} |")
    lines += ["", "## Paired feedback events", "", "| Model | Pair | Δ Joint | Trigger | Repair | Regression | Function regression |", "|---|---|---:|---:|---:|---:|---:|"]
    for model in report["models"]:
        for name, item in model["paired_feedback"].items():
            lines.append(f"| {model['model']} | {name} | {item['mean_joint_difference']:.3f} | {item['feedback_trigger_count']} | {item['joint_improvement_count']} | {item['joint_regression_count']} | {item['function_regression_count']} |")
    lines += ["", "## Boundary", "", "This is fresh-seed technical confirmatory evidence, but the user explicitly skipped independent human G7. It remains `formal_results_use=false`; it must not be described as human-qualified formal benchmark evidence. With three tasks, inferential statistics are descriptive and underpowered.", ""]
    return "\n".join(lines)


def main() -> None:
    a = args()
    loaded = [load_run(path) for path in a.runs]
    oracle_ids = {manifest["oracle_set_id"] for manifest, _ in loaded}
    if oracle_ids != {"codeguardplus-technical-confirmatory-no-g7-v1"}:
        raise RuntimeError("Unexpected oracle-set identity")
    models = []
    all_records = []
    for index, (manifest, records) in enumerate(loaded):
        summary = summarize_model(manifest["model"], records, a.bootstrap_replicates, a.bootstrap_seed + 10000 * index)
        summary["paired_feedback"] = paired(records)
        models.append(summary)
        all_records.extend(records)
    report = {"schema_version": 1, "report_id": "codeguardplus-technical-confirmatory-no-g7-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "formal_results_use": False, "technical_confirmatory": True, "independent_human_review_complete": False, "human_g7_status": "skipped_by_user", "oracle_set_id": next(iter(oracle_ids)), "design": {"models": len(models), "tasks": len({x['task'] for x in all_records}), "methods": len(METHODS), "seeds": len({x['generation_seed'] for x in all_records}), "trajectories": len(all_records), "bootstrap_replicates": a.bootstrap_replicates, "inference_boundary": "descriptive_due_to_three_tasks"}, "models": models}
    a.json_output.parent.mkdir(parents=True, exist_ok=True)
    a.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    a.json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    a.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"trajectory_count": len(all_records), "model_count": len(models), "task_count": report["design"]["tasks"], "formal_results_use": False, "human_g7_status": "skipped_by_user"}, indent=2))


if __name__ == "__main__":
    main()
