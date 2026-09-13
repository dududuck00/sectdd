#!/usr/bin/env python3
"""Run a small B0-B5/SecTDD method matrix against a local vLLM server."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORT))

from sectdd.orchestrator import (
    PROJECT_ROOT,
    aggregate_trajectories,
    configure_local_network,
    run_trajectory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-model", default="qwen25-coder-7b")
    parser.add_argument("--api-base", default="http://127.0.0.1:18080/v1")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "experiments"
        / "cweval_methods_pilot.json",
    )
    parser.add_argument(
        "--visible-split",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "splits"
        / "cweval_python25_pilot_visible.json",
    )
    parser.add_argument(
        "--hidden-split",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "splits"
        / "cweval_python25_pilot_hidden.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", action="append", dest="tasks", required=True)
    parser.add_argument("--method", action="append", dest="methods")
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    return parser.parse_args()


def check_server(api_base: str, served_model: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/models",
        headers={"Authorization": "Bearer local-sectdd"},
    )
    with opener.open(request, timeout=10) as response:
        models = json.load(response)
    available = {item["id"] for item in models.get("data", [])}
    if served_model not in available:
        raise RuntimeError(
            f"Model {served_model!r} not available; server has {sorted(available)}"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; choose a new path to preserve provenance"
        )
    config_path = args.config.resolve()
    visible_path = args.visible_split.resolve()
    hidden_path = args.hidden_split.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    visible_split = json.loads(visible_path.read_text(encoding="utf-8"))
    methods = args.methods or list(config["methods"])
    unknown = sorted(set(methods) - set(config["methods"]))
    if unknown:
        raise ValueError(f"Unknown methods: {unknown}")
    missing_tasks = sorted(set(args.tasks) - set(visible_split["tasks"]))
    if missing_tasks:
        raise ValueError(f"Tasks absent from visible split: {missing_tasks}")
    seeds = args.seeds or [11]

    configure_local_network()
    check_server(args.api_base, args.served_model)
    output.mkdir(parents=True)
    trajectories = []
    total = len(args.tasks) * len(methods) * len(seeds)
    completed = 0
    for task in args.tasks:
        for method_id in methods:
            for seed in seeds:
                trajectory_dir = (
                    output / "trajectories" / method_id / task / f"seed_{seed}"
                )
                trajectory = run_trajectory(
                    task=task,
                    generation_seed=seed,
                    method_id=method_id,
                    method=config["methods"][method_id],
                    config=config,
                    served_model=args.served_model,
                    api_base=args.api_base,
                    visible_split=visible_split,
                    visible_split_path=visible_path,
                    hidden_split_path=hidden_path,
                    trajectory_dir=trajectory_dir,
                )
                trajectories.append(trajectory)
                completed += 1
                joint = trajectory["final_hidden"]["joint_pass"]
                print(
                    f"[{completed}/{total}] {method_id} {task} seed={seed} "
                    f"calls={len(trajectory['rounds'])} hidden_joint={joint}",
                    flush=True,
                )

    run_manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "pilot_only": True,
        "model": args.served_model,
        "tasks": args.tasks,
        "methods": methods,
        "seeds": seeds,
        "config": str(config_path),
        "visible_split": str(visible_path),
        "hidden_split": str(hidden_path),
        "input_sha256": {
            "config": sha256_file(config_path),
            "visible_split": sha256_file(visible_path),
            "hidden_split": sha256_file(hidden_path),
        },
        "trajectory_count": len(trajectories),
    }
    (output / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8"
    )
    summary = aggregate_trajectories(trajectories)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Summary: {output / 'summary.json'}")


if __name__ == "__main__":
    main()
