#!/usr/bin/env python3
"""Build the paper-facing synthesis across Qwen and DeepSeek evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
JSON_OUTPUT = ROOT / "artifacts/reports/unified-paper-evidence-v2.json"
UNIFIED_MD = ROOT / "docs/unified-paper-evidence-v2.md"
PAPER_MD = ROOT / "docs/paper-results-and-validity-draft-v1.md"
CASES_MD = ROOT / "docs/paper-case-studies-v1.md"
FREEZE = ROOT / "benchmarks/manifests/paper-evidence-v2-results-freeze.json"
METHODS = ("B0", "B3", "B4", "M", "B6")


RUNS = (
    ("CWEval", "Qwen", "qwen25-coder-7b", ROOT / "artifacts/main_internal/qwen25-coder-7b-main-002", 315),
    ("CWEval", "Qwen", "qwen25-coder-14b", ROOT / "artifacts/main_internal/qwen25-coder-14b-main-003-corrected", 315),
    ("CWEval", "Qwen", "qwen3-32b", ROOT / "artifacts/main_internal/qwen3-32b-main-002", 315),
    ("SALLM", "Qwen", "qwen25-coder-7b", ROOT / "artifacts/sallm_formal_main/qwen25-coder-7b-main-002", 275),
    ("SALLM", "Qwen", "qwen25-coder-14b", ROOT / "artifacts/sallm_formal_main/qwen25-coder-14b-main-002", 275),
    ("SALLM", "Qwen", "qwen36-27b", ROOT / "artifacts/sallm_formal_main/qwen36-27b-main-002", 275),
    ("CodeGuard+", "Qwen", "qwen25-coder-7b", ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1/qwen25-coder-7b", 75),
    ("CodeGuard+", "Qwen", "qwen25-coder-14b", ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1/qwen25-coder-14b", 75),
    ("CodeGuard+", "Qwen", "qwen36-27b", ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1/qwen36-27b", 75),
    ("SALLM", "DeepSeek", "deepseek-v4-flash", ROOT / "artifacts/deepseek-external-confirmatory-v1/sallm", 275),
    ("CodeGuard+", "DeepSeek", "deepseek-v4-flash", ROOT / "artifacts/deepseek-external-confirmatory-v1/codeguardplus", 75),
)

SOURCE_REPORTS = (
    ROOT / "artifacts/reports/main-internal-main-003-corrected.json",
    ROOT / "artifacts/reports/sallm-main-main-002.json",
    ROOT / "artifacts/codeguardplus-technical-confirmatory-no-g7-v1/report.json",
    ROOT / "artifacts/deepseek-external-confirmatory-v1/report.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def adjusted_p_values(value: Any) -> list[float]:
    found: list[float] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"holm_adjusted_p", "holm_adjusted_pvalue"} and isinstance(child, (int, float)):
                found.append(float(child))
            else:
                found.extend(adjusted_p_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(adjusted_p_values(child))
    return found


def state(item: dict) -> str:
    functional = item["final_hidden"]["functional"]["all_passed"]
    secure = item["final_hidden"]["security"]["all_passed"]
    return f"F{'+' if functional else '-'}S{'+' if secure else '-'}"


def visible_joint(item: dict) -> bool:
    visible = item["final_visible"]
    cases = visible.get("cases", [])
    if cases:
        functional = all(x["passed"] for x in cases if x["marker"] == "functionality")
        secure = all(x["passed"] for x in cases if x["marker"] == "security")
        return functional and secure
    return bool(visible["summary"]["all_passed"])


def load_records() -> tuple[list[dict], list[dict]]:
    all_records: list[dict] = []
    run_records = []
    for benchmark, family, model, root, expected in RUNS:
        manifest_path = root / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = []
        trajectory_files = sorted(root.glob("trajectories/*/*/seed_*/trajectory.json"))
        grid_hasher = hashlib.sha256()
        for path in trajectory_files:
            relative = path.relative_to(root).as_posix()
            digest = sha256(path)
            grid_hasher.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["model"] != model:
                raise RuntimeError(f"Model drift in {path}")
            item["_benchmark"] = benchmark
            item["_family"] = family
            item["_trajectory_path"] = path.relative_to(ROOT).as_posix()
            records.append(item)
        if len(records) != expected or manifest["trajectory_count"] != expected:
            raise RuntimeError(f"Trajectory count mismatch: {root}")
        all_records.extend(records)
        run_records.append(
            {
                "benchmark": benchmark,
                "family": family,
                "model": model,
                "tasks": len({x["task"] for x in records}),
                "methods": len({x["method"] for x in records}),
                "repetitions": len({x["generation_seed"] for x in records}),
                "trajectories": len(records),
                "manifest": file_record(manifest_path),
                "trajectory_grid_sha256": grid_hasher.hexdigest(),
                "provider_seed_supported": manifest.get("provider_seed_supported", True),
            }
        )
    if len(all_records) != 2345:
        raise RuntimeError("Expected exactly 2,345 frozen trajectories")
    return all_records, run_records


def summarize(items: list[dict]) -> dict[str, Any]:
    functional = [bool(x["final_hidden"]["functional"]["all_passed"]) for x in items]
    secure = [bool(x["final_hidden"]["security"]["all_passed"]) for x in items]
    joint = [bool(x["final_hidden"]["joint_pass"]) for x in items]
    visible = [visible_joint(x) for x in items]
    visible_denominator = sum(visible)
    overfit = sum(v and not j for v, j in zip(visible, joint))
    states: dict[str, int] = defaultdict(int)
    for item in items:
        states[state(item)] += 1
    return {
        "n": len(items),
        "functional": average([int(x) for x in functional]),
        "secure": average([int(x) for x in secure]),
        "joint": average([int(x) for x in joint]),
        "safe": average([float(x["final_hidden"]["safe"]) for x in items]),
        "security_given_functional": sum(joint) / sum(functional) if sum(functional) else None,
        "visible_joint": average([int(x) for x in visible]),
        "tfor": {
            "numerator": overfit,
            "denominator": visible_denominator,
            "rate": overfit / visible_denominator if visible_denominator else None,
        },
        "states": dict(sorted(states.items())),
        "cost": {
            key: average([float(x["budget_usage"][key]) for x in items])
            for key in ("model_calls", "input_tokens", "output_tokens", "feedback_tokens")
        },
    }


def condition_summaries(records: list[dict]) -> dict[str, dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in records:
        grouped[(item["_benchmark"], item["model"], item["method"])].append(item)
    output: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    for (benchmark, model, method), items in grouped.items():
        output[benchmark][model][method] = summarize(items)
    return {b: dict(models) for b, models in output.items()}


def paired(records: list[dict], target: str, reference: str) -> dict[str, Any]:
    index = {
        (x["_benchmark"], x["model"], x["task"], x["generation_seed"], x["method"]): x
        for x in records
    }
    cells = []
    for key, current in index.items():
        benchmark, model, task, slot, method = key
        if method != target:
            continue
        base = index.get((benchmark, model, task, slot, reference))
        if base is not None:
            cells.append((current, base))
    result: dict[str, Any] = {
        "eligible_cells": len(cells),
        "feedback_triggered": 0,
        "joint_improved": 0,
        "joint_regressed": 0,
        "function_regressed": 0,
        "security_regressed": 0,
        "security_only_repaired": 0,
        "target_better": 0,
        "reference_better": 0,
        "outcome_tied": 0,
    }
    call_deltas = []
    feedback_deltas = []
    for current, base in cells:
        cj, bj = bool(current["final_hidden"]["joint_pass"]), bool(base["final_hidden"]["joint_pass"])
        cf, bf = bool(current["final_hidden"]["functional"]["all_passed"]), bool(base["final_hidden"]["functional"]["all_passed"])
        cs, bs = bool(current["final_hidden"]["security"]["all_passed"]), bool(base["final_hidden"]["security"]["all_passed"])
        result["feedback_triggered"] += int(len(current["rounds"]) > 1)
        result["joint_improved"] += int(cj and not bj)
        result["joint_regressed"] += int(bj and not cj)
        result["function_regressed"] += int(bf and not cf)
        result["security_regressed"] += int(bs and not cs)
        result["security_only_repaired"] += int(bf and not bs and cj)
        result["target_better"] += int(cj and not bj)
        result["reference_better"] += int(bj and not cj)
        result["outcome_tied"] += int(cj == bj)
        call_deltas.append(current["budget_usage"]["model_calls"] - base["budget_usage"]["model_calls"])
        feedback_deltas.append(current["budget_usage"]["feedback_tokens"] - base["budget_usage"]["feedback_tokens"])
    triggered = result["feedback_triggered"]
    result["repair_per_trigger"] = result["joint_improved"] / triggered if triggered else None
    result["regression_per_trigger"] = result["joint_regressed"] / triggered if triggered else None
    result["mean_call_delta"] = average(call_deltas)
    result["mean_feedback_token_delta"] = average(feedback_deltas)
    return result


def rq1(condition: dict[str, dict]) -> dict[str, Any]:
    rows = []
    for benchmark, models in condition.items():
        for model, methods in models.items():
            if "B0" not in methods or "B3" not in methods:
                continue
            rows.append(
                {
                    "benchmark": benchmark,
                    "model": model,
                    **{
                        f"delta_{metric}": methods["B3"][metric] - methods["B0"][metric]
                        for metric in ("functional", "secure", "joint", "safe")
                    },
                }
            )
    deltas = [x["delta_joint"] for x in rows]
    return {
        "comparison": "B3_vs_B0_non_shared_generation_condition_contrast",
        "condition_count": len(rows),
        "mean_condition_delta": {
            metric: average([x[f"delta_{metric}"] for x in rows])
            for metric in ("functional", "secure", "joint", "safe")
        },
        "joint_direction_counts": {
            "positive": sum(x > 1e-12 for x in deltas),
            "tie": sum(abs(x) <= 1e-12 for x in deltas),
            "negative": sum(x < -1e-12 for x in deltas),
        },
        "conditions": rows,
        "causal_boundary": "B0 and B3 do not share an initial candidate; interpret as a matched condition contrast, not a trajectory-level repair effect.",
    }


def rq4(records: list[dict]) -> dict[str, Any]:
    by_method: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        if item["method"] in METHODS:
            by_method[item["method"]].append(item)
    output = {}
    for method, items in by_method.items():
        visible = [x for x in items if visible_joint(x)]
        numerator = sum(not x["final_hidden"]["joint_pass"] for x in visible)
        output[method] = {
            "visible_joint_passes": len(visible),
            "visible_pass_hidden_joint_fail": numerator,
            "tfor": numerator / len(visible) if visible else None,
            "hidden_joint_retention": 1 - numerator / len(visible) if visible else None,
        }
    return output


def rq5(condition: dict[str, dict]) -> dict[str, Any]:
    result = {}
    for benchmark in ("SALLM", "CodeGuard+"):
        models = condition[benchmark]
        qwen = [value for model, value in models.items() if model != "deepseek-v4-flash"]
        deepseek = models["deepseek-v4-flash"]
        result[benchmark] = {}
        for method in METHODS:
            qwen_joint = average([x[method]["joint"] for x in qwen])
            result[benchmark][method] = {
                "qwen_model_macro_joint": qwen_joint,
                "deepseek_joint": deepseek[method]["joint"],
                "deepseek_minus_qwen_macro": deepseek[method]["joint"] - qwen_joint,
            }
    return result


def case_record(item: dict) -> dict[str, Any]:
    failed = [
        {
            "marker": case["marker"],
            "behavior_family": case.get("behavior_family"),
            "description": case.get("description"),
        }
        for case in item["final_hidden"]["raw"].get("cases", [])
        if not case["passed"]
    ]
    final_round = item["rounds"][-1]
    candidate_record = final_round.get("candidate")
    if candidate_record is not None:
        candidate = candidate_record["path"]
    else:
        trajectory_path = ROOT / item["_trajectory_path"]
        candidate_path = (
            trajectory_path.parent
            / f"round_{final_round['round']}"
            / "eval/generated_0/core/py"
            / f"{item['task']}_raw.py"
        )
        if not candidate_path.is_file():
            raise FileNotFoundError(candidate_path)
        candidate = candidate_path.relative_to(ROOT).as_posix()
    return {
        "benchmark": item["_benchmark"],
        "model": item["model"],
        "task": item["task"],
        "request_slot_or_seed": item["generation_seed"],
        "method": item["method"],
        "state": state(item),
        "visible_joint": visible_joint(item),
        "rounds": len(item["rounds"]),
        "candidate": candidate,
        "trajectory": item["_trajectory_path"],
        "failed_hidden_behaviors": failed,
    }


def select_cases(records: list[dict]) -> list[dict]:
    index = {
        (x["_benchmark"], x["model"], x["task"], x["generation_seed"], x["method"]): x
        for x in records
    }
    cases = []

    def add_pair(case_id: str, interpretation: str, current: dict, base: dict) -> None:
        cases.append(
            {
                "case_id": case_id,
                "interpretation": interpretation,
                "before": case_record(base),
                "after": case_record(current),
            }
        )

    for current in records:
        if current["_benchmark"] == "SALLM" and current["model"] == "deepseek-v4-flash" and current["method"] == "B6":
            key = (current["_benchmark"], current["model"], current["task"], current["generation_seed"], "B3")
            base = index[key]
            if current["final_hidden"]["joint_pass"] and not base["final_hidden"]["joint_pass"]:
                add_pair("deepseek_sallm_feedback_repair", "Structured feedback repairs a shared B3 candidate on an external model family.", current, base)
                break
    for current in records:
        if current["_benchmark"] == "CWEval" and current["method"] == "M":
            base = index[(current["_benchmark"], current["model"], current["task"], current["generation_seed"], "B0")]
            bf = base["final_hidden"]["functional"]["all_passed"]
            bs = base["final_hidden"]["security"]["all_passed"]
            if bf and not bs and current["final_hidden"]["joint_pass"]:
                add_pair("cweval_function_preserving_security_repair", "SecTDD repairs a security-only failure without sacrificing functionality.", current, base)
                break
    for current in records:
        if current["_benchmark"] == "SALLM" and current["model"] == "deepseek-v4-flash" and current["method"] == "M":
            base = index[(current["_benchmark"], current["model"], current["task"], current["generation_seed"], "B4")]
            if base["final_hidden"]["joint_pass"] and not current["final_hidden"]["joint_pass"]:
                add_pair("structured_feedback_regression", "M and B4 share the initial candidate, but structured feedback regresses where raw feedback succeeds.", current, base)
                break
    for current in records:
        if current["_benchmark"] == "CodeGuard+" and current["model"] == "deepseek-v4-flash" and current["method"] == "B3":
            base = index[(current["_benchmark"], current["model"], current["task"], current["generation_seed"], "B0")]
            if base["final_hidden"]["joint_pass"] and not current["final_hidden"]["joint_pass"]:
                add_pair("upfront_test_security_harm", "Same-slot condition contrast: upfront tests preserve functionality but produce a hidden security failure; candidates are not shared.", current, base)
                break
    overfit = next((x for x in records if visible_joint(x) and not x["final_hidden"]["joint_pass"]), None)
    if overfit:
        cases.append(
            {
                "case_id": "visible_hidden_overfitting",
                "interpretation": "A candidate passes the complete visible partition but fails a hidden behavior family.",
                "candidate": case_record(overfit),
            }
        )
    return cases


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def evidence_markdown(report: dict) -> str:
    lines = [
        "# Unified paper evidence v2", "",
        "This synthesis is generated from frozen trajectories and includes the DeepSeek cross-family wave.", "",
        "## Scope", "",
        "| Benchmark | Family | Model | Tasks | Methods | Repetitions | Trajectories |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        lines.append(f"| {run['benchmark']} | {run['family']} | {run['model']} | {run['tasks']} | {run['methods']} | {run['repetitions']} | {run['trajectories']} |")
    lines += ["| **Total** | — | 11 benchmark–model conditions | — | — | — | **2,345** |", "", "## Per-condition outcomes", "", "| Benchmark | Model | Method | Func | Secure | Joint | SAFE | SGF | Calls | TFOR |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for benchmark, models in report["condition_methods"].items():
        for model, methods in models.items():
            for method in METHODS:
                if method not in methods:
                    continue
                x = methods[method]
                lines.append(f"| {benchmark} | {model} | {method} | {pct(x['functional'])} | {pct(x['secure'])} | {pct(x['joint'])} | {pct(x['safe'])} | {pct(x['security_given_functional'])} | {x['cost']['model_calls']:.2f} | {pct(x['tfor']['rate'])} |")
    lines += ["", "## RQ1: upfront executable specifications", "", f"Across {report['rq1']['condition_count']} benchmark–model conditions, B3−B0 has a model-condition macro Joint difference of {pct(report['rq1']['mean_condition_delta']['joint'])}; directions are {report['rq1']['joint_direction_counts']['positive']} positive, {report['rq1']['joint_direction_counts']['tie']} ties, and {report['rq1']['joint_direction_counts']['negative']} negative. This is a condition contrast because B0 and B3 do not share candidates.", "", "## RQ2/RQ3: shared-candidate feedback", "", "| Pair | Eligible | Triggered | Joint repair | Joint regression | Repair/trigger | Function regression | Security-only repair |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, value in report["shared_candidate_feedback"].items():
        lines.append(f"| {name} | {value['eligible_cells']} | {value['feedback_triggered']} | {value['joint_improved']} | {value['joint_regressed']} | {pct(value['repair_per_trigger'])} | {value['function_regressed']} | {value['security_only_repaired']} |")
    lines += ["", "## RQ4: visible-to-hidden overfitting", "", "| Method | Visible joint passes | Hidden joint failures | TFOR | HJR |", "|---|---:|---:|---:|---:|"]
    for method in METHODS:
        x = report["rq4"][method]
        lines.append(f"| {method} | {x['visible_joint_passes']} | {x['visible_pass_hidden_joint_fail']} | {pct(x['tfor'])} | {pct(x['hidden_joint_retention'])} |")
    lines += ["", "B6 was not run on CWEval, so its pooled TFOR uses a different task grid and must not be ranked directly against B0/B3/B4/M from this table.", "", "## Statistical and evidentiary boundary", "", f"The smallest Holm-adjusted p-value in the frozen component reports is {report['statistical_boundary']['smallest_holm_adjusted_p']:.3g}. Effects are therefore reported as descriptive estimates and paired event counts, not universal statistically significant superiority. CWEval is internal; SALLM is machine-qualified; CodeGuard+ skipped independent human G7; DeepSeek request slots are not deterministic server seeds. Consequently, `formal_results_use=false` remains in force.", ""]
    return "\n".join(lines)


def paper_markdown(report: dict) -> str:
    r1 = report["rq1"]
    b4, method_m, b6, m_vs_b4 = (report["shared_candidate_feedback"][x] for x in ("B4_vs_B0", "M_vs_B0", "B6_vs_B3", "M_vs_B4"))
    lines = [
        "# Paper results and validity draft v1", "",
        "## Experimental scope", "",
        "We analyzed 2,345 trajectories from three benchmarks. The evidence comprises 945 internal CWEval trajectories, 1,050 Qwen external trajectories on SALLM and CodeGuard+, and 350 DeepSeek API trajectories on the same external task sets. Each condition uses five repetitions; DeepSeek repetitions are independent request slots rather than deterministic provider seeds.", "",
        "## RQ1 — Are tests useful as upfront executable specifications?", "",
        f"Across 11 benchmark–model conditions, B3 changed Hidden Secure-Pass@1 by {pct(r1['mean_condition_delta']['joint'])} on average relative to B0. The direction was positive in {r1['joint_direction_counts']['positive']} conditions, tied in {r1['joint_direction_counts']['tie']}, and negative in {r1['joint_direction_counts']['negative']}. The negative case is substantively important: on DeepSeek/CodeGuard+, B0 achieved 100% Joint while B3 achieved 66.7%, with all failures concentrated in CWE-89. Thus, upfront tests are often useful specifications but are not monotonically beneficial. Because B0 and B3 use different prompts and do not share the generated candidate, this result is a matched-condition contrast rather than an edit-level causal repair estimate.", "",
        "## RQ2 — Does iterative test feedback repair failed candidates?", "",
        f"The shared-candidate comparisons provide the clearest evidence. B4 triggered feedback in {b4['feedback_triggered']} of {b4['eligible_cells']} eligible cells and produced {b4['joint_improved']} joint repairs against {b4['joint_regressed']} regressions. M triggered in {method_m['feedback_triggered']} cells and produced {method_m['joint_improved']} repairs with {method_m['joint_regressed']} joint regressions. These gains coexist with {b4['function_regressed']} B4 and {method_m['function_regressed']} M functionality regressions relative to their B0 candidates. B6, which starts from B3, triggered only {b6['feedback_triggered']} times and repaired {b6['joint_improved']} candidates ({pct(b6['repair_per_trigger'])} of triggers) without a joint regression, although one cell traded an initially secure state for an insecure state while improving another dimension. These results support the mechanism-level claim that executable feedback can convert a subset of failed initial candidates into hidden joint successes while exposing safety–functionality trade-offs. They do not imply that feedback can repair hidden failures when all visible tests already pass.", "",
        "## RQ3 — Is structured feedback better than raw feedback?", "",
        f"The direct M-versus-B4 comparison covers {m_vs_b4['eligible_cells']} exactly shared initial candidates. M is better on {m_vs_b4['target_better']} cells, B4 is better on {m_vs_b4['reference_better']}, and they tie on {m_vs_b4['outcome_tied']}. M therefore does not exhibit universal outcome superiority over fixed raw feedback. Its paper contribution should be framed as a feedback design whose benefits depend on the task and failure, while the principal robust effect belongs to iterative executable feedback itself. No component report has a Holm-adjusted p-value below {report['statistical_boundary']['smallest_holm_adjusted_p']:.3g}.", "",
        "## RQ4 — Do methods overfit visible tests?", "",
        "Visible success is not a sufficient safety criterion. The pooled TFOR table in the unified report contains visible-joint candidates that fail hidden behavior families under every major prompt/feedback regime. In particular, the DeepSeek CodeGuard+ CWE-89 candidate passes all visible tests, so B6 stops after one call, yet it fails hidden security. This demonstrates a coverage-limited feedback failure rather than an orchestration bug: a feedback loop cannot react to a property its visible oracle does not expose. B6 lacks a CWEval condition, so its pooled TFOR is based on a different grid and is not directly rank-comparable with the other methods.", "",
        "## RQ5 — Does the result generalize beyond Qwen?", "",
        "DeepSeek supplies a second major model family on 14 external tasks. On SALLM, B4 and M each improve Joint from 52.7% to 67.3% over their shared B0 initial candidates, with eight repairs and no regressions; B6 improves B3 from 81.8% to 87.3% through three repairs. This reproduces the feedback-repair phenomenon outside Qwen. Conversely, the CodeGuard+ B0 ceiling and B3 degradation show that effect size and even direction depend on the benchmark and entry point. The supported generalization is therefore qualitative—feedback can repair failures across model families—not that one method dominates everywhere.", "",
        "## Overall finding", "",
        "> Test feedback improves secure code generation by repairing a subset of failed candidates, while simultaneously exposing a safety–functionality and coverage trade-off. The effect is model-, task-, and oracle-dependent; M is not uniformly superior to simpler feedback.", "",
        "## Threats to validity", "",
        "### Construct validity", "",
        "Dynamic oracle success does not prove absence of vulnerabilities. Hidden Secure-Pass@1 remains the primary outcome, with Func, Secure, SGF, four-state outcomes, TFOR, SAFE, and costs used as decompositions. SAFE currently often collapses to Joint because SALLM and CodeGuard+ have only one hidden functional case per task; it should be presented as a sensitivity analysis rather than independent corroboration.", "",
        "### Internal validity", "",
        "B4/M and B6 use byte-identical shared initial responses, enabling edit-level paired repair analysis. B0 versus B3 does not share candidates and is only a condition contrast. Local runs use frozen generation seeds; the DeepSeek endpoint does not guarantee seed control, so frozen numbers identify request slots and pairing keys. Prompt budgets and stopping rules are frozen, but API-side model revisions remain uncontrolled.", "",
        "### Oracle validity", "",
        "SALLM and CodeGuard+ oracles were gated using safe implementations, vulnerable mutants, repeated sandbox executions, visible/hidden behavior partitions, and machine semantic review. Nevertheless, SALLM lacks completed independent human semantic review, and CodeGuard+ explicitly skipped G7. The latter remains technical confirmatory evidence and cannot be called human-qualified formal evidence.", "",
        "### External validity", "",
        "The study now covers two major model families, three benchmarks, several parameter scales, and multiple CWE mechanisms, but all evaluated tasks are Python functions or small components. Results may not transfer to repository-level maintenance, other languages, long-context agents, or production toolchains. CodeGuard+ contains only three selected tasks and is particularly susceptible to ceiling effects.", "",
        "### Statistical conclusion validity", "",
        "Task—not trajectory—is the inference unit. Five seeds/request slots are within-task repetitions, and 2,345 must not be treated as the independent sample size. Confidence intervals are wide on small external sets, and no Holm-adjusted component comparison is below 0.5. We therefore emphasize effect sizes, repair/regression counts, and consistency across settings rather than significance claims.", "",
        "### Data contamination and reproducibility", "",
        "Public benchmark tasks may have appeared in pretraining. Behavior-family hidden partitions mitigate direct memorization but do not eliminate contamination. Local checkpoints and all oracle/config hashes are frozen. DeepSeek is a remotely versioned service, so raw responses, usage, dates, model IDs, and request-slot semantics are retained, but bitwise regeneration cannot be promised.", "",
        "## Paper-use boundary", "",
        "This draft is suitable for writing the Results and Threats sections, but the aggregate remains `formal_results_use=false`. Before presenting CodeGuard+ as formal benchmark evidence, an independent human G7 submission must be completed; otherwise it must remain explicitly labeled technical confirmatory evidence.", "",
    ]
    return "\n".join(lines)


def cases_markdown(cases: list[dict]) -> str:
    lines = ["# Paper case-study audit v1", "", "These examples are selected mechanically from frozen trajectories. Hidden behavior descriptions are used only in post-hoc analysis and were never fed back to generation.", ""]
    for case in cases:
        lines += [f"## {case['case_id']}", "", case["interpretation"], ""]
        for label in ("before", "after", "candidate"):
            if label not in case:
                continue
            item = case[label]
            lines += [f"- {label}: `{item['benchmark']}` / `{item['model']}` / `{item['task']}` / `{item['method']}` / slot `{item['request_slot_or_seed']}`", f"- state: `{item['state']}`; visible joint: `{str(item['visible_joint']).lower()}`; rounds: {item['rounds']}", f"- candidate: `{item['candidate']}`", f"- trajectory: `{item['trajectory']}`"]
            if item["failed_hidden_behaviors"]:
                descriptions = "; ".join(x.get("behavior_family") or x.get("description") or "unspecified" for x in item["failed_hidden_behaviors"])
                lines.append(f"- failed hidden behaviors: {descriptions}")
            lines.append("")
    lines += ["## Usage caution", "", "The upfront-test case is a same-slot condition contrast, not a shared-candidate edit. The other paired cases use shared initial candidates. Case studies illustrate mechanisms and must not substitute for aggregate estimates.", ""]
    return "\n".join(lines)


def main() -> None:
    records, runs = load_records()
    source_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in SOURCE_REPORTS]
    all_adjusted_p = [p for payload in source_payloads for p in adjusted_p_values(payload)]
    if not all_adjusted_p:
        raise RuntimeError("No Holm-adjusted p-values found in component reports")
    condition = condition_summaries(records)
    feedback = {
        "B4_vs_B0": paired(records, "B4", "B0"),
        "M_vs_B0": paired(records, "M", "B0"),
        "B6_vs_B3": paired(records, "B6", "B3"),
        "M_vs_B4": paired(records, "M", "B4"),
    }
    report = {
        "schema_version": 2,
        "report_id": "unified-paper-evidence-v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_results_use": False,
        "trajectory_total": len(records),
        "benchmark_count": 3,
        "benchmark_model_condition_count": len(runs),
        "major_model_families": ["Qwen", "DeepSeek"],
        "runs": runs,
        "condition_methods": condition,
        "rq1": rq1(condition),
        "shared_candidate_feedback": feedback,
        "rq4": rq4(records),
        "rq5": rq5(condition),
        "statistical_boundary": {
            "smallest_holm_adjusted_p": min(all_adjusted_p),
            "component_adjusted_p_value_count": len(all_adjusted_p),
            "inference_unit": "task",
        },
        "case_studies": select_cases(records),
        "source_reports": [file_record(path) for path in SOURCE_REPORTS],
        "interpretation": {
            "supported": [
                "iterative executable feedback repairs a subset of shared failed candidates",
                "the qualitative feedback-repair mechanism appears in Qwen and DeepSeek",
                "visible passing does not guarantee hidden joint passing",
                "effect direction and magnitude depend on model, task, benchmark, and feedback entry point",
            ],
            "not_supported": [
                "M is universally superior to raw feedback",
                "upfront tests are monotonically beneficial",
                "2,345 trajectories are independent statistical samples",
                "CodeGuard+ is human-G7-qualified formal evidence",
            ],
        },
    }
    for path in (JSON_OUTPUT, UNIFIED_MD, PAPER_MD, CASES_MD):
        path.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    UNIFIED_MD.write_text(evidence_markdown(report), encoding="utf-8")
    PAPER_MD.write_text(paper_markdown(report), encoding="utf-8")
    CASES_MD.write_text(cases_markdown(report["case_studies"]), encoding="utf-8")
    freeze = {
        "schema_version": 1,
        "freeze_id": "paper-evidence-v2-results",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "formal_results_use": False,
        "summary": {
            "benchmarks": 3,
            "major_model_families": 2,
            "benchmark_model_conditions": len(runs),
            "trajectories": len(records),
            "case_studies": len(report["case_studies"]),
        },
        "inputs": {
            "source_reports": report["source_reports"],
            "run_manifests": [x["manifest"] for x in runs],
        },
        "outputs": {
            "report": file_record(JSON_OUTPUT),
            "unified_markdown": file_record(UNIFIED_MD),
            "paper_draft": file_record(PAPER_MD),
            "case_studies": file_record(CASES_MD),
        },
        "interpretation_boundary": "Paper-facing synthesis of mixed internal, machine-qualified, and technical-confirmatory evidence; formal_results_use=false.",
    }
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**freeze["summary"], "complete": True, "formal_results_use": False}, indent=2))
    print(f"Report: {JSON_OUTPUT.relative_to(ROOT)}")
    print(f"Paper draft: {PAPER_MD.relative_to(ROOT)}")
    print(f"Freeze: {FREEZE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
