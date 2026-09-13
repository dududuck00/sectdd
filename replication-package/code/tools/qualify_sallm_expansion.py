#!/usr/bin/env python3
"""Select and repeatedly qualify SALLM expansion secure references.

This stage uses only the already-frozen original SALLM oracle.  It selects the
lowest candidate index that is functional-pass/security-pass, materializes the
benchmark vulnerable reference as a targeted security-fix reversion, and runs
safe/unsafe/mutant subjects in three fresh Bubblewrap executions.  Tasks that
cannot pass a gate are retained as rejected evidence rather than aborting the
whole expansion wave.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "configs/benchmarks/sallm_expansion_candidates_v1.json"
DEFAULT_GENERATION = (
    ROOT
    / "artifacts/sallm-secure-reference/deepseek-v4-flash-expansion-v1"
)
DEFAULT_MANIFEST = ROOT / "benchmarks/manifests/sallm-v1.json"
DEFAULT_OVERLAY = ROOT / "configs/benchmarks/sallm_audit_overlay_v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/sallm-expansion-qualification-v1"
DEFAULT_ORACLE_ROOT = ROOT / "oracles/sallm_expansion_v1"
DEFAULT_SELECTION = (
    ROOT / "benchmarks/manifests/sallm-expansion-safe-selection-v1.json"
)
DEFAULT_QUALIFIED_TASKS = (
    ROOT / "configs/benchmarks/sallm_expansion_machine_qualified_v1.json"
)
PYTHON = ROOT / ".venv-sallm/bin/python"
EXECUTOR = ROOT / "tools/sallm_bwrap.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--oracle-root", type=Path, default=DEFAULT_ORACLE_ROOT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument(
        "--qualified-task-file", type=Path, default=DEFAULT_QUALIFIED_TASKS
    )
    parser.add_argument(
        "--selection-id",
        default="sallm-expansion-safe-selection-v1",
        help="Stable identifier written into the selection manifest",
    )
    parser.add_argument(
        "--mutation-set-id",
        default="sallm-expansion-v1-primary",
        help="Stable identifier written into the primary mutant manifest",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args()


def checked(path: Path, *, exists: bool) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_results(run: Path) -> dict[str, dict[str, Any]]:
    return {
        item["task_id"]: item
        for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if (item := json.loads(line))
    }


def run_executor(
    *,
    output: Path,
    overlay: Path,
    tasks: list[str],
    candidate_root: Path | None,
    timeout_seconds: float,
) -> None:
    command = [
        str(PYTHON),
        str(EXECUTOR),
        "--overlay",
        str(overlay),
        "--output",
        str(output),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if candidate_root is not None:
        command.extend(("--candidate-root", str(candidate_root)))
    for task in tasks:
        command.extend(("--task", task))
    subprocess.run(command, cwd=ROOT, check=True)


def read_generation_index(generation: Path) -> dict[tuple[str, int], dict[str, Any]]:
    index_path = generation / "candidate_index.jsonl"
    if not index_path.is_file():
        return {}
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {(row["task_id"], int(row["candidate_index"])): row for row in rows}


def recorded_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def candidate_path(
    generation: Path,
    task: str,
    index: int,
    generation_index: dict[tuple[str, int], dict[str, Any]],
) -> Path:
    row = generation_index.get((task, index))
    if row and row.get("candidate_path"):
        return recorded_path(row["candidate_path"])
    return (
        generation
        / "tasks"
        / task.removesuffix(".py")
        / f"candidate_{index:03d}"
        / "candidate.py"
    )


def candidate_metadata_path(
    generation: Path,
    task: str,
    index: int,
    generation_index: dict[tuple[str, int], dict[str, Any]],
) -> Path:
    row = generation_index.get((task, index))
    if row and row.get("source_metadata"):
        return recorded_path(row["source_metadata"])
    return candidate_path(generation, task, index, generation_index).parent / "metadata.json"


def stage_candidates(
    generation: Path,
    tasks: list[str],
    indices: list[int],
    root: Path,
    generation_index: dict[tuple[str, int], dict[str, Any]],
) -> dict[int, list[str]]:
    available: dict[int, list[str]] = {}
    for index in indices:
        destination = root / f"candidate-{index}"
        destination.mkdir(parents=True)
        staged = []
        for task in tasks:
            source = candidate_path(generation, task, index, generation_index)
            metadata = candidate_metadata_path(
                generation, task, index, generation_index
            )
            if not source.is_file() or not metadata.is_file():
                continue
            if load_json(metadata).get("status") != "success":
                continue
            shutil.copy2(source, destination / task)
            staged.append(task)
        available[index] = staged
    return available


def main() -> None:
    args = parse_args()
    if args.repeats < 3:
        raise ValueError("--repeats must be at least 3")
    plan_path = checked(args.plan, exists=True)
    generation = checked(args.generation, exists=True)
    manifest_path = checked(args.manifest, exists=True)
    overlay = checked(args.overlay, exists=True)
    output = checked(args.output, exists=False)
    oracle_root = checked(args.oracle_root, exists=False)
    selection_path = checked(args.selection, exists=False)
    qualified_path = checked(args.qualified_task_file, exists=False)
    for path in (output, oracle_root, selection_path, qualified_path):
        if path.exists():
            raise FileExistsError(path)
    if not PYTHON.is_file():
        raise FileNotFoundError(PYTHON)

    plan = load_json(plan_path)
    generation_manifest = load_json(generation / "run_manifest.json")
    generation_summary = load_json(generation / "summary.json")
    if generation_summary.get("complete") is not True:
        raise RuntimeError("Secure-reference generation is incomplete")
    tasks = list(plan["tasks"])
    if generation_manifest.get("selection") != tasks:
        raise RuntimeError("Generation task selection differs from expansion plan")
    indices = list(range(int(generation_manifest["candidates_per_task"])))
    manifest = load_json(manifest_path)
    benchmark = {task["task_id"]: task for task in manifest["tasks"]}
    generation_index = read_generation_index(generation)

    output.mkdir(parents=True)
    roots = output / "candidate-roots"
    available = stage_candidates(
        generation, tasks, indices, roots, generation_index
    )
    screening_runs = {}
    screening_results = {}
    for index in indices:
        selected = available[index]
        if not selected:
            continue
        run = output / "candidate-screening" / f"candidate-{index}"
        print(f"[screen] candidate={index} tasks={len(selected)}", flush=True)
        run_executor(
            output=run,
            overlay=overlay,
            tasks=selected,
            candidate_root=roots / f"candidate-{index}",
            timeout_seconds=args.timeout_seconds,
        )
        screening_runs[index] = run
        screening_results[index] = read_results(run)

    chosen: dict[str, int] = {}
    task_screening = {}
    for task in tasks:
        observations = []
        for index in indices:
            result = screening_results.get(index, {}).get(task)
            observation = {
                "candidate_index": index,
                "generated_successfully": task in available.get(index, []),
                "functional_pass": result.get("functional_pass") if result else None,
                "security_pass": result.get("security_pass") if result else None,
                "joint_pass": result.get("joint_pass") if result else None,
            }
            observations.append(observation)
            if task not in chosen and result and result.get("joint_pass") is True:
                chosen[task] = index
        task_screening[task] = observations

    safe_root = oracle_root / "references"
    mutant_root = oracle_root / "mutants/primary"
    safe_root.mkdir(parents=True)
    mutant_root.mkdir(parents=True)
    selected_records = {}
    for task, index in sorted(chosen.items()):
        safe_source = candidate_path(generation, task, index, generation_index)
        metadata_source = candidate_metadata_path(
            generation, task, index, generation_index
        )
        unsafe_source = ROOT / benchmark[task]["source"]["reference_file"]["path"]
        safe_destination = safe_root / task
        mutant_destination = mutant_root / task
        shutil.copy2(safe_source, safe_destination)
        shutil.copy2(unsafe_source, mutant_destination)
        selected_records[task] = {
            "candidate_index": index,
            "safe_reference": record(safe_destination),
            "generation_metadata": record(metadata_source),
            "targeted_mutant": record(mutant_destination),
            "mutation_operator": "revert secure repair to benchmark vulnerable reference",
            "mutation_provenance": record(unsafe_source),
        }

    qualified_tasks = sorted(chosen)
    modes: dict[str, Path | None] = {
        "unsafe_reference": None,
        "safe_reference": safe_root,
        "targeted_mutant": mutant_root,
    }
    expected = {
        "unsafe_reference": (True, False),
        "safe_reference": (True, True),
        "targeted_mutant": (True, False),
    }
    repeated_runs: dict[str, list[Path]] = {mode: [] for mode in modes}
    if qualified_tasks:
        for mode, candidate_root in modes.items():
            for repeat in range(1, args.repeats + 1):
                run = output / "repeat-audit" / mode / f"repeat-{repeat}"
                print(f"[repeat] mode={mode} repeat={repeat}", flush=True)
                run_executor(
                    output=run,
                    overlay=overlay,
                    tasks=qualified_tasks,
                    candidate_root=candidate_root,
                    timeout_seconds=args.timeout_seconds,
                )
                repeated_runs[mode].append(run)

    final_qualified = []
    repeat_audit = {}
    for task in qualified_tasks:
        mode_audit = {}
        all_passed = True
        for mode, runs in repeated_runs.items():
            observations = []
            for run in runs:
                result = read_results(run)[task]
                observations.append(
                    {
                        "functional_pass": result["functional_pass"],
                        "security_pass": result["security_pass"],
                        "joint_pass": result["joint_pass"],
                        "run": run.relative_to(ROOT).as_posix(),
                        "results_sha256": sha256(run / "results.jsonl"),
                    }
                )
            pairs = {
                (item["functional_pass"], item["security_pass"])
                for item in observations
            }
            passed = pairs == {expected[mode]} and len(observations) == args.repeats
            all_passed &= passed
            mode_audit[mode] = {
                "expected": {
                    "functional_pass": expected[mode][0],
                    "security_pass": expected[mode][1],
                },
                "stable": len(pairs) == 1,
                "passed_gate": passed,
                "observations": observations,
            }
        repeat_audit[task] = mode_audit
        if all_passed:
            final_qualified.append(task)

    rejected = {}
    for task in tasks:
        if task not in chosen:
            reason = "no_generated_candidate_passed_original_joint_oracle"
        elif task not in final_qualified:
            reason = "failed_three_repeat_safe_unsafe_or_mutant_gate"
        else:
            continue
        rejected[task] = {
            "reason": reason,
            "screening": task_screening[task],
            "repeat_audit": repeat_audit.get(task),
        }

    selection = {
        "schema_version": 1,
        "selection_id": args.selection_id,
        "status": "machine_qualified_original_oracle",
        "formal_experiment_ready": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "remaining_gates": [
            "visible/hidden behavior-family oracle construction and repeat audit",
            "model preflight identifiability audit",
            "independent semantic review",
        ],
        "inputs": {
            "expansion_plan": record(plan_path),
            "generation_manifest": record(generation / "run_manifest.json"),
            "generation_summary": record(generation / "summary.json"),
            "benchmark_manifest": record(manifest_path),
            "execution_overlay": record(overlay),
            "executor": record(EXECUTOR),
        },
        "summary": {
            "requested_task_count": len(tasks),
            "generated_candidate_count": generation_summary.get(
                "success_count", generation_summary.get("successful_candidate_count")
            ),
            "candidate_slot_count": len(tasks) * len(indices),
            "screening_selected_task_count": len(chosen),
            "three_repeat_qualified_task_count": len(final_qualified),
            "rejected_task_count": len(rejected),
            "repeat_count": args.repeats,
        },
        "tasks": {
            task: {
                **selected_records[task],
                "screening": task_screening[task],
                "repeat_audit": repeat_audit[task],
            }
            for task in final_qualified
        },
        "rejected_tasks": rejected,
        "runs": {
            "candidate_screening": {
                str(index): record(run / "run_manifest.json")
                for index, run in screening_runs.items()
            },
            "repeat_audit": {
                mode: [record(run / "run_manifest.json") for run in runs]
                for mode, runs in repeated_runs.items()
            },
        },
        "review": {
            "machine_checks": "passed for listed tasks",
            "independent_semantic_reviewer": None,
            "status": "pending",
        },
    }
    write_json(selection_path, selection)
    write_json(
        qualified_path,
        {
            "selection_id": selection["selection_id"],
            "formal_experiment_ready": False,
            "tasks": final_qualified,
        },
    )
    write_json(
        oracle_root / "mutants/primary.json",
        {
            "schema_version": 1,
            "mutation_set_id": args.mutation_set_id,
            "task_count": len(final_qualified),
            "tasks": {
                task: {
                    "mutation_operator": selected_records[task]["mutation_operator"],
                    "candidate": selected_records[task]["targeted_mutant"],
                    "provenance": selected_records[task]["mutation_provenance"],
                }
                for task in final_qualified
            },
        },
    )
    print(json.dumps(selection["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
