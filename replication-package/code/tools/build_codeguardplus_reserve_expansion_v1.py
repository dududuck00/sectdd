#!/usr/bin/env python3
"""Freeze the contamination boundary and execution contract for reserve wave v1."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
CONFIG = ROOT / "configs/experiments/codeguardplus_reserve_expansion_v1.json"
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_expansion_v1.lock.json"
REPORT = ROOT / "docs/codeguardplus-reserve-expansion-v1.md"
MODEL_PATH = Path("<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def task_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("task_id"), str):
            result.add(value["task_id"])
        for child in value.values():
            result.update(task_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(task_ids(child))
    return result


def exposure_audit(reserve: set[str]) -> dict[str, Any]:
    dry_prompt: dict[str, set[str]] = {}
    model: dict[str, set[str]] = {}
    oracle: dict[str, set[str]] = {}
    for manifest_path in sorted((ROOT / "artifacts").glob("codeguardplus*/**/run_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        selected = set(manifest.get("selection", [])) | set(manifest.get("task_ids", []))
        overlap = selected & reserve
        if not overlap:
            continue
        rel = manifest_path.relative_to(ROOT).as_posix()
        if manifest.get("status") == "dry_run":
            target = dry_prompt
        elif manifest.get("provider") or manifest.get("generator"):
            target = model
        else:
            target = oracle
        for item in overlap:
            target.setdefault(item, set()).add(rel)

    # A result file is stronger evidence than a run-manifest declaration.
    for path in sorted((ROOT / "artifacts").glob("codeguardplus*/**/*")):
        if not path.is_file() or path.name not in {
            "candidates.jsonl", "mutants.jsonl", "results.jsonl", "trajectories.jsonl"
        }:
            continue
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            continue
        overlap = set().union(*(task_ids(row) for row in rows)) & reserve if rows else set()
        target = model if path.name in {"candidates.jsonl", "mutants.jsonl", "trajectories.jsonl"} else oracle
        for item in overlap:
            target.setdefault(item, set()).add(path.relative_to(ROOT).as_posix())

    def render(value: dict[str, set[str]]) -> dict[str, list[str]]:
        return {key: sorted(paths) for key, paths in sorted(value.items())}

    return {
        "dry_run_prompt_only": render(dry_prompt),
        "model_generation": render(model),
        "oracle_execution": render(oracle),
        "dry_run_prompt_task_count": len(dry_prompt),
        "model_generation_task_count": len(model),
        "oracle_execution_task_count": len(oracle),
    }


def used_base_seeds() -> set[int]:
    values: set[int] = set()
    for path in ROOT.glob("artifacts/codeguardplus*/**/run_manifest.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("base_seed")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, int):
            values.add(value)
    return values


def main() -> None:
    for path in (PLAN, BENCHMARK, MODEL_PATH / "config.json"):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (CONFIG, LOCK, REPORT):
        if path.exists():
            raise FileExistsError(path)

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    reserve = plan["reserve_task_ids"]
    if len(reserve) != 32 or len(reserve) != len(set(reserve)):
        raise RuntimeError("Frozen reserve pool is not the expected 32 unique tasks")
    plan_rows = {item["task_id"]: item for item in plan["tasks"]}
    if any(plan_rows[item]["selection_state"] != "reserve" for item in reserve):
        raise RuntimeError("Reserve order and task labels disagree")
    audit = exposure_audit(set(reserve))
    if audit["model_generation_task_count"] or audit["oracle_execution_task_count"]:
        raise RuntimeError("Reserve pool already has model-generation or oracle-result exposure")

    seeds = {
        "safe_candidate_base_seed": 20260910,
        "vulnerability_mutant_base_seed": 20260920,
        "partitioned_oracle_base_seed": 20260930,
    }
    reused = sorted(set(seeds.values()) & used_base_seeds())
    if reused:
        raise RuntimeError(f"Expansion authoring seed reuse: {reused}")
    cwes = Counter(plan_rows[item]["cwe"] for item in reserve)
    paths = {
        "safe_generation": "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-safe",
        "safe_screen": "artifacts/codeguardplus-reserve-expansion-v1/qualification/safe-screen",
        "safe_selection": "benchmarks/manifests/codeguardplus-reserve-safe-selection-v1.json",
        "safe_repeats": "artifacts/codeguardplus-reserve-expansion-v1/qualification/safe-repeats3",
        "stable_safe": "benchmarks/manifests/codeguardplus-reserve-stable-safe-v1.json",
        "mutant_generation": "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-mutants",
        "mutant_screen": "artifacts/codeguardplus-reserve-expansion-v1/qualification/mutant-screen",
        "mutant_selection": "benchmarks/manifests/codeguardplus-reserve-mutant-selection-v1.json",
        "mutant_repeats": "artifacts/codeguardplus-reserve-expansion-v1/qualification/mutant-repeats3",
        "oracle_pairs": "benchmarks/manifests/codeguardplus-reserve-oracle-pairs-v1.json",
    }
    config = {
        "schema_version": 1,
        "experiment_id": "codeguardplus-reserve-expansion-v1",
        "study_phase": "oracle_construction_development",
        "development_only": True,
        "formal_results_use": False,
        "selection_state": "reserve",
        "selection_rule": "include the entire pre-ranked reserve pool in its original frozen order",
        "tasks": reserve,
        "cwe_counts": dict(sorted(cwes.items())),
        "authoring_model": {
            "served_model": "qwen36-27b",
            "checkpoint": str(MODEL_PATH),
            "checkpoint_config_sha256": sha(MODEL_PATH / "config.json"),
            "api_base": "http://127.0.0.1:18083/v1",
            "thinking": "disabled",
        },
        "generation": {
            "candidates_per_task": 3,
            "mutants_per_task": 3,
            "partitioned_oracle_attempts": 3,
            "temperature": 0.4,
            "top_p": 0.95,
            "max_tokens": 8192,
            **seeds,
        },
        "qualification": {
            "screen_repeats": 1,
            "stability_repeats": 3,
            "safe_gate": "F+S+ in all three independent repetitions",
            "mutant_gate": "F+S- in all three independent repetitions",
            "partition_gate": "disjoint visible/hidden behavior families plus semantic review",
            "preflight_gate": "fresh-seed multi-model G8 after semantic freeze",
        },
        "paths": paths,
    }
    write(CONFIG, config)
    lock = {
        "schema_version": 1,
        "lock_id": "codeguardplus-reserve-expansion-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_wave_generation": True,
        "selection_reads_prior_g8_outcomes": False,
        "entire_reserve_selected": True,
        "reserve_exhausted_after_wave": True,
        "task_count": len(reserve),
        "cwe_count": len(cwes),
        "task_order": reserve,
        "authoring_seeds": seeds,
        "prior_exposure_audit": audit,
        "inputs": {"qualification_plan": record(PLAN), "benchmark_manifest": record(BENCHMARK)},
        "frozen_config": record(CONFIG),
    }
    write(LOCK, lock)

    rows = [
        "# CodeGuard+ reserve expansion wave v1",
        "",
        "本 wave 一次性纳入原资格化计划中预先排序的全部 32 道 reserve 题。任务成员与顺序不读取上一轮 G8 成败，避免结果驱动挑题。",
        "",
        f"- 任务：32，CWE：{len(cwes)}",
        "- 模型生成暴露交集：0；oracle 结果暴露交集：0",
        f"- 仅旧 dry-run 本地提示物化：{audit['dry_run_prompt_task_count']} 题（未调用模型、未执行 oracle）",
        "- 安全候选、漏洞变异体与 partitioned oracle 均固定为每题 3 个候选/尝试",
        "- 全阶段仅用于 oracle 建设，不能计入正式方法效果",
        "",
        "## CWE 分层",
        "",
        "| CWE | Tasks |",
        "|---|---:|",
    ]
    rows.extend(f"| {cwe} | {count} |" for cwe, count in sorted(cwes.items()))
    rows.extend([
        "",
        "后续门槛固定为：安全实现三次 F+S+；漏洞变异体三次 F+S-；visible/hidden 行为族互不重叠并通过语义审查；最后才使用全新 seeds 做多模型 G8 preflight。",
        "",
    ])
    REPORT.write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps({"tasks": len(reserve), "cwes": len(cwes), "audit": audit, "config": record(CONFIG), "lock": record(LOCK)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
