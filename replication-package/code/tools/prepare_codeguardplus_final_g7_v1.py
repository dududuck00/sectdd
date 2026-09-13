#!/usr/bin/env python3
"""Prepare a result-blinded independent-human G7 packet bundle.

The reviewer bundle deliberately omits task IDs, author-model identities,
candidate paths, construction outcomes, G8 trajectories, seeds, and method
effects.  A private manifest retains the provenance mapping for later audit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks/manifests/codeguardplus-v1.json"
OUTPUT = ROOT / "artifacts/codeguardplus-final-g7-v1"
BUNDLE = OUTPUT / "reviewer_bundle"
PRIVATE_MANIFEST = OUTPUT / "packet_manifest.private.json"
BUNDLE_MANIFEST = BUNDLE / "packet_manifest.json"
REVIEW_TEMPLATE = BUNDLE / "review_submission.template.json"
INSTRUCTIONS = BUNDLE / "REVIEWER_INSTRUCTIONS.md"
FREEZE = ROOT / "benchmarks/manifests/codeguardplus-final-g7-packet-v1-freeze.json"

TASK_SOURCES = (
    {
        "packet_id": "G7-A",
        "task_id": "cwe-089/2-py",
        "oracle": "oracles/codeguardplus_reserve_partitioned_v2/manifest.json",
        "preflight_freeze": "benchmarks/manifests/codeguardplus-reserve-preflight-v2-freeze.json",
    },
    {
        "packet_id": "G7-B",
        "task_id": "cwe-117/2-py",
        "oracle": "oracles/codeguardplus_reserve_breadth_wave4/manifest.json",
        "preflight_freeze": "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-preflight-v1-freeze.json",
    },
    {
        "packet_id": "G7-C",
        "task_id": "cwe-327/2-py",
        "oracle": "oracles/codeguardplus_partitioned_v2/manifest.json",
        "preflight_freeze": "benchmarks/manifests/codeguardplus-preflight-v1-freeze.json",
    },
)

CWE_SOURCES = {
    "CWE-89": {
        "title": "Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')",
        "url": "https://cwe.mitre.org/data/definitions/89.html",
    },
    "CWE-117": {
        "title": "Improper Output Neutralization for Logs",
        "url": "https://cwe.mitre.org/data/definitions/117.html",
    },
    "CWE-327": {
        "title": "Use of a Broken or Risky Cryptographic Algorithm",
        "url": "https://cwe.mitre.org/data/definitions/327.html",
    },
}

CRITERIA = (
    "public_context_contract_consistency",
    "cwe_alignment",
    "safe_functionality_preservation",
    "safe_security_mitigation",
    "mutant_functionality_preservation",
    "mutant_reintroduces_target_cwe",
    "visible_oracle_semantic_validity",
    "hidden_oracle_semantic_validity",
    "visible_hidden_behavior_family_independence",
    "implementation_independent_assertions",
    "deterministic_offline_bounded_execution",
)

ATTESTATION = (
    "I completed this review independently, did not author the reviewed artifacts, "
    "and did not inspect model-preflight outcomes before recording my decisions."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    path.relative_to(ROOT)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def checked_record(value: dict[str, Any]) -> tuple[dict[str, Any], str]:
    path = (ROOT / value["path"]).resolve()
    path.relative_to(ROOT)
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256(path) != value["sha256"] or path.stat().st_size != value["size_bytes"]:
        raise RuntimeError(f"Frozen source drift: {path}")
    return record(path), path.read_text(encoding="utf-8")


def write_frozen(path: Path, value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"Frozen G7 artifact drift: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def verify_preflight(task_id: str, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("qualified_task_ids") != [task_id]:
        raise RuntimeError(f"Unexpected G8-qualified task set in {path}")
    if not freeze.get("model_preflight_complete"):
        raise RuntimeError(f"G8 is incomplete: {path}")
    if freeze.get("formal_experiment_ready") is not False:
        raise RuntimeError("Preflight evidence must remain development-only")
    if freeze.get("independent_human_review_complete") is not False:
        raise RuntimeError("G7 was already or incorrectly claimed complete")
    report_record = freeze["outputs"]["report"]
    _, report_text = checked_record(report_record)
    report = json.loads(report_text)
    if report.get("qualified_tasks") != [task_id]:
        raise RuntimeError(f"G8 report/freeze disagreement for {task_id}")
    if report.get("formal_experiment_results") is not False:
        raise RuntimeError("G8 report must not be formal experimental evidence")
    return freeze, report


def make_packet(packet_id: str, benchmark: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    public_context: dict[str, str] = {}
    for name in ("file_context", "function_context", "info"):
        _, public_context[name] = checked_record(benchmark["source"][name])
    reviewed_artifacts: dict[str, str] = {}
    for output_name, source_name in (
        ("safe_implementation", "safe_reference"),
        ("targeted_vulnerability_mutant", "vulnerability_mutant"),
        ("visible_test", "visible_test"),
        ("hidden_test", "hidden_test"),
    ):
        _, reviewed_artifacts[output_name] = checked_record(oracle[source_name])
    packet = {
        "schema_version": 1,
        "packet_id": packet_id,
        "language": benchmark["language"],
        "cwe": benchmark["cwe"],
        "authoritative_cwe": CWE_SOURCES[benchmark["cwe"]],
        "declared_contract": oracle["contract"],
        "declared_behavior_families": oracle["families"],
        "public_context": public_context,
        "reviewed_artifacts": reviewed_artifacts,
        "expected_semantics": {
            "safe_implementation": "functional pass and security pass",
            "targeted_vulnerability_mutant": "functional pass and security fail",
            "visible_and_hidden_tests": "each contains a functional and a security case; behavior families must be materially distinct",
        },
        "review_criteria": list(CRITERIA),
        "blinding": {
            "task_id_included": False,
            "source_paths_included": False,
            "author_model_identity_included": False,
            "candidate_attempt_index_included": False,
            "construction_execution_outcomes_included": False,
            "model_preflight_outcomes_included": False,
            "generation_seeds_included": False,
            "method_effects_included": False,
        },
    }
    serialized = json.dumps(packet, ensure_ascii=False).lower()
    for forbidden in ("deepseek", "qwen", "seed_", "trajectory_count", "joint_repair_count"):
        if forbidden in serialized:
            raise RuntimeError(f"Blinding leak in {packet_id}: {forbidden}")
    return packet


def review_template(packet_records: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "review_id": "REPLACE_WITH_REVIEW_ID",
        "packet_bundle_manifest_sha256": sha256(BUNDLE_MANIFEST),
        "reviewer": {
            "reviewer_id": "REPLACE_WITH_PSEUDONYM_OR_ID",
            "human_reviewer": True,
            "independent_second_researcher": True,
            "authored_any_reviewed_artifact": False,
            "accessed_model_preflight_outcomes_before_decisions": False,
            "conflicts_declared": True,
        },
        "reviewed_at_utc": "REPLACE_WITH_ISO_8601_UTC_TIMESTAMP",
        "attestation": ATTESTATION,
        "reviews": {
            packet_id: {
                "packet_sha256": value["sha256"],
                "verdict": "REPLACE_WITH_accept_OR_reject",
                "summary": "REPLACE_WITH_CONCISE_SEMANTIC_ASSESSMENT",
                "criteria": {
                    criterion: {"passed": None, "evidence": "REPLACE_WITH_CODE_OR_TEST_EVIDENCE"}
                    for criterion in CRITERIA
                },
                "critical_issues": [],
            }
            for packet_id, value in packet_records.items()
        },
    }


def instructions_text() -> str:
    criteria = "\n".join(f"- `{item}`" for item in CRITERIA)
    return f"""# CodeGuard+ final G7 independent review v1

