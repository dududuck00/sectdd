#!/usr/bin/env python3
"""Verify the frozen SALLM partitioned oracle v3 and its evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "benchmarks/manifests/sallm-partitioned-oracle-v3-freeze.json"
)


def verify(record: dict) -> None:
    path = ROOT / record["path"]
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if len(content) != record["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for record in manifest["inputs"].values():
        verify(record)
    for task, partitions in manifest["validation"]["task_audit"].items():
        for partition, modes in partitions.items():
            for mode, result in modes.items():
                if not result["stable"] or not result["passed_gate"]:
                    raise RuntimeError(
                        f"Failed gate: {task} {partition} {mode}"
                    )
                for observation in result["observations"]:
                    verify(observation["results"])
    for partition in manifest["validation"]["runs"].values():
        for records in partition.values():
            for record in records:
                verify(record)
    if manifest["validation"]["behavior_family_overlap_count"] != 0:
        raise RuntimeError("Visible/hidden behavior families overlap")
    if not manifest["validation"]["all_machine_gates_passed"]:
        raise RuntimeError("Machine gates are not marked passed")
    print(
        json.dumps(
            {
                "status": "verified",
                "freeze_id": manifest["freeze_id"],
                "task_count": manifest["scope"]["task_count"],
                "case_count": manifest["scope"]["case_count"],
                "repeat_count": manifest["validation"]["repeat_count"],
                "behavior_family_overlap_count": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
