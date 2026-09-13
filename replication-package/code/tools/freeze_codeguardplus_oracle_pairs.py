#!/usr/bin/env python3
"""Freeze CodeGuard+ safe/mutant pairs after three stable independent repetitions."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
SAFE = ROOT / "benchmarks/manifests/codeguardplus-stable-safe-v1.json"
MUTANTS = ROOT / "benchmarks/manifests/codeguardplus-mutant-selection-v1.json"
EVALUATION = ROOT / "artifacts/codeguardplus-qualification/selected-mutants-v1-repeats3"
OUTPUT = ROOT / "benchmarks/manifests/codeguardplus-oracle-pairs-v1.json"
REPORT = ROOT / "docs/codeguardplus-oracle-pairs-v1.md"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project(path: Path, *, exists: bool = True) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def record(path: Path) -> dict[str, Any]:
    path = project(path)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def state(result: dict[str, Any]) -> str:
    functional = result["functional"]["passed"]
    security = result["security"]["passed"]
    if functional is None or security is None:
        return "infrastructure_or_oracle_error"
    return f"F{'+' if functional else '-'}S{'+' if security else '-'}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--safe-selection", type=Path, default=SAFE)
    parser.add_argument("--mutant-selection", type=Path, default=MUTANTS)
    parser.add_argument("--mutant-evaluation-run", type=Path, default=EVALUATION)
    parser.add_argument("--freeze-id", default="codeguardplus-oracle-pairs-v1")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    plan_path = project(args.plan)
    safe_path = project(args.safe_selection)
    mutant_path = project(args.mutant_selection)
    evaluation = project(args.mutant_evaluation_run)
    output = project(args.output, exists=False)
    report = project(args.report, exists=False)
    if output.exists() or report.exists():
        raise FileExistsError(output if output.exists() else report)

    plan = load_json(plan_path)
    benchmark_manifest = load_json(
        project(ROOT / plan["inputs"]["benchmark_manifest"]["path"])
    )
    safe = load_json(safe_path)
    mutants = load_json(mutant_path)
    evaluation_manifest = load_json(evaluation / "run_manifest.json")
    evaluation_summary = load_json(evaluation / "summary.json")
    results = load_jsonl(evaluation / "results.jsonl")
    plan_hash = sha256_file(plan_path)
    if safe["inputs"]["qualification_plan"]["sha256"] != plan_hash:
        raise RuntimeError("Safe-reference selection used a different plan")
    if mutants["inputs"]["qualification_plan"]["sha256"] != plan_hash:
        raise RuntimeError("Mutant selection used a different plan")
    if evaluation_manifest["qualification_plan"]["sha256"] != plan_hash:
        raise RuntimeError("Mutant repetitions used a different plan")
    if evaluation_manifest["repeats"] != 3:
        raise RuntimeError("Oracle-pair freeze requires exactly three mutant repetitions")
    expected_ids = mutants["selected_task_ids"]
    observed_ids = [item["task_id"] for item in evaluation_manifest["subjects"]]
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != set(expected_ids):
        raise RuntimeError("Mutant repetition subjects differ from the selection")
    if evaluation_summary["result_count"] != len(expected_ids) * 3 or not evaluation_summary["complete"]:
        raise RuntimeError("Mutant repetition grid is incomplete")
    if any(item["status"] != "completed" for item in results):
        raise RuntimeError("Mutant repetitions contain infrastructure/oracle errors")

    safe_items = {item["task_id"]: item for item in safe["selected"]}
    mutant_items = {item["task_id"]: item for item in mutants["selected"]}
    by_task: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in expected_ids}
    for result in results:
        if result["task_id"] not in by_task:
            raise RuntimeError(f"Unexpected task in mutant repetitions: {result['task_id']}")
        by_task[result["task_id"]].append(result)

    qualified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rows: list[tuple[str, str, list[str], str]] = []
    for task_id in expected_ids:
        task_results = sorted(by_task[task_id], key=lambda item: item["repeat"])
        if [item["repeat"] for item in task_results] != [1, 2, 3]:
            raise RuntimeError(f"Invalid mutant repeat grid for {task_id}")
        states = [state(item) for item in task_results]
        safe_item = safe_items[task_id]
        mutant_item = mutant_items[task_id]
        safe_file = project(ROOT / safe_item["candidate"]["path"])
        mutant_file = project(ROOT / mutant_item["mutant"]["path"])
        if sha256_file(safe_file) != safe_item["candidate"]["sha256"]:
            raise RuntimeError(f"Safe reference drift: {safe_file}")
        if sha256_file(mutant_file) != mutant_item["mutant"]["sha256"]:
            raise RuntimeError(f"Mutant drift: {mutant_file}")
        evidence = {
            "safe_reference_repeat_states": safe_item["stability_gate"]["repeat_states"],
            "mutant_repeat_states": {str(index + 1): value for index, value in enumerate(states)},
        }
        if all(value == "F+S-" for value in states):
            qualified.append(
                {
                    "task_id": task_id,
                    "cwe": safe_item["cwe"],
                    "safe_reference": safe_item["candidate"],
                    "safe_candidate_index": safe_item["candidate_index"],
                    "vulnerability_mutant": mutant_item["mutant"],
                    "mutant_index": mutant_item["mutant_index"],
                    "mutation_summary": mutant_item.get("mutation_summary", ""),
                    "qualification_evidence": evidence,
                }
            )
            decision = "qualified"
        else:
            rejected.append(
                {
                    "task_id": task_id,
                    "cwe": safe_item["cwe"],
                    "decision": "rejected_mutant_not_F+S-_in_all_three_repetitions",
                    **evidence,
                }
            )
            decision = "rejected"
        rows.append((task_id, safe_item["cwe"], states, decision))

    payload = {
        "schema_version": 1,
        "manifest_type": "codeguardplus_machine_qualified_oracle_pairs",
        "freeze_id": args.freeze_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "path": benchmark_manifest["repository"]["path"],
            "commit": plan["inputs"]["repository_commit"],
        },
        "study_phase": "oracle_construction_development",
        "development_only": True,
        "formal_results_use": False,
        "qualification_rule": "safe reference is F+S+ in three repeats and paired mutant is F+S- in three repeats",
        "inputs": {
            "qualification_plan": record(plan_path),
            "stable_safe_selection": record(safe_path),
            "mutant_selection": record(mutant_path),
            "mutant_evaluation_manifest": record(evaluation / "run_manifest.json"),
            "mutant_evaluation_results": record(evaluation / "results.jsonl"),
            "mutant_evaluation_summary": record(evaluation / "summary.json"),
        },
        "counts": {
            "mutant_screen_selected_tasks": len(expected_ids),
            "mutant_repeat_results": len(results),
            "qualified_tasks": len(qualified),
            "rejected_tasks": len(rejected),
            "qualified_cwes": len({item["cwe"] for item in qualified}),
        },
        "qualified_task_ids": [item["task_id"] for item in qualified],
        "tasks": qualified,
        "rejected": rejected,
        "formal_experiment_ready": False,
        "remaining_gates": [
            "independent visible/hidden behavioral-family construction",
            "safe/mutant observations against both behavioral partitions",
            "independent semantic review",
            "fresh-seed multi-model G8 preflight",
            "final prompt/oracle/budget hash freeze",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# CodeGuard+ 机器资格化 oracle pairs v1",
        "",
        "每个保留任务都有一个三次稳定 F+S+ 的安全参考实现，以及一个三次稳定",
        "F+S- 的定向漏洞变异体。该结果证明当前功能/CodeQL oracle 能形成目标对照，",
        "但尚未通过独立行为族与语义审查，不能用于正式方法效果比较。",
        "",
        f"- 机器资格化：{len(qualified)}/{len(expected_ids)} 题，{len({item['cwe'] for item in qualified})} 个 CWE",
        f"- 剔除：{len(rejected)}/{len(expected_ids)} 题",
        f"- 本轮 mutant 独立观察：{len(results)} 次",
        "",
        "| Task | CWE | mutant repeat 1/2/3 | 决定 |",
        "|---|---|---|---|",
    ]
    for task_id, cwe, states, decision in rows:
        lines.append(f"| {task_id} | {cwe} | {' / '.join(states)} | {decision} |")
    lines.extend(
        [
            "",
            "下一步必须为这些任务建设互不重叠的 visible/hidden 行为族，分别观察安全",
            "参考和漏洞变异体，再进行独立语义审查和全新 seed 多模型 G8 preflight。",
            "",
        ]
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))


if __name__ == "__main__":
    main()
