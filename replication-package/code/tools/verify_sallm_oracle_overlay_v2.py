#!/usr/bin/env python3
"""Verify hashes and machine gates in the frozen SALLM overlay v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "benchmarks/manifests/sallm-oracle-overlay-v2-freeze.json"
)


def verify_record(record: dict[str, object]) -> None:
    path = ROOT / str(record["path"])
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != record["sha256"]:
        raise RuntimeError(f"Hash mismatch: {path}")
    if len(content) != record["size_bytes"]:
        raise RuntimeError(f"Size mismatch: {path}")


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    inputs = manifest["inputs"]
    for name in (
        "overlay",
        "parent_overlay",
        "benchmark_manifest",
        "executor",
        "mutation_manifest",
    ):
        verify_record(inputs[name])
    for record in inputs["safe_references"].values():
        verify_record(record)
    for record in inputs["test_overrides"].values():
        verify_record(record)
    for records in manifest["validation"]["runs"].values():
        for record in records:
            verify_record(record)
    for task_id, audit in manifest["validation"]["task_audit"].items():
        for mode, result in audit["modes"].items():
            if not result["stable"] or not result["passed_gate"]:
                raise RuntimeError(f"Failed gate: {task_id} {mode}")
            for observation in result["observations"]:
                result_path = ROOT / observation["run"] / "results.jsonl"
                if hashlib.sha256(result_path.read_bytes()).hexdigest() != (
                    observation["result_sha256"]
                ):
                    raise RuntimeError(f"Result hash mismatch: {result_path}")
    if not manifest["validation"]["all_machine_gates_passed"]:
        raise RuntimeError("Freeze manifest does not pass all machine gates")
    print(
        json.dumps(
            {
                "status": "verified",
                "freeze_id": manifest["freeze_id"],
                "qualified_task_count": manifest["validation"][
                    "qualified_task_count"
                ],
                "excluded_task_count": manifest["validation"][
                    "excluded_task_count"
                ],
                "repeat_count": manifest["validation"]["repeat_count"],
                "overlay_sha256": inputs["overlay"]["sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
