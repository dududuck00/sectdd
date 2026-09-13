#!/usr/bin/env python3
"""Select the lowest-index F+S+ CodeGuard+ candidate per frozen primary task."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
GENERATION = ROOT / "artifacts/codeguardplus-qualification-generation/deepseek-v4-flash-primary-v2-merged"
EVALUATION = ROOT / "artifacts/codeguardplus-qualification/deepseek-v4-flash-primary-v2-screen"
OUTPUT = ROOT / "benchmarks/manifests/codeguardplus-safe-selection-v1.json"
REPORT = ROOT / "docs/codeguardplus-safe-selection-v1.md"


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
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--generation-run", type=Path, default=GENERATION)
    parser.add_argument("--evaluation-run", type=Path, default=EVALUATION)
    parser.add_argument("--selection-state", choices=("primary", "reserve"), default="primary")
    parser.add_argument("--selection-id", default="codeguardplus-safe-selection-v1")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    plan_path = project(args.plan)
    generation = project(args.generation_run)
    evaluation = project(args.evaluation_run)
    output = project(args.output, exists=False)
    report = project(args.report, exists=False)
    if output.exists() or report.exists():
        raise FileExistsError(output if output.exists() else report)

    plan = load_json(plan_path)
    generation_manifest = load_json(generation / "run_manifest.json")
    evaluation_manifest = load_json(evaluation / "run_manifest.json")
    evaluation_summary = load_json(evaluation / "summary.json")
    candidate_records = load_jsonl(generation / "candidates.jsonl")
    candidates = [item for item in candidate_records if item.get("status") == "success"]
    results = load_jsonl(evaluation / "results.jsonl")
    plan_hash = sha256_file(plan_path)
    if generation_manifest["input_files"]["qualification_plan"]["sha256"] != plan_hash:
        raise RuntimeError("Generation used a different plan")
    if evaluation_manifest["qualification_plan"]["sha256"] != plan_hash:
        raise RuntimeError("Evaluation used a different plan")
    task_ids = plan[f"{args.selection_state}_task_ids"]
    candidate_indices = generation_manifest["candidate_indices"]
    expected_slots = len(task_ids) * len(candidate_indices)
    if generation_manifest.get("selection_state") != args.selection_state:
        raise RuntimeError("Generation selection state differs from requested pool")
    if evaluation_manifest.get("selection_state", "primary") != args.selection_state:
        raise RuntimeError("Evaluation selection state differs from requested pool")
    if (
        not evaluation_summary["complete"]
        or evaluation_summary["result_count"] != len(candidates)
    ):
        raise RuntimeError("Evaluation grid is incomplete")
    if any(item["status"] != "completed" for item in results):
        raise RuntimeError("Evaluation contains oracle/infrastructure errors")
    by_candidate = {(item["task_id"], item["candidate_index"]): item for item in candidates}
    by_result = {(item["task_id"], int(item["subject_id"].removeprefix("candidate_"))): item for item in results}
    if (
        len(candidate_records) != expected_slots
        or len(by_candidate) != len(candidates)
        or len(by_result) != len(candidates)
        or set(by_candidate) != set(by_result)
    ):
        raise RuntimeError("Candidate/evaluation grids differ")

    selected = []
    rejected = []
    task_rows = []
    all_states: Counter[str] = Counter()
    task_metadata = {item["task_id"]: item for item in plan["tasks"]}
    for task_id in task_ids:
        states = {
            str(index): "GEN_FAIL"
            for index in candidate_indices
            if (task_id, index) not in by_candidate
        }
        passing = []
        available_indices = sorted(
            index for candidate_task, index in by_result if candidate_task == task_id
        )
        for index in available_indices:
            result = by_result[(task_id, index)]
            functional = result["functional"]["passed"]
            security = result["security"]["passed"]
            state = f"F{'+' if functional else '-'}S{'+' if security else '-'}"
            states[str(index)] = state
            all_states[state] += 1
            if functional and security:
                passing.append(index)
        cwe = task_metadata[task_id]["cwe"]
        if passing:
            index = min(passing)
            candidate = by_candidate[(task_id, index)]
            candidate_path = project(ROOT / candidate["candidate"]["path"])
            if sha256_file(candidate_path) != candidate["candidate"]["sha256"]:
                raise RuntimeError(f"Candidate drift: {candidate_path}")
            selected.append(
                {
                    "task_id": task_id,
                    "cwe": cwe,
                    "candidate_index": index,
                    "selection_rule": "lowest_candidate_index_with_F+S+",
                    "candidate": record(candidate_path),
                    "screen_result": {
                        "functional_pass": True,
                        "security_pass": True,
                        "raw_finding_count": by_result[(task_id, index)]["security"]["raw_finding_count"],
                        "filtered_finding_count": by_result[(task_id, index)]["security"]["filtered_finding_count"],
                    },
                    "all_candidate_states": states,
                }
            )
            decision = f"selected candidate {index}"
        else:
            state_counts = Counter(states.values())
            rejected.append(
                {
                    "task_id": task_id,
                    "cwe": cwe,
                    "decision": "rejected_no_F+S+_candidate",
                    "candidate_states": states,
                    "state_counts": dict(sorted(state_counts.items())),
                }
            )
            decision = "rejected"
        task_rows.append((task_id, cwe, states, decision))

    payload = {
        "schema_version": 1,
        "manifest_type": "codeguardplus_safe_reference_screen_selection",
        "selection_id": args.selection_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_phase": "oracle_construction_development",
        "development_only": True,
        "formal_results_use": False,
        "selection_rule": "lowest candidate index satisfying functional_pass=true and security_pass=true",
        "inputs": {
            "qualification_plan": record(plan_path),
            "generation_manifest": record(generation / "run_manifest.json"),
            "generation_candidates": record(generation / "candidates.jsonl"),
            "evaluation_manifest": record(evaluation / "run_manifest.json"),
            "evaluation_results": record(evaluation / "results.jsonl"),
            "evaluation_summary": record(evaluation / "summary.json"),
        },
        "counts": {
            "source_tasks": len(task_ids),
            "selection_state": args.selection_state,
            "candidate_slots": expected_slots,
            "generation_successes": len(candidates),
            "generation_failures": expected_slots - len(candidates),
            "candidate_results": len(results),
            "selected_tasks": len(selected),
            "rejected_tasks": len(rejected),
            "selected_cwes": len({item["cwe"] for item in selected}),
        },
        "selected_task_ids": [item["task_id"] for item in selected],
        "selected": selected,
        "rejected": rejected,
        "next_gate": "Three independent sandbox repetitions for each selected safe reference, followed by targeted vulnerability-mutant construction.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# CodeGuard+ 安全参考初筛 v1",
        "",
        f"{len(candidates)} 个成功生成候选均完成一次功能与 CodeQL 初筛，无基础设施错误。每题固定选择",
        "candidate index 最小的 F+S+ 实现；没有联合通过候选的任务直接拒绝。",
        "",
        f"- 来源池：{args.selection_state}",
        f"- 入选：{len(selected)}/{len(task_ids)} 题，{len({item['cwe'] for item in selected})} 个 CWE",
        f"- 拒绝：{len(rejected)}/{len(task_ids)} 题",
        "- 候选象限：" + "、".join(f"{key} {value}" for key, value in sorted(all_states.items())),
        "",
        "| Task | CWE | candidate states | 决定 |",
        "|---|---|---|---|",
    ]
    for task_id, cwe, states, decision in task_rows:
        rendered_states = " / ".join(
            f"{index}:{states[str(index)]}" for index in candidate_indices
        )
        lines.append(f"| {task_id} | {cwe} | {rendered_states} | {decision} |")
    lines.extend(
        [
            "",
            "该初筛只产生安全参考候选，不证明 oracle 对漏洞敏感，也不构成方法效果",
            "证据。入选实现仍须三次独立 sandbox 稳定通过，并由定向漏洞变异体证明",
            "对应 CodeQL/功能 oracle 能形成 F+S- 对照。",
            "",
        ]
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))


if __name__ == "__main__":
    main()
