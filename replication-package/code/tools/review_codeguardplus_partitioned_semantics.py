#!/usr/bin/env python3
"""Build blinded CodeGuard+ packets and collect independent machine reviews.

The command is deliberately resumable. A report is emitted only after at least
two distinct reviewer checkpoints have completed every frozen packet. External
credentials are accepted only through environment variables and are never
written to review artifacts.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "benchmarks/manifests/codeguardplus-partitioned-v1-freeze.json"
DEFAULT_BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
DEFAULT_ORACLE = ROOT / "oracles/codeguardplus_partitioned_v1/manifest.json"
DEFAULT_OUTPUT = ROOT / "artifacts/codeguardplus-semantic-review-v1"
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

CWE_SOURCES = {
    "CWE-22": ("Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal')", "22"),
    "CWE-117": ("Improper Output Neutralization for Logs", "117"),
    "CWE-78": ("Improper Neutralization of Special Elements used in an OS Command ('OS Command Injection')", "78"),
    "CWE-79": ("Improper Neutralization of Input During Web Page Generation ('Cross-site Scripting')", "79"),
    "CWE-89": ("Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')", "89"),
    "CWE-295": ("Improper Certificate Validation", "295"),
    "CWE-312": ("Cleartext Storage of Sensitive Information", "312"),
    "CWE-327": ("Use of a Broken or Risky Cryptographic Algorithm", "327"),
    "CWE-377": ("Insecure Temporary File", "377"),
    "CWE-400": ("Uncontrolled Resource Consumption", "400"),
    "CWE-611": ("Improper Restriction of XML External Entity Reference", "611"),
    "CWE-643": ("Improper Neutralization of Data within XPath Expressions ('XPath Injection')", "643"),
    "CWE-732": ("Incorrect Permission Assignment for Critical Resource", "732"),
}

CRITERIA = (
    "prompt_contract_consistency",
    "cwe_alignment",
    "safe_functionality_preservation",
    "safe_security_mitigation",
    "mutant_represents_target_cwe",
    "visible_oracle_semantic_validity",
    "hidden_oracle_semantic_validity",
    "visible_hidden_behavior_family_independence",
    "implementation_independent_assertions",
    "deterministic_offline_bounded_execution",
)

SYSTEM_PROMPT = """\
You are a skeptical benchmark-oracle reviewer. Review semantic validity, not
whether the supplied safe/mutant pair happens to pass the tests. Detect
contradictions among the public task context, declared contract, CWE, safe
implementation, targeted mutant, and test assertions. Reject an oracle that
requires one particular implementation, accepts reject-everything behavior,
tests a different weakness, relies on probabilistic timing/randomness, performs
network access, or gives visible and hidden partitions materially equivalent
inputs or attack mechanisms.

The safe implementation should preserve the public functional contract and
mitigate the declared CWE. The targeted mutant should preserve ordinary
functionality while reintroducing that CWE. Both visible and hidden files have
test_correctness (functional) and test_vulnerability (security). The expected
safe state is F+S+ and the expected mutant state is F+S-. Those execution
outcomes are intentionally omitted: reason from semantics only. Do not require
an oracle to use a specific security API when multiple secure designs satisfy
the public contract. The two behavior families may address the same CWE but
must exercise meaningfully different inputs or failure mechanisms.

Return exactly one JSON object with this schema:
{
  "verdict": "accept" | "reject" | "needs_human",
  "summary": "concise overall assessment",
  "criteria": {
    "criterion_name": {"passed": true | false | null, "evidence": ["specific evidence"]}
  },
  "critical_issues": [
    {"severity": "critical" | "major" | "minor", "category": "...", "evidence": "...", "recommended_action": "..."}
  ],
  "behavior_family_assessment": {
    "visible": "...", "hidden": "...", "materially_distinct": true | false
  },
  "confidence": 0.0
}
Include every requested criterion exactly once. Use null only when evidence is
absent. A prompt-oracle or CWE-oracle contradiction cannot receive accept. Be
concise: no more than two short evidence strings per criterion and at most
three genuine issues."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--oracle-manifest", type=Path, default=DEFAULT_ORACLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--report-id",
        default="codeguardplus-partitioned-semantic-machine-panel-v1",
    )
    parser.add_argument("--reviewer", metavar="MODEL=API_BASE")
    parser.add_argument("--provider", choices=("local", "deepseek"), default="local")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    parser.add_argument("--local-thinking", choices=("enabled", "disabled"), default="disabled")
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"), default="high")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--confirm-machine-review", action="store_true")
    return parser.parse_args()


