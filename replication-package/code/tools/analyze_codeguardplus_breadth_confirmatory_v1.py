#!/usr/bin/env python3
"""Validate, analyze, and freeze the 11-task CodeGuard+ breadth wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from analyze_sallm_main import exact_sign_flip, holm, task_cluster_ci


METHODS = ("B0", "B3", "B4", "B5", "M", "B6")
PAIRS = (("B4", "B0"), ("B5", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4"), ("M", "B5"))
CONFIG = ROOT / "configs/experiments/codeguardplus_breadth_confirmatory_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_breadth_confirmatory_v1.lock.json"
REPORT = ROOT / "artifacts/codeguardplus-breadth-confirmatory-v1/report.json"
MARKDOWN = ROOT / "docs/codeguardplus-breadth-confirmatory-v1.md"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-breadth-confirmatory-results-v1-freeze.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def load_run(path: Path, expected: int) -> tuple[dict, list[dict]]:
    manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
    records = [json.loads(item.read_text(encoding="utf-8")) for item in sorted(path.glob("trajectories/*/*/seed_*/trajectory.json"))]
    if manifest["trajectory_count"] != expected or len(records) != expected:
        raise RuntimeError(f"Expected {expected} trajectories in {path}")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if manifest["oracle_set_id"] != config["oracle_set_id"] or manifest["tasks"] != config["tasks"] or manifest["methods"] != list(config["methods"]) or manifest["seeds"] != config["generation_seeds"]:
        raise RuntimeError(f"Frozen grid mismatch: {path}")
    for key, relative in (("config", manifest["config"]), ("visible_projection", manifest["visible_projection"]), ("hidden_projection", manifest["hidden_projection"])):
        if sha256(ROOT / relative) != manifest["input_sha256"][key]:
            raise RuntimeError(f"Input drift in {path}: {key}")
    index = {(x["method"], x["task"], x["generation_seed"]): x for x in records}
    for item in records:
        audit = item["hidden_leak_audit"]
        if not audit["passed"] or audit["hidden_feedback_used"] or audit["hidden_evaluation_count"] != 1:
            raise RuntimeError("Hidden isolation failure")
        for round_value in item["rounds"]:
            candidate = ROOT / round_value["candidate"]["path"]
            if not candidate.is_file() or sha256(candidate) != round_value["candidate"]["sha256"]:
                raise RuntimeError(f"Candidate drift: {candidate}")
        reference = config["methods"][item["method"]].get("shared_initial_from")
        if reference:
            source = index[(reference, item["task"], item["generation_seed"])]["rounds"][0]
            reused = item["rounds"][0]
            if not reused["generation_reused"]:
                raise RuntimeError("Shared initial candidate was not reused")
            for key in ("messages", "request_seed", "response", "usage"):
                if reused[key] != source[key]:
                    raise RuntimeError(f"Shared candidate mismatch: {key}")
    return manifest, records


def summarize(model: str, records: list[dict], bootstrap_seed: int) -> dict:
    by_method: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        by_method[item["method"]].append(item)
    methods = {}
    for method in METHODS:
        items = by_method[method]
        getters = {
            "functional": lambda x: x["final_hidden"]["functional"]["all_passed"],
            "secure": lambda x: x["final_hidden"]["security"]["all_passed"],
            "joint": lambda x: x["final_hidden"]["joint_pass"],
            "safe": lambda x: x["final_hidden"]["safe"],
        }
        value = {"trajectories": len(items)}
        for offset, (name, getter) in enumerate(getters.items()):
            value[name] = sum(getter(x) for x in items) / len(items)
            value[f"{name}_ci95"] = list(task_cluster_ci(items, getter, 10000, random.Random(bootstrap_seed + 100 * METHODS.index(method) + offset)))
        functional_successes = sum(getters["functional"](x) for x in items)
        joint_successes = sum(getters["joint"](x) for x in items)
        visible = [x for x in items if x["final_visible"]["summary"]["all_passed"]]
        overfit = sum(not x["final_hidden"]["joint_pass"] for x in visible)
        states: dict[str, int] = defaultdict(int)
        for item in items:
            f = item["final_hidden"]["functional"]["all_passed"]
            s = item["final_hidden"]["security"]["all_passed"]
            states[f"F{'+' if f else '-'}S{'+' if s else '-'}"] += 1
        value.update({
            "security_given_functional": joint_successes / functional_successes if functional_successes else None,
            "tfor": {"numerator": overfit, "denominator": len(visible), "rate": overfit / len(visible) if visible else None},
            "states": dict(states),
            "mean_calls": sum(x["budget_usage"]["model_calls"] for x in items) / len(items),
            "mean_input_tokens": sum(x["budget_usage"]["input_tokens"] for x in items) / len(items),
            "mean_output_tokens": sum(x["budget_usage"]["output_tokens"] for x in items) / len(items),
            "mean_feedback_tokens": sum(x["budget_usage"]["feedback_tokens"] for x in items) / len(items),
        })
        methods[method] = value
    return {"model": model, "methods": methods, "paired_feedback": paired(records)}


def paired(records: list[dict]) -> dict:
    index = {(x["method"], x["task"], x["generation_seed"]): x for x in records}
    tasks = sorted({x["task"] for x in records}); seeds = sorted({x["generation_seed"] for x in records})
    result, raw_p = {}, {}
    for target, reference in PAIRS:
        differences = []
        trigger = repair = regression = function_regression = security_regression = security_only_repair = 0
        for task in tasks:
            task_differences = []
            for seed in seeds:
                current, base = index[(target, task, seed)], index[(reference, task, seed)]
                cj, bj = current["final_hidden"]["joint_pass"], base["final_hidden"]["joint_pass"]
                cf, bf = current["final_hidden"]["functional"]["all_passed"], base["final_hidden"]["functional"]["all_passed"]
                cs, bs = current["final_hidden"]["security"]["all_passed"], base["final_hidden"]["security"]["all_passed"]
                task_differences.append(int(cj) - int(bj))
                trigger += int(len(current["rounds"]) > 1); repair += int(cj and not bj); regression += int(bj and not cj)
                function_regression += int(bf and not cf); security_regression += int(bs and not cs); security_only_repair += int(bf and not bs and cj)
            differences.append(sum(task_differences) / len(task_differences))
        name = f"{target}_vs_{reference}"; p = exact_sign_flip(differences); raw_p[name] = p
        result[name] = {"eligible_cells": len(tasks) * len(seeds), "feedback_trigger_count": trigger, "joint_improvement_count": repair, "joint_regression_count": regression, "function_regression_count": function_regression, "security_regression_count": security_regression, "security_only_repair_count": security_only_repair, "repair_per_trigger": repair / trigger if trigger else None, "mean_joint_difference": sum(differences) / len(differences), "task_differences": differences, "exact_sign_flip_p": p}
    for name, adjusted in holm(raw_p).items():
        result[name]["holm_adjusted_p"] = adjusted
    return result


def pct(value) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def markdown(report: dict) -> str:
    lines = ["# CodeGuard+ outcome-unfiltered breadth confirmatory v1", "", "Design: 11 machine-semantic-qualified tasks × 2 model families × 6 methods × 5 repetitions = 660 trajectories. No G8 outcome or feedback-trigger filter was applied.", "", "| Model | Method | Func | Secure | Joint | SAFE | SGF | TFOR | Calls |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for model in report["models"]:
        for method in METHODS:
            x = model["methods"][method]
            lines.append(f"| {model['model']} | {method} | {pct(x['functional'])} | {pct(x['secure'])} | {pct(x['joint'])} | {pct(x['safe'])} | {pct(x['security_given_functional'])} | {pct(x['tfor']['rate'])} | {x['mean_calls']:.2f} |")
    lines += ["", "## Shared-candidate feedback events", "", "| Model | Pair | Trigger | Repair | Joint regression | Function regression | Security-only repair | Δ Joint | Holm p |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for model in report["models"]:
        for name, x in model["paired_feedback"].items():
            lines.append(f"| {model['model']} | {name} | {x['feedback_trigger_count']} | {x['joint_improvement_count']} | {x['joint_regression_count']} | {x['function_regression_count']} | {x['security_only_repair_count']} | {pct(x['mean_joint_difference'])} | {x['holm_adjusted_p']:.3f} |")
    lines += ["", "## Interpretation boundary", "", "This wave removes the final G8 outcome-selection filter but remains machine-semantic-qualified. Independent human G7 is incomplete, so `formal_results_use=false`. DeepSeek request slots are not deterministic provider seeds; task is the inference unit.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("qwen_run", type=Path)
    parser.add_argument("deepseek_run", type=Path)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for item in lock["frozen_files"].values():
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError(f"Frozen input drift: {item['path']}")
    expected = lock["expected_trajectory_count_per_model"]
    q_manifest, q_records = load_run(args.qwen_run.resolve(), expected)
    d_manifest, d_records = load_run(args.deepseek_run.resolve(), expected)
    if (q_manifest["model"], q_manifest["provider"]) != ("qwen25-coder-14b", "local"):
        raise RuntimeError("Qwen run identity mismatch")
    if (d_manifest["model"], d_manifest["provider"], d_manifest["provider_seed_supported"]) != ("deepseek-v4-flash", "deepseek", False):
        raise RuntimeError("DeepSeek run identity/seed-policy mismatch")
    models = [summarize("qwen25-coder-14b", q_records, 20260811), summarize("deepseek-v4-flash", d_records, 20260812)]
    report = {"schema_version": 1, "report_id": "codeguardplus-breadth-confirmatory-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "complete": True, "formal_results_use": False, "technical_confirmatory": True, "independent_human_g7_complete": False, "g8_outcome_filter_applied": False, "design": {"tasks": 11, "models": 2, "model_families": 2, "methods": 6, "repetitions": 5, "trajectories": len(q_records) + len(d_records)}, "models": models, "interpretation_boundary": lock["interpretation_boundary"]}
    REPORT.parent.mkdir(parents=True, exist_ok=True); MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); MARKDOWN.write_text(markdown(report), encoding="utf-8")
    freeze = {"schema_version": 1, "freeze_id": "codeguardplus-breadth-confirmatory-results-v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "complete": True, "formal_results_use": False, "summary": report["design"], "inputs": {"lock": rec(LOCK), **lock["frozen_files"]}, "outputs": {"report": rec(REPORT), "markdown": rec(MARKDOWN), "qwen_manifest": rec(args.qwen_run.resolve() / "run_manifest.json"), "deepseek_manifest": rec(args.deepseek_run.resolve() / "run_manifest.json")}, "interpretation_boundary": lock["interpretation_boundary"]}
    FREEZE.parent.mkdir(parents=True, exist_ok=True); FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report["design"], "complete": True, "formal_results_use": False}, indent=2)); print(f"Results freeze: {FREEZE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
