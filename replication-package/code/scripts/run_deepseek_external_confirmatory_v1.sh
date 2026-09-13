#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-all}"
sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_api_base="${DEEPSEEK_API_BASE:-https://api.deepseek.com}"
sectdd_model="deepseek-v4-flash"
sectdd_tokenizer="<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct"
sectdd_root_out="artifacts/deepseek-external-confirmatory-v1"
sectdd_sallm_shards="${sectdd_root_out}/sallm-shards"
sectdd_sallm_run="${sectdd_root_out}/sallm"
sectdd_codeguard_run="${sectdd_root_out}/codeguardplus"
sectdd_sallm_config="configs/experiments/deepseek_sallm_external_confirmatory_v1.json"
sectdd_codeguard_config="configs/experiments/deepseek_codeguardplus_external_confirmatory_v1.json"

build_inputs() {
  "${sectdd_python}" tools/build_deepseek_external_confirmatory_v1.py
}

require_remote_authorization() {
  if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    echo "DEEPSEEK_API_KEY is not set. Export it in this shell; it is never written by this script." >&2
    exit 2
  fi
  if [[ "${SECTDD_CONFIRM_PAID_API:-0}" != "1" ]]; then
    echo "Set SECTDD_CONFIRM_PAID_API=1 to authorize paid API calls and external prompt transfer." >&2
    exit 2
  fi
  if [[ "${sectdd_api_base%/}" != "https://api.deepseek.com" ]]; then
    echo "Only the frozen official DeepSeek API base is accepted." >&2
    exit 2
  fi
}

run_sallm() {
  require_remote_authorization
  "${sectdd_python}" tools/run_sallm_task_shards.py \
    --served-model "${sectdd_model}" \
    --provider deepseek \
    --api-base "${sectdd_api_base}" \
    --api-key-env DEEPSEEK_API_KEY \
    --tokenizer "${sectdd_tokenizer}" \
    --config "${sectdd_sallm_config}" \
    --visible-projection configs/oracles/sallm_partitioned_oracle_v3_visible.json \
    --hidden-projection configs/oracles/sallm_partitioned_oracle_v3_hidden.json \
    --output-root "${sectdd_sallm_shards}" \
    --max-workers "${SECTDD_API_WORKERS:-2}" \
    --resume
  if [[ ! -f "${sectdd_sallm_run}/run_manifest.json" ]]; then
    "${sectdd_python}" tools/merge_sallm_formal_shards.py \
      "${sectdd_sallm_shards}" --output "${sectdd_sallm_run}"
  fi
  "${sectdd_python}" tools/validate_sallm_formal.py "${sectdd_sallm_run}"
}

run_codeguardplus() {
  require_remote_authorization
  "${sectdd_python}" tools/run_codeguardplus_preflight.py \
    --served-model "${sectdd_model}" \
    --provider deepseek \
    --api-base "${sectdd_api_base}" \
    --api-key-env DEEPSEEK_API_KEY \
    --tokenizer "${sectdd_tokenizer}" \
    --config "${sectdd_codeguard_config}" \
    --visible configs/oracles/codeguardplus_technical_confirmatory_no_g7_visible_v1.json \
    --hidden configs/oracles/codeguardplus_technical_confirmatory_no_g7_hidden_v1.json \
    --output "${sectdd_codeguard_run}" \
    --resume
}

analyze_and_freeze() {
  "${sectdd_python}" tools/validate_sallm_formal.py "${sectdd_sallm_run}"
  "${sectdd_python}" tools/analyze_sallm_main.py "${sectdd_sallm_run}" \
    --json-output "${sectdd_root_out}/sallm-report.json" \
    --markdown-output "${sectdd_root_out}/sallm-report.md" \
    --bootstrap-seed 20260806
  "${sectdd_python}" tools/analyze_codeguardplus_technical_confirmatory_v1.py \
    "${sectdd_codeguard_run}" \
    --json-output "${sectdd_root_out}/codeguardplus-report.json" \
    --markdown-output "${sectdd_root_out}/codeguardplus-report.md" \
    --bootstrap-seed 20260807
  "${sectdd_python}" tools/finalize_deepseek_external_confirmatory_v1.py
}

case "${sectdd_action}" in
  build)
    build_inputs
    ;;
  sallm)
    build_inputs
    run_sallm
    ;;
  codeguardplus)
    build_inputs
    run_codeguardplus
    ;;
  analyze)
    analyze_and_freeze
    ;;
  all)
    build_inputs
    run_sallm
    run_codeguardplus
    analyze_and_freeze
    ;;
  *)
    echo "Usage: $0 {build|sallm|codeguardplus|analyze|all}" >&2
    exit 2
    ;;
esac
