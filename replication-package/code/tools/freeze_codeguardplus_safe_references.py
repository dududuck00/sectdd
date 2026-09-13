#!/usr/bin/env python3
"""Freeze CodeGuard+ safe references that pass every independent repetition."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "benchmarks/manifests/codeguardplus-safe-selection-v1.json"
EVALUATION = ROOT / "artifacts/codeguardplus-qualification/selected-safe-v1-repeats3"
OUTPUT = ROOT / "benchmarks/manifests/codeguardplus-stable-safe-v1.json"
REPORT = ROOT / "docs/codeguardplus-stable-safe-v1.md"


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
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--evaluation-run", type=Path, default=EVALUATION)
    parser.add_argument("--selection-id", default="codeguardplus-stable-safe-v1")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    selection_path = project(args.selection)
    evaluation = project(args.evaluation_run)
    output = project(args.output, exists=False)
    report = project(args.report, exists=False)
    if output.exists() or report.exists():
        raise FileExistsError(output if output.exists() else report)

    selection = load_json(selection_path)
    evaluation_manifest = load_json(evaluation / "run_manifest.json")
    summary = load_json(evaluation / "summary.json")
    results = load_jsonl(evaluation / "results.jsonl")

    expected_tasks = selection["selected_task_ids"]
    repeats = evaluation_manifest["repeats"]
    if repeats != 3:
        raise RuntimeError("Safe-reference freeze requires exactly three repetitions")
    if evaluation_manifest["subject_count"] != len(expected_tasks):
        raise RuntimeError("Evaluation subject count differs from screen selection")
    evaluated_task_ids = [item["task_id"] for item in evaluation_manifest["subjects"]]
    if len(evaluated_task_ids) != len(set(evaluated_task_ids)) or set(evaluated_task_ids) != set(expected_tasks):
        raise RuntimeError("Evaluation subjects differ from screen selection")
    if summary["result_count"] != len(expected_tasks) * repeats or not summary["complete"]:
        raise RuntimeError("Independent repetition grid is incomplete")
    if any(item["status"] != "completed" for item in results):
        raise RuntimeError("Evaluation contains infrastructure/oracle errors")

    selection_items = {item["task_id"]: item for item in selection["selected"]}
    by_task: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in expected_tasks}
    for item in results:
        if item["task_id"] not in by_task:
            raise RuntimeError(f"Unexpected task in evaluation: {item['task_id']}")
        by_task[item["task_id"]].append(item)

    stable: list[dict[str, Any]] = []
    unstable: list[dict[str, Any]] = []
    rows: list[tuple[str, str, list[str], str]] = []
    for task_id in expected_tasks:
        task_results = sorted(by_task[task_id], key=lambda item: item["repeat"])
        if [item["repeat"] for item in task_results] != [1, 2, 3]:
            raise RuntimeError(f"Invalid repeat grid for {task_id}")
        item_states = [state(item) for item in task_results]
        source = selection_items[task_id]
        candidate_path = project(ROOT / source["candidate"]["path"])
        if sha256_file(candidate_path) != source["candidate"]["sha256"]:
            raise RuntimeError(f"Safe candidate drift: {candidate_path}")
        evidence = {
            "repeat_states": {str(index + 1): value for index, value in enumerate(item_states)},
            "all_repeats_F+S+": all(value == "F+S+" for value in item_states),
        }
        if evidence["all_repeats_F+S+"]:
            stable.append({**source, "stability_gate": evidence})
            decision = "frozen"
        else:
            unstable.append(
                {
                    "task_id": task_id,
                    "cwe": source["cwe"],
                    "candidate_index": source["candidate_index"],
                    "decision": "rejected_not_F+S+_in_all_three_repetitions",
                    **evidence,
                }
            )
            decision = "rejected"
        rows.append((task_id, source["cwe"], item_states, decision))

    payload = {
        "schema_version": 1,
        "manifest_type": "codeguardplus_stable_safe_reference_selection",
        "selection_id": args.selection_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_phase": "oracle_construction_development",
        "development_only": True,
        "formal_results_use": False,
        "selection_rule": "retain a screened F+S+ candidate iff all three independent sandbox repetitions are F+S+",
        "inputs": {
            "qualification_plan": selection["inputs"]["qualification_plan"],
            "screen_selection": record(selection_path),
            "evaluation_manifest": record(evaluation / "run_manifest.json"),
            "evaluation_results": record(evaluation / "results.jsonl"),
            "evaluation_summary": record(evaluation / "summary.json"),
        },
        "counts": {
            "screen_selected_tasks": len(expected_tasks),
            "repetitions_per_task": repeats,
            "result_count": len(results),
            "stable_tasks": len(stable),
            "unstable_tasks": len(unstable),
            "stable_cwes": len({item["cwe"] for item in stable}),
        },
        "selected_task_ids": [item["task_id"] for item in stable],
        "selected": stable,
        "rejected": unstable,
        "next_gate": "Generate targeted vulnerability mutants and retain tasks only when a mutant is stably F+S-.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# CodeGuard+ 稳定安全参考冻结 v1",
        "",
        "初筛安全参考在隔离 sandbox 中独立执行三次。冻结规则预先固定为：三次均须",
        "同时通过功能 oracle 与 CodeQL 安全 oracle（F+S+）；任何一次不满足即剔除。",
        "",
        f"- 冻结：{len(stable)}/{len(expected_tasks)} 题，{len({item['cwe'] for item in stable})} 个 CWE",
        f"- 剔除：{len(unstable)}/{len(expected_tasks)} 题",
        f"- 独立观察：{len(results)} 次",
        "",
        "| Task | CWE | repeat 1/2/3 | 决定 |",
        "|---|---|---|---|",
    ]
    for task_id, cwe, item_states, decision in rows:
        lines.append(f"| {task_id} | {cwe} | {' / '.join(item_states)} | {decision} |")
    lines.extend(
        [
            "",
            "该冻结仍属于 oracle 构建阶段，不能作为方法效果结果。下一关要求定向漏洞",
            "变异体在保持功能通过的同时被安全 oracle 命中（F+S-），之后再构建",
            "visible/hidden 行为族并接受独立语义审查。",
            "",
        ]
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))


if __name__ == "__main__":
    main()
