#!/usr/bin/env python3
"""Freeze DeepSeek external-confirmatory inputs without storing credentials."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SALLM_SOURCE = ROOT / "configs/experiments/sallm_partitioned_main_v1_1.json"
CODEGUARD_SOURCE = ROOT / "configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.json"
SALLM_CONFIG = ROOT / "configs/experiments/deepseek_sallm_external_confirmatory_v1.json"
CODEGUARD_CONFIG = ROOT / "configs/experiments/deepseek_codeguardplus_external_confirmatory_v1.json"
LOCK = ROOT / "configs/experiments/deepseek_external_confirmatory_v1.lock.json"
SALLM_VISIBLE = ROOT / "configs/oracles/sallm_partitioned_oracle_v3_visible.json"
SALLM_HIDDEN = ROOT / "configs/oracles/sallm_partitioned_oracle_v3_hidden.json"
CODEGUARD_VISIBLE = ROOT / "configs/oracles/codeguardplus_technical_confirmatory_no_g7_visible_v1.json"
CODEGUARD_HIDDEN = ROOT / "configs/oracles/codeguardplus_technical_confirmatory_no_g7_hidden_v1.json"

MODEL = "deepseek-v4-flash"
REQUEST_SLOTS = [83003, 89009, 97001, 101009, 103043]
EXCLUDED_PRIOR_SEEDS = [
    17, 101, 202, 303, 404, 505, 606, 707, 808, 909, 1001, 1701,
    2903, 8113, 9277, 13007, 17011, 23011, 29021, 41017, 47059,
    53047, 59053, 61057, 67061, 71069, 73079, 79087,
]
TOKENIZER_PROXY = "<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def model_record() -> dict:
    return {
        "provider": "deepseek",
        "remote_model": True,
        "remote_model_id": MODEL,
        "api_base": "https://api.deepseek.com",
        "family": "DeepSeek",
        "parameter_scale": "undisclosed_api",
        "tokenizer_proxy": TOKENIZER_PROXY,
        "tokenizer_accounting": "local_proxy_for_budget_only",
        "max_model_len": 16384,
    }


def build(source: Path, destination: Path, benchmark: str) -> dict:
    value = json.loads(source.read_text(encoding="utf-8"))
    value.update(
        {
            "schema_version": 3,
            "protocol_revision": "deepseek-external-v1",
            "supersedes": None,
            "pilot_only": False,
            "development_only": False,
            "formal_experiment": False,
            "formal_results_use": False,
            "technical_confirmatory": True,
            "study_phase": f"{benchmark}_deepseek_external_confirmatory_v1",
            "readiness_note": (
                "Non-Qwen remote-API robustness check. Request-slot IDs are "
                "frozen but are not sent as deterministic provider seeds."
            ),
            "generation_seeds": REQUEST_SLOTS,
            "generation_request_slots": REQUEST_SLOTS,
            "models": {MODEL: model_record()},
            "remote_provider": {
                "credential_env": "DEEPSEEK_API_KEY",
                "credential_persisted": False,
                "provider_seed_supported": False,
                "request_slot_policy": (
                    "IDs identify independent paid sampling requests and pair "
                    "shared initial candidates; they do not claim API determinism."
                ),
                "external_data_transfer": True,
            },
        }
    )
    value.pop("amendment_reason", None)
    generation = value["generation"]
    generation["model_overrides"] = {
        MODEL: {"extra_body": {"thinking": {"type": "disabled"}}}
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value


def main() -> None:
    if set(REQUEST_SLOTS) & set(EXCLUDED_PRIOR_SEEDS):
        raise RuntimeError("Fresh request slots overlap prior generation seeds")
    if not Path(TOKENIZER_PROXY).joinpath("tokenizer_config.json").is_file():
        raise FileNotFoundError(f"Tokenizer proxy is incomplete: {TOKENIZER_PROXY}")
    sallm = build(SALLM_SOURCE, SALLM_CONFIG, "sallm")
    codeguard = build(CODEGUARD_SOURCE, CODEGUARD_CONFIG, "codeguardplus")
    methods = len(sallm["methods"])
    expected_sallm = len(sallm["tasks"]) * methods * len(REQUEST_SLOTS)
    expected_codeguard = len(codeguard["tasks"]) * methods * len(REQUEST_SLOTS)
    frozen_files = {
        "sallm_config": record(SALLM_CONFIG),
        "sallm_visible": record(SALLM_VISIBLE),
        "sallm_hidden": record(SALLM_HIDDEN),
        "codeguardplus_config": record(CODEGUARD_CONFIG),
        "codeguardplus_visible": record(CODEGUARD_VISIBLE),
        "codeguardplus_hidden": record(CODEGUARD_HIDDEN),
    }
    lock = {
        "schema_version": 1,
        "lock_id": "deepseek-external-confirmatory-v1",
        "frozen_before_generation": True,
        "formal_results_use": False,
        "technical_confirmatory": True,
        "model": MODEL,
        "provider": "deepseek",
        "credential_env": "DEEPSEEK_API_KEY",
        "credential_persisted": False,
        "external_data_transfer": True,
        "paid_api_confirmation_required": True,
        "provider_seed_supported": False,
        "generation_request_slots": REQUEST_SLOTS,
        "excluded_prior_generation_seeds": EXCLUDED_PRIOR_SEEDS,
        "fresh_seed_overlap_count": 0,
        "expected": {
            "sallm_trajectories": expected_sallm,
            "codeguardplus_trajectories": expected_codeguard,
            "total_trajectories": expected_sallm + expected_codeguard,
            "maximum_paid_model_calls": (
                (len(sallm["tasks"]) + len(codeguard["tasks"]))
                * len(REQUEST_SLOTS) * 11
            ),
        },
        "frozen_files": frozen_files,
        "interpretation_boundary": (
            "External non-Qwen technical confirmation; not a deterministic-seed "
            "replication and not human-G7-qualified formal evidence."
        ),
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock["expected"], indent=2))
    print(f"Frozen lock: {LOCK.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