def checked(path: Path, *, exists: bool = True) -> Path:
    result = path.expanduser().resolve()
    result.relative_to(ROOT)
    if exists and not result.exists():
        raise FileNotFoundError(result)
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verified_text(value: dict[str, Any]) -> tuple[dict[str, Any], str]:
    path = checked(ROOT / value["path"])
    if sha256(path) != value["sha256"] or path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Frozen input drift: {path}")
    return record(path), path.read_text(encoding="utf-8")


def build_packet(task_id: str, benchmark: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for name in ("file_context", "function_context", "info"):
        metadata, content = verified_text(benchmark["source"][name])
        sources[name] = {**metadata, "content": content}
    for name in ("safe_reference", "vulnerability_mutant", "visible_test", "hidden_test"):
        metadata, content = verified_text(oracle[name])
        sources[name] = {**metadata, "content": content}
    cwe = benchmark["cwe"]
    title, number = CWE_SOURCES.get(
        cwe,
        (f"MITRE Common Weakness Enumeration {cwe}", cwe.removeprefix("CWE-")),
    )
    return {
        "schema_version": 1,
        "task_id": task_id,
        "cwe": benchmark["cwe"],
        "authoritative_cwe": {"title": title, "url": f"https://cwe.mitre.org/data/definitions/{number}.html"},
        "declared_contract": oracle["contract"],
        "declared_behavior_families": oracle["families"],
        "sources": sources,
        "blinding": {
            "author_model_identity_included": False,
            "candidate_attempt_index_included": False,
            "construction_execution_outcomes_included": False,
            "model_preflight_outcomes_included": False,
            "benchmark_functional_tests_included": False,
            "codeql_query_included": False,
        },
        "review_criteria": list(CRITERIA),
    }


def validate_review(review: Any) -> dict[str, Any]:
    if not isinstance(review, dict) or review.get("verdict") not in {"accept", "reject", "needs_human"}:
        raise ValueError("Invalid verdict")
    criteria = review.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ValueError("Review criteria do not match the frozen rubric")
    for name in CRITERIA:
        item = criteria[name]
        if not isinstance(item, dict) or item.get("passed") not in {True, False, None} or not isinstance(item.get("evidence"), list):
            raise ValueError(f"Invalid criterion: {name}")
    if not isinstance(review.get("critical_issues"), list):
        raise ValueError("critical_issues must be a list")
    family = review.get("behavior_family_assessment")
    if not isinstance(family, dict) or not isinstance(family.get("materially_distinct"), bool):
        raise ValueError("Invalid behavior-family assessment")
    confidence = review.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between zero and one")
    return review


def request_review(
    provider: str,
    model: str,
    api_base: str,
    api_key: str | None,
    packet: dict[str, Any],
    max_tokens: int,
    timeout: float,
    thinking: str,
    reasoning_effort: str,
    local_thinking: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(packet, ensure_ascii=False, indent=2)},
    ]
    last_error: Exception | None = None
    prior_attempts: list[dict[str, Any]] = []
    for attempt in range(4):
        attempt_thinking = thinking
        response_format = "json_object"
        if provider == "deepseek" and attempt >= 1:
            # DeepSeek documents occasional empty JSON-mode responses. Fall
            # back first to non-thinking JSON, then to prompt-constrained text
            # while retaining the same strict local schema validation.
            attempt_thinking = "disabled"
        if provider == "deepseek" and attempt >= 2:
            response_format = "text"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "response_format": {"type": response_format},
            "stream": False,
        }
        if provider == "local":
            payload["seed"] = 20260802 + attempt
            payload["chat_template_kwargs"] = {
                "enable_thinking": local_thinking == "enabled"
            }
        else:
            payload["thinking"] = {"type": attempt_thinking}
            if attempt_thinking == "enabled":
                payload["reasoning_effort"] = reasoning_effort
        request = urllib.request.Request(
            f"{api_base.rstrip('/')}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key or 'local-semantic-review'}",
                "Content-Type": "application/json",
            },
        )
        try:
            opener = (
                urllib.request.build_opener(urllib.request.ProxyHandler({}))
                if provider == "local"
                else urllib.request.build_opener()
            )
            with opener.open(request, timeout=timeout) as response:
                raw = json.load(response)
            choice = raw["choices"][0]
            message = choice["message"]
            content_value = message.get("content")
            if not isinstance(content_value, str) or not content_value.strip():
                reasoning_value = message.get("reasoning_content")
                reasoning_length = len(reasoning_value) if isinstance(reasoning_value, str) else 0
                raise ValueError(
                    "Empty response content "
                    f"(finish_reason={choice.get('finish_reason')}, reasoning_chars={reasoning_length})"
                )
            content = content_value.strip()
            match = FENCE_RE.fullmatch(content)
            review = validate_review(json.loads(match.group(1) if match else content))
            return review, {
                "id": raw.get("id"), "model": raw.get("model"), "usage": raw.get("usage"),
                "created": raw.get("created"), "system_fingerprint": raw.get("system_fingerprint"),
                "finish_reason": raw.get("choices", [{}])[0].get("finish_reason"),
                "request_config": {
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                    "response_format": response_format,
                    "thinking": (
                        attempt_thinking if provider == "deepseek" else local_thinking
                    ),
                    "reasoning_effort": (
                        reasoning_effort
                        if provider == "deepseek" and attempt_thinking == "enabled"
                        else None
                    ),
                    "retry_attempt": attempt,
                },
                "prior_attempts": prior_attempts,
            }
        except (OSError, AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            prior_attempts.append({
                "attempt": attempt,
                "error_type": type(error).__name__,
                "error": str(error)[:500],
                "response_format": response_format,
                "thinking": (
                    attempt_thinking if provider == "deepseek" else local_thinking
                ),
            })
            if attempt == 3:
                break
            messages = messages[:2] + [{"role": "user", "content": (
                f"Correct the JSON schema error ({type(error).__name__}: {error}). "
                "Return only concise valid JSON with every criterion. The top-level "
                "behavior_family_assessment object is mandatory and must contain "
                "visible and hidden strings plus materially_distinct as the JSON "
                "boolean true or false (never a string)."
            )}]
            time.sleep(2**attempt + random.random() * 0.2)
    raise RuntimeError(f"Reviewer {model} failed: {last_error}")


def main() -> None:
    args = parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", args.report_id):
        raise ValueError("Invalid --report-id")
    if not args.confirm_machine_review:
        raise ValueError("Pass --confirm-machine-review")
    if args.prepare_only == bool(args.reviewer):
        raise ValueError("Choose exactly one of --prepare-only or --reviewer")
    task_file = checked(args.task_file)
    benchmark_file = checked(args.benchmark)
    oracle_file = checked(args.oracle_manifest)
    output = checked(args.output, exists=False)
    output.mkdir(parents=True, exist_ok=True)
    freeze = json.loads(task_file.read_text(encoding="utf-8"))
    task_ids = freeze["qualified_task_ids"]
    benchmark = {item["task_id"]: item for item in json.loads(benchmark_file.read_text(encoding="utf-8"))["tasks"]}
    oracle = json.loads(oracle_file.read_text(encoding="utf-8"))["tasks"]
    if set(task_ids) != set(oracle):
        raise RuntimeError("Partition freeze and oracle manifest task sets differ")

    packets = {}
    for task_id in task_ids:
        packet = build_packet(task_id, benchmark[task_id], oracle[task_id])
        path = output / "packets" / f"{task_id.replace('/', '__')}.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != packet:
            raise RuntimeError(f"Packet drift: {task_id}")
        write_json(path, packet)
        packets[task_id] = packet
    if args.prepare_only:
        write_json(output / "packet_manifest.json", {
            "schema_version": 1,
            "report_id": args.report_id,
            "task_file": record(task_file), "benchmark_manifest": record(benchmark_file), "oracle_manifest": record(oracle_file),
            "task_count": len(task_ids), "packets": {task: record(output / "packets" / f"{task.replace('/', '__')}.json") for task in task_ids},
            "blinded": True,
        })
        print(json.dumps({"prepared_packets": len(task_ids), "blinded": True}, indent=2))
        return

    packet_manifest_path = output / "packet_manifest.json"
    if not packet_manifest_path.is_file():
        raise FileNotFoundError(f"Prepare blinded packets first: {packet_manifest_path}")
    packet_manifest = json.loads(packet_manifest_path.read_text(encoding="utf-8"))
    prepared_report_id = packet_manifest.get(
        "report_id", "codeguardplus-partitioned-semantic-machine-panel-v1"
    )
    if prepared_report_id != args.report_id:
        raise RuntimeError("Semantic-review report identity drift")

    model, separator, api_base = args.reviewer.partition("=")
    if not separator or not model or not api_base:
        raise ValueError("Reviewer must be MODEL=API_BASE")
    api_key = None
    if args.provider == "local":
        if not api_base.startswith("http://127.0.0.1:"):
            raise ValueError("Local reviewer must use MODEL=http://127.0.0.1:PORT/v1")
        reviewer_kind = "local_language_model"
        external_data_transfer = False
    else:
        parsed = urllib.parse.urlparse(api_base)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.deepseek.com"
            or parsed.path.rstrip("/") not in {"", "/v1"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("DeepSeek reviewer API base must be https://api.deepseek.com or https://api.deepseek.com/v1")
        if model not in {"deepseek-v4-flash", "deepseek-v4-pro"}:
            raise ValueError("DeepSeek reviewer model must be deepseek-v4-flash or deepseek-v4-pro")
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise ValueError(f"DeepSeek credential is absent: set {args.api_key_env}")
        reviewer_kind = "external_language_model_api"
        external_data_transfer = True
    reviewer_metadata = {
        "kind": reviewer_kind,
        "provider": args.provider,
        "model": model,
        "human_reviewer": False,
        "external_data_transfer": external_data_transfer,
    }
    review_root = output / "reviews" / model
    completed_names = {path.name for path in review_root.glob("*.json")}
    futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for task_id in task_ids:
            name = f"{task_id.replace('/', '__')}.json"
            if name in completed_names:
                existing = json.loads((review_root / name).read_text(encoding="utf-8"))
                existing_reviewer = existing.get("reviewer", {})
                if (
                    existing_reviewer.get("model") != model
                    or existing_reviewer.get("provider", "local") != args.provider
                ):
                    raise RuntimeError(f"Reviewer identity drift: {review_root / name}")
                continue
            future = pool.submit(
                request_review,
                args.provider,
                model,
                api_base,
                api_key,
                packets[task_id],
                args.max_tokens,
                args.timeout_seconds,
                args.thinking,
                args.reasoning_effort,
                args.local_thinking,
            )
            futures[future] = task_id
        for future in concurrent.futures.as_completed(futures):
            task_id = futures[future]
            review, api = future.result()
            packet_path = output / "packets" / f"{task_id.replace('/', '__')}.json"
            destination = review_root / f"{task_id.replace('/', '__')}.json"
            write_json(destination, {
                "schema_version": 1,
                "reviewer": reviewer_metadata,
                "packet": record(packet_path), "review": review, "api": api,
                "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            })
            print(f"[{model}] {task_id}: {review['verdict']}", flush=True)

    model_roots = sorted(path for path in (output / "reviews").iterdir() if path.is_dir())
    complete_models = [path.name for path in model_roots if len(list(path.glob("*.json"))) == len(task_ids)]
    if len(complete_models) >= 2:
        reviewers = []
        for model_name in complete_models:
            sample = output / "reviews" / model_name / f"{task_ids[0].replace('/', '__')}.json"
            reviewers.append(json.loads(sample.read_text(encoding="utf-8"))["reviewer"])
        audits = {}
        unanimous = []
        for task_id in task_ids:
            name = f"{task_id.replace('/', '__')}.json"
            verdicts = {model_name: json.loads((output / "reviews" / model_name / name).read_text(encoding="utf-8"))["review"]["verdict"] for model_name in complete_models}
            panel = "accept" if set(verdicts.values()) == {"accept"} else ("reject" if "reject" in verdicts.values() else "needs_human")
            if panel == "accept":
                unanimous.append(task_id)
            audits[task_id] = {"machine_panel_verdict": panel, "reviewer_verdicts": verdicts, "reviews": {model_name: record(output / "reviews" / model_name / name) for model_name in complete_models}}
        report = {
            "schema_version": 1, "report_id": args.report_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "review_kind": "machine_assisted_blinded_panel",
            "independent_human_review_complete": False, "formal_g7_complete": False,
            "inputs": {"task_file": record(task_file), "benchmark_manifest": record(benchmark_file), "oracle_manifest": record(oracle_file)},
            "reviewers": reviewers,
            "summary": {"task_count": len(task_ids), "reviewer_count": len(complete_models), "unanimous_machine_accept_count": len(unanimous), "machine_reject_or_escalate_count": len(task_ids) - len(unanimous)},
            "unanimous_machine_accept_tasks": unanimous, "task_audit": audits,
        }
        write_json(output / "report.json", report)
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    else:
        print(json.dumps({"completed_reviewer": model, "complete_reviewer_count": len(complete_models), "report_pending": True}, indent=2))


if __name__ == "__main__":
    main()
