#!/usr/bin/env python3
"""Generate test-blind secure-reference candidates for CodeGuard+ tasks."""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from .generate_sallm_secure_candidates import (
        APIClient,
        DEEPSEEK_BASE_URL,
        DEEPSEEK_MODEL,
        atomic_write_text,
        canonical_json,
        model_provenance,
        parse_candidate,
        request_payload,
        response_content,
        sanitized_response,
        sha256_bytes,
        sha256_file,
        utc_now,
        write_json,
    )
else:
    from generate_sallm_secure_candidates import (
        APIClient,
        DEEPSEEK_BASE_URL,
        DEEPSEEK_MODEL,
        atomic_write_text,
        canonical_json,
        model_provenance,
        parse_candidate,
        request_payload,
        response_content,
        sanitized_response,
        sha256_bytes,
        sha256_file,
        utc_now,
        write_json,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
DEFAULT_MANIFEST = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
SYSTEM_PROMPT = """\
You are creating an independent secure reference implementation for a software
security benchmark. Complete the supplied Python module while preserving its
imports, public functions, classes, Flask routes, argument names, return types,
documented behavior, and observable error behavior. Eliminate the target CWE
using a general production-like mitigation. Do not access or mention tests,
CodeQL queries, benchmark probes, hidden files, or the network. Do not add
undeclared third-party dependencies, hard-code examples, reject all inputs, or
weaken functionality merely to avoid the vulnerability.

Return one JSON object only with fields "code" (the complete Python module),
"security_summary" (a concise mitigation description), and "assumptions" (an
array of concise strings). Do not use a Markdown fence or add other text."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("deepseek", "local"), default="deepseek")
    parser.add_argument("--model")
    parser.add_argument("--api-base")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--local-model-path", type=Path)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--selection-state", choices=("primary", "reserve"), default="primary")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidates-per-task", type=int, default=3)
    parser.add_argument("--candidate-index", action="append", type=int, dest="candidate_indices")
    parser.add_argument("--base-seed", type=int, default=20260802)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    parser.add_argument("--local-thinking", choices=("enabled", "disabled"), default="disabled")
    parser.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high"), default="high")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-paid-api", action="store_true")
    parser.add_argument("--skip-model-check", action="store_true")
    return parser.parse_args()


def project_path(path: Path, *, exists: bool = True) -> Path:
    value = path.expanduser().resolve()
    value.relative_to(ROOT)
    if exists and not value.exists():
        raise FileNotFoundError(value)
    return value


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def validate_args(args: argparse.Namespace) -> None:
    if args.candidates_per_task < 1:
        raise ValueError("--candidates-per-task must be positive")
    if args.num_workers < 1 or args.max_tokens < 1 or args.timeout_seconds <= 0:
        raise ValueError("Worker, token, and timeout limits must be positive")
    if not 0 <= args.temperature <= 2 or not 0 < args.top_p <= 1:
        raise ValueError("Invalid sampling parameters")
    if args.candidate_indices:
        if len(args.candidate_indices) != len(set(args.candidate_indices)):
            raise ValueError("Duplicate --candidate-index")
        if any(index < 0 or index >= args.candidates_per_task for index in args.candidate_indices):
            raise ValueError("--candidate-index outside candidate range")
    if args.provider == "local" and (not args.model or not args.api_base):
        raise ValueError("Local provider requires --model and --api-base")
    if args.provider == "deepseek" and not (args.dry_run or args.confirm_paid_api):
        raise ValueError("Pass --confirm-paid-api for non-dry-run DeepSeek requests")
    if args.resume and args.dry_run:
        raise ValueError("--resume and --dry-run cannot be combined")


def verified_text(value: dict[str, Any]) -> str:
    path = project_path(ROOT / value["path"])
    if sha256_file(path) != value["sha256"] or path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Frozen input changed: {path}")
    return path.read_text(encoding="utf-8")


def load_selection(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any], list[dict[str, Any]]]:
    plan_path = project_path(args.plan)
    manifest_path = project_path(args.benchmark_manifest)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan_manifest = plan["inputs"]["benchmark_manifest"]
    if sha256_file(manifest_path) != plan_manifest["sha256"]:
        raise RuntimeError("Qualification plan points to a different benchmark manifest")
    plan_tasks = {
        item["task_id"]: item
        for item in plan["tasks"]
        if item["selection_state"] == args.selection_state
    }
    manifest_tasks = {item["task_id"]: item for item in manifest["tasks"]}
    requested = args.tasks or (
        plan["primary_task_ids"] if args.selection_state == "primary" else plan["reserve_task_ids"]
    )
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate task selection")
    missing = sorted(set(requested) - set(plan_tasks))
    if missing:
        raise ValueError(f"Tasks are not in selected plan state: {missing}")
    result = []
    for task_id in requested:
        if task_id not in manifest_tasks:
            raise RuntimeError(f"Manifest task disappeared: {task_id}")
        result.append({"plan": plan_tasks[task_id], "benchmark": manifest_tasks[task_id]})
    return plan_path, manifest_path, plan, result


def public_context(item: dict[str, Any]) -> dict[str, Any]:
    plan_task = item["plan"]
    benchmark = item["benchmark"]
    inputs = plan_task["public_generation_inputs"]
    if any(
        inputs[key]
        for key in (
            "benchmark_probe_exposed_to_model",
            "functional_test_exposed_to_model",
            "security_query_exposed_to_model",
        )
    ):
        raise RuntimeError("Plan attempts to expose an oracle to the generator")
    file_context = verified_text(inputs["file_context"])
    function_context = verified_text(inputs["function_context"])
    verified_text(inputs["info"])
    prefix = file_context.rstrip()
    suffix = function_context.rstrip()
    if prefix and suffix and suffix.startswith(prefix):
        incomplete_module = suffix
    else:
        incomplete_module = "\n\n".join(part for part in (prefix, suffix) if part)
    return {
        "task_id": benchmark["task_id"],
        "target_cwe": benchmark["cwe"],
        "language": "python",
        "scenario": benchmark["source"]["scenario"],
        "incomplete_public_module": incomplete_module,
        "declared_dependency_sets": benchmark["dependencies"]["dependency_set_ids"],
    }


def messages(context: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Complete this task securely:\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True),
        },
    ]


def candidate_dir(output: Path, task_id: str, index: int) -> Path:
    return output / "tasks" / task_id.replace("/", "__") / f"candidate_{index:03d}"


def codeguard_static_flags(code: str) -> list[str]:
    lowered = code.lower()
    flags = []
    if any(
        marker in lowered
        for marker in (
            "functional.py",
            "test_case.py",
            "test_cases.py",
            "codeql",
            "pytest",
            "unittest",
        )
    ):
        flags.append("possible_oracle_reference")
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(name.startswith(("test", "tests")) for name in names):
                flags.append("test_module_import")
                break
    return sorted(set(flags))


def indices(args: argparse.Namespace) -> list[int]:
    return sorted(args.candidate_indices) if args.candidate_indices else list(range(args.candidates_per_task))


def prepare(args: argparse.Namespace) -> tuple[Path, str, str, list[dict[str, Any]], dict[str, Any]]:
    plan_path, manifest_path, plan, selected = load_selection(args)
    output = project_path(args.output, exists=False)
    model = args.model or DEEPSEEK_MODEL
    api_base = args.api_base or DEEPSEEK_BASE_URL
    config = {
        "schema_version": 1,
        "generator": "tools/generate_codeguardplus_secure_candidates.py",
        "provider": args.provider,
        "model": model,
        "api_base": api_base,
        "local_model": model_provenance(args.local_model_path),
        "selection_state": args.selection_state,
        "selection": [item["benchmark"]["task_id"] for item in selected],
        "candidates_per_task": args.candidates_per_task,
        "candidate_indices": indices(args),
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "base_seed": args.base_seed if args.provider == "local" else None,
        "thinking": args.thinking if args.provider == "deepseek" else None,
        "local_thinking": args.local_thinking if args.provider == "local" else None,
        "reasoning_effort": args.reasoning_effort if args.provider == "deepseek" else None,
        "input_files": {
            "qualification_plan": {"path": relative(plan_path), "sha256": sha256_file(plan_path)},
            "benchmark_manifest": {"path": relative(manifest_path), "sha256": sha256_file(manifest_path)},
        },
        "tests_exposed_to_model": False,
        "security_query_exposed_to_model": False,
        "benchmark_probe_exposed_to_model": False,
        "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode()),
        "formal_results_use": False,
    }
    fingerprint = sha256_bytes(canonical_json(config).encode())
    manifest_out = output / "run_manifest.json"
    if args.resume:
        if not manifest_out.is_file():
            raise FileNotFoundError(manifest_out)
        observed = json.loads(manifest_out.read_text(encoding="utf-8"))
        if observed["configuration_sha256"] != fingerprint:
            raise RuntimeError("Resume configuration mismatch")
    else:
        if output.exists():
            raise FileExistsError(output)
        output.mkdir(parents=True)
        write_json(
            manifest_out,
            {
                **config,
                "configuration_sha256": fingerprint,
                "created_at_utc": utc_now(),
                "status": "dry_run" if args.dry_run else "in_progress",
                "api_key_env": args.api_key_env,
                "api_key_persisted": False,
            },
        )
    return output, model, api_base, selected, plan


def generate_one(
    *, client: APIClient, args: argparse.Namespace, model: str, output: Path,
    item: dict[str, Any], candidate_index: int,
) -> dict[str, Any]:
    task = item["benchmark"]
    task_id = task["task_id"]
    directory = candidate_dir(output, task_id, candidate_index)
    metadata_path = directory / "metadata.json"
    if args.resume and metadata_path.is_file():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        if existing.get("status") == "success":
            return existing
    context = public_context(item)
    prompt = messages(context)
    task_root = output / "tasks" / task_id.replace("/", "__")
    prompt_path = task_root / "prompt.json"
    if not prompt_path.exists():
        write_json(
            prompt_path,
            {
                "task_id": task_id,
                "context": context,
                "messages": prompt,
                "tests_included": False,
                "security_query_included": False,
                "benchmark_probe_included": False,
                "prompt_sha256": sha256_bytes(canonical_json(prompt).encode()),
            },
        )
    directory.mkdir(parents=True, exist_ok=True)
    payload = request_payload(
        provider=args.provider,
        model=model,
        messages=prompt,
        candidate_index=candidate_index,
        args=args,
    )
    if args.provider == "local":
        payload["chat_template_kwargs"] = {
            "enable_thinking": args.local_thinking == "enabled"
        }
    started = utc_now()
    try:
        response = client.completion(payload)
        parsed = parse_candidate(response_content(response))
        candidate_path = directory / "candidate.py"
        atomic_write_text(candidate_path, parsed["code"])
        metadata = {
            "schema_version": 1,
            "task_id": task_id,
            "cwe": task["cwe"],
            "candidate_index": candidate_index,
            "status": "success",
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "candidate": {
                "path": relative(candidate_path),
                "sha256": sha256_file(candidate_path),
                "size_bytes": candidate_path.stat().st_size,
            },
            "security_summary": parsed["security_summary"],
            "assumptions": parsed["assumptions"],
            "static_flags": codeguard_static_flags(parsed["code"]),
            "response": sanitized_response(response),
        }
    except Exception as error:
        metadata = {
            "schema_version": 1,
            "task_id": task_id,
            "cwe": task["cwe"],
            "candidate_index": candidate_index,
            "status": "failed",
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "error_type": type(error).__name__,
            "error": str(error),
        }
    write_json(metadata_path, metadata)
    return metadata


def rebuild(output: Path, expected: int, task_count: int) -> dict[str, Any]:
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((output / "tasks").glob("*/candidate_*/metadata.json"))
    ]
    records.sort(key=lambda item: (item["task_id"], item["candidate_index"]))
    with (output / "candidates.jsonl").open("w", encoding="utf-8") as stream:
        for item in records:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter(item["status"] for item in records)
    success_hashes = [item["candidate"]["sha256"] for item in records if item["status"] == "success"]
    summary = {
        "updated_at_utc": utc_now(),
        "task_count": task_count,
        "candidates_per_task": expected // task_count,
        "expected_candidate_count": expected,
        "recorded_candidate_count": len(records),
        "success_count": counts["success"],
        "failed_count": counts["failed"],
        "static_flagged_count": sum(bool(item.get("static_flags")) for item in records),
        "unique_successful_implementation_count": len(set(success_hashes)),
        "complete": len(records) == expected,
        "formal_results_use": False,
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    validate_args(args)
    output, model, api_base, selected, _ = prepare(args)
    for item in selected:
        context = public_context(item)
        task_root = output / "tasks" / item["benchmark"]["task_id"].replace("/", "__")
        write_json(
            task_root / "prompt.json",
            {
                "task_id": item["benchmark"]["task_id"],
                "context": context,
                "messages": messages(context),
                "tests_included": False,
                "security_query_included": False,
                "benchmark_probe_included": False,
                "prompt_sha256": sha256_bytes(canonical_json(messages(context)).encode()),
            },
        )
    expected = len(selected) * len(indices(args))
    if args.dry_run:
        summary = {
            "updated_at_utc": utc_now(),
            "task_count": len(selected),
            "expected_candidate_count": expected,
            "recorded_candidate_count": 0,
            "complete": True,
            "dry_run": True,
            "formal_results_use": False,
        }
        write_json(output / "summary.json", summary)
        print(json.dumps(summary, indent=2))
        return
    api_key = "EMPTY" if args.provider == "local" else os.environ.get(args.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"API key environment variable is unset: {args.api_key_env}")
    client = APIClient(api_base, api_key, args.timeout_seconds, args.max_retries, args.provider == "local")
    if not args.skip_model_check:
        available = client.available_models()
        if model not in available:
            raise RuntimeError(f"Model {model!r} absent from /models: {sorted(available)}")
    jobs = [
        (item, index)
        for item in selected
        for index in indices(args)
        if not (
            args.resume
            and (candidate_dir(output, item["benchmark"]["task_id"], index) / "metadata.json").is_file()
            and json.loads((candidate_dir(output, item["benchmark"]["task_id"], index) / "metadata.json").read_text()).get("status") == "success"
        )
    ]
    lock = threading.Lock()
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        future_map = {
            pool.submit(
                generate_one,
                client=client,
                args=args,
                model=model,
                output=output,
                item=item,
                candidate_index=index,
            ): (item["benchmark"]["task_id"], index)
            for item, index in jobs
        }
        for future in concurrent.futures.as_completed(future_map):
            task_id, index = future_map[future]
            result = future.result()
            with lock:
                completed += 1
                print(f"[{completed}/{len(jobs)}] {task_id} candidate={index}: {result['status']}", flush=True)
    summary = rebuild(output, expected, len(selected))
    run_manifest = json.loads((output / "run_manifest.json").read_text())
    run_manifest["status"] = "complete" if summary["complete"] else "incomplete"
    run_manifest["completed_at_utc"] = utc_now()
    write_json(output / "run_manifest.json", run_manifest)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
