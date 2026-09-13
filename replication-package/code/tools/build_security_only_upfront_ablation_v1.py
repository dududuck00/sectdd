#!/usr/bin/env python3
"""Freeze the post-primary security-only upfront ablation before generation."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ("sallm", "codeguardplus")
CONFIG_DIR = ROOT / "configs/experiments"
FREEZE = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-input-freeze.json"
RELOCATION = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-checkpoint-relocation.json"
QWEN36_RELOCATION = ROOT / "benchmarks/manifests/security-only-upfront-ablation-v1-qwen36-checkpoint-relocation.json"
B7 = {
    "name": "Security Tests Upfront",
    "security_reminder": False,
    "upfront_tests": "security",
    "feedback": "none",
    "max_calls": 1,
    "shared_initial_from": None,
}
PROJECTIONS = {
    "sallm": (
        ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json",
        ROOT / "configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json",
    ),
    "codeguardplus": (
        ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json",
        ROOT / "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json",
    ),
}
RELOCATED_MODELS = {
    "qwen25-coder-7b": "<MODEL_ROOT>/Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen25-coder-14b": "<MODEL_ROOT>/Qwen/Qwen2.5-Coder-14B-Instruct",
    "qwen36-27b": "<MODEL_ROOT>/Qwen/Qwen3.6-27B",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha(path),
        "size_bytes": path.stat().st_size,
    }


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def audit_projection(benchmark: str, path: Path, tasks: list[str]) -> dict[str, Any]:
    projection = json.loads(path.read_text(encoding="utf-8"))
    if projection.get("partition") != "visible":
        raise RuntimeError(f"Not a visible projection: {path}")
    counts = {}
    for task in tasks:
        cases = projection["tasks"][task]["cases"]
        security = [case for case in cases if case.get("marker") == "security"]
        functional = [
            case
            for case in cases
            if case.get("marker") in {"functional", "functionality"}
        ]
        if not security or not functional:
            raise RuntimeError(f"{benchmark}/{task}: incomplete visible marker families")
        security_methods = {
            case.get("test_name") or case.get("test_method") for case in security
        }
        functional_methods = {
            case.get("test_name") or case.get("test_method") for case in functional
        }
        if security_methods & functional_methods:
            raise RuntimeError(f"{benchmark}/{task}: marker/test-method overlap")
        counts[task] = {
            "functional_cases_withheld": len(functional),
            "security_cases_exposed": len(security),
        }
    return counts


def main() -> None:
    if FREEZE.is_file():
        frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
        relocation = json.loads(RELOCATION.read_text(encoding="utf-8")) if RELOCATION.is_file() else None
        qwen36_relocation = (
            json.loads(QWEN36_RELOCATION.read_text(encoding="utf-8"))
            if QWEN36_RELOCATION.is_file()
            else None
        )
        if relocation is not None:
            for model in ("qwen25-coder-7b", "qwen25-coder-14b"):
                checkpoint = Path(relocation["path_relocations"][model]["to"])
                for name, expected in relocation["checkpoint_identity_sha256"][model].items():
                    path = checkpoint / name
                    if not path.is_file() or sha(path) != expected:
                        raise RuntimeError(f"Relocated checkpoint identity mismatch: {path}")
        qwen36_identity_pending = False
        if qwen36_relocation is not None:
            model = "qwen36-27b"
            checkpoint = Path(qwen36_relocation["path_relocations"][model]["to"])
            identity = qwen36_relocation["checkpoint_identity_sha256"][model]
            if all((checkpoint / name).is_file() for name in identity):
                for name, expected in identity.items():
                    path = checkpoint / name
                    if sha(path) != expected:
                        raise RuntimeError(f"Relocated checkpoint identity mismatch: {path}")
            else:
                qwen36_identity_pending = True
        for benchmark in BENCHMARKS:
            for key in ("base_config", "ablation_config", "visible_projection", "hidden_projection"):
                item = frozen["configs"][benchmark][key]
                path = ROOT / item["path"]
                expected = item["sha256"]
                if key == "ablation_config" and relocation is not None:
                    if relocation["original_frozen_config_sha256"][benchmark] != expected:
                        raise RuntimeError("Checkpoint relocation does not match the pre-result freeze")
                    expected = relocation["relocated_config_sha256"][benchmark]
                    if qwen36_relocation is not None:
                        if qwen36_relocation["original_config_sha256"][benchmark] != expected:
                            raise RuntimeError("Qwen3.6 relocation does not match the prior authorized config")
                        expected = qwen36_relocation["relocated_config_sha256"][benchmark]
                if not path.is_file() or sha(path) != expected:
                    raise RuntimeError(
                        f"Frozen input drift ({benchmark}/{key}): {path}. "
                        "Do not overwrite the pre-result freeze."
                    )
        print("Resume: pre-result ablation freeze and authorized checkpoint relocation are valid.")
        if qwen36_identity_pending:
            print("Qwen3.6-27B download is incomplete; its identity will be enforced before generation.")
        print(json.dumps(frozen["scope"], indent=2))
        return
    configs = {}
    total_tasks = 0
    for benchmark in BENCHMARKS:
        base_path = CONFIG_DIR / f"{benchmark}_paper_expansion_full_v1.json"
        output_path = CONFIG_DIR / f"{benchmark}_security_only_upfront_ablation_v1.json"
        base = json.loads(base_path.read_text(encoding="utf-8"))
        for required in ("B0", "B2", "B3"):
            if required not in base["methods"]:
                raise RuntimeError(f"{base_path}: missing {required}")
        value = copy.deepcopy(base)
        value["schema_version"] = 1
        value["study_phase"] = f"{benchmark}_security_only_upfront_ablation_v1"
        value["methods"] = {"B7": B7}
        for model, checkpoint in RELOCATED_MODELS.items():
            value["models"][model]["checkpoint"] = checkpoint
        value["models"]["deepseek-v4-flash"]["tokenizer_proxy"] = RELOCATED_MODELS[
            "qwen25-coder-14b"
        ]
        value["post_primary_addendum"] = True
        value["formal_results_use"] = True
        value["selection_policy"] = (
            "Reuse every SALLM/CodeGuard+ task, model, and repetition from the "
            "balanced primary grid; no task selection or pilot outcome filter"
        )
        value["ablation_design"] = {
            "factorial": "visible functional tests present/absent x visible security tests present/absent",
            "archived_conditions": {"none": "B0", "functional_only": "B2", "both": "B3"},
            "new_condition": {"security_only": "B7"},
            "primary_outcome": "hidden_joint_at_1",
            "inference_unit": "task",
            "bootstrap_clusters": "task",
            "bootstrap_replicates": 10000,
            "disclosure": "Hypothesis-driven addendum frozen after the original primary analysis and before B7 generation",
        }
        value["statistics"]["paired_comparisons"] = [
            "B2_vs_B0",
            "B7_vs_B0",
            "B3_vs_B0",
            "B3_vs_B2",
            "B3_vs_B7",
            "factorial_functional_main_effect",
            "factorial_security_main_effect",
            "factorial_interaction",
        ]
        write(output_path, value)
        visible, hidden = PROJECTIONS[benchmark]
        visible_counts = audit_projection(benchmark, visible, value["tasks"])
        if json.loads(hidden.read_text(encoding="utf-8")).get("partition") != "hidden":
            raise RuntimeError(f"Not a hidden projection: {hidden}")
        expected = len(value["tasks"]) * len(value["models"]) * len(value["generation_seeds"])
        total_tasks += len(value["tasks"])
        configs[benchmark] = {
            "base_config": record(base_path),
            "ablation_config": record(output_path),
            "visible_projection": record(visible),
            "hidden_projection": record(hidden),
            "tasks": value["tasks"],
            "models": list(value["models"]),
            "request_slots": value["generation_seeds"],
            "visible_case_audit": visible_counts,
            "expected_new_trajectories": expected,
            "expected_new_model_calls": expected,
        }
    freeze = {
        "schema_version": 1,
        "freeze_id": "security-only-upfront-ablation-v1-input",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "post_primary_addendum": True,
        "results_observed_at_freeze": False,
        "scope": {
            "benchmarks": list(BENCHMARKS),
            "task_count": total_tasks,
            "model_count": 4,
            "repetitions_per_cell": 5,
            "new_condition": "B7-security-tests-only-upfront",
            "new_trajectory_count": sum(item["expected_new_trajectories"] for item in configs.values()),
            "factorial_trajectory_count_including_archived_B0_B2_B3": 4 * 4 * 5 * total_tasks,
        },
        "configs": configs,
        "interpretation_boundary": (
            "This hypothesis-driven ablation was specified after inspection of the "
            "original primary results but before any B7 response. It strengthens RQ1 "
            "mechanism decomposition and is reported as a post-primary addendum."
        ),
    }
    write(FREEZE, freeze)
    print(json.dumps(freeze["scope"], indent=2))


if __name__ == "__main__":
    main()
