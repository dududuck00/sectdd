#!/usr/bin/env python3
"""Recompute the paper-facing metrics from the exported trajectory records."""

from __future__ import annotations

import gzip
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reproduced"
METHODS = ("B0", "B1", "B2", "B3", "B4", "B5", "M", "B6")
PRIMARY_PAIRS = (
    ("B1", "B0"),
    ("B2", "B0"),
    ("B3", "B0"),
    ("B4", "B0"),
    ("B5", "B0"),
    ("M", "B0"),
    ("B6", "B3"),
    ("M", "B4"),
    ("M", "B5"),
)
COMBINED_PAIRS = (("B3", "B0"), ("B4", "B0"), ("M", "B0"), ("B6", "B3"), ("M", "B4"))


def load_records(name: str) -> list[dict[str, Any]]:
    path = ROOT / "data" / f"{name}-trajectories.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def outcome(row: dict[str, Any]) -> tuple[int, int, int, float]:
    hidden = row["final_hidden"]
    functional = int(hidden["functional"]["all_passed"])
    security = int(hidden["security"]["all_passed"])
    joint = int(hidden["joint_pass"])
    safe = hidden.get("safe", joint)
    if not isinstance(safe, (int, float)):
        safe = joint
    return functional, security, joint, float(safe)


def visible_joint(row: dict[str, Any]) -> bool:
    visible = row["final_visible"]
    cases = visible.get("cases", [])
    if cases:
        functional = [c for c in cases if c.get("marker") in {"functional", "functionality"}]
        security = [c for c in cases if c.get("marker") == "security"]
        return bool(functional and security) and all(c.get("passed") for c in functional + security)
    return bool(visible.get("summary", {}).get("all_passed"))


def cluster_name(row: dict[str, Any]) -> str:
    return f"{row['_artifact']['benchmark']}:{row['task']}"


def identity(row: dict[str, Any]) -> tuple[str, str, str, int, str]:
    return (
        row["_artifact"]["benchmark"],
        row["model"],
        row["task"],
        int(row["generation_seed"]),
        row["method"],
    )


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def compare(rows: list[dict[str, Any]], target: str, reference: str, seed: int) -> dict[str, Any]:
    index = {identity(row): row for row in rows}
    deltas: dict[str, list[int]] = defaultdict(list)
    wins = losses = ties = triggers = 0
    function_regressions = security_regressions = security_only_repairs = 0
    for row in rows:
        if row["method"] != target:
            continue
        key = identity(row)
        baseline = index.get((*key[:-1], reference))
        if baseline is None:
            continue
        bf, bs, bj, _ = outcome(baseline)
        tf, ts, tj, _ = outcome(row)
        delta = tj - bj
        deltas[cluster_name(row)].append(delta)
        wins += int(delta > 0)
        losses += int(delta < 0)
        ties += int(delta == 0)
        triggers += int(len(row["rounds"]) > 1)
        function_regressions += int(bf and not tf)
        security_regressions += int(bs and not ts)
        security_only_repairs += int(bf and not bs and tj)
    tasks = sorted(deltas)
    observed = mean(mean(deltas[task]) for task in tasks)
    rng = random.Random(seed)
    samples = []
    for _ in range(10_000):
        chosen = [rng.choice(tasks) for _ in tasks]
        samples.append(mean(mean(deltas[task]) for task in chosen))
    return {
        "target": target,
        "reference": reference,
        "eligible_task_clusters": len(tasks),
        "eligible_trajectory_pairs": wins + losses + ties,
        "task_macro_joint_delta": observed,
        "task_bootstrap_ci95": [percentile(samples, 0.025), percentile(samples, 0.975)],
        "bootstrap_replicates": 10_000,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "feedback_triggered": triggers,
        "function_regressions": function_regressions,
        "security_regressions": security_regressions,
        "security_only_repairs": security_only_repairs,
    }


