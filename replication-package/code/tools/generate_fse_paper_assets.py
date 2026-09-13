#!/usr/bin/env python3
"""Generate FSE paper assets from the corrected balanced and 51-task freezes."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "artifacts/reports/paper-expansion-full-v1.json"
COMBINED = ROOT / "artifacts/reports/unified-paper-evidence-v4.json"
OUT = ROOT / "FSE/paper/generated"
ORDER = ("B0", "B1", "B2", "B3", "B4", "B5", "M", "B6")


def pct(value: float) -> str:
    return f"{100 * value:.1f}"


def esc(value: str) -> str:
    return value.replace("_", r"\_").replace("+", r"\texttt{+}")


def write(name: str, body: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(body.rstrip() + "\n", encoding="utf-8")


def comparison(report: dict, target: str, reference: str) -> dict:
    return next(
        item
        for item in report["paired_joint_comparisons"]
        if item["treatment"] == target and item["control"] == reference
    )


def main() -> None:
    primary = json.loads(PRIMARY.read_text(encoding="utf-8"))
    combined = json.loads(COMBINED.read_text(encoding="utf-8"))
    if not primary.get("complete") or primary["trajectory_count"] != 3200:
        raise RuntimeError("Corrected balanced report is incomplete")
    if not combined.get("complete") or combined["scope"]["combined_trajectories"] != 5905:
        raise RuntimeError("51-task evidence report is incomplete")

    by_benchmark = defaultdict(list)
    for run in primary["runs"]:
        by_benchmark[run["benchmark"]].append(run)
    scope = [
        r"\begin{tabular}{llrrrrr}",
        r"\toprule",
        r"Role & Benchmark & Tasks & Models & Meth. & Rep. & Traj. \\",
        r"\midrule",
    ]
    labels = {"cweval": "CWEval", "sallm": "SALLM", "codeguardplus": "CodeGuard+"}
    for benchmark in ("cweval", "sallm", "codeguardplus"):
        runs = by_benchmark[benchmark]
        scope.append(
            f"Balanced primary & {labels[benchmark]} & {runs[0]['tasks']} & {len(runs)} & "
            f"{runs[0]['methods']} & {runs[0]['repeats']} & {sum(x['trajectories'] for x in runs):,} \\\\"
        )
    scope += [
        r"\midrule",
        r"Balanced primary & \multicolumn{5}{r}{20 task instances} & 3,200 \\",
        r"Legacy support & \multicolumn{5}{r}{31 disjoint task instances} & 2,705 \\",
        r"Combined coverage & \multicolumn{5}{r}{51 task instances} & 5,905 \\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    write("scope-table.tex", "\n".join(scope))

    aggregate_index = {
        (item["benchmark"], item["model"], item["method"]): item
        for item in primary["aggregates"]
    }
    outcomes = [
        r"\begin{tabular}{llrrrrrrrr}",
        r"\toprule",
        r"Benchmark & Model & B0 & B1 & B2 & B3 & B4 & B5 & M & B6 \\",
        r"\midrule",
    ]
    pairs = sorted({(item["benchmark"], item["model"]) for item in primary["aggregates"]})
    for benchmark, model in pairs:
        cells = [pct(aggregate_index[(benchmark, model, method)]["joint_rate"]) for method in ORDER]
        outcomes.append(f"{labels[benchmark]} & {esc(model)} & " + " & ".join(cells) + r" \\")
    outcomes += [r"\bottomrule", r"\end{tabular}"]
    write("joint-outcomes-table.tex", "\n".join(outcomes))

    marginal = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Method & Pass@1 & Secure@1 & Joint@1 & SAFE@1 \\",
        r"\midrule",
    ]
    for method in ORDER:
        rows = [item for item in primary["aggregates"] if item["method"] == method]
        total = sum(item["trajectories"] for item in rows)
        weighted = {
            key: sum(item[key] * item["trajectories"] for item in rows) / total
            for key in ("functional_rate", "security_rate", "joint_rate", "safe_mean")
        }
        marginal.append(
            f"{method} & {pct(weighted['functional_rate'])} & {pct(weighted['security_rate'])} & "
            f"{pct(weighted['joint_rate'])} & {pct(weighted['safe_mean'])} \\\\"
        )
    marginal += [r"\bottomrule", r"\end{tabular}"]
    write("marginal-metrics-table.tex", "\n".join(marginal))

    feedback = [
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Comparison & Cells & Trig. & Repair & J.Reg. & F.Reg. & Sec.-only \\",
        r"\midrule",
    ]
    for target, reference in (("B4", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4")):
        item = comparison(primary, target, reference)
        feedback.append(
            f"{target} $-$ {reference} & {item['wins'] + item['losses'] + item['ties']} & "
            f"{item['feedback_trigger_count']} & {item['wins']} & {item['losses']} & "
            f"{item['function_regression_count']} & {item['security_only_repair_count']} \\\\"
        )
    feedback += [r"\bottomrule", r"\end{tabular}"]
    write("feedback-events-table.tex", "\n".join(feedback))

    tfor = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Method & Visible joint & Hidden failures & TFOR (\%) \\",
        r"\midrule",
    ]
    for method in ("B0", "B3", "B4", "M", "B6"):
        rows = [item for item in primary["aggregates"] if item["method"] == method]
        denominator = sum(item["tfor"]["denominator"] for item in rows)
        numerator = sum(item["tfor"]["numerator"] for item in rows)
        tfor.append(
            f"{method} & {denominator} & {numerator} & {pct(numerator / denominator)} \\\\"
        )
    tfor += [r"\bottomrule", r"\end{tabular}"]
    write("tfor-table.tex", "\n".join(tfor))

    robustness = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Comparison & Tasks & Pairs & Joint $\Delta$ (pp) & 95\% CI (pp) \\",
        r"\midrule",
    ]
    for item in combined["combined_task_cluster_comparisons"]:
        low, high = item["task_bootstrap_ci95"]
        robustness.append(
            f"{item['target']} $-$ {item['reference']} & {item['eligible_task_clusters']} & "
            f"{item['eligible_trajectory_pairs']} & {100 * item['task_macro_joint_delta']:.2f} & "
            f"[{100 * low:.2f}, {100 * high:.2f}] \\\\"
        )
    robustness += [r"\bottomrule", r"\end{tabular}"]
    write("robustness-table.tex", "\n".join(robustness))

    upfront = comparison(primary, "B3", "B0")
    raw = comparison(primary, "B4", "B0")
    structured = comparison(primary, "M", "B0")
    b6 = comparison(primary, "B6", "B3")
    head = comparison(primary, "M", "B4")
    directions = []
    for benchmark, model in pairs:
        directions.append(
            aggregate_index[(benchmark, model, "B3")]["joint_rate"]
            - aggregate_index[(benchmark, model, "B0")]["joint_rate"]
        )
    macros = [
        r"\newcommand{\PrimaryTrajectories}{3,200}",
        r"\newcommand{\PrimaryTaskInstances}{20}",
        r"\newcommand{\PrimaryCWEs}{16}",
        r"\newcommand{\CoverageTrajectories}{5,905}",
        r"\newcommand{\CoverageTaskInstances}{51}",
        f"\\newcommand{{\\CoverageCWEs}}{{{combined['scope']['distinct_cwe_count']}}}",
        f"\\newcommand{{\\UpfrontMacroDelta}}{{{100 * upfront['mean_delta']:.1f}}}",
        f"\\newcommand{{\\UpfrontCILow}}{{{100 * upfront['ci95_low']:.1f}}}",
        f"\\newcommand{{\\UpfrontCIHigh}}{{{100 * upfront['ci95_high']:.1f}}}",
        f"\\newcommand{{\\UpfrontPositive}}{{{sum(value > 0 for value in directions)}}}",
        f"\\newcommand{{\\UpfrontNegative}}{{{sum(value < 0 for value in directions)}}}",
        f"\\newcommand{{\\MRepairs}}{{{structured['wins']}}}",
        f"\\newcommand{{\\MRegressions}}{{{structured['losses']}}}",
        f"\\newcommand{{\\RawRepairs}}{{{raw['wins']}}}",
        f"\\newcommand{{\\RawRegressions}}{{{raw['losses']}}}",
        f"\\newcommand{{\\BsixRepairs}}{{{b6['wins']}}}",
        f"\\newcommand{{\\StructuredWins}}{{{head['wins']}}}",
        f"\\newcommand{{\\StructuredLosses}}{{{head['losses']}}}",
        f"\\newcommand{{\\StructuredTies}}{{{head['ties']}}}",
    ]
    write("result-macros.tex", "\n".join(macros))
    print(f"Generated {len(list(OUT.glob('*.tex')))} LaTeX assets in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
