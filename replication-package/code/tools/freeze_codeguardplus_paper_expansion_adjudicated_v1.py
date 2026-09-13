#!/usr/bin/env python3
"""Freeze CodeGuard+ paper-expansion tasks under a blinded 2/3 policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "artifacts/paper-expansion-v1/codeguardplus/semantic-review/report.json"
DISPUTE = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-dispute-freeze.json"
DISPUTE_REVIEWS = ROOT / "artifacts/paper-expansion-v1/codeguardplus/semantic-dispute-review/reviews/qwen3-32b"
SOURCE_VISIBLE = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_visible.json"
SOURCE_HIDDEN = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_hidden.json"
SOURCE_ORACLE = ROOT / "oracles/codeguardplus_paper_expansion_v1/manifest.json"
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
PROMPTS = ROOT / "configs/prompts/codeguardplus_paper_expansion_full_v1"
OUTPUT_VISIBLE = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json"
OUTPUT_HIDDEN = ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json"
CANONICAL = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-machine-oracle.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-machine-freeze.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "size_bytes": path.stat().st_size}


def write_frozen(path: Path, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"CodeGuard+ adjudicated freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def main() -> None:
    for path in (PANEL, DISPUTE, SOURCE_VISIBLE, SOURCE_HIDDEN, SOURCE_ORACLE, BENCHMARK):
        if not path.is_file():
            raise FileNotFoundError(path)
    panel, dispute = load(PANEL), load(DISPUTE)
    visible, hidden, source_oracle = load(SOURCE_VISIBLE), load(SOURCE_HIDDEN), load(SOURCE_ORACLE)
    benchmark = {item["task_id"]: item for item in load(BENCHMARK)["tasks"]}
    disputed = dispute["qualified_task_ids"]
    expected_disputed = sorted(
        task for task, audit in panel["task_audit"].items()
        if set(audit["reviewer_verdicts"].values()) == {"accept", "reject"}
    )
    if disputed != expected_disputed or dispute["third_reviewer_packet_contains_prior_verdicts"] is not False:
        raise RuntimeError("Invalid CodeGuard+ semantic-dispute freeze")

    adjudication: dict[str, Any] = {}
    accepted: list[str] = []
    rejected: list[str] = []
    review_records: dict[str, Any] = {}
    for task, audit in panel["task_audit"].items():
        initial = audit["reviewer_verdicts"]
        if set(initial.values()) == {"accept"}:
            decision, policy, third = "accept", "initial_unanimous_accept", None
        elif task in disputed:
            review_path = DISPUTE_REVIEWS / f"{task.replace('/', '__')}.json"
            if not review_path.is_file():
                raise FileNotFoundError(review_path)
            third = load(review_path)["review"]["verdict"]
            review_records[task] = rec(review_path)
            accept_votes = sum(value == "accept" for value in initial.values()) + (third == "accept")
            decision = "accept" if accept_votes >= 2 else "reject"
            policy = "blinded_third_reviewer_two_of_three_majority"
        else:
            decision, policy, third = "reject", "initial_unanimous_reject", None
        (accepted if decision == "accept" else rejected).append(task)
        adjudication[task] = {
            "decision": decision,
            "policy": policy,
            "initial_verdicts": initial,
            "third_reviewer": "qwen3-32b" if third is not None else None,
            "third_verdict": third,
        }
    accepted_set = set(accepted)
    accepted = [task for task in visible["tasks"] if task in accepted_set]
    if len(accepted) != 4:
        raise RuntimeError(f"Expected four adjudicated CodeGuard+ tasks, got {len(accepted)}")
    if set(visible["tasks"]) != set(hidden["tasks"]) or set(source_oracle["tasks"]) != set(visible["tasks"]):
        raise RuntimeError("CodeGuard+ source oracle/projection mismatch")

    created = datetime.now(timezone.utc).isoformat()
    canonical = {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-paper-expansion-v1-semantic-machine",
        "benchmark": "codeguardplus",
        "created_at_utc": created,
        "tasks": accepted,
        "semantic_policy": "initial unanimous accept or blinded Qwen3-32B 2/3 majority accept",
        "method_or_g8_outcome_filter_applied": False,
        "independent_human_review_complete": False,
        "formal_results_use": False,
        "adjudication": adjudication,
    }
    if CANONICAL.exists():
        canonical["created_at_utc"] = load(CANONICAL)["created_at_utc"]
    write_frozen(CANONICAL, canonical)
    common = {
        "schema_version": 1,
        "oracle_set_id": canonical["oracle_set_id"],
        "canonical_manifest_sha256": sha(CANONICAL),
        "machine_semantic_review_complete": True,
        "independent_human_review_complete": False,
    }
    projections: dict[str, dict[str, Any]] = {"visible": {}, "hidden": {}}
    prompt_records: dict[str, Any] = {}
    for task in accepted:
        source = benchmark[task]["source"]
        pieces = []
        for key in ("file_context", "function_context"):
            path = ROOT / source[key]["path"]
            if sha(path) != source[key]["sha256"]:
                raise RuntimeError(f"CodeGuard+ prompt source drift: {path}")
            pieces.append(path.read_text(encoding="utf-8").rstrip())
        prompt_text = "\n\n".join(piece for piece in pieces if piece) + "\n"
        prompt_path = PROMPTS / f"{task.replace('/', '__')}.py"
        if prompt_path.exists() and prompt_path.read_text(encoding="utf-8") != prompt_text:
            raise RuntimeError(f"CodeGuard+ prompt drift: {prompt_path}")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")
        prompt_records[task] = rec(prompt_path)
        for partition, source_projection in (("visible", visible), ("hidden", hidden)):
            item = source_projection["tasks"][task]
            test = item["oracle_file"]
            cases = [
                {
                    "case_id": case["case_id"],
                    "marker": case["marker"],
                    "behavior_family": case["behavior_family"],
                    "description": case["behavior_family"],
                    "test_method": case.get("test_method", case.get("unittest_method")),
                }
                for case in item["cases"]
            ]
            if any(not case["test_method"] for case in cases):
                raise RuntimeError(f"CodeGuard+ test method missing: {task}/{partition}")
            projections[partition][task] = {
                "cwe": item["cwe"],
                "contract": source_oracle["tasks"][task]["contract"],
                "prompt_file": prompt_records[task]["path"],
                "prompt_sha256": prompt_records[task]["sha256"],
                "oracle_file": test["path"],
                "oracle_sha256": test["sha256"],
                "cases": cases,
            }
    write_frozen(OUTPUT_VISIBLE, {**common, "partition": "visible", "tasks": projections["visible"]})
    write_frozen(OUTPUT_HIDDEN, {**common, "partition": "hidden", "tasks": projections["hidden"]})
    freeze = {
        "schema_version": 1,
        "freeze_id": canonical["oracle_set_id"],
        "complete": True,
        "benchmark": "codeguardplus",
        "machine_semantic_review_complete": True,
        "independent_human_review_complete": False,
        "method_or_g8_outcome_filter_applied": False,
        "qualified_task_count": len(accepted),
        "qualified_tasks": accepted,
        "rejected_tasks": sorted(rejected),
        "formal_results_use": False,
        "inputs": {
            "source_oracle": rec(SOURCE_ORACLE),
            "source_visible": rec(SOURCE_VISIBLE),
            "source_hidden": rec(SOURCE_HIDDEN),
            "benchmark_manifest": rec(BENCHMARK),
            "initial_panel": rec(PANEL),
            "dispute_freeze": rec(DISPUTE),
            "third_reviews": review_records,
        },
        "outputs": {"canonical": rec(CANONICAL), "visible": rec(OUTPUT_VISIBLE), "hidden": rec(OUTPUT_HIDDEN), "prompts": prompt_records},
    }
    write_frozen(FREEZE, freeze)
    print(json.dumps({"benchmark": "codeguardplus", "qualified_task_count": len(accepted), "qualified_tasks": accepted, "complete": True}, indent=2))


if __name__ == "__main__":
    main()
