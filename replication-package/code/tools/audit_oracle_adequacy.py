#!/usr/bin/env python3
"""Audit per-case mutant kills and summarize oracle mutation adequacy."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("validation_summary", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "oracles" / "cweval_python_v1" / "manifest.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def function_from_nodeid(nodeid: str) -> str:
    return nodeid.rsplit("::", 1)[-1]


def main() -> None:
    args = parse_args()
    summary_path = args.validation_summary.expanduser().resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    records = {
        (record["candidate_id"], record["partition"]): record
        for record in summary["records"]
    }

    failed_functions: dict[tuple[str, str], set[str]] = {}
    for key, record in records.items():
        per_repeat = []
        for repeat in record["repeats"]:
            failed = {
                function_from_nodeid(case["nodeid"])
                for case in repeat["result"]["cases"]
                if not case["passed"]
            }
            per_repeat.append(failed)
        if any(failed != per_repeat[0] for failed in per_repeat[1:]):
            raise AssertionError(f"Nondeterministic failing case set: {key}")
        failed_functions[key] = per_repeat[0]

    reference_candidates = [
        candidate
        for candidate in manifest["candidates"]
        if candidate["kind"] == "reference"
    ]
    for candidate in reference_candidates:
        for partition in ("visible", "hidden"):
            failed = failed_functions[(candidate["candidate_id"], partition)]
            if failed:
                raise AssertionError(
                    f"Reference failed {partition}: "
                    f"{candidate['candidate_id']}: {sorted(failed)}"
                )

    case_target_pairs = []
    targeted_kills = 0
    cases_by_task = {
        task: task_data["cases"]
        for task, task_data in manifest["tasks"].items()
    }
    for task, cases in cases_by_task.items():
        for case in cases:
            function_name = function_from_nodeid(case["pytest_nodeid"])
            for mutant_id in case["target_mutants"]:
                killed = function_name in failed_functions[
                    (mutant_id, case["partition"])
                ]
                case_target_pairs.append(
                    {
                        "task": task,
                        "case_id": case["case_id"],
                        "behavior_family": case["behavior_family"],
                        "partition": case["partition"],
                        "mutant_id": mutant_id,
                        "killed": killed,
                    }
                )
                targeted_kills += int(killed)
                if not killed:
                    raise AssertionError(
                        f"Target case did not kill mutant: "
                        f"{case['case_id']} -> {mutant_id}"
                    )

    mutant_rows = []
    by_task = defaultdict(
        lambda: {
            "mutants": 0,
            "visible_killed": 0,
            "hidden_killed": 0,
            "union_killed": 0,
            "hidden_only": 0,
        }
    )
    for candidate in manifest["candidates"]:
        if candidate["kind"] != "mutant":
            continue
        visible_killed = bool(
            failed_functions[(candidate["candidate_id"], "visible")]
        )
        hidden_killed = bool(
            failed_functions[(candidate["candidate_id"], "hidden")]
        )
        row = {
            "candidate_id": candidate["candidate_id"],
            "task": candidate["task"],
            "visible_killed": visible_killed,
            "hidden_killed": hidden_killed,
            "union_killed": visible_killed or hidden_killed,
            "hidden_only": hidden_killed and not visible_killed,
        }
        mutant_rows.append(row)
        task_summary = by_task[candidate["task"]]
        task_summary["mutants"] += 1
        for key in (
            "visible_killed",
            "hidden_killed",
            "union_killed",
            "hidden_only",
        ):
            task_summary[key] += int(row[key])

    totals = {
        "mutants": len(mutant_rows),
        "visible_killed": sum(row["visible_killed"] for row in mutant_rows),
        "hidden_killed": sum(row["hidden_killed"] for row in mutant_rows),
        "union_killed": sum(row["union_killed"] for row in mutant_rows),
        "hidden_only": sum(row["hidden_only"] for row in mutant_rows),
        "target_case_mutant_pairs": len(case_target_pairs),
        "target_case_mutant_pairs_killed": targeted_kills,
    }
    if totals["union_killed"] != totals["mutants"]:
        raise AssertionError("At least one mutant survived both partitions")
    report = {
        "schema_version": 1,
        "oracle_id": manifest["oracle_id"],
        "validation_summary": str(summary_path),
        "reference_candidates": len(reference_candidates),
        "all_references_passed": True,
        "all_target_case_mutant_pairs_killed": True,
        "totals": totals,
        "by_task": dict(by_task),
        "mutants": mutant_rows,
        "case_target_pairs": case_target_pairs,
    }
    output = args.output or summary_path.with_name("adequacy_report.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"OK: references={len(reference_candidates)}, "
        f"mutants={totals['mutants']}, "
        f"visible_killed={totals['visible_killed']}, "
        f"hidden_killed={totals['hidden_killed']}, "
        f"union_killed={totals['union_killed']}, "
        f"hidden_only={totals['hidden_only']}, "
        f"target_pairs={targeted_kills}/{len(case_target_pairs)}."
    )
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
