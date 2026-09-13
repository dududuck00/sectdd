#!/usr/bin/env python3
"""Validate a real independent-human G7 submission and freeze its decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import prepare_codeguardplus_final_g7_v1 as protocol


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_MANIFEST = ROOT / "artifacts/codeguardplus-final-g7-v1/packet_manifest.private.json"
BUNDLE_MANIFEST = ROOT / "artifacts/codeguardplus-final-g7-v1/reviewer_bundle/packet_manifest.json"
QUALIFIED = ROOT / "configs/benchmarks/codeguardplus_final_g7_qualified_v1.json"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-final-g7-v1-freeze.json"
REPORT = ROOT / "docs/codeguardplus-final-g7-v1.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-submission", type=Path, required=True)
    parser.add_argument("--confirm-independent-human-review", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    path.relative_to(ROOT)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Existing G7 freeze drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or value.startswith("REPLACE_"):
        raise ValueError("reviewed_at_utc must be a real ISO-8601 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at_utc must include a timezone")


def validate_submission(submission: dict[str, Any], bundle: dict[str, Any]) -> None:
    if submission.get("schema_version") != 1:
        raise ValueError("Unsupported review schema")
    if not isinstance(submission.get("review_id"), str) or submission["review_id"].startswith("REPLACE_"):
        raise ValueError("A real review_id is required")
    if submission.get("packet_bundle_manifest_sha256") != sha256(BUNDLE_MANIFEST):
        raise ValueError("Reviewer bundle hash mismatch")
    reviewer = submission.get("reviewer")
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("human_reviewer") is not True
        or reviewer.get("independent_second_researcher") is not True
        or reviewer.get("conflicts_declared") is not True
    ):
        raise ValueError("A real independent human reviewer and conflict declaration are required")
    if reviewer.get("authored_any_reviewed_artifact") is not False:
        raise ValueError("The reviewer must not have authored reviewed artifacts")
    if reviewer.get("accessed_model_preflight_outcomes_before_decisions") is not False:
        raise ValueError("The review must remain blind to model-preflight outcomes")
    reviewer_id = reviewer.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip() or reviewer_id.startswith("REPLACE_"):
        raise ValueError("A reviewer pseudonym or ID is required")
    if submission.get("attestation") != protocol.ATTESTATION:
        raise ValueError("The exact independent-review attestation is required")
    validate_timestamp(submission.get("reviewed_at_utc"))
    reviews = submission.get("reviews")
    if not isinstance(reviews, dict) or set(reviews) != set(bundle["packets"]):
        raise ValueError("Every frozen packet must be reviewed exactly once")
    for packet_id, review in reviews.items():
        if review.get("packet_sha256") != bundle["packets"][packet_id]["sha256"]:
            raise ValueError(f"Packet hash mismatch: {packet_id}")
        if review.get("verdict") not in {"accept", "reject"}:
            raise ValueError(f"Final accept/reject verdict required: {packet_id}")
        if not isinstance(review.get("summary"), str) or review["summary"].startswith("REPLACE_"):
            raise ValueError(f"A substantive summary is required: {packet_id}")
        criteria = review.get("criteria")
        if not isinstance(criteria, dict) or set(criteria) != set(protocol.CRITERIA):
            raise ValueError(f"Frozen rubric mismatch: {packet_id}")
        for name, item in criteria.items():
            if not isinstance(item, dict) or not isinstance(item.get("passed"), bool):
                raise ValueError(f"Boolean criterion decision required: {packet_id}/{name}")
            evidence = item.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip() or evidence.startswith("REPLACE_"):
                raise ValueError(f"Criterion evidence required: {packet_id}/{name}")
        if review["verdict"] == "accept" and not all(item["passed"] for item in criteria.values()):
            raise ValueError(f"Accepted packet has a failed criterion: {packet_id}")
        issues = review.get("critical_issues")
        if not isinstance(issues, list):
            raise ValueError(f"critical_issues must be a list: {packet_id}")
        if review["verdict"] == "reject" and not issues:
            raise ValueError(f"Rejected packet requires at least one critical issue: {packet_id}")


def main() -> None:
    args = parse_args()
    if not args.confirm_independent_human_review:
        raise ValueError("Pass --confirm-independent-human-review only after a real second researcher signs")
    submission_path = args.review_submission.expanduser().resolve()
    submission_path.relative_to(ROOT)
    if not submission_path.is_file():
        raise FileNotFoundError(submission_path)
    private = json.loads(PRIVATE_MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE_MANIFEST.read_text(encoding="utf-8"))
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    validate_submission(submission, bundle)

    accepted_packets = [packet for packet, review in submission["reviews"].items() if review["verdict"] == "accept"]
    rejected_packets = [packet for packet in bundle["packets"] if packet not in accepted_packets]
    accepted_tasks = [private["tasks"][packet]["task_id"] for packet in accepted_packets]
    rejected_tasks = [private["tasks"][packet]["task_id"] for packet in rejected_packets]
    reviewer_id = submission["reviewer"]["reviewer_id"]
    blockers = ["final prompt/oracle/model/method/budget/confirmatory-seed freeze"]
    if not accepted_tasks:
        blockers.insert(0, "no task passed independent human G7")

    qualified = {
        "schema_version": 1,
        "oracle_set_id": "codeguardplus-final-g7-v1",
        "independent_human_review_complete": True,
        "formal_experiment_ready": False,
        "tasks": accepted_tasks,
        "rejected_tasks": rejected_tasks,
        "remaining_gates": blockers,
    }
    write_json(QUALIFIED, qualified)
    freeze = {
        "schema_version": 1,
        "freeze_id": "codeguardplus-final-g7-v1",
        "created_at_utc": submission["reviewed_at_utc"],
        "status": "g7_complete_final_experiment_freeze_pending" if accepted_tasks else "g7_complete_no_tasks_qualified",
        "formal_experiment_ready": False,
        "independent_human_review_complete": True,
        "human_reviewer_id": reviewer_id,
        "accepted_task_ids": accepted_tasks,
        "rejected_task_ids": rejected_tasks,
        "summary": {
            "reviewed_task_count": len(bundle["packets"]),
            "accepted_task_count": len(accepted_tasks),
            "rejected_task_count": len(rejected_tasks),
        },
        "inputs": {
            "private_packet_manifest": record(PRIVATE_MANIFEST),
            "reviewer_bundle_manifest": record(BUNDLE_MANIFEST),
            "human_review_submission": record(submission_path),
        },
        "outputs": {"qualified_tasks": record(QUALIFIED)},
        "formal_readiness_blockers": blockers,
    }
    write_json(FREEZE, freeze)
    rows = [
        "# CodeGuard+ final independent-human G7 v1",
        "",
        "## Outcome",
        "",
        f"Independent reviewer `{reviewer_id}` reviewed {len(bundle['packets'])} result-blinded packets.",
        f"Accepted: {len(accepted_tasks)}; rejected: {len(rejected_tasks)}.",
        "",
        "| Task | CWE | Decision |",
        "|---|---|---|",
    ]
    for packet_id in bundle["packets"]:
        task = private["tasks"][packet_id]
        rows.append(f"| `{task['task_id']}` | {task['cwe']} | {submission['reviews'][packet_id]['verdict']} |")
    rows += [
        "",
        "## Boundary",
        "",
        "G7 completion does not reuse G8 trajectories as formal evidence. The formal experiment remains blocked until prompt, oracle, model, method, budget, and untouched confirmatory seeds are frozen.",
        "",
    ]
    rendered = "\n".join(rows)
    if REPORT.exists() and REPORT.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Existing G7 report drift: {REPORT}")
    REPORT.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "independent_human_review_complete": True,
        "reviewed_task_count": len(bundle["packets"]),
        "accepted_task_count": len(accepted_tasks),
        "rejected_task_count": len(rejected_tasks),
        "formal_experiment_ready": False,
    }, indent=2))


if __name__ == "__main__":
    main()
