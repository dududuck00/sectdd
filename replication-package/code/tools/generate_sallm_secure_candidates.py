#!/usr/bin/env python3
"""Generate auditable secure-reference candidates for qualified SALLM tasks.

The generator deliberately does not expose benchmark tests to the model.  It
supports DeepSeek's OpenAI-compatible API and local OpenAI-compatible servers
(for example vLLM).  Candidate code is parsed but never executed here.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUALIFICATION = (
    PROJECT_ROOT
    / "benchmarks"
    / "manifests"
    / "sallm-reference-qualified-v1.json"
)
DEFAULT_BENCHMARK_MANIFEST = (
    PROJECT_ROOT / "benchmarks" / "manifests" / "sallm-v1.json"
)
DEFAULT_OVERLAY = (
    PROJECT_ROOT / "configs" / "benchmarks" / "sallm_audit_overlay_v1.json"
)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
SYSTEM_PROMPT = """\
You are creating an independent secure reference implementation for a software
security benchmark. Preserve the stated behavior, public functions, classes,
Flask routes, argument names, return types, and observable error behavior as
closely as possible. Eliminate the target CWE using a general, production-like
fix. Do not special-case examples, guess hidden assertions, access tests, read
unrelated files, use the network, add undeclared dependencies, or weaken
functionality merely to block all inputs.

Return one JSON object only, with these fields:
- "code": the complete Python module as a string
- "security_summary": a concise description of the general mitigation
- "assumptions": a JSON array of concise assumptions

