#!/usr/bin/env python3
"""Run one frozen formal-experiment shard per task with bounded concurrency."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "tools" / "run_formal_pilot.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-model", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--visible-projection", required=True, type=Path)
    parser.add_argument("--hidden-projection", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    output_root = args.output_root.resolve()
    output_root.relative_to(PROJECT_ROOT)
    if output_root.exists() and not args.resume:
        raise FileExistsError(f"{output_root} already exists")
    config = json.loads(args.config.read_text())
    tasks = args.tasks or config["tasks"]
    if any(task not in config["tasks"] for task in tasks):
        raise ValueError("Requested task absent from frozen config")
    output_root.mkdir(parents=True, exist_ok=args.resume)
    logs = output_root / "logs"
    logs.mkdir(exist_ok=args.resume)
    pending = list(tasks)
    running: dict[str, tuple[subprocess.Popen, object]] = {}
    completed = 0
    while pending or running:
        while pending and len(running) < args.max_workers:
            task = pending.pop(0)
            destination = output_root / "shards" / task
            manifest_path = destination / "run_manifest.json"
            if args.resume and manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                expected_hashes = {
                    "config": sha256(args.config.resolve()),
                    "visible_projection": sha256(args.visible_projection.resolve()),
                    "hidden_projection": sha256(args.hidden_projection.resolve()),
                }
                expected = len(config["methods"]) * len(config["generation_seeds"])
                if (
                    manifest.get("model") == args.served_model
                    and manifest.get("provider", "local") == args.provider
                    and manifest.get("tasks") == [task]
                    and manifest.get("methods") == list(config["methods"])
                    and manifest.get("seeds") == config["generation_seeds"]
                    and manifest.get("trajectory_count") == expected
                    and manifest.get("input_sha256") == expected_hashes
                ):
                    completed += 1
                    print(
                        f"resumed {task} ({completed}/{len(tasks)})", flush=True
                    )
                    continue
            log_handle = (logs / f"{task}.log").open(
                "a" if args.resume else "w"
            )
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
                str(args.tokenizer.resolve()),
                "--config",
                str(args.config.resolve()),
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
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            running[task] = (process, log_handle)
            print(f"started {task} pid={process.pid}", flush=True)
        finished = []
        for task, (process, log_handle) in running.items():
            return_code = process.poll()
            if return_code is None:
                continue
            log_handle.close()
            if return_code != 0:
                for other, (other_process, other_log) in running.items():
                    if other != task and other_process.poll() is None:
                        other_process.terminate()
                        other_log.close()
                raise RuntimeError(
                    f"{task} failed with code {return_code}; "
                    f"see {logs / f'{task}.log'}"
                )
            completed += 1
            print(
                f"completed {task} ({completed}/{len(tasks)})", flush=True
            )
            finished.append(task)
        for task in finished:
            del running[task]
        if running and not finished:
            try:
                next(iter(running.values()))[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


if __name__ == "__main__":
    main()
