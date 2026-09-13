#!/usr/bin/env python3
"""Merge validated per-task CodeGuard+ shards into one model run."""

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

from sectdd.codeguardplus_formal_orchestrator import aggregate_trajectories


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shard_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    shard_root, output = args.shard_root.resolve(), args.output.resolve()
    shard_root.relative_to(ROOT); output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError(output)
    status = json.loads((shard_root / "shard_status.json").read_text(encoding="utf-8"))
    if not status["complete"]:
        raise RuntimeError("Shard run is incomplete")
    shard_dirs = sorted(path.parent for path in (shard_root / "shards").glob("*/run_manifest.json"))
    if len(shard_dirs) != status["task_count"]:
        raise RuntimeError("Shard count mismatch")
    manifests = [json.loads((path / "run_manifest.json").read_text(encoding="utf-8")) for path in shard_dirs]
    first = manifests[0]
    invariant = ("model", "provider", "methods", "seeds", "config", "visible_projection", "hidden_projection", "oracle_set_id", "canonical_oracle_manifest_sha256", "input_sha256", "model_freeze", "tokenizer")
    for manifest in manifests[1:]:
        for key in invariant:
            if manifest[key] != first[key]:
                raise RuntimeError(f"Shard invariant mismatch: {key}")
    config = json.loads((ROOT / first["config"]).read_text(encoding="utf-8"))
    by_task = {manifest["tasks"][0]: path for manifest, path in zip(manifests, shard_dirs)}
    if set(by_task) != set(config["tasks"]):
        raise RuntimeError("Shard task grid mismatch")
    output.mkdir(parents=True)
    trajectories = []
    for task in config["tasks"]:
        slug = task.replace("/", "__")
        for method in first["methods"]:
            source = by_task[task] / "trajectories" / method / slug
            destination = output / "trajectories" / method / slug
            shutil.copytree(source, destination)
            trajectories.extend(json.loads(path.read_text(encoding="utf-8")) for path in sorted(destination.glob("seed_*/trajectory.json")))
    trajectory_hashes = {path.relative_to(output).as_posix(): sha256(path) for path in sorted((output / "trajectories").glob("*/*/seed_*/trajectory.json"))}
    manifest = {**first, "created_at_utc": datetime.now(timezone.utc).isoformat(), "tasks": config["tasks"], "trajectory_count": len(trajectories), "trajectory_sha256": trajectory_hashes, "source_shards": [{"path": path.relative_to(ROOT).as_posix(), "run_manifest_sha256": sha256(path / "run_manifest.json")} for path in shard_dirs]}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(aggregate_trajectories(trajectories), indent=2) + "\n", encoding="utf-8")
    print(f"Merged {len(shard_dirs)} shards and {len(trajectories)} trajectories into {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
