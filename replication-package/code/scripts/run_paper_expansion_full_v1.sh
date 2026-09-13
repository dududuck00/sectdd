#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-status}"
sectdd_model="${2:-}"
sectdd_gpu="${SECTDD_GPU:-2}"
sectdd_port="${SECTDD_PORT:-19480}"
sectdd_workers="${SECTDD_MAX_WORKERS:-3}"
sectdd_output_root="artifacts/paper-expansion-full-v1"
sectdd_server_pid=""

sectdd_cleanup() {
  if [[ -n "${sectdd_server_pid}" ]] && kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    kill "${sectdd_server_pid}" 2>/dev/null || true
    wait "${sectdd_server_pid}" 2>/dev/null || true
  fi
}
trap sectdd_cleanup EXIT INT TERM

sectdd_config() { printf 'configs/experiments/%s_paper_expansion_full_v1.json\n' "$1"; }
sectdd_visible() { printf 'configs/oracles/%s\n' "$1"; }

sectdd_inputs() {
  local benchmark="$1"
  case "${benchmark}" in
    cweval)
      sectdd_cfg="$(sectdd_config cweval)"
      sectdd_vis="$(sectdd_visible cweval_py_paper_expansion_v1_semantic_machine_visible.json)"
      sectdd_hid="$(sectdd_visible cweval_py_paper_expansion_v1_semantic_machine_hidden.json)"
      ;;
    sallm)
      sectdd_cfg="$(sectdd_config sallm)"
      sectdd_vis="$(sectdd_visible sallm_paper_expansion_v1_semantic_machine_visible.json)"
      sectdd_hid="$(sectdd_visible sallm_paper_expansion_v1_semantic_machine_hidden.json)"
      ;;
    codeguardplus)
      sectdd_cfg="$(sectdd_config codeguardplus)"
      sectdd_vis="$(sectdd_visible codeguardplus_paper_expansion_v1_semantic_machine_visible.json)"
      sectdd_hid="$(sectdd_visible codeguardplus_paper_expansion_v1_semantic_machine_hidden.json)"
      ;;
    *) echo "Unknown benchmark: ${benchmark}" >&2; exit 2 ;;
  esac
  for path in "${sectdd_cfg}" "${sectdd_vis}" "${sectdd_hid}"; do
    [[ -f "${path}" ]] || { echo "Missing frozen input: ${path}; finish oracle construction first." >&2; exit 2; }
  done
}

sectdd_model_inputs() {
  case "${sectdd_model}" in
    qwen25-coder-7b)
      sectdd_provider=local
      sectdd_tokenizer=<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct
      sectdd_server_kind=qwen25
      sectdd_server_variant=7b
      ;;
    qwen25-coder-14b)
      sectdd_provider=local
      sectdd_tokenizer=<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct
      sectdd_server_kind=qwen25
      sectdd_server_variant=14b
      ;;
    qwen36-27b)
      sectdd_provider=local
      sectdd_tokenizer=<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B
      sectdd_server_kind=qwen36
      sectdd_server_variant=27b
      ;;
    deepseek-v4-flash)
      sectdd_provider=deepseek
      sectdd_tokenizer=<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct
      sectdd_server_kind=none
      sectdd_server_variant=none
      ;;
    *)
      echo "Model must be qwen25-coder-7b, qwen25-coder-14b, qwen36-27b, or deepseek-v4-flash." >&2
      exit 2
      ;;
  esac
  [[ -f "${sectdd_tokenizer}/config.json" ]] || { echo "Incomplete model/tokenizer checkpoint: ${sectdd_tokenizer}" >&2; exit 2; }
}

sectdd_assert_gpu() {
  local count used
  count="$(nvidia-smi -L | wc -l)"
  [[ "${sectdd_gpu}" =~ ^[0-9]+$ && "${sectdd_gpu}" -lt "${count}" ]] || { echo "Invalid GPU ${sectdd_gpu}; server exposes ${count}." >&2; exit 2; }
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  [[ -n "${used}" && "${used}" -le "${SECTDD_MAX_USED_MIB:-2048}" ]] || { echo "GPU ${sectdd_gpu} is not sufficiently free: ${used:-unknown} MiB." >&2; exit 3; }
}