Do not wrap the JSON in a Markdown fence and do not include any other text."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
    )
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate multiple secure candidates without exposing SALLM tests"
        )
    )
    parser.add_argument(
        "--provider",
        choices=("deepseek", "local"),
        default="deepseek",
    )
    parser.add_argument(
        "--model",
        help=(
            f"Model ID (default: {DEEPSEEK_MODEL} for DeepSeek; required locally)"
        ),
    )
    parser.add_argument(
        "--api-base",
        help=(
            f"API base (default: {DEEPSEEK_BASE_URL} for DeepSeek; "
            "required locally, normally http://127.0.0.1:PORT/v1)"
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="DEEPSEEK_API_KEY",
        help="Environment variable containing the API key",
    )
    parser.add_argument(
        "--local-model-path",
        type=Path,
        help="Optional local checkpoint path to record and validate",
    )
    parser.add_argument("--output", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", action="append", dest="tasks")
    selection.add_argument("--task-file", type=Path)
    selection.add_argument("--all-qualified", action="store_true")
    parser.add_argument("--candidates-per-task", type=int, default=5)
    parser.add_argument(
        "--candidate-index",
        action="append",
        type=int,
        dest="candidate_indices",
        help=(
            "Generate only this zero-based candidate index; repeat for multiple "
            "indices. The value must be below --candidates-per-task."
        ),
    )
    parser.add_argument("--base-seed", type=int, default=20260730)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument(
        "--thinking",
        choices=("enabled", "disabled"),
        default="enabled",
        help="DeepSeek thinking mode; ignored for local servers",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high"),
        default="high",
        help="DeepSeek reasoning effort; ignored for local servers",
    )
    parser.add_argument(
        "--qualification",
        type=Path,
        default=DEFAULT_QUALIFICATION,
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=DEFAULT_BENCHMARK_MANIFEST,
    )
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a run with exactly the same generation configuration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write prompts and provenance but make no API requests",
    )
    parser.add_argument(
        "--confirm-paid-api",
        action="store_true",
        help="Required for non-dry-run DeepSeek requests",
    )
    parser.add_argument(
        "--skip-model-check",
        action="store_true",
        help="Skip the read-only GET /models preflight",
    )
    return parser.parse_args()


def read_task_file(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(content)
        if isinstance(payload, dict):
            payload = payload.get("tasks")
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise ValueError("JSON task file must be a list or an object with tasks")
        return payload
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_args(args: argparse.Namespace) -> None:
    if args.candidates_per_task < 1:
        raise ValueError("--candidates-per-task must be positive")
    if args.candidate_indices:
        if len(args.candidate_indices) != len(set(args.candidate_indices)):
            raise ValueError("--candidate-index values must be unique")
        invalid = [
            index
            for index in args.candidate_indices
            if index < 0 or index >= args.candidates_per_task
        ]
        if invalid:
            raise ValueError(
                "--candidate-index must be in [0, "
                f"{args.candidates_per_task - 1}]: {invalid}"
            )
    if args.num_workers < 1:
        raise ValueError("--num-workers must be positive")
    if args.max_tokens < 1 or args.timeout_seconds <= 0:
        raise ValueError("Token and timeout limits must be positive")
    if args.max_retries < 0:
        raise ValueError("--max-retries cannot be negative")
    if not 0 <= args.temperature <= 2:
        raise ValueError("--temperature must be in [0, 2]")
    if not 0 < args.top_p <= 1:
        raise ValueError("--top-p must be in (0, 1]")
    if args.provider == "local" and (not args.model or not args.api_base):
        raise ValueError("--model and --api-base are required for local provider")
    if args.provider == "deepseek" and not (
        args.dry_run or args.confirm_paid_api
    ):
        raise ValueError(
            "DeepSeek requests may incur cost; pass --confirm-paid-api "
            "or inspect first with --dry-run"
        )
    if args.resume and args.dry_run:
        raise ValueError("--resume and --dry-run cannot be combined")


def select_tasks(
    args: argparse.Namespace,
    qualification: dict[str, Any],
    benchmark: dict[str, Any],
) -> list[dict[str, Any]]:
    qualified = {
        task["task_id"]: task
        for task in qualification["tasks"]
        if task["decision"] == "candidate"
    }
    benchmark_by_id = {task["task_id"]: task for task in benchmark["tasks"]}
    if args.all_qualified:
        requested = sorted(qualified)
    elif args.task_file:
        requested = read_task_file(args.task_file.expanduser().resolve())
    else:
        requested = args.tasks
    if not requested:
        raise ValueError("No tasks selected")
    duplicates = sorted(
        task_id for task_id in set(requested) if requested.count(task_id) > 1
    )
    if duplicates:
        raise ValueError(f"Duplicate task IDs: {duplicates}")
    unknown = sorted(set(requested) - set(qualified))
    if unknown:
        raise ValueError(
            "Tasks are not reference-oracle candidates: " + ", ".join(unknown)
        )
    missing = sorted(set(requested) - set(benchmark_by_id))
    if missing:
        raise ValueError("Tasks absent from benchmark manifest: " + ", ".join(missing))
    return [
        {
            "qualification": qualified[task_id],
            "benchmark": benchmark_by_id[task_id],
        }
        for task_id in requested
    ]


def load_dataset_records(
    selected: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    required = {item["benchmark"]["task_id"] for item in selected}
    dataset_paths = {
        resolve_project_path(item["benchmark"]["source"]["dataset"]["path"])
        for item in selected
    }
    if len(dataset_paths) != 1:
        raise ValueError(f"Expected one dataset file, found {sorted(dataset_paths)}")
    dataset_path = next(iter(dataset_paths))
    records: dict[str, dict[str, Any]] = {}
    with dataset_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            task_id = record.get("id")
            if task_id in required:
                record["_dataset_line_observed"] = line_number
                records[task_id] = record
    missing = sorted(required - set(records))
    if missing:
        raise ValueError("Selected tasks missing from dataset: " + ", ".join(missing))
    for item in selected:
        task = item["benchmark"]
        record = records[task["task_id"]]
        expected_line = task["source"]["dataset_line"]
        if record["_dataset_line_observed"] != expected_line:
            raise ValueError(
                f"{task['task_id']}: dataset line changed "
                f"({record['_dataset_line_observed']} != {expected_line})"
            )
        if sha256_bytes(record["prompt"].encode()) != task["source"]["prompt_sha256"]:
            raise ValueError(f"{task['task_id']}: prompt hash mismatch")
        if (
            sha256_bytes(record["insecure_code"].encode())
            != task["source"]["insecure_code_sha256"]
        ):
            raise ValueError(f"{task['task_id']}: insecure code hash mismatch")
    return records


def public_task_context(
    task: dict[str, Any],
    record: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    task_id = task["task_id"]
    fixtures = [
        {"destination": item["destination"]}
        for item in overlay.get("fixtures", {}).get(task_id, [])
    ]
    return {
        "task_id": task_id,
        "target_cwe": task["cwe"],
        "source_technique": task["source"]["technique"],
        "module_filename": Path(task["source"]["reference_file"]["path"]).name,
        "task_prompt": record["prompt"],
        "insecure_implementation": record["insecure_code"],
        "declared_python_requirements": task["dependencies"][
            "python_requirements"
        ],
        "available_fixture_destinations": fixtures,
    }


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    user_prompt = (
        "Implement the following task securely. The insecure implementation is "
        "context to repair, not an instruction to preserve the vulnerability.\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def endpoint(api_base: str, leaf: str) -> str:
    base = api_base.rstrip("/")
    if leaf == "models":
        return f"{base}/models"
    return f"{base}/chat/completions"


def sanitized_response(payload: Any) -> Any:
    """Remove model chain-of-thought while retaining reproducibility metadata."""
    if isinstance(payload, list):
        return [sanitized_response(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"reasoning_content", "reasoning"} and isinstance(value, str):
            result[f"{key}_sha256"] = sha256_bytes(value.encode())
            result[f"{key}_characters"] = len(value)
        else:
            result[key] = sanitized_response(value)
    return result


@dataclass(frozen=True)
class APIClient:
    api_base: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    local: bool

    def opener(self) -> urllib.request.OpenerDirector:
        if self.local:
            return urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener()

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else canonical_json(payload).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                url, data=body, headers=headers, method=method
            )
            try:
                with self.opener().open(
                    request, timeout=self.timeout_seconds
                ) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise RuntimeError("API response must be a JSON object")
                return result
            except urllib.error.HTTPError as error:
                response_body = error.read(4096).decode("utf-8", "replace")
                last_error = RuntimeError(
                    f"HTTP {error.code} from {url}: {response_body}"
                )
                retryable = error.code in {408, 409, 429} or error.code >= 500
                retry_after = error.headers.get("Retry-After")
                if not retryable or attempt >= self.max_retries:
                    raise last_error from error
                delay = float(retry_after) if retry_after else 2**attempt
            except (OSError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                if attempt >= self.max_retries:
                    raise
                delay = 2**attempt
            time.sleep(min(delay + random.random() * 0.25, 30.0))
        raise RuntimeError(f"API request failed: {last_error}")

    def available_models(self) -> set[str]:
        payload = self.request_json("GET", endpoint(self.api_base, "models"))
        return {
            item["id"]
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }

    def completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            "POST", endpoint(self.api_base, "chat/completions"), payload
        )


def request_payload(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    candidate_index: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    if provider == "deepseek":
        payload["thinking"] = {"type": args.thinking}
        payload["reasoning_effort"] = args.reasoning_effort
    else:
        payload["seed"] = args.base_seed + candidate_index
    return payload


def response_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("Expected exactly one completion choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(
        message.get("content"), str
    ):
        raise ValueError("Completion has no string message content")
    return message["content"]


FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_candidate(content: str) -> dict[str, Any]:
    text = content.strip()
    match = FENCE_RE.fullmatch(text)
    if match:
        text = match.group(1)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Model output JSON must be an object")
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Model output must contain non-empty string field 'code'")
    assumptions = payload.get("assumptions", [])
    if not isinstance(assumptions, list) or not all(
        isinstance(item, str) for item in assumptions
    ):
        raise ValueError("'assumptions' must be an array of strings")
    summary = payload.get("security_summary", "")
    if not isinstance(summary, str):
        raise ValueError("'security_summary' must be a string")
    ast.parse(code)
    return {
        "code": code.rstrip() + "\n",
        "security_summary": summary,
        "assumptions": assumptions,
    }


def static_flags(code: str, benchmark_task: dict[str, Any]) -> list[str]:
    lowered = code.lower()
    flags: list[str] = []
    forbidden = {
        Path(benchmark_task["tests"]["entrypoint"]["path"]).name.lower(),
        "pytest",
        "unittest",
    }
    if any(value in lowered for value in forbidden):
        flags.append("possible_test_reference")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return flags + ["syntax_error"]
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


def model_provenance(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Local model directory does not exist: {resolved}")
    config = resolved / "config.json"
    if not config.is_file():
        raise FileNotFoundError(
            f"Local model directory has no config.json (possibly incomplete): {resolved}"
        )
    files = {}
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "model.safetensors.index.json",
    ):
        item = resolved / name
        if item.is_file():
            files[name] = {
                "sha256": sha256_file(item),
                "size_bytes": item.stat().st_size,
            }
    return {"path": str(resolved), "identity_files": files}


def selected_candidate_indices(args: argparse.Namespace) -> list[int]:
    if args.candidate_indices:
        return sorted(args.candidate_indices)
    return list(range(args.candidates_per_task))


def prepare_run(
    args: argparse.Namespace,
) -> tuple[
    Path,
    str,
    str,
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    qualification_path = args.qualification.expanduser().resolve()
    benchmark_path = args.benchmark_manifest.expanduser().resolve()
    overlay_path = args.overlay.expanduser().resolve()
    qualification = load_json(qualification_path)
    benchmark = load_json(benchmark_path)
    overlay = load_json(overlay_path)
    selected = select_tasks(args, qualification, benchmark)
    records = load_dataset_records(selected)

    model = args.model or DEEPSEEK_MODEL
    api_base = args.api_base or DEEPSEEK_BASE_URL
    output = args.output.expanduser().resolve()
    local_provenance = model_provenance(args.local_model_path)
    selection = [item["benchmark"]["task_id"] for item in selected]
    run_config = {
        "schema_version": 1,
        "generator": "tools/generate_sallm_secure_candidates.py",
        "provider": args.provider,
        "model": model,
        "api_base": api_base,
        "local_model": local_provenance,
        "selection": selection,
        "candidates_per_task": args.candidates_per_task,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "base_seed": args.base_seed if args.provider == "local" else None,
        "thinking": args.thinking if args.provider == "deepseek" else None,
        "reasoning_effort": (
            args.reasoning_effort if args.provider == "deepseek" else None
        ),
        "input_files": {
            "qualification": {
                "path": relative_or_absolute(qualification_path),
                "sha256": sha256_file(qualification_path),
            },
            "benchmark_manifest": {
                "path": relative_or_absolute(benchmark_path),
                "sha256": sha256_file(benchmark_path),
            },
            "overlay": {
                "path": relative_or_absolute(overlay_path),
                "sha256": sha256_file(overlay_path),
            },
        },
        "hidden_tests_exposed_to_model": False,
        "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode()),
    }
    # Omit this field for ordinary runs to preserve the configuration
    # fingerprint of runs created before targeted retries were introduced.
    if args.candidate_indices:
        run_config["candidate_indices"] = selected_candidate_indices(args)
    fingerprint = sha256_bytes(canonical_json(run_config).encode())
    manifest_path = output / "run_manifest.json"
    if args.resume:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Cannot resume: {manifest_path} is absent")
        existing = load_json(manifest_path)
        if existing.get("configuration_sha256") != fingerprint:
            raise ValueError(
                "Resume configuration does not match existing run manifest"
            )
    else:
        if output.exists():
            raise FileExistsError(
                f"Output already exists: {output}; use --resume or a new path"
            )
        output.mkdir(parents=True)
        write_json(
            manifest_path,
            {
                **run_config,
                "configuration_sha256": fingerprint,
                "created_at_utc": utc_now(),
                "status": "dry_run" if args.dry_run else "in_progress",
                "api_key_env": args.api_key_env,
                "api_key_persisted": False,
            },
        )
    return (
        output,
        model,
        api_base,
        selected,
        records,
        overlay,
        run_config,
    )


def candidate_directory(output: Path, task_id: str, index: int) -> Path:
    return output / "tasks" / Path(task_id).stem / f"candidate_{index:03d}"


def write_prompt_artifact(
    output: Path,
    task: dict[str, Any],
    context: dict[str, Any],
    messages: list[dict[str, str]],
) -> None:
    task_dir = output / "tasks" / Path(task["task_id"]).stem
    write_json(
        task_dir / "prompt.json",
        {
            "task_id": task["task_id"],
            "context": context,
            "messages": messages,
            "tests_included": False,
            "prompt_sha256": sha256_bytes(canonical_json(messages).encode()),
        },
    )


def generate_one(
    *,
    client: APIClient,
    args: argparse.Namespace,
    model: str,
    output: Path,
    item: dict[str, Any],
    record: dict[str, Any],
    overlay: dict[str, Any],
    candidate_index: int,
) -> dict[str, Any]:
    task = item["benchmark"]
    task_id = task["task_id"]
    directory = candidate_directory(output, task_id, candidate_index)
    metadata_path = directory / "metadata.json"
    if args.resume and metadata_path.is_file():
        metadata = load_json(metadata_path)
        if metadata.get("status") == "success":
            return metadata
    context = public_task_context(task, record, overlay)
    messages = build_messages(context)
    payload = request_payload(
        provider=args.provider,
        model=model,
        messages=messages,
        candidate_index=candidate_index,
        args=args,
    )
    directory.mkdir(parents=True, exist_ok=True)
    write_json(
        directory / "request.json",
        {
            **payload,
            "request_sha256": sha256_bytes(canonical_json(payload).encode()),
            "authorization_persisted": False,
        },
    )
    started = utc_now()
    try:
        response = client.completion(payload)
        write_json(directory / "response.json", sanitized_response(response))
        content = response_content(response)
        atomic_write_text(directory / "response_content.txt", content)
        parsed = parse_candidate(content)
        code = parsed.pop("code")
        flags = static_flags(code, task)
        atomic_write_text(directory / "candidate.py", code)
        metadata = {
            "schema_version": 1,
            "status": "success",
            "task_id": task_id,
            "target_cwe": task["cwe"],
            "candidate_index": candidate_index,
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "candidate_sha256": sha256_bytes(code.encode()),
            "response_content_sha256": sha256_bytes(content.encode()),
            "syntax_valid": True,
            "static_flags": flags,
            **parsed,
            "api": {
                "id": response.get("id"),
                "model": response.get("model"),
                "system_fingerprint": response.get("system_fingerprint"),
                "usage": response.get("usage"),
                "finish_reason": response.get("choices", [{}])[0].get(
                    "finish_reason"
                ),
            },
        }
    except Exception as error:  # keep other independent jobs running
        metadata = {
            "schema_version": 1,
            "status": "failed",
            "task_id": task_id,
            "target_cwe": task["cwe"],
            "candidate_index": candidate_index,
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "error_type": type(error).__name__,
            "error": str(error),
        }
    write_json(metadata_path, metadata)
    return metadata


def rebuild_indexes(
    output: Path,
    selected: list[dict[str, Any]],
    candidate_indices: list[int],
    candidates_per_task: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    expected = len(selected) * len(candidate_indices)
    for item in selected:
        task_id = item["benchmark"]["task_id"]
        for index in candidate_indices:
            path = candidate_directory(output, task_id, index) / "metadata.json"
            if path.is_file():
                metadata = load_json(path)
                rows.append(
                    {
                        **metadata,
                        "directory": relative_or_absolute(path.parent),
                    }
                )
    rows.sort(key=lambda row: (row["task_id"], row["candidate_index"]))
    atomic_write_text(
        output / "candidate_index.jsonl",
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
    )
    summary = {
        "updated_at_utc": utc_now(),
        "task_count": len(selected),
        "candidates_per_task": candidates_per_task,
        "candidate_indices": candidate_indices,
        "expected_candidate_count": expected,
        "recorded_candidate_count": len(rows),
        "success_count": sum(row["status"] == "success" for row in rows),
        "failed_count": sum(row["status"] == "failed" for row in rows),
        "static_flagged_count": sum(bool(row.get("static_flags")) for row in rows),
        "complete": len(rows) == expected,
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    args = parse_args()
    validate_args(args)
    (
        output,
        model,
        api_base,
        selected,
        records,
        overlay,
        run_config,
    ) = prepare_run(args)
    for item in selected:
        task = item["benchmark"]
        context = public_task_context(task, records[task["task_id"]], overlay)
        write_prompt_artifact(
            output, task, context, build_messages(context)
        )

    candidate_indices = selected_candidate_indices(args)
    if args.dry_run:
        summary = {
            "updated_at_utc": utc_now(),
            "task_count": len(selected),
            "candidates_per_task": args.candidates_per_task,
            "candidate_indices": candidate_indices,
            "expected_candidate_count": (
                len(selected) * len(candidate_indices)
            ),
            "recorded_candidate_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "static_flagged_count": 0,
            "complete": False,
            "dry_run": True,
        }
        write_json(output / "summary.json", summary)
        print(
            f"Dry run prepared {len(selected)} tasks x "
            f"{len(candidate_indices)} selected candidate index(es) "
            f"{candidate_indices} in {output}"
        )
        return

    api_key = os.environ.get(args.api_key_env)
    if args.provider == "local":
        api_key = api_key or "local-sectdd"
    if not api_key:
        raise RuntimeError(
            f"Set API key in environment variable {args.api_key_env!r}"
        )
    client = APIClient(
        api_base=api_base,
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        local=args.provider == "local",
    )
    if not args.skip_model_check:
        available = client.available_models()
        if model not in available:
            raise RuntimeError(
                f"Model {model!r} is not exposed by {api_base}; "
                f"available models: {sorted(available)}"
            )

    jobs = [
        (item, candidate_index)
        for item in selected
        for candidate_index in candidate_indices
    ]
    done = 0
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.num_workers, len(jobs))
    ) as executor:
        futures = [
            executor.submit(
                generate_one,
                client=client,
                args=args,
                model=model,
                output=output,
                item=item,
                record=records[item["benchmark"]["task_id"]],
                overlay=overlay,
                candidate_index=candidate_index,
            )
            for item, candidate_index in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            metadata = future.result()
            done += 1
            print(
                f"[{done}/{len(jobs)}] {metadata['task_id']} "
                f"candidate {metadata['candidate_index']}: "
                f"{metadata['status']}",
                flush=True,
            )

    summary = rebuild_indexes(
        output,
        selected,
        candidate_indices,
        args.candidates_per_task,
    )
    manifest = load_json(output / "run_manifest.json")
    manifest["status"] = (
        "completed" if summary["failed_count"] == 0 else "completed_with_failures"
    )
    manifest["completed_at_utc"] = utc_now()
    manifest["summary_sha256"] = sha256_file(output / "summary.json")
    write_json(output / "run_manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed_count"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
