#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-all}"
sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_gpu="${SECTDD_GPU_14B:-2}"
sectdd_port="${SECTDD_PORT_14B:-19381}"
sectdd_local_workers="${SECTDD_LOCAL_WORKERS:-3}"
sectdd_api_workers="${SECTDD_API_WORKERS:-2}"
sectdd_model="qwen25-coder-14b"
sectdd_remote_model="deepseek-v4-flash"
sectdd_tokenizer="<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct"
sectdd_config="configs/experiments/codeguardplus_breadth_confirmatory_v1.json"
sectdd_visible="configs/oracles/codeguardplus_breadth_confirmatory_visible_v1.json"
sectdd_hidden="configs/oracles/codeguardplus_breadth_confirmatory_hidden_v1.json"
sectdd_output="artifacts/codeguardplus-breadth-confirmatory-v1"
sectdd_qwen_shards="${sectdd_output}/qwen25-coder-14b-shards"
sectdd_qwen_run="${sectdd_output}/qwen25-coder-14b"
sectdd_deepseek_shards="${sectdd_output}/deepseek-v4-flash-shards"
sectdd_deepseek_run="${sectdd_output}/deepseek-v4-flash"
sectdd_expected=330
sectdd_server_pid=""

sectdd_cleanup() {
  if [[ -n "${sectdd_server_pid}" ]] && kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    kill "${sectdd_server_pid}" 2>/dev/null || true
    wait "${sectdd_server_pid}" 2>/dev/null || true
  fi
}
trap sectdd_cleanup EXIT INT TERM

sectdd_build() {
  "${sectdd_python}" tools/build_codeguardplus_breadth_confirmatory_v1.py
}

sectdd_count() {
  local directory="$1/trajectories"
  [[ -d "${directory}" ]] || { echo 0; return; }
  find "${directory}" -type f -name trajectory.json | wc -l
}

sectdd_assert_gpu() {
  local count used
  count="$(nvidia-smi -L | wc -l)"
  [[ "${sectdd_gpu}" =~ ^[0-9]+$ && "${sectdd_gpu}" -lt "${count}" ]] || { echo "Invalid GPU index ${sectdd_gpu}; server exposes ${count} GPUs." >&2; exit 2; }
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  [[ -n "${used}" && "${used}" -le 2048 ]] || { echo "GPU ${sectdd_gpu} is not free: ${used:-unknown} MiB" >&2; exit 3; }
}

sectdd_wait_model() {
  local attempt
  for attempt in $(seq 1 240); do
    kill -0 "${sectdd_server_pid}" 2>/dev/null || { tail -n 120 "${sectdd_output}/qwen-server.log" >&2 || true; return 3; }
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null | "${sectdd_python}" -c 'import json,sys; model=sys.argv[1]; print(int(model in {x.get("id") for x in json.load(sys.stdin).get("data",[])}))' "${sectdd_model}" 2>/dev/null | grep -qx 1; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    (( attempt % 12 != 0 )) || echo "Still waiting for ${sectdd_model}..."
    sleep 5
  done
  tail -n 120 "${sectdd_output}/qwen-server.log" >&2 || true
  return 3
}

sectdd_merge_if_needed() {
  local shards="$1" destination="$2"
  if [[ ! -f "${destination}/run_manifest.json" ]]; then
    "${sectdd_python}" tools/merge_codeguardplus_shards.py "${shards}" --output "${destination}"
  elif [[ "$(sectdd_count "${destination}")" -ne "${sectdd_expected}" ]]; then
    echo "Merged run is incomplete: ${destination}. Preserve it for audit and move it aside before re-merging." >&2
    exit 3
  else
    echo "Resume: merged run already contains ${sectdd_expected} trajectories: ${destination}"
  fi
}

sectdd_run_qwen() {
  if [[ -f "${sectdd_qwen_run}/run_manifest.json" && "$(sectdd_count "${sectdd_qwen_run}")" -eq "${sectdd_expected}" ]]; then
    echo "Resume: Qwen14B breadth run complete."
    return
  fi
  sectdd_assert_gpu
  mkdir -p "${sectdd_output}"
  SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=8192 \
    scripts/serve_qwen25_coder.sh 14b >"${sectdd_output}/qwen-server.log" 2>&1 &
  sectdd_server_pid=$!
  sectdd_wait_model
  "${sectdd_python}" tools/run_codeguardplus_task_shards.py \
    --served-model "${sectdd_model}" --provider local \
    --api-base "http://127.0.0.1:${sectdd_port}/v1" \
    --tokenizer "${sectdd_tokenizer}" --config "${sectdd_config}" \
    --visible "${sectdd_visible}" --hidden "${sectdd_hidden}" \
    --output-root "${sectdd_qwen_shards}" --max-workers "${sectdd_local_workers}" --resume
  sectdd_cleanup
  sectdd_server_pid=""
  sectdd_merge_if_needed "${sectdd_qwen_shards}" "${sectdd_qwen_run}"
}

sectdd_require_paid_api() {
  [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "DEEPSEEK_API_KEY is not set; export it in this shell. It is never persisted." >&2; exit 2; }
  [[ "${SECTDD_CONFIRM_PAID_API:-0}" == "1" ]] || { echo "Set SECTDD_CONFIRM_PAID_API=1 to authorize up to 770 paid calls and external prompt transfer." >&2; exit 2; }
}

sectdd_run_deepseek() {
  if [[ -f "${sectdd_deepseek_run}/run_manifest.json" && "$(sectdd_count "${sectdd_deepseek_run}")" -eq "${sectdd_expected}" ]]; then
    echo "Resume: DeepSeek breadth run complete."
    return
  fi
  sectdd_require_paid_api
  "${sectdd_python}" tools/run_codeguardplus_task_shards.py \
    --served-model "${sectdd_remote_model}" --provider deepseek \
    --api-base "https://api.deepseek.com" --api-key-env DEEPSEEK_API_KEY \
    --tokenizer "${sectdd_tokenizer}" --config "${sectdd_config}" \
    --visible "${sectdd_visible}" --hidden "${sectdd_hidden}" \
    --output-root "${sectdd_deepseek_shards}" --max-workers "${sectdd_api_workers}" --resume
  sectdd_merge_if_needed "${sectdd_deepseek_shards}" "${sectdd_deepseek_run}"
}

sectdd_analyze() {
  [[ "$(sectdd_count "${sectdd_qwen_run}")" -eq "${sectdd_expected}" ]] || { echo "Qwen run is incomplete." >&2; exit 3; }
  [[ "$(sectdd_count "${sectdd_deepseek_run}")" -eq "${sectdd_expected}" ]] || { echo "DeepSeek run is incomplete." >&2; exit 3; }
  "${sectdd_python}" tools/analyze_codeguardplus_breadth_confirmatory_v1.py "${sectdd_qwen_run}" "${sectdd_deepseek_run}"
}

mkdir -p "${sectdd_output}"
case "${sectdd_action}" in
  build) sectdd_build ;;
  qwen) sectdd_build; sectdd_run_qwen ;;
  deepseek) sectdd_build; sectdd_run_deepseek ;;
  analyze) sectdd_analyze ;;
  all) sectdd_build; sectdd_run_qwen; sectdd_run_deepseek; sectdd_analyze ;;
  *) echo "Usage: $0 {build|qwen|deepseek|analyze|all}" >&2; exit 2 ;;
esac
