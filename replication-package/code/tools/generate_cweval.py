#!/usr/bin/env python3
"""Generate reproducible CWEval Python samples through a local API."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CWEVAL_ROOT = PROJECT_ROOT / "third_party" / "CWEval"
DEFAULT_TASKS = ("cwe_020_0", "cwe_078_0", "cwe_079_0")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-path", type=Path, required=True)
    parser.add_argument("--served-model", default="qwen25-coder-7b")
    parser.add_argument("--api-base", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--prompt", choices=("direct", "secure"), default="direct")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--all-python", action="store_true")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--seed", action="append", type=int, dest="seeds")
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-completion-tokens", type=int, default=2048)
    return parser.parse_args()


def check_server(api_base: str, served_model: str) -> None:
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/models",
        headers={"Authorization": "Bearer local-cweval"},
    )
    # Do not route a localhost model request through the cluster HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        payload = json.load(response)
    available = {item["id"] for item in payload.get("data", [])}
    if served_model not in available:
        raise RuntimeError(
            f"Model {served_model!r} is not served; API exposes {sorted(available)}"
        )


def main() -> None:
    args = parse_args()
    eval_path = args.eval_path.expanduser().resolve()
    if eval_path.exists():
        raise FileExistsError(
            f"{eval_path} already exists; use a new path to preserve provenance"
        )
    if args.samples < 1:
        raise ValueError("--samples must be positive")
    if args.num_workers < 1:
        raise ValueError("--num-workers must be positive")
    if args.all_python and args.tasks:
        raise ValueError("--all-python and --task cannot be used together")

    seeds = args.seeds or list(range(args.samples))
    if len(seeds) != len(set(seeds)):
        raise ValueError("Generation seeds must be unique")
    tasks = [] if args.all_python else (args.tasks or list(DEFAULT_TASKS))
    for variable in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(variable, "")
        entries = [item for item in current.split(",") if item]
        for local_host in ("127.0.0.1", "localhost"):
            if local_host not in entries:
                entries.append(local_host)
        os.environ[variable] = ",".join(entries)
    check_server(args.api_base, args.served_model)

    sys.path.insert(0, str(CWEVAL_ROOT))
    os.chdir(CWEVAL_ROOT)
    from cweval.ai import AIAPI
    from cweval.generate import Gener
    from cweval.ppt import make_prompt

    generator = Gener(
        eval_path=str(eval_path),
        model=f"openai/{args.served_model}",
        ppt=args.prompt,
        num_proc=1,
        langs=["py"],
        include_path=tasks,
        n=1,
        max_completion_tokens=args.max_completion_tokens,
        temperature=args.temperature,
        api_base=args.api_base,
        api_key="local-cweval",
    )
    expected = 25 if args.all_python else len(tasks)
    actual = len(generator.cases)
    if actual != expected:
        raise RuntimeError(
            f"Requested {expected} task patterns but selected {actual} cases"
        )

    prompt = make_prompt(args.prompt)

    def generate_one(case: dict[str, str], sample_index: int, seed: int) -> str:
        ai = AIAPI(
            f"openai/{args.served_model}",
            n=1,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
            seed=seed,
            api_base=args.api_base,
            api_key="local-cweval",
        )
        responses = prompt.req_ai(
            ai,
            case["lang"],
            case["code_prompt"],
            metadata={
                key: value
                for key, value in case.items()
                if key not in ("code_prompt", "lang")
            },
        )
        if len(responses) != 1:
            raise RuntimeError(f"Expected one response, received {len(responses)}")
        output_path = Path(
            case["out_path_template"].format(index=sample_index)
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(responses[0], encoding="utf-8")
        return output_path.name

    jobs = [
        (case, sample_index, seed)
        for case in generator.cases.values()
        for sample_index, seed in enumerate(seeds)
    ]
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.num_workers, len(jobs))
    ) as executor:
        futures = [
            executor.submit(generate_one, case, sample_index, seed)
            for case, sample_index, seed in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()
            completed += 1
            if completed % 10 == 0 or completed == len(jobs):
                print(f"Generated {completed}/{len(jobs)} samples", flush=True)

    selected_tasks = [
        os.path.relpath(case["task_file_path"], CWEVAL_ROOT / "benchmark")
        for case in generator.cases.values()
    ]
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cweval_commit": "e9a2a124c8c53679b6d8d27adfd2f6c40e7576d7",
        "model": args.served_model,
        "api_base": args.api_base,
        "prompt": args.prompt,
        "tasks": selected_tasks,
        "task_count": actual,
        "samples_per_task": len(seeds),
        "generation_seeds": seeds,
        "num_workers": min(args.num_workers, len(jobs)),
        "temperature": args.temperature,
        "max_completion_tokens": args.max_completion_tokens,
    }
    eval_path.mkdir(parents=True, exist_ok=True)
    (eval_path / "generation_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Generated {actual} tasks x {len(seeds)} seeds in {eval_path}"
    )


if __name__ == "__main__":
    main()
