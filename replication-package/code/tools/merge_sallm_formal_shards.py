#!/usr/bin/env python3
"""Merge per-task SALLM formal shards into one validated run directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sectdd.sallm_formal_orchestrator import aggregate_trajectories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("shard_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    shard_root = args.shard_root.expanduser().resolve()
    shard_root.relative_to(ROOT)
    output = args.output.expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError(output)
    status = json.loads((shard_root / "shard_status.json").read_text())
    if not status["complete"]:
        raise RuntimeError("Shard run is incomplete")
    shard_dirs = sorted(
        path.parent
        for path in (shard_root / "shards").glob("*/run_manifest.json")
    )
    if len(shard_dirs) != status["task_count"]:
        raise RuntimeError("Shard count mismatch")
    manifests = [
        json.loads((path / "run_manifest.json").read_text())
        for path in shard_dirs
    ]
    first = manifests[0]
    invariant_keys = (
        "model",
        "methods",
        "seeds",
        "config",
        "visible_projection",
        "hidden_projection",
        "oracle_set_id",
        "canonical_oracle_manifest_sha256",
        "input_sha256",
        "model_freeze",
        "tokenizer",
    )
    for manifest in manifests[1:]:
        for key in invariant_keys:
            if manifest[key] != first[key]:
                raise RuntimeError(f"Shard invariant mismatch: {key}")
    config = json.loads((ROOT / first["config"]).read_text())
    by_task = {manifest["tasks"][0]: path for manifest, path in zip(manifests, shard_dirs)}
    if set(by_task) != set(config["tasks"]):
        raise RuntimeError("Shard task grid mismatch")

    output.mkdir(parents=True)
    trajectories = []
    for task in config["tasks"]:
        shard = by_task[task]
        for method in first["methods"]:
            source = shard / "trajectories" / method / task
            destination = output / "trajectories" / method / task
            shutil.copytree(source, destination)
            for path in sorted(destination.glob("seed_*/trajectory.json")):
                trajectories.append(json.loads(path.read_text()))
    manifest = {
        **first,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tasks": config["tasks"],
        "trajectory_count": len(trajectories),
        "source_shards": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "run_manifest_sha256": sha256(path / "run_manifest.json"),
            }
            for path in shard_dirs
        ],
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(aggregate_trajectories(trajectories), indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Merged {len(shard_dirs)} shards and {len(trajectories)} "
        f"trajectories into {output.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
