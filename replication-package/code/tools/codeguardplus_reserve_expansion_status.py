#!/usr/bin/env python3
"""Report the first incomplete stage of CodeGuard+ reserve expansion v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "configs/experiments/codeguardplus_reserve_expansion_v1.lock.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summary_complete(path: Path) -> tuple[bool, dict[str, Any] | None]:
    if not path.is_file():
        return False, None
    value = load(path)
    return bool(value.get("complete")), value


def main() -> None:
    if not LOCK.is_file():
        print(json.dumps({"built": False, "next_action": "build"}, indent=2))
        return
    lock = load(LOCK)
    config_path = ROOT / lock["frozen_config"]["path"]
    if sha(config_path) != lock["frozen_config"]["sha256"]:
        raise RuntimeError("Frozen reserve expansion config drift")

    stages: list[tuple[str, Path, str]] = [
        ("secure_generation", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-safe-merged/summary.json", "freeze-generation-recovery"),
        ("safe_screen", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/qualification/safe-screen/summary.json", "safe-screen"),
        ("safe_selection", ROOT / "benchmarks/manifests/codeguardplus-reserve-safe-selection-v1.json", "safe-select"),
        ("safe_repeats", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/qualification/safe-repeats3/summary.json", "safe-repeat"),
        ("stable_safe_freeze", ROOT / "benchmarks/manifests/codeguardplus-reserve-stable-safe-v1.json", "safe-freeze"),
        ("mutant_generation", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/generation/qwen36-27b-mutants/summary.json", "mutant-generate"),
        ("mutant_screen", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/qualification/mutant-screen/summary.json", "mutant-screen"),
        ("mutant_selection", ROOT / "benchmarks/manifests/codeguardplus-reserve-mutant-selection-v1.json", "mutant-select"),
        ("mutant_repeats", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/qualification/mutant-repeats3/summary.json", "mutant-repeat"),
        ("pair_freeze", ROOT / "benchmarks/manifests/codeguardplus-reserve-oracle-pairs-v1.json", "pair-freeze"),
        ("partition_generation", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/partitioned-generation/qwen36-27b/summary.json", "partition-generate"),
        ("partition_qualification", ROOT / "artifacts/codeguardplus-reserve-expansion-v1/partitioned-qualification/summary.json", "partition-qualify"),
    ]
    rows = []
    next_action = "semantic-prepare"
    for name, path, action in stages:
        if path.name == "summary.json":
            complete, value = summary_complete(path)
        else:
            complete, value = path.is_file(), load(path) if path.is_file() else None
        rows.append({
            "stage": name,
            "complete": complete,
            "path": path.relative_to(ROOT).as_posix(),
            "counts": value.get("counts", value) if value else None,
        })
        if not complete and next_action == "semantic-prepare":
            next_action = action
    print(json.dumps({
        "built": True,
        "lock_valid": True,
        "task_count": lock["task_count"],
        "cwe_count": lock["cwe_count"],
        "stages": rows,
        "next_action": next_action,
        "formal_results_use": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
