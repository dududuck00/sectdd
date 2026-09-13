#!/usr/bin/env python3
"""Create the paper-facing CWEval/SALLM/CodeGuard+ evidence synthesis."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CWEVAL = ROOT / "artifacts/reports/main-internal-main-003-corrected.json"
SALLM = ROOT / "artifacts/reports/sallm-main-main-002.json"
CODEGUARD = ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1/report.json"
SALLM_RUNS = (
    ROOT / "artifacts/sallm_formal_main/qwen25-coder-7b-main-002",
    ROOT / "artifacts/sallm_formal_main/qwen25-coder-14b-main-002",
    ROOT / "artifacts/sallm_formal_main/qwen36-27b-main-002",
)
CODEGUARD_RUN = ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1"
JSON_OUTPUT = ROOT / "artifacts/reports/unified-cweval-sallm-codeguard-v1.json"
MARKDOWN_OUTPUT = ROOT / "docs/unified-cweval-sallm-codeguard-results-v1.md"
COMMON_METHODS = ("B0", "B3", "B4", "M", "B6")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def load_trajectories(roots: tuple[Path, ...] | list[Path]) -> list[dict]:
    return [json.loads(path.read_text()) for root in roots for path in sorted(root.glob("trajectories/*/*/seed_*/trajectory.json"))]


def normalized_methods() -> dict[str, dict[str, dict[str, float]]]:
    cwe, sallm, codeguard = [json.loads(path.read_text()) for path in (CWEVAL, SALLM, CODEGUARD)]
    result: dict[str, dict[str, dict[str, float]]] = {}
    cwe_models = {}
    for model, data in cwe["models"].items():
        cwe_models[model] = {method: {"functional": item["hidden_func_at_1"], "secure": item["hidden_secure_at_1"], "joint": item["hidden_secure_pass_at_1"], "safe": item["hidden_safe_at_1"], "calls": item["cost"]["model_calls"]["mean"]} for method, item in data["methods"].items()}
    result["CWEval"] = cwe_models
    for name, report in (("SALLM", sallm), ("CodeGuard+", codeguard)):
        result[name] = {model["model"]: {method: {"functional": item["functional"], "secure": item["secure"], "joint": item["joint"], "safe": item["safe"], "calls": item["mean_calls"]} for method, item in model["methods"].items()} for model in report["models"]}
    return result


def paired_events(records: list[dict], target: str, reference: str) -> dict[str, int]:
    index = {(item["model"], item["task"], item["generation_seed"], item["method"]): item for item in records}
    cells = sorted({key[:3] for key in index if key[3] == target})
    result = {"eligible_cells": len(cells), "feedback_triggered": 0, "joint_improved": 0, "joint_regressed": 0, "function_regressed": 0, "security_only_repaired": 0}
    for model, task, seed in cells:
        current, base = index[(model, task, seed, target)], index[(model, task, seed, reference)]
        cj, bj = current["final_hidden"]["joint_pass"], base["final_hidden"]["joint_pass"]
        cf = current["final_hidden"]["functional"]["all_passed"]
        bf = base["final_hidden"]["functional"]["all_passed"]
        bs = base["final_hidden"]["security"]["all_passed"]
        result["feedback_triggered"] += int(len(current["rounds"]) > 1)
        result["joint_improved"] += int(cj and not bj)
        result["joint_regressed"] += int(bj and not cj)
        result["function_regressed"] += int(bf and not cf)
        result["security_only_repaired"] += int(bf and not bs and cj)
    return result


def cweval_events(report: dict, method: str) -> dict[str, int]:
    keys = {"eligible_cells": "n", "feedback_triggered": "triggered", "joint_improved": "joint_improved", "joint_regressed": "joint_regressed", "function_regressed": "functionality_regressions", "security_only_repaired": "secure_repairs_without_function_loss"}
    return {out: sum(model["paired_feedback"][method][source] for model in report["models"].values()) for out, source in keys.items()}


def macro_table(methods: dict[str, dict[str, dict[str, float]]]) -> dict[str, dict[str, dict[str, float]]]:
    output = {}
    for benchmark, models in methods.items():
        available = sorted(set.intersection(*(set(value) for value in models.values())))
        output[benchmark] = {}
        for method in available:
            output[benchmark][method] = {metric: mean([values[method][metric] for values in models.values()]) for metric in ("functional", "secure", "joint", "safe", "calls")}
    return output


def markdown(report: dict) -> str:
    lines = ["# CWEval / SALLM / CodeGuard+ unified evidence v1", "", "## Evidence scope", "", "| Benchmark | Status | Models | Tasks | Methods | Seeds | Trajectories |", "|---|---|---:|---:|---:|---:|---:|"]
    for item in report["design"]:
        lines.append(f"| {item['benchmark']} | {item['status']} | {item['models']} | {item['tasks']} | {item['methods']} | {item['seeds']} | {item['trajectories']} |")
    lines += ["| Total | Do not treat trajectories as independent inference units | — | — | — | — | 1,995 |", "", "## Model-macro outcomes", "", "| Benchmark | Method | Func@1 | Secure@1 | Joint@1 | SAFE@1 | Calls |", "|---|---|---:|---:|---:|---:|---:|"]
    for benchmark, methods in report["macro_methods"].items():
        for method, value in methods.items():
            if method in COMMON_METHODS:
                lines.append(f"| {benchmark} | {method} | {value['functional']:.3f} | {value['secure']:.3f} | {value['joint']:.3f} | {value['safe']:.3f} | {value['calls']:.2f} |")
    lines += ["", "## Shared-initial feedback events", "", "| Benchmark | Pair | Eligible | Triggered | Joint repair | Joint regression | Security-only repair | Function regression |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for benchmark, pairs in report["paired_feedback"].items():
        for name, value in pairs.items():
            lines.append(f"| {benchmark} | {name} | {value['eligible_cells']} | {value['feedback_triggered']} | {value['joint_improved']} | {value['joint_regressed']} | {value['security_only_repaired']} | {value['function_regressed']} |")
    lines += ["", "## Paper-facing conclusion", "", "Executable-test feedback repeatedly converts failed initial candidates into hidden functional-and-security joint passes, but gains depend on model, task, and feedback entry point. Raw feedback B4 and structured feedback M are usually competitive, so current evidence supports the feedback mechanism rather than universal superiority of M. CodeGuard+ further shows that exposing all visible tests can harm a strong model and that feedback can partly recover this loss.", "", "## Validity boundary", "", "- CWEval is internal confirmatory evidence because its tasks participated in method development.", "- SALLM is external but machine-qualified; independent human semantic review remains incomplete.", "- CodeGuard+ contains only three G8-selected tasks and explicitly skipped human G7; it is technical evidence with `formal_results_use=false`.", "- All evaluated generation models are Qwen-family models. Cross-family evidence is still required.", "- Task is the inference unit; the 1,995 trajectories are repeated observations, not 1,995 independent samples.", ""]
    return "\n".join(lines)


def main() -> None:
    cwe = json.loads(CWEVAL.read_text())
    normalized = normalized_methods()
    sallm_records = load_trajectories(SALLM_RUNS)
    codeguard_roots = [CODEGUARD_RUN / model for model in ("qwen25-coder-7b", "qwen25-coder-14b", "qwen36-27b")]
    codeguard_records = load_trajectories(codeguard_roots)
    report = {
        "schema_version": 1,
        "report_id": "unified-cweval-sallm-codeguard-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_results_use": False,
        "design": [
            {"benchmark": "CWEval", "status": "internal_confirmatory", "models": 3, "tasks": 9, "methods": 7, "seeds": 5, "trajectories": 945},
            {"benchmark": "SALLM", "status": "external_machine_qualified", "models": 3, "tasks": 11, "methods": 5, "seeds": 5, "trajectories": 825},
            {"benchmark": "CodeGuard+", "status": "technical_confirmatory_human_g7_skipped", "models": 3, "tasks": 3, "methods": 5, "seeds": 5, "trajectories": 225},
        ],
        "trajectory_total": 1995,
        "macro_methods": macro_table(normalized),
        "per_model_methods": normalized,
        "paired_feedback": {
            "CWEval": {"B4_vs_B0": cweval_events(cwe, "B4"), "M_vs_B0": cweval_events(cwe, "M")},
            "SALLM": {"B4_vs_B0": paired_events(sallm_records, "B4", "B0"), "M_vs_B0": paired_events(sallm_records, "M", "B0"), "B6_vs_B3": paired_events(sallm_records, "B6", "B3")},
            "CodeGuard+": {"B4_vs_B0": paired_events(codeguard_records, "B4", "B0"), "M_vs_B0": paired_events(codeguard_records, "M", "B0"), "B6_vs_B3": paired_events(codeguard_records, "B6", "B3")},
        },
        "inputs": {name: record(path) for name, path in (("cweval", CWEVAL), ("sallm", SALLM), ("codeguardplus", CODEGUARD))},
        "interpretation": {"supports": ["test feedback repairs a subset of failed candidates", "feedback benefits are model/task dependent", "security and functionality must be evaluated jointly", "upfront tests and iterative feedback are distinct interventions"], "does_not_support": ["M is universally best", "structured feedback is significantly better than raw feedback", "the result generalizes beyond Qwen model families", "CodeGuard+ is a broad human-qualified formal benchmark result"]},
    }
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MARKDOWN_OUTPUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"trajectory_total": 1995, "benchmark_count": 3, "model_conditions": 9, "formal_results_use": False, "json": JSON_OUTPUT.relative_to(ROOT).as_posix(), "markdown": MARKDOWN_OUTPUT.relative_to(ROOT).as_posix()}, indent=2))


if __name__ == "__main__":
    main()
