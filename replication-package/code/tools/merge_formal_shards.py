#!/usr/bin/env python3
"""Merge validated per-task formal-experiment shards into one run."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sectdd.formal_orchestrator import aggregate_trajectories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("shard_roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.relative_to(PROJECT_ROOT)
    if output.exists():
        raise FileExistsError(f"{output} already exists")
    config_path = None
    manifests = []
    for raw_root in args.shard_roots:
        shard_root = raw_root.resolve()
        for path in sorted(
            (shard_root / "shards").glob("*/run_manifest.json")
        ):
            manifest = json.loads(path.read_text())
            manifests.append((path.parent.name, path, manifest))
            config_path = Path(manifest["config"])
    if not manifests or config_path is None:
        raise AssertionError("No completed shards found")
    config = json.loads(config_path.read_text())
    expected_tasks = config["tasks"]
    observed_tasks = [task for task, _, _ in manifests]
    if len(observed_tasks) != len(set(observed_tasks)):
        raise AssertionError(f"Duplicate task shards: {observed_tasks}")
    if sorted(observed_tasks) != sorted(expected_tasks):
        raise AssertionError(
            f"Incomplete shards: {observed_tasks} != {expected_tasks}"
        )
    reference = manifests[0][2]
    stable_keys = (
        "model",
        "provider",
        "provider_seed_supported",
        "remote_seed_policy",
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
        "shared_initial_candidate_policies",
    )
    for task, _, manifest in manifests:
        if manifest["tasks"] != [task]:
            raise AssertionError(f"{task}: shard task mismatch")
        for key in stable_keys:
            if manifest[key] != reference[key]:
                raise AssertionError(f"{task}: manifest {key} mismatch")

    output.mkdir(parents=True)
    for _, path, _ in manifests:
        shutil.copytree(
            path.parent / "trajectories",
            output / "trajectories",
            dirs_exist_ok=True,
        )
    paths = sorted(
        output.glob("trajectories/*/*/seed_*/trajectory.json")
    )
    trajectories = [json.loads(path.read_text()) for path in paths]
    expected_count = (
        len(expected_tasks)
        * len(reference["methods"])
        * len(reference["seeds"])
    )
    if len(trajectories) != expected_count:
        raise AssertionError(
            f"Expected {expected_count} trajectories, got {len(trajectories)}"
        )
    manifest = dict(reference)
    manifest["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["tasks"] = expected_tasks
    manifest["trajectory_count"] = len(trajectories)
    manifest["merged_from"] = [
        str(path) for _, path, _ in manifests
    ]
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    (output / "summary.json").write_text(
        json.dumps(aggregate_trajectories(trajectories), indent=2) + "\n"
    )
    print(f"Merged {len(manifests)} shards and {len(trajectories)} trajectories")


if __name__ == "__main__":
    main()
