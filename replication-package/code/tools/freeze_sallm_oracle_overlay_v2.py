#!/usr/bin/env python3
"""Run the repeat/mutation gates and freeze the SALLM oracle overlay v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import build_sallm_oracle_overlay_v2 as overlay_builder
import build_sallm_oracle_v2_mutants as mutant_builder


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "configs/benchmarks/sallm_oracle_overlay_v2.json"
SAFE_ROOT = ROOT / "oracles/sallm_v2/references"
MUTANT_ROOT = ROOT / "oracles/sallm_v2/mutants/primary"
MUTANT_METADATA = ROOT / "oracles/sallm_v2/mutants/primary.json"
EXECUTOR = ROOT / "tools/sallm_bwrap.py"
DEFAULT_PYTHON = ROOT / ".venv-sallm/bin/python"
DEFAULT_OUTPUT = ROOT / "artifacts/sallm-oracle-v2-freeze"
FREEZE_MANIFEST = (
    ROOT / "benchmarks/manifests/sallm-oracle-overlay-v2-freeze.json"
)
ALL_TASKS = (
    *overlay_builder.QUALIFIED_TASKS,
    overlay_builder.EXCLUDED_PILOT_TASK,
)
MODES = {
    "unsafe_reference": None,
    "safe_reference": SAFE_ROOT,
    "targeted_mutant": MUTANT_ROOT,
}
EXPECTED = {
    "unsafe_reference": (True, False),
    "safe_reference": (True, True),
    "targeted_mutant": (True, False),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeats", type=int, default=3)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def checked_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.relative_to(ROOT)
    if resolved.exists():
        raise FileExistsError(
            f"{resolved} already exists; choose a new --output to preserve "
            "the previous audit"
        )
    return resolved


def run_once(
    python: Path,
    output: Path,
    mode: str,
    candidate_root: Path | None,
    repeat: int,
) -> Path:
    destination = output / mode / f"repeat-{repeat}"
    command = [
        str(python),
        str(EXECUTOR),
        "--overlay",
        str(OVERLAY),
        "--output",
        str(destination),
    ]
    if candidate_root is not None:
        command.extend(("--candidate-root", str(candidate_root)))
    for task_id in ALL_TASKS:
        command.extend(("--task", task_id))
    print(f"[freeze] {mode} repeat={repeat}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return destination


def read_results(run: Path) -> dict[str, dict[str, object]]:
    return {
        item["task_id"]: item
        for line in (run / "results.jsonl").read_text().splitlines()
        if (item := json.loads(line))
    }


def verify_runs(
    runs: dict[str, list[Path]],
) -> dict[str, dict[str, object]]:
    audit = {}
    failures = []
    for task_id in overlay_builder.QUALIFIED_TASKS:
        mode_records = {}
        for mode, mode_runs in runs.items():
            observations = []
            for run in mode_runs:
                result = read_results(run)[task_id]
                observation = {
                    "functional_pass": result["functional_pass"],
                    "security_pass": result["security_pass"],
                    "joint_pass": result["joint_pass"],
                    "result_sha256": sha256(run / "results.jsonl"),
                    "run": run.relative_to(ROOT).as_posix(),
                }
                observations.append(observation)
            pairs = {
                (item["functional_pass"], item["security_pass"])
                for item in observations
            }
            expected = EXPECTED[mode]
            stable = len(pairs) == 1
            passed_gate = stable and pairs == {expected}
            if not passed_gate:
                failures.append(
                    f"{task_id} {mode}: observed={sorted(map(str, pairs))}, "
                    f"expected={expected}"
                )
            mode_records[mode] = {
                "expected": {
                    "functional_pass": expected[0],
                    "security_pass": expected[1],
                },
                "stable": stable,
                "passed_gate": passed_gate,
                "observations": observations,
            }
        audit[task_id] = {
            "status": "qualified",
            "modes": mode_records,
        }
    excluded = overlay_builder.EXCLUDED_PILOT_TASK
    for mode, mode_runs in runs.items():
        for run in mode_runs:
            result = read_results(run)[excluded]
            if result["status"] != "excluded_by_overlay":
                failures.append(f"{excluded} was not excluded in {mode}")
    if failures:
        raise RuntimeError("Freeze gates failed:\n" + "\n".join(failures))
    return audit


def main() -> None:
    args = parse_args()
    if args.repeats < 3:
        raise ValueError("--repeats must be at least 3")
    python = args.python.expanduser().resolve()
    if not python.is_file():
        raise FileNotFoundError(python)
    output = checked_output(args.output)

    overlay_builder.main()
    mutant_builder.main()
    runs = {
        mode: [
            run_once(python, output, mode, candidate_root, repeat)
            for repeat in range(1, args.repeats + 1)
        ]
        for mode, candidate_root in MODES.items()
    }
    task_audit = verify_runs(runs)
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "freeze_type": "sallm_oracle_overlay_technical_freeze",
        "freeze_id": "sallm-oracle-overlay-v2",
        "status": "technically_frozen",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_experiment_ready": False,
        "formal_readiness_blockers": [
            "G6 independent second-researcher semantic review is pending",
            "visible/hidden behavior-family partition is outside this overlay's pilot scope",
        ],
        "scope": overlay["scope"],
        "inputs": {
            "overlay": record(OVERLAY),
            "parent_overlay": record(
                ROOT / "configs/benchmarks/sallm_audit_overlay_v1.json"
            ),
            "benchmark_manifest": record(
                ROOT / "benchmarks/manifests/sallm-v1.json"
            ),
            "executor": record(EXECUTOR),
            "mutation_manifest": record(MUTANT_METADATA),
            "safe_references": {
                task_id: record(SAFE_ROOT / task_id)
                for task_id in overlay_builder.QUALIFIED_TASKS
            },
            "test_overrides": overlay["test_overrides"],
        },
        "validation": {
            "repeat_count": args.repeats,
            "isolation": "fresh Bubblewrap sandbox per test method",
            "network": "socket/socketpair denied by seccomp",
            "qualified_task_count": len(task_audit),
            "excluded_task_count": 1,
            "all_machine_gates_passed": True,
            "task_audit": task_audit,
            "runs": {
                mode: [
                    record(run / "run_manifest.json") for run in mode_runs
                ]
                for mode, mode_runs in runs.items()
            },
        },
        "review": {
            "designer": "Codex-assisted construction under researcher direction",
            "independent_reviewer": None,
            "status": "pending",
        },
    }
    FREEZE_MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "qualified_task_count": len(task_audit),
                "excluded_task_count": 1,
                "repeat_count": args.repeats,
                "overlay_sha256": record(OVERLAY)["sha256"],
                "freeze_manifest": FREEZE_MANIFEST.relative_to(ROOT).as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
