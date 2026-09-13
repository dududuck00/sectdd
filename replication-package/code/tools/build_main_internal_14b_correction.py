#!/usr/bin/env python3
"""Freeze the corrected Qwen2.5-Coder-14B-Instruct internal-main condition."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v2.json"
OUTPUT = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.json"
LOCK = ROOT / "configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.lock.json"
VISIBLE = ROOT / "configs/oracles/cweval_py_paper_candidate_v2_visible.json"
HIDDEN = ROOT / "configs/oracles/cweval_py_paper_candidate_v2_hidden.json"
CORRECT_MODEL = Path("<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct")
INVALID_RUN = ROOT / "artifacts/main_internal/qwen25-coder-14b-main-002/run_manifest.json"
VALID_PEERS = {
    "qwen25-coder-7b": ROOT / "artifacts/main_internal/qwen25-coder-7b-main-002/run_manifest.json",
    "qwen3-32b": ROOT / "artifacts/main_internal/qwen3-32b-main-002/run_manifest.json",
}
EXPECTED_SOURCE_SHA256 = "6a4a0b878b0e2aa91c32ae7814f24fc4e3d975b17b612b5f02e26eecfef49eb3"
EXPECTED_MODEL_HASHES = {
    "config.json": "9051fe83840dcd3a0f7e9f5b3372fc3927419eb56983273eac2dc635a5da7eae",
    "generation_config.json": "fdaccbcb02f3e1e7914ccb0f69ebe899071ffd27cf825166d823163e156870f2",
    "model.safetensors.index.json": "425811015c8708208c9efc04c4cfae250c7927a1b04c99dda5a9121caf4bf77a",
    "tokenizer.json": "c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
    "tokenizer_config.json": "959e7f1d9a1b7641a6d6ce05ca97b75c7894fcb66cbe5a040406458fb1128ee4",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "size_bytes": path.stat().st_size}


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    for path in (SOURCE, VISIBLE, HIDDEN, INVALID_RUN, *VALID_PEERS.values()):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (OUTPUT, LOCK):
        if path.exists():
            raise FileExistsError(path)
    if digest(SOURCE) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("The original frozen config changed")
    observed_model_hashes = {}
    for name, expected in EXPECTED_MODEL_HASHES.items():
        path = CORRECT_MODEL / name
        observed_model_hashes[name] = digest(path)
        if observed_model_hashes[name] != expected:
            raise RuntimeError(f"Corrected model identity mismatch: {name}")

    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    invalid_path = config["models"]["qwen25-coder-14b"]["checkpoint"]
    if invalid_path == str(CORRECT_MODEL):
        raise RuntimeError("Source config does not contain the checkpoint defect")
    config["models"]["qwen25-coder-14b"]["checkpoint"] = str(CORRECT_MODEL)
    write(OUTPUT, config)

    source_normalized = json.loads(SOURCE.read_text(encoding="utf-8"))
    corrected_normalized = json.loads(OUTPUT.read_text(encoding="utf-8"))
    source_normalized["models"]["qwen25-coder-14b"]["checkpoint"] = "<QWEN25_CODER_14B_INSTRUCT>"
    corrected_normalized["models"]["qwen25-coder-14b"]["checkpoint"] = "<QWEN25_CODER_14B_INSTRUCT>"
    if source_normalized != corrected_normalized:
        raise RuntimeError("Correction changed more than the 14B checkpoint path")

    invalid_manifest = json.loads(INVALID_RUN.read_text(encoding="utf-8"))
    invalid_config_hash = invalid_manifest["model_freeze"]["files_sha256"]["config.json"]
    if invalid_config_hash == EXPECTED_MODEL_HASHES["config.json"]:
        raise RuntimeError("Excluded run unexpectedly used the corrected checkpoint")
    lock = {
        "schema_version": 1,
        "lock_id": "main-internal-v3-14b-checkpoint-correction",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_rerun": True,
        "correction_scope": "Only the qwen25-coder-14b checkpoint path is changed; tasks, methods, seeds, prompts, budgets, and oracles are identical to v2.",
        "excluded_condition": {
            "reason": "The main-002 14B run used the old Base-checkpoint path while labeled as Instruct.",
            "run_manifest": record(INVALID_RUN),
            "recorded_config_sha256": invalid_config_hash,
        },
        "inputs": {
            "source_config": record(SOURCE),
            "corrected_config": record(OUTPUT),
            "visible_projection": record(VISIBLE),
            "hidden_projection": record(HIDDEN),
            "valid_peer_runs": {model: record(path) for model, path in VALID_PEERS.items()},
        },
        "corrected_model": {
            "checkpoint": str(CORRECT_MODEL),
            "files_sha256": observed_model_hashes,
        },
        "expected_shape": {"tasks": 9, "methods": 7, "seeds": 5, "trajectories": 315},
    }
    write(LOCK, lock)
    print(json.dumps({"config": record(OUTPUT), "lock": record(LOCK), "expected_trajectories": 315}, indent=2))


if __name__ == "__main__":
    main()
