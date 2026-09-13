#!/usr/bin/env python3
"""Verify every file recorded by the SALLM external main v1 lock."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "configs/experiments/sallm_partitioned_main_v1.lock.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    lock = json.loads(LOCK.read_text())
    for raw_path, expected in lock["input_sha256"].items():
        path = ROOT / raw_path
        if digest(path) != expected:
            raise RuntimeError(f"Locked input changed: {path}")
    for model, metadata in lock["models"].items():
        root = Path(metadata["checkpoint"])
        for name, expected in metadata["files_sha256"].items():
            if digest(root / name) != expected:
                raise RuntimeError(f"Locked model file changed: {model}/{name}")
    print(
        json.dumps(
            {
                "status": "verified",
                "lock_id": lock["lock_id"],
                **lock["experiment_shape"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
