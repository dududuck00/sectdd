#!/usr/bin/env bash
set -euo pipefail
export SECTDD_G8_CONFIG=configs/experiments/codeguardplus_reserve_breadth_wave4_preflight_v1.json
export SECTDD_G8_LOCK=configs/experiments/codeguardplus_reserve_breadth_wave4_preflight_v1.lock.json
export SECTDD_G8_VISIBLE=configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_visible_v1.json
export SECTDD_G8_HIDDEN=configs/oracles/codeguardplus_reserve_breadth_wave4_preflight_hidden_v1.json
export SECTDD_G8_PROMPTS=configs/prompts/codeguardplus_reserve_breadth_wave4_preflight_v1
export SECTDD_G8_QUALIFIED=configs/benchmarks/codeguardplus_reserve_breadth_wave4_preflight_qualified_v1.json
export SECTDD_G8_FREEZE=benchmarks/manifests/codeguardplus-reserve-breadth-wave4-preflight-v1-freeze.json
export SECTDD_G8_OUTPUT=artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/g8-preflight-v1
export SECTDD_G8_MARKDOWN=docs/codeguardplus-reserve-breadth-wave4-g8-preflight-v1.md
export SECTDD_G8_BUILDER=tools/build_codeguardplus_breadth_wave4_preflight_v1.py
export SECTDD_G8_FREEZER=tools/freeze_codeguardplus_breadth_wave4_preflight_v1.py
export SECTDD_G8_REPORT_ID=codeguardplus-reserve-breadth-wave4-preflight-v1
export SECTDD_G8_TITLE="CodeGuard+ reserve breadth-wave4 G8 preflight v1"
export SECTDD_G8_PER_MODEL=16
export SECTDD_G8_LOG_TAG=codeguardplus-breadth-wave4-g8
export SECTDD_G8_COMPLETION_LABEL=Breadth-wave4
export SECTDD_PORT_7B="${SECTDD_PORT_7B:-19080}"
export SECTDD_PORT_14B="${SECTDD_PORT_14B:-19081}"
exec "$(dirname "$0")/run_codeguardplus_reserve_breadth_wave3_g8_preflight_v1.sh"