def summarize_methods(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["method"]].append(row)
    result: dict[str, dict[str, Any]] = {}
    for method in METHODS:
        samples = groups.get(method, [])
        if not samples:
            continue
        values = [outcome(row) for row in samples]
        visible = [row for row in samples if visible_joint(row)]
        failures = sum(not outcome(row)[2] for row in visible)
        result[method] = {
            "n": len(samples),
            "functional": mean(value[0] for value in values),
            "secure": mean(value[1] for value in values),
            "joint": mean(value[2] for value in values),
            "safe": mean(value[3] for value in values),
            "visible_joint_passes": len(visible),
            "visible_pass_hidden_joint_fail": failures,
            "tfor": failures / len(visible) if visible else None,
            "states": dict(sorted(Counter(
                f"F{'+' if value[0] else '-'}S{'+' if value[1] else '-'}" for value in values
            ).items())),
        }
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def main() -> None:
    primary = load_records("primary")
    legacy = load_records("legacy")
    if len(primary) != 3_200 or len(legacy) != 2_705:
        raise RuntimeError("Exported trajectory counts are incomplete")
    if len({identity(row) for row in primary}) != len(primary):
        raise RuntimeError("Duplicate identity in the balanced primary data")

    primary_report = {
        "evidence_role": "primary_confirmatory",
        "trajectory_count": len(primary),
        "task_count": len({cluster_name(row) for row in primary}),
        "model_count": len({row["model"] for row in primary}),
        "method_count": len({row["method"] for row in primary}),
        "methods": summarize_methods(primary),
        "paired_joint_comparisons": [
            compare(primary, target, reference, 20261101 + offset)
            for offset, (target, reference) in enumerate(PRIMARY_PAIRS)
        ],
    }
    combined = primary + legacy
    combined_report = {
        "evidence_role": "descriptive_only",
        "trajectory_count": len(combined),
        "task_count": len({cluster_name(row) for row in combined}),
        "model_count": len({row["model"] for row in combined}),
        "methods": summarize_methods(combined),
        "paired_joint_comparisons": [
            compare(combined, target, reference, 20261201 + offset)
            for offset, (target, reference) in enumerate(COMBINED_PAIRS)
        ],
    }

    # These assertions protect the headline values from silent analysis drift.
    primary_pairs = {(x["target"], x["reference"]): x for x in primary_report["paired_joint_comparisons"]}
    expected = {
        ("B3", "B0"): (0.17, 85, 17),
        ("B4", "B0"): (0.1475, 59, 0),
        ("M", "B0"): (0.13, 52, 0),
        ("B6", "B3"): (0.08, 32, 0),
    }
    for pair, (delta, wins, losses) in expected.items():
        item = primary_pairs[pair]
        if abs(item["task_macro_joint_delta"] - delta) > 1e-12 or item["wins"] != wins or item["losses"] != losses:
            raise RuntimeError(f"Headline result mismatch for {pair}: {item}")
    tfor = primary_report["methods"]
    expected_tfor = {"B0": (21, 216), "B3": (45, 319), "B4": (38, 303), "M": (37, 295), "B6": (45, 351)}
    for method, (failures, passes) in expected_tfor.items():
        if (tfor[method]["visible_pass_hidden_joint_fail"], tfor[method]["visible_joint_passes"]) != (failures, passes):
            raise RuntimeError(f"TFOR mismatch for {method}")

    write_json(OUT / "primary-summary.json", primary_report)
    write_json(OUT / "combined-descriptive-summary.json", combined_report)
    lines = [
        "# Independently reproduced results",
        "",
        "The 20-task balanced matrix is confirmatory; the 51-task combined view is descriptive.",
        "",
        "## Balanced primary methods",
        "",
        "| Method | Functional | Secure | Joint | SAFE | TFOR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method, item in primary_report["methods"].items():
        lines.append(f"| {method} | {pct(item['functional'])} | {pct(item['secure'])} | {pct(item['joint'])} | {pct(item['safe'])} | {pct(item['tfor'])} |")
    lines.extend(["", "## Paired hidden-joint comparisons", "", "| Pair | Delta | 95% task-bootstrap CI | Wins | Losses |", "|---|---:|---:|---:|---:|"])
    for item in primary_report["paired_joint_comparisons"]:
        low, high = item["task_bootstrap_ci95"]
        lines.append(f"| {item['target']} - {item['reference']} | {100*item['task_macro_joint_delta']:.2f} pp | [{100*low:.2f}, {100*high:.2f}] | {item['wins']} | {item['losses']} |")
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("OK: reproduced primary and combined paper results.")


if __name__ == "__main__":
    main()
