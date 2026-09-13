#!/usr/bin/env python3
"""Run one partitioned SALLM formal shard per task in parallel."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/run_sallm_formal.py"
DEFAULT_CONFIG = ROOT / "configs/experiments/sallm_partitioned_main_v1.json"
DEFAULT_VISIBLE = ROOT / "configs/oracles/sallm_partitioned_oracle_v3_visible.json"
DEFAULT_HIDDEN = ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-model", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--visible-projection", type=Path, default=DEFAULT_VISIBLE)
    parser.add_argument("--hidden-projection", type=Path, default=DEFAULT_HIDDEN)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def slug(task: str) -> str:
    return task.removesuffix(".py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    output = args.output_root.expanduser().resolve()
    output.relative_to(ROOT)
    if output.exists() and not args.resume:
        raise FileExistsError(output)
    if args.max_workers < 1:
        raise ValueError("--max-workers must be positive")
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    output.mkdir(parents=True, exist_ok=args.resume)
    logs = output / "logs"
    logs.mkdir(exist_ok=args.resume)

    def run_task(task: str) -> tuple[str, Path]:
        destination = output / "shards" / slug(task)
        log_path = logs / f"{slug(task)}.log"
        manifest_path = destination / "run_manifest.json"
        if args.resume and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = len(config["methods"]) * len(config["generation_seeds"])
            expected_hashes = {
                "config": sha256(config_path),
                "visible_projection": sha256(args.visible_projection.resolve()),
                "hidden_projection": sha256(args.hidden_projection.resolve()),
            }
            if (manifest.get("model") == args.served_model and
                    manifest.get("tasks") == [task] and
                    manifest.get("trajectory_count") == expected and
                    manifest.get("provider", "local") == args.provider and
                    manifest.get("methods") == list(config["methods"]) and
                    manifest.get("seeds") == config["generation_seeds"] and
                    manifest.get("input_sha256") == expected_hashes):
                return task, destination
        command = [
            sys.executable,
            str(RUNNER),
            "--served-model",
            args.served_model,
            "--api-base",
            args.api_base,
            "--provider",
            args.provider,
            "--api-key-env",
            args.api_key_env,
            "--tokenizer",
            str(args.tokenizer),
            "--config",
            str(config_path),
            "--visible-projection",
            str(args.visible_projection.resolve()),
            "--hidden-projection",
            str(args.hidden_projection.resolve()),
            "--output",
            str(destination),
            "--task",
            task,
        ]
        if args.resume:
            command.append("--resume")
        with log_path.open("a" if args.resume else "w", encoding="utf-8") as log:
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        return task, destination

    failures = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(run_task, task): task for task in config["tasks"]
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                _, destination = future.result()
            except Exception as exc:
                failures.append((task, repr(exc)))
                print(f"FAILED {task}: {exc}", flush=True)
            else:
                completed += 1
                print(
                    f"[{completed}/{len(config['tasks'])}] completed {task}: "
                    f"{destination.relative_to(ROOT)}",
                    flush=True,
                )
    status = {
        "schema_version": 1,
        "served_model": args.served_model,
        "task_count": len(config["tasks"]),
        "completed_task_count": completed,
        "failed": failures,
        "complete": not failures and completed == len(config["tasks"]),
    }
    (output / "shard_status.json").write_text(
        json.dumps(status, indent=2) + "\n", encoding="utf-8"
    )
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
