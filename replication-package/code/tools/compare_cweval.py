#!/usr/bin/env python3
"""Build a compact comparison report from detailed CWEval metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="Run in LABEL=EVAL_PATH form; repeat for multiple runs.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def parse_run(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Expected LABEL=EVAL_PATH, received {value!r}")
    label, raw_path = value.split("=", 1)
    if not label:
        raise ValueError("Run label cannot be empty")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(path)
    return label, path


def summarize_run(path: Path) -> dict:
    manifest = json.loads(
        (path / "generation_manifest.json").read_text(encoding="utf-8")
    )
    metrics_1 = json.loads((path / "metrics_k1.json").read_text(encoding="utf-8"))
    metrics_n = json.loads(
        (path / f"metrics_k{manifest['samples_per_task']}.json").read_text(
            encoding="utf-8"
        )
    )
    quadrants = {"F+S+": 0, "F+S-": 0, "F-S+": 0, "F-S-": 0}
    functional_fractions = []
    security_fractions = []
    per_seed = {
        str(seed): {"functional": 0, "secure": 0, "joint": 0, "safe": 0.0}
        for seed in manifest["generation_seeds"]
    }
    task_joint_rates = {}

    for task, task_result in metrics_1["per_task"].items():
        joint_count = 0
        for sample in task_result["samples"]:
            functional = sample["functional"]
            secure = sample["secure"]
            quadrant = ("F+" if functional else "F-") + (
                "S+" if secure else "S-"
            )
            quadrants[quadrant] += 1
            functional_fractions.append(sample["functional_test_fraction"])
            security_fractions.append(sample["security_test_fraction"])
            seed = str(manifest["generation_seeds"][sample["sample_index"]])
            per_seed[seed]["functional"] += int(functional)
            per_seed[seed]["secure"] += int(secure)
            per_seed[seed]["joint"] += int(functional and secure)
            per_seed[seed]["safe"] += sample["safe_score"]
            joint_count += int(functional and secure)
        task_joint_rates[task] = joint_count / len(task_result["samples"])

    task_count = metrics_1["task_count"]
    for seed_result in per_seed.values():
        for name in seed_result:
            seed_result[name] /= task_count

    functional_total = quadrants["F+S+"] + quadrants["F+S-"]
    return {
        "manifest": manifest,
        "metrics_at_1": metrics_1["aggregate"],
        f"metrics_at_{manifest['samples_per_task']}": metrics_n["aggregate"],
        "quadrants": quadrants,
        "security_given_functional": (
            quadrants["F+S+"] / functional_total if functional_total else None
        ),
        "mean_functional_test_fraction": (
            sum(functional_fractions) / len(functional_fractions)
        ),
        "mean_security_test_fraction": (
            sum(security_fractions) / len(security_fractions)
        ),
        "per_seed": per_seed,
        "task_joint_rates": task_joint_rates,
    }


def main() -> None:
    args = parse_args()
    runs = dict(parse_run(value) for value in args.run)
    if len(runs) != len(args.run):
        raise ValueError("Run labels must be unique")
    report = {"runs": {label: summarize_run(path) for label, path in runs.items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Comparison: {args.output.resolve()}")


if __name__ == "__main__":
    main()

