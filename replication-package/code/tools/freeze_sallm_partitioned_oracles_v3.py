#!/usr/bin/env python3
"""Freeze the machine-qualified SALLM visible/hidden oracle v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import build_sallm_partitioned_oracles_v3 as builder
from build_sallm_oracle_overlay_v2 import QUALIFIED_TASKS, ROOT


PYTHON = ROOT / ".venv-sallm/bin/python"
EXECUTOR = ROOT / "tools/sallm_bwrap.py"
DEFAULT_OUTPUT = ROOT / "artifacts/sallm-oracle-v3-freeze"
FREEZE_MANIFEST = (
    ROOT / "benchmarks/manifests/sallm-partitioned-oracle-v3-freeze.json"
)
MODES = {
    "unsafe_reference": None,
    "safe_reference": ROOT / "oracles/sallm_v2/references",
    "targeted_mutant": ROOT / "oracles/sallm_v2/mutants/primary",
}
EXPECTED = {
    "unsafe_reference": (True, False),
    "safe_reference": (True, True),
    "targeted_mutant": (True, False),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=3)
    return parser.parse_args()


def record(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def run_once(
    output: Path,
    partition: str,
    mode: str,
    candidate_root: Path | None,
    repeat: int,
) -> Path:
    destination = output / partition / mode / f"repeat-{repeat}"
    command = [
        str(PYTHON),
        str(EXECUTOR),
        "--overlay",
        str(
            ROOT
            / f"configs/benchmarks/sallm_oracle_overlay_v3_{partition}.json"
        ),
        "--output",
        str(destination),
    ]
    if candidate_root is not None:
        command.extend(("--candidate-root", str(candidate_root)))
    for task in QUALIFIED_TASKS:
        command.extend(("--task", task))
    print(f"[freeze-v3] {partition} {mode} repeat={repeat}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return destination


def results(path: Path) -> dict[str, dict]:
    return {
        item["task_id"]: item
        for line in (path / "results.jsonl").read_text().splitlines()
        if (item := json.loads(line))
    }


def main() -> None:
    args = parse_args()
    if args.repeats < 3:
        raise ValueError("--repeats must be at least 3")
    output = args.output.expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError(output)
    builder.main()
    runs = {
        partition: {
            mode: [
                run_once(output, partition, mode, candidate_root, repeat)
                for repeat in range(1, args.repeats + 1)
            ]
            for mode, candidate_root in MODES.items()
        }
        for partition in ("visible", "hidden")
    }
    audit = {}
    failures = []
    for task in QUALIFIED_TASKS:
        task_audit = {}
        for partition, partition_runs in runs.items():
            task_audit[partition] = {}
            for mode, mode_runs in partition_runs.items():
                observations = []
                for run in mode_runs:
                    item = results(run)[task]
                    observations.append(
                        {
                            "functional_pass": item["functional_pass"],
                            "security_pass": item["security_pass"],
                            "run": run.relative_to(ROOT).as_posix(),
                            "results": record(run / "results.jsonl"),
                        }
                    )
                pairs = {
                    (item["functional_pass"], item["security_pass"])
                    for item in observations
                }
                expected = EXPECTED[mode]
                passed = len(pairs) == 1 and pairs == {expected}
                if not passed:
                    failures.append(
                        f"{task} {partition} {mode}: {pairs} != {expected}"
                    )
                task_audit[partition][mode] = {
                    "stable": len(pairs) == 1,
                    "passed_gate": passed,
                    "expected": {
                        "functional_pass": expected[0],
                        "security_pass": expected[1],
                    },
                    "observations": observations,
                }
        audit[task] = task_audit
    if failures:
        raise RuntimeError("\n".join(failures))

    visible = json.loads(
        (
            ROOT / "configs/oracles/sallm_partitioned_oracle_v3_visible.json"
        ).read_text()
    )
    hidden = json.loads(
        (
            ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"
        ).read_text()
    )
    for task in QUALIFIED_TASKS:
        visible_families = {
            case["behavior_family"] for case in visible["tasks"][task]["cases"]
        }
        hidden_families = {
            case["behavior_family"] for case in hidden["tasks"][task]["cases"]
        }
        if visible_families & hidden_families:
            raise RuntimeError(f"Behavior-family overlap: {task}")

    manifest = {
        "schema_version": 1,
        "freeze_type": "sallm_partitioned_oracle_technical_freeze",
        "freeze_id": builder.ORACLE_SET_ID,
        "status": "technically_frozen",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_experiment_ready": False,
        "formal_readiness_blockers": [
            "G6 independent second-researcher semantic review is pending"
        ],
        "scope": {
            "task_count": len(QUALIFIED_TASKS),
            "case_count": len(QUALIFIED_TASKS) * 4,
            "visible_case_count": len(QUALIFIED_TASKS) * 2,
            "hidden_case_count": len(QUALIFIED_TASKS) * 2,
            "task_ids": list(QUALIFIED_TASKS),
        },
        "inputs": {
            "canonical_manifest": record(builder.MANIFEST),
            "visible_projection": record(
                ROOT
                / "configs/oracles/sallm_partitioned_oracle_v3_visible.json"
            ),
            "hidden_projection": record(
                ROOT
                / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"
            ),
            "visible_overlay": record(
                ROOT
                / "configs/benchmarks/sallm_oracle_overlay_v3_visible.json"
            ),
            "hidden_overlay": record(
                ROOT
                / "configs/benchmarks/sallm_oracle_overlay_v3_hidden.json"
            ),
            "executor": record(EXECUTOR),
        },
        "validation": {
            "repeat_count": args.repeats,
            "behavior_family_overlap_count": 0,
            "all_machine_gates_passed": True,
            "task_audit": audit,
            "runs": {
                partition: {
                    mode: [
                        record(run / "run_manifest.json")
                        for run in mode_runs
                    ]
                    for mode, mode_runs in partition_runs.items()
                }
                for partition, partition_runs in runs.items()
            },
        },
        "review": {
            "status": "pending",
            "independent_reviewer": None,
        },
    }
    FREEZE_MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "technically_frozen",
                "task_count": len(QUALIFIED_TASKS),
                "case_count": len(QUALIFIED_TASKS) * 4,
                "repeat_count": args.repeats,
                "freeze_manifest": FREEZE_MANIFEST.relative_to(ROOT).as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