sectdd_wait_model() {
  local attempt
  for attempt in $(seq 1 240); do
    kill -0 "${sectdd_server_pid}" 2>/dev/null || { tail -n 120 "${sectdd_server_log}" >&2 || true; exit 3; }
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null | .venv/bin/python -c 'import json,sys; wanted=sys.argv[1]; raise SystemExit(0 if wanted in {x.get("id") for x in json.load(sys.stdin).get("data",[])} else 1)' "${sectdd_model}" 2>/dev/null; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    (( attempt % 12 != 0 )) || echo "Still waiting for ${sectdd_model}..."
    sleep 5
  done
  tail -n 120 "${sectdd_server_log}" >&2 || true
  exit 3
}

sectdd_start_server() {
  [[ "${sectdd_provider}" == local ]] || return
  sectdd_assert_gpu
  mkdir -p "${sectdd_output_root}/logs"
  sectdd_server_log="${sectdd_output_root}/logs/server-${sectdd_model}-${sectdd_port}.log"
  if [[ "${sectdd_server_kind}" == qwen25 ]]; then
    SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=8192 \
      scripts/serve_qwen25_coder.sh "${sectdd_server_variant}" >"${sectdd_server_log}" 2>&1 &
  else
    SECTDD_GPUS="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=16384 SECTDD_MAX_NUM_SEQS=64 \
      scripts/serve_qwen36.sh "${sectdd_server_variant}" >"${sectdd_server_log}" 2>&1 &
  fi
  sectdd_server_pid=$!
  sectdd_wait_model
}

sectdd_count() {
  local root="$1"
  [[ -d "${root}/trajectories" ]] || { echo 0; return; }
  find "${root}/trajectories" -type f -name trajectory.json | wc -l
}

sectdd_expected() {
  .venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["tasks"])*len(d["methods"])*len(d["generation_seeds"]))' "${sectdd_cfg}"
}

sectdd_merge() {
  local benchmark="$1" shards="$2" run="$3" expected="$4"
  if [[ -f "${run}/run_manifest.json" && "$(sectdd_count "${run}")" -eq "${expected}" ]]; then
    echo "Resume: merged run is complete: ${run}"
    return
  fi
  if [[ -e "${run}" ]]; then
    local quarantine="${run}.incomplete.$(date -u +%Y%m%dT%H%M%SZ)"
    mv "${run}" "${quarantine}"
    echo "Preserved incomplete merged output at ${quarantine}"
  fi
  case "${benchmark}" in
    cweval) .venv/bin/python tools/merge_formal_shards.py "${shards}" --output "${run}" ;;
    sallm) .venv/bin/python tools/merge_sallm_formal_shards.py "${shards}" --output "${run}" ;;
    codeguardplus) .venv/bin/python tools/merge_codeguardplus_shards.py "${shards}" --output "${run}" ;;
  esac
  [[ "$(sectdd_count "${run}")" -eq "${expected}" ]] || { echo "Merged trajectory count mismatch for ${run}" >&2; exit 3; }
  case "${benchmark}" in
    cweval) .venv/bin/python tools/validate_formal_pilot.py "${run}" ;;
    sallm) .venv/bin/python tools/validate_sallm_formal.py "${run}" ;;
  esac
}

