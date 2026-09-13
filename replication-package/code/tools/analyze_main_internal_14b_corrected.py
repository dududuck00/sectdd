#!/usr/bin/env python3
"""Analyze the internal main after replacing only the invalid 14B condition."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import analyze_main_internal as base


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v2.json"
CORRECTED_CONFIG = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.json"
LOCK = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.lock.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs=3, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260728)
    return parser.parse_args()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    args = parse_args()
    for path in (args.json_output, args.markdown_output):
        if path.exists():
            raise FileExistsError(path)
    runs = [base.load_run(path) for path in args.run_dirs]
    by_model = {run["manifest"]["model"]: run for run in runs}
    expected_models = {"qwen25-coder-7b", "qwen25-coder-14b", "qwen3-32b"}
    if set(by_model) != expected_models:
        raise RuntimeError("Corrected report requires the exact three-model grid")
    source = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    corrected = json.loads(CORRECTED_CONFIG.read_text(encoding="utf-8"))
    for value in (source, corrected):
        value["models"]["qwen25-coder-14b"]["checkpoint"] = "<QWEN25_CODER_14B_INSTRUCT>"
    if source != corrected:
        raise RuntimeError("Frozen configs are not design-equivalent")
    source_hash = digest(SOURCE_CONFIG)
    corrected_hash = digest(CORRECTED_CONFIG)
    for model, run in by_model.items():
        expected_hash = corrected_hash if model == "qwen25-coder-14b" else source_hash
        if run["manifest"]["input_sha256"]["config"] != expected_hash:
            raise RuntimeError(f"Unexpected config hash for {model}")
    projection_hashes = [
        (run["manifest"]["input_sha256"]["visible_projection"], run["manifest"]["input_sha256"]["hidden_projection"])
        for run in runs
    ]
    if len(set(projection_hashes)) != 1:
        raise RuntimeError("Runs do not share the frozen oracle projections")
    seeds = [run["manifest"]["seeds"] for run in runs]
    if len({tuple(value) for value in seeds}) != 1:
        raise RuntimeError("Runs do not share generation seeds")

    rng = random.Random(args.bootstrap_seed)
    models = {
        model: base.analyze_model(by_model[model], args.bootstrap_replicates, rng)
        for model in ("qwen25-coder-7b", "qwen25-coder-14b", "qwen3-32b")
    }
    report = {
        "schema_version": 1,
        "study_phase": "main_internal_confirmatory_14b_checkpoint_corrected",
        "primary_metric": "hidden_secure_pass_at_1",
        "development_results_included": False,
        "checkpoint_correction": {
            "lock": {"path": LOCK.relative_to(ROOT).as_posix(), "sha256": digest(LOCK)},
            "excluded_run": "artifacts/main_internal/qwen25-coder-14b-main-002",
            "replacement_run": str(by_model["qwen25-coder-14b"]["run_dir"]),
            "design_equivalent_except_14b_checkpoint_path": True,
        },
        "design": {"models": 3, "tasks": 9, "methods": 7, "seeds": seeds[0], "trajectory_count": 945},
        "immutable_inputs": {
            "config_sha256_by_model": {model: run["manifest"]["input_sha256"]["config"] for model, run in by_model.items()},
            "oracle_projection_sha256": {"visible": projection_hashes[0][0], "hidden": projection_hashes[0][1]},
            "canonical_oracle_manifest_sha256": runs[0]["manifest"]["canonical_oracle_manifest_sha256"],
        },
        "statistics": {
            "inference_unit": "task", "bootstrap_replicates": args.bootstrap_replicates,
            "bootstrap_seed": args.bootstrap_seed, "confidence_level": 0.95,
            "paired_test": "exact_sign_flip_permutation", "multiple_comparison_correction": "holm_within_model",
        },
        "models": models,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    note = (
        "# Protocol v2 内部确认性主实验（14B checkpoint 校正版）\n\n"
        "main-002 中错误标记为 Instruct 的 14B 条件已排除；本报告以相同任务、"
        "方法、seeds、预算和 oracle 下重跑的正确 Instruct 条件替换它。\n\n"
    )
    rendered = base.markdown(report)
    rendered = rendered.split("\n", 2)[2]
    args.markdown_output.write_text(note + rendered, encoding="utf-8")
    print(json.dumps({"models": list(models), "trajectory_count": 945, "json": str(args.json_output), "markdown": str(args.markdown_output)}, indent=2))


if __name__ == "__main__":
    main()
