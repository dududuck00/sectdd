#!/usr/bin/env python3
"""Validate and freeze the development-only CodeGuard+ Python smoke evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "artifacts/codeguardplus-smoke/python-v2"
DEFAULT_OUTPUT = (
    ROOT
    / "benchmarks/manifests/codeguardplus-python-smoke-v1-freeze.json"
)
CONFIG = ROOT / "configs/benchmarks/codeguardplus_python_smoke_v1.json"
SOURCE_INPUTS = (
    CONFIG,
    ROOT / "benchmarks/manifests/codeguardplus-v1.json",
    ROOT / "requirements/codeguardplus-audit-v1-lock.txt",
    ROOT / "scripts/bootstrap_codeguardplus_env.sh",
    ROOT / "scripts/bootstrap_codeguardplus_codeql.sh",
    ROOT / "tools/codeguardplus_bwrap.py",
    ROOT / "tools/freeze_codeguardplus_smoke.py",
    ROOT / "tests/test_codeguardplus_bwrap.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    path.relative_to(ROOT)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    run = args.run.expanduser().resolve()
    output = args.output.expanduser().resolve()
    run.relative_to(ROOT)
    output.relative_to(ROOT)
    if output.exists():
        raise FileExistsError(output)

    config = load_json(CONFIG)
    run_manifest = load_json(run / "run_manifest.json")
    summary = load_json(run / "summary.json")
    results = [
        json.loads(line)
        for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    expected_ids = [item["task_id"] for item in config["tasks"]]
    observed_ids = [item["task_id"] for item in results]
    if run_manifest.get("tasks") != expected_ids:
        raise RuntimeError("Run task order differs from the frozen smoke config")
    if run_manifest.get("repeats") != 1 or observed_ids != expected_ids:
        raise RuntimeError("Smoke evidence is not the exact six-task, one-repeat grid")
    if any(item.get("status") != "completed" for item in results):
        raise RuntimeError("Smoke contains infrastructure/oracle errors")
    if not summary.get("complete") or summary.get("result_count") != len(expected_ids):
        raise RuntimeError("Smoke summary is incomplete")
    if (
        config.get("formal_results_use") is not False
        or run_manifest.get("formal_results_use") is not False
        or summary.get("formal_results_use") is not False
    ):
        raise RuntimeError("Smoke must remain excluded from formal results")

    expected_candidates = {
        item["task_id"]: item["candidate"] for item in config["tasks"]
    }
    for item in results:
        expected = expected_candidates[item["task_id"]]
        candidate = item["candidate"]
        if candidate["sha256"] != expected["sha256"]:
            raise RuntimeError(f"Candidate drift: {item['task_id']}")

    run_files = sorted(path for path in run.rglob("*") if path.is_file())
    payload = {
        "schema_version": 1,
        "manifest_type": "codeguardplus_python_smoke_freeze",
        "freeze_id": "codeguardplus-python-smoke-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "formal_results_use": False,
        "repository_commit": config["repository_commit"],
        "task_ids": expected_ids,
        "state_counts": summary["state_counts"],
        "status_counts": summary["status_counts"],
        "source_files": [record(path) for path in SOURCE_INPUTS],
        "run_files": [record(path) for path in run_files],
        "python_environment": run_manifest["python_environment"],
        "codeql_environment": run_manifest["codeql_environment"],
        "sandbox": run_manifest["sandbox"],
        "interpretation": (
            "Infrastructure compatibility evidence only. Benchmark-supplied "
            "test_case.py candidates are not secure references and these results "
            "must not enter formal method-effect analyses."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "frozen", "output": record(output)}, indent=2))


if __name__ == "__main__":
    main()