Review only the three `G7-*.json` files and `packet_manifest.json` in this
directory. Do not open `packet_manifest.private.json`, G8 reports,
trajectories, method summaries, or model outputs before recording decisions.

For each packet, determine whether the public context, contract, CWE, safe
implementation, targeted mutant, and both test partitions are semantically
consistent. Passing a supplied test is not sufficient: reject tests that
overfit one implementation, permit reject-everything behavior, exercise the
wrong CWE, duplicate visible/hidden attack mechanisms, access the network, or
depend on unbounded/probabilistic behavior.

Frozen criteria:

{criteria}

Copy `review_submission.template.json` to `review_submission.json`. Replace
every placeholder and every null criterion. An `accept` decision requires all
criteria to pass. For a reject, mark failed criteria and describe critical
issues. The reviewer must be a human second researcher who did not author the
reviewed implementation, mutant, or tests.

The exact attestation text must remain unchanged. Submit the completed JSON;
the validator will check packet hashes and schema. This G7 review does not use
or disclose preflight outcomes and does not itself make the formal experiment
ready; a separate final design freeze is still required.
"""


def main() -> None:
    benchmark_document = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    benchmark_tasks = {item["task_id"]: item for item in benchmark_document["tasks"]}
    private_tasks: dict[str, Any] = {}
    packet_records: dict[str, Any] = {}
    source_freezes: dict[str, Any] = {}

    for source in TASK_SOURCES:
        packet_id = source["packet_id"]
        task_id = source["task_id"]
        oracle_path = ROOT / source["oracle"]
        preflight_path = ROOT / source["preflight_freeze"]
        verify_preflight(task_id, preflight_path)
        oracle_document = json.loads(oracle_path.read_text(encoding="utf-8"))
        oracle = oracle_document["tasks"].get(task_id)
        if oracle is None or benchmark_tasks[task_id]["cwe"] != oracle["cwe"]:
            raise RuntimeError(f"Benchmark/oracle mismatch for {task_id}")
        packet = make_packet(packet_id, benchmark_tasks[task_id], oracle)
        packet_path = BUNDLE / f"{packet_id}.json"
        write_frozen(packet_path, packet)
        packet_records[packet_id] = record(packet_path)
        source_freezes[packet_id] = record(preflight_path)
        private_tasks[packet_id] = {
            "task_id": task_id,
            "cwe": oracle["cwe"],
            "oracle_manifest": record(oracle_path),
            "preflight_freeze": record(preflight_path),
            "reviewed_source_records": {
                name: oracle[name]
                for name in ("safe_reference", "vulnerability_mutant", "visible_test", "hidden_test")
            },
        }

    bundle_manifest = {
        "schema_version": 1,
        "bundle_id": "codeguardplus-final-g7-v1",
        "packet_count": len(packet_records),
        "packets": packet_records,
        "review_criteria": list(CRITERIA),
        "result_blinded": True,
        "private_task_mapping_included": False,
    }
    write_frozen(BUNDLE_MANIFEST, bundle_manifest)
    write_frozen(REVIEW_TEMPLATE, review_template(packet_records))
    instruction = instructions_text()
    if INSTRUCTIONS.exists() and INSTRUCTIONS.read_text(encoding="utf-8") != instruction:
        raise RuntimeError(f"Frozen G7 instruction drift: {INSTRUCTIONS}")
    INSTRUCTIONS.write_text(instruction, encoding="utf-8")

    private_manifest = {
        "schema_version": 1,
        "bundle_id": "codeguardplus-final-g7-v1",
        "benchmark_manifest": record(BENCHMARK),
        "reviewer_bundle_manifest": record(BUNDLE_MANIFEST),
        "review_template": record(REVIEW_TEMPLATE),
        "reviewer_instructions": record(INSTRUCTIONS),
        "tasks": private_tasks,
        "blinding_boundary": "Do not provide this private manifest to the independent reviewer before decisions are frozen.",
    }
    write_frozen(PRIVATE_MANIFEST, private_manifest)

    created = datetime.now(timezone.utc).isoformat()
    if FREEZE.exists():
        created = json.loads(FREEZE.read_text(encoding="utf-8"))["created_at_utc"]
    freeze = {
        "schema_version": 1,
        "freeze_id": "codeguardplus-final-g7-packet-v1",
        "created_at_utc": created,
        "status": "independent_human_g7_pending",
        "formal_experiment_ready": False,
        "independent_human_review_complete": False,
        "model_preflight_complete": True,
        "packet_count": len(packet_records),
        "source_preflight_freezes": source_freezes,
        "outputs": {
            "private_manifest": record(PRIVATE_MANIFEST),
            "reviewer_bundle_manifest": record(BUNDLE_MANIFEST),
            "review_template": record(REVIEW_TEMPLATE),
            "reviewer_instructions": record(INSTRUCTIONS),
        },
        "formal_readiness_blockers": [
            "independent second-researcher semantic review (G7)",
            "final prompt/oracle/model/method/budget/confirmatory-seed freeze",
        ],
    }
    write_frozen(FREEZE, freeze)
    print(json.dumps({
        "prepared_packet_count": len(packet_records),
        "result_blinded": True,
        "independent_human_review_complete": False,
        "formal_experiment_ready": False,
        "reviewer_bundle": BUNDLE.relative_to(ROOT).as_posix(),
    }, indent=2))


if __name__ == "__main__":
    main()