sectdd_run() {
  local benchmark="$1"
  sectdd_inputs "${benchmark}"
  sectdd_model_inputs
  local out="${sectdd_output_root}/${benchmark}/${sectdd_model}"
  local shards="${out}-shards"
  local expected
  expected="$(sectdd_expected)"
  if [[ -f "${out}/run_manifest.json" && "$(sectdd_count "${out}")" -eq "${expected}" ]]; then
    echo "Resume: ${benchmark}/${sectdd_model} already complete (${expected}/${expected})."
    return
  fi
  if [[ "${sectdd_provider}" == deepseek ]]; then
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "DEEPSEEK_API_KEY is required and is never persisted." >&2; exit 2; }
    [[ "${SECTDD_CONFIRM_PAID_API:-0}" == 1 ]] || { echo "Set SECTDD_CONFIRM_PAID_API=1 to authorize paid requests and external prompt transfer." >&2; exit 2; }
    sectdd_api=https://api.deepseek.com
  else
    sectdd_start_server
    sectdd_api="http://127.0.0.1:${sectdd_port}/v1"
  fi
  mkdir -p "${sectdd_output_root}/${benchmark}"
  case "${benchmark}" in
    cweval)
      .venv/bin/python tools/run_task_shards.py \
        --served-model "${sectdd_model}" --provider "${sectdd_provider}" --api-base "${sectdd_api}" \
        --tokenizer "${sectdd_tokenizer}" --config "${sectdd_cfg}" \
        --visible-projection "${sectdd_vis}" --hidden-projection "${sectdd_hid}" \
        --output-root "${shards}" --max-workers "${sectdd_workers}" --resume
      ;;
    sallm)
      .venv/bin/python tools/run_sallm_task_shards.py \
        --served-model "${sectdd_model}" --provider "${sectdd_provider}" --api-base "${sectdd_api}" \
        --tokenizer "${sectdd_tokenizer}" --config "${sectdd_cfg}" \
        --visible-projection "${sectdd_vis}" --hidden-projection "${sectdd_hid}" \
        --output-root "${shards}" --max-workers "${sectdd_workers}" --resume
      ;;
    codeguardplus)
      .venv/bin/python tools/run_codeguardplus_task_shards.py \
        --served-model "${sectdd_model}" --provider "${sectdd_provider}" --api-base "${sectdd_api}" \
        --tokenizer "${sectdd_tokenizer}" --config "${sectdd_cfg}" \
        --visible "${sectdd_vis}" --hidden "${sectdd_hid}" \
        --output-root "${shards}" --max-workers "${sectdd_workers}" --resume
      ;;
  esac
  sectdd_cleanup
  sectdd_server_pid=""
  sectdd_merge "${benchmark}" "${shards}" "${out}" "${expected}"
  echo "Completed ${benchmark}/${sectdd_model}: ${out}"
}

sectdd_status() {
  local benchmark model cfg expected run actual
  for benchmark in cweval sallm codeguardplus; do
    cfg="$(sectdd_config "${benchmark}")"
    if [[ ! -f "${cfg}" ]]; then
      echo "${benchmark}: configuration pending oracle construction"
      continue
    fi
    expected="$(.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["tasks"])*len(d["methods"])*len(d["generation_seeds"]))' "${cfg}")"
    for model in qwen25-coder-7b qwen25-coder-14b qwen36-27b deepseek-v4-flash; do
      run="${sectdd_output_root}/${benchmark}/${model}"
      actual="$(sectdd_count "${run}")"
      echo "${benchmark}/${model}: ${actual}/${expected}"
    done
  done
}

case "${sectdd_action}" in
  build) .venv/bin/python tools/build_paper_expansion_full_configs_v1.py --allow-more-tasks ;;
  build-qualified) .venv/bin/python tools/build_paper_expansion_full_configs_v1.py --allow-more-tasks --accept-qualified-shortfall ;;
  cweval|sallm|codeguardplus)
    [[ -n "${sectdd_model}" ]] || { echo "Usage: $0 ${sectdd_action} MODEL" >&2; exit 2; }
    sectdd_run "${sectdd_action}"
    ;;
  status) sectdd_status ;;
  analyze) .venv/bin/python tools/analyze_paper_expansion_full_v1.py ;;
  all-local)
    for benchmark in cweval sallm codeguardplus; do
      for model in qwen25-coder-7b qwen25-coder-14b qwen36-27b; do
        "${BASH_SOURCE[0]}" "${benchmark}" "${model}"
      done
    done
    ;;
  all-deepseek)
    sectdd_require_paid_api_missing=0
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || sectdd_require_paid_api_missing=1
    [[ "${SECTDD_CONFIRM_PAID_API:-0}" == 1 ]] || sectdd_require_paid_api_missing=1
    [[ "${sectdd_require_paid_api_missing}" == 0 ]] || { echo "DEEPSEEK_API_KEY and SECTDD_CONFIRM_PAID_API=1 are required." >&2; exit 2; }
    for benchmark in cweval sallm codeguardplus; do
      "${BASH_SOURCE[0]}" "${benchmark}" deepseek-v4-flash
    done
    ;;
  all)
    "${BASH_SOURCE[0]}" all-local
    "${BASH_SOURCE[0]}" all-deepseek
    "${BASH_SOURCE[0]}" analyze
    ;;
  *)
    echo "Usage: $0 {build|build-qualified|status|analyze|all-local|all-deepseek|all|cweval MODEL|sallm MODEL|codeguardplus MODEL}" >&2
    exit 2
    ;;
esac
