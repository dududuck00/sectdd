#!/usr/bin/env python3
"""Prepare a recoverable rerun for the CodeGuard+ functional-marker defect."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/paper-expansion-full-v1/codeguardplus"
QUARANTINE = (
    ROOT
    / "artifacts/paper-expansion-full-v1/quarantine"
    / "codeguardplus-functional-marker-v1"
)
MANIFEST = (
    ROOT
    / "benchmarks/manifests"
    / "codeguardplus-paper-expansion-functional-marker-correction-v1.json"
)
RESULT_FREEZE = (
    ROOT / "benchmarks/manifests/paper-expansion-full-v1-results-freeze.json"
)
MODELS = (
    "qwen25-coder-7b",
    "qwen25-coder-14b",
    "qwen36-27b",
    "deepseek-v4-flash",
)
TASKS = (
    "cwe-022/0-py",
    "cwe-079/1-py",
    "cwe-117/0-py",
    "cwe-312/0-py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker_summary(result: dict[str, Any], marker: str) -> dict[str, Any]:
    aliases = {"functional", "functionality"} if marker == "functional" else {marker}
    cases = [case for case in result["cases"] if case["marker"] in aliases]
    passed = sum(bool(case["passed"]) for case in cases)
    return {
        "count": len(cases),
        "passed": passed,
        "fraction": passed / len(cases) if cases else None,
        "all_passed": bool(cases) and passed == len(cases),
    }


def safe_score(secure: bool, functional_fraction: float | None) -> float:
    if not secure or functional_fraction is None:
        return 0.0
    # Same SAFE@1 transform used by the trajectory orchestrators.
    return (math.exp(functional_fraction) - 1.0) / (math.e - 1.0)


def normalize_trajectory(path: Path) -> None:
    item = json.loads(path.read_text(encoding="utf-8"))
    hidden = item["final_hidden"]["raw"]
    functional = marker_summary(hidden, "functional")
    security = marker_summary(hidden, "security")
    item["final_hidden"]["functional"] = functional
    item["final_hidden"]["security"] = security
    item["final_hidden"]["joint_pass"] = (
        functional["all_passed"] and security["all_passed"]
    )
    item["final_hidden"]["safe"] = safe_score(
        security["all_passed"], functional["fraction"]
    )
    path.write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")


def move_required(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def main() -> None:
    if MANIFEST.exists():
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if payload.get("prepared"):
            print("Resume: CodeGuard+ functional-marker correction already prepared.")
            print(MANIFEST.relative_to(ROOT))
            return
        raise RuntimeError(f"Incomplete correction manifest exists: {MANIFEST}")
    if not RESULT_FREEZE.is_file():
        raise FileNotFoundError(RESULT_FREEZE)
    old_freeze_hash = sha256(RESULT_FREEZE)
    moved_b2_trajectories = 0
    normalized_trajectories = 0
    records = []
    for model in MODELS:
        merged = RUN_ROOT / model
        merged_destination = QUARANTINE / "merged" / model
        move_required(merged, merged_destination)
        shard_root = RUN_ROOT / f"{model}-shards"
        for task in TASKS:
            slug = task.replace("/", "__")
            shard = shard_root / "shards" / slug
            b2 = shard / "trajectories" / "B2" / slug
            b2_destination = (
                QUARANTINE / "shards" / model / slug / "trajectories" / "B2" / slug
            )
            moved_b2_trajectories += len(list(b2.glob("seed_*/trajectory.json")))
            move_required(b2, b2_destination)
            metadata = QUARANTINE / "shards" / model / slug / "metadata"
            for name in ("run_manifest.json", "summary.json"):
                source = shard / name
                if source.exists():
                    move_required(source, metadata / name)
            for path in sorted(shard.glob("trajectories/*/*/seed_*/trajectory.json")):
                normalize_trajectory(path)
                normalized_trajectories += 1
        records.append(
            {
                "model": model,
                "merged_output_quarantined_at": merged_destination.relative_to(ROOT).as_posix(),
                "shard_root_to_resume": shard_root.relative_to(ROOT).as_posix(),
            }
        )
    if moved_b2_trajectories != 80:
        raise RuntimeError(f"Expected 80 B2 trajectories, moved {moved_b2_trajectories}")
    if normalized_trajectories != 560:
        raise RuntimeError(
            f"Expected 560 non-B2 trajectories, normalized {normalized_trajectories}"
        )
    payload = {
        "schema_version": 1,
        "correction_id": "codeguardplus-paper-expansion-functional-marker-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "prepared": True,
        "complete": False,
        "formal_results_use": False,
        "defect": {
            "oracle_marker": "functional",
            "orchestrator_expected_marker": "functionality",
            "effects": [
                "B2 omitted the visible functional case from its initial prompt",
                "all CodeGuard+ hidden functional summaries were empty and false",
            ],
        },
        "repair_policy": {
            "rerun": "B2 only for every CodeGuard+ task/model/slot",
            "recompute": "derived hidden functional/security/joint/SAFE summaries for other methods from immutable raw case outcomes",
            "old_outputs": "recoverably quarantined",
        },
        "moved_b2_trajectory_count": moved_b2_trajectories,
        "normalized_non_b2_trajectory_count": normalized_trajectories,
        "old_results_freeze_sha256": old_freeze_hash,
        "models": records,
        "required_post_steps": [
            "rerun four CodeGuard+ model matrices with resume",
            "rerun paper-expansion-full-v1 analysis",
            "rerun paper-evidence-v4 synthesis",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "moved_b2_trajectories": moved_b2_trajectories,
                "normalized_non_b2_trajectories": normalized_trajectories,
                "prepared": True,
                "formal_results_use": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
