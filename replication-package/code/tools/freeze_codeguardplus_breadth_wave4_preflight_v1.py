#!/usr/bin/env python3
"""Configure and freeze completed wave4 G8 evidence."""

from pathlib import Path

import freeze_codeguardplus_breadth_wave3_preflight_v1 as implementation


root = Path(__file__).resolve().parents[1]
implementation.RUN_ROOT = root / "artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/g8-preflight-v1"
implementation.REPORT = implementation.RUN_ROOT / "report.json"
implementation.LOCK = root / "configs/experiments/codeguardplus_reserve_breadth_wave4_preflight_v1.lock.json"
implementation.QUALIFIED = root / "configs/benchmarks/codeguardplus_reserve_breadth_wave4_preflight_qualified_v1.json"
implementation.SEMANTIC = root / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-machine-v1-freeze.json"
implementation.FREEZE = root / "benchmarks/manifests/codeguardplus-reserve-breadth-wave4-preflight-v1-freeze.json"
implementation.SEEDS = [53047, 59053]
implementation.LOCK_ID = "codeguardplus-reserve-breadth-wave4-preflight-v1"
implementation.REPORT_ID = implementation.LOCK_ID
implementation.FREEZE_ID = implementation.LOCK_ID
implementation.EXPECTED_TOTAL = 32
implementation.EXPECTED_PER_MODEL = 16


if __name__ == "__main__":
    implementation.main()
