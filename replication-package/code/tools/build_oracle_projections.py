#!/usr/bin/env python3
"""Build partition-specific manifests so visible execution never loads hidden metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from oracle_manifest import load_oracle_manifest, manifest_dependency_digest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=(
            PROJECT_ROOT
            / "oracles"
            / "cweval_py"
            / "paper_candidate_v1"
            / "manifest.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "configs" / "oracles",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_project_path(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT))


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    manifest, manifest_sources = load_oracle_manifest(manifest_path)
    base = manifest_path.parent
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.relative_to(PROJECT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    for partition in ("visible", "hidden"):
        output_path = (
            output_dir
            / f"{manifest['oracle_set_id']}_{partition}.json"
        )
        if output_path.exists() and not args.force:
            raise FileExistsError(output_path)
        tasks = {}
        for task, task_data in manifest["tasks"].items():
            oracle_path = (base / task_data["oracles"][partition]).resolve()
            oracle_path.relative_to(PROJECT_ROOT)
            cases = [
                case
                for case in task_data["cases"]
                if case["partition"] == partition
            ]
            tasks[task] = {
                "cwe": task_data["cwe"],
                "callable": task_data["callable"],
                "contract": task_data["contract"],
                "oracle_file": relative_project_path(oracle_path),
                "oracle_sha256": sha256_file(oracle_path),
                "cases": cases,
            }
        other_partition = "hidden" if partition == "visible" else "visible"
        projection = {
            "schema_version": 1,
            "oracle_set_id": manifest["oracle_set_id"],
            "oracle_status": manifest["status"],
            "canonical_manifest": relative_project_path(manifest_path),
            "canonical_manifest_sha256": manifest_dependency_digest(
                manifest_sources
            ),
            "canonical_manifest_sources_sha256": manifest_sources,
            "partition": partition,
            "masked_project_path": relative_project_path(
                base / other_partition
            ),
            "tasks": tasks,
        }
        output_path.write_text(
            json.dumps(projection, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
