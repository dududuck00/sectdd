#!/usr/bin/env python3
"""Build a frozen candidate list from a completed SALLM reference audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = (
    PROJECT_ROOT
    / "artifacts"
    / "sallm-audit"
    / "reference-overlay-v1-001"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "benchmarks"
    / "manifests"
    / "sallm-reference-qualified-v1.json"
)
SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "sallm_reference_qualification.schema.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def project_path(path: Path, *, exists: bool) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path must be beneath {PROJECT_ROOT}: {resolved}") from exc
    if exists and not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_json(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def classify_result(result: dict[str, Any]) -> tuple[str, str]:
    status = result["status"]
    if status == "excluded_by_overlay":
        return "excluded", result["reason"]
    if status == "not_runnable":
        return "excluded", result["reason"]
    if status == "infrastructure_error":
        raise RuntimeError(
            f"Infrastructure error cannot be qualified: {result['task_id']}"
        )
    if status != "completed":
        raise ValueError(f"Unexpected task status: {status}")
    if result["functional_pass"] is not True:
        return "excluded", "reference_functional_failed"
    if result["security_pass"] is not False:
        return "excluded", "unsafe_reference_not_rejected"
    return "candidate", "functional_pass_and_unsafe_reference_rejected"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_manifest_path = run_dir / "run_manifest.json"
    results_path = run_dir / "results.jsonl"
    run_manifest = load_json(run_manifest_path)
    if run_manifest["status"] != "completed":
        raise RuntimeError("SALLM audit run is not complete")
    if run_manifest["source_mode"] != "manifest_reference":
        raise RuntimeError("Qualification requires manifest reference sources")
    if run_manifest.get("overlay") is None:
        raise RuntimeError("Qualification requires an audited overlay run")
    if sha256_file(results_path) != run_manifest["results"]["sha256"]:
        raise RuntimeError("SALLM result hash does not match run manifest")

    benchmark_path = project_path(
        PROJECT_ROOT / run_manifest["benchmark_manifest"]["path"],
        exists=True,
    )
    if (
        sha256_file(benchmark_path)
        != run_manifest["benchmark_manifest"]["sha256"]
    ):
        raise RuntimeError("Benchmark manifest changed after audit")
    overlay_path = project_path(
        PROJECT_ROOT / run_manifest["overlay"]["path"],
        exists=True,
    )
    if sha256_file(overlay_path) != run_manifest["overlay"]["sha256"]:
        raise RuntimeError("Audit overlay changed after execution")

    results = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    task_ids = [result["task_id"] for result in results]
    if len(task_ids) != len(set(task_ids)):
        raise RuntimeError("Audit results contain duplicate task IDs")
    if task_ids != run_manifest["task_ids"]:
        raise RuntimeError("Audit result ordering/tasks differ from run manifest")
    for result in results:
        for method in result["method_results"]:
            log_path = project_path(
                PROJECT_ROOT / method["log"]["path"],
                exists=True,
            )
            if sha256_file(log_path) != method["log"]["sha256"]:
                raise RuntimeError(f"Audit log changed: {log_path}")
    return run_manifest, results


def build_qualification(
    run_dir: Path,
    run_manifest: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    tasks = []
    reason_counts: Counter[str] = Counter()
    candidate_cwes = set()
    for result in results:
        decision, reason = classify_result(result)
        reason_counts[reason] += 1
        if decision == "candidate":
            candidate_cwes.add(result["cwe"])
        tasks.append(
            {
                "task_id": result["task_id"],
                "cwe": result["cwe"],
                "decision": decision,
                "reason_code": reason,
                "evidence": {
                    "execution_status": result["status"],
                    "functional_pass": result["functional_pass"],
                    "security_pass": result["security_pass"],
                    "joint_pass": result["joint_pass"],
                    "candidate_sha256": (
                        result.get("candidate", {}).get("sha256")
                    ),
                    "method_logs": [
                        {
                            "category": method["category"],
                            "method": method["method"],
                            "status": method["status"],
                            "sha256": method["log"]["sha256"],
                        }
                        for method in result["method_results"]
                    ],
                },
            }
        )

    candidate_count = sum(
        task["decision"] == "candidate" for task in tasks
    )
    run_manifest_path = run_dir / "run_manifest.json"
    results_path = run_dir / "results.jsonl"
    return {
        "$schema": SCHEMA_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "schema_version": 1,
        "manifest_type": "sallm_reference_oracle_qualification",
        "qualification_level": "reference_oracle_candidate",
        "formal_experiment_ready": False,
        "remaining_gate": (
            "Secure-reference and mutation audits are required before "
            "formal experiment qualification."
        ),
        "policy": {
            "candidate_requires": {
                "execution_status": "completed",
                "functional_pass": True,
                "security_pass": False,
            },
            "policy_version": 1,
        },
        "inputs": {
            "run_manifest": {
                "path": run_manifest_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": sha256_file(run_manifest_path),
            },
            "results": {
                "path": results_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": sha256_file(results_path),
            },
            "benchmark_manifest": run_manifest["benchmark_manifest"],
            "overlay": run_manifest["overlay"],
            "environment_sha256": run_manifest["python"][
                "installed_distributions_sha256"
            ],
        },
        "summary": {
            "task_count": len(tasks),
            "candidate_count": candidate_count,
            "excluded_count": len(tasks) - candidate_count,
            "candidate_cwe_count": len(candidate_cwes),
            "reason_counts": dict(sorted(reason_counts.items())),
        },
        "tasks": tasks,
    }


def main() -> None:
    args = parse_args()
    run_dir = project_path(args.run, exists=True)
    if not run_dir.is_dir():
        raise NotADirectoryError(run_dir)
    output = project_path(args.output, exists=False)
    run_manifest, results = verify_run(run_dir)
    qualification = build_qualification(run_dir, run_manifest, results)
    rendered = render_json(qualification)
    if args.check:
        if not output.is_file() or output.read_bytes() != rendered:
            raise SystemExit(f"Qualification manifest is stale: {output}")
        print(f"OK: {output} is current")
        return
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rendered)
    print(f"Wrote {output}")
    print(json.dumps(qualification["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
