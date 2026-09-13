#!/usr/bin/env python3
"""Run one resumable CodeGuard+ trajectory shard per task."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/run_codeguardplus_preflight.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-model", required=True)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--visible", type=Path, required=True)
    parser.add_argument("--hidden", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def slug(task: str) -> str:
    return task.replace("/", "__")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise ValueError("--max-workers must be positive")
    output = args.output_root.resolve()
    output.relative_to(ROOT)
    if output.exists() and not args.resume:
        raise FileExistsError(output)
    config_path, visible_path, hidden_path = args.config.resolve(), args.visible.resolve(), args.hidden.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=args.resume)
    logs = output / "logs"
    logs.mkdir(exist_ok=args.resume)
    expected_per_task = len(config["methods"]) * len(config["generation_seeds"])
    input_hashes = {"config": sha256(config_path), "visible_projection": sha256(visible_path), "hidden_projection": sha256(hidden_path)}

    def run_task(task: str) -> tuple[str, Path, bool]:
        destination = output / "shards" / slug(task)
        manifest_path = destination / "run_manifest.json"
        if args.resume and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (manifest.get("model") == args.served_model and manifest.get("provider", "local") == args.provider and manifest.get("tasks") == [task] and manifest.get("methods") == list(config["methods"]) and manifest.get("seeds") == config["generation_seeds"] and manifest.get("trajectory_count") == expected_per_task and manifest.get("input_sha256") == input_hashes):
                return task, destination, True
        command = [
            sys.executable, str(RUNNER), "--served-model", args.served_model,
            "--api-base", args.api_base, "--provider", args.provider,
            "--api-key-env", args.api_key_env, "--tokenizer", str(args.tokenizer),
            "--config", str(config_path), "--visible", str(visible_path),
            "--hidden", str(hidden_path), "--output", str(destination),
            "--task", task, "--resume",
        ]
        log_path = logs / f"{slug(task)}.log"
        with log_path.open("a" if args.resume else "w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
        return task, destination, False

    failures = []
    completed = resumed = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(run_task, task): task for task in config["tasks"]}
        for future in as_completed(futures):
            task = futures[future]
            try:
                _, destination, skipped = future.result()
            except Exception as exc:
                failures.append((task, repr(exc)))
                print(f"FAILED {task}: {exc}", flush=True)
            else:
                completed += 1
                resumed += int(skipped)
                print(f"[{completed}/{len(config['tasks'])}] {'resumed' if skipped else 'completed'} {task}: {destination.relative_to(ROOT)}", flush=True)
    status = {"schema_version": 1, "served_model": args.served_model, "provider": args.provider, "task_count": len(config["tasks"]), "completed_task_count": completed, "resumed_task_count": resumed, "failed": failures, "complete": not failures and completed == len(config["tasks"])}
    (output / "shard_status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
