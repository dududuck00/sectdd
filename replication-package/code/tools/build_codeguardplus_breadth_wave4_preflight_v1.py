#!/usr/bin/env python3
"""Configure and build the fresh-seed wave4 G8 input freeze."""

from pathlib import Path

import build_codeguardplus_breadth_wave3_preflight_v1 as implementation


root = Path(__file__).resolve().parents[1]
implementation.TASK_FILE = root / "configs/benchmarks/codeguardplus_reserve_breadth_wave4_semantic_machine_v1.json"
implementation.SEMANTIC = root / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-machine-v1-freeze.json"
implementation.ORACLE = root / "oracles/codeguardplus_reserve_breadth_wave4/manifest.json"
implementation.CONFIG = root / "configs/experiments/codeguardplus_reserve_breadth_wave4_preflight_v1.json"
implementation.LOCK = root / "configs/experiments/codeguardplus_reserve_breadth_wave4_preflight_v1.lock.json"
implementation.VISIBLE = root / "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_visible_v1.json"
implementation.HIDDEN = root / "configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_hidden_v1.json"
implementation.PROMPTS = root / "configs/prompts/codeguardplus_reserve_breadth_wave4_preflight_v1"
implementation.SEEDS = [53047, 59053]
implementation.ORACLE_ID = "codeguardplus-reserve-breadth-wave4-preflight-v1"
implementation.STUDY_PHASE = "codeguardplus_reserve_breadth_wave4_model_preflight_v1"
implementation.EXPECTED_TRAJECTORY_COUNT = 32


if __name__ == "__main__":
    implementation.main()
