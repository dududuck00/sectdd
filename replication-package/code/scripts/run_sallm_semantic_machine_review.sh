#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_output="artifacts/sallm-semantic-review-v2"
sectdd_log_root="artifacts/logs"
sectdd_pids=()

sectdd_cleanup() {
  local sectdd_pid
  for sectdd_pid in "${sectdd_pids[@]:-}"; do
    if kill -0 "${sectdd_pid}" 2>/dev/null; then
      kill "${sectdd_pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

if [[ -e "${sectdd_output}" ]]; then
  echo "Semantic-review output already exists: ${sectdd_output}" >&2
  exit 2
fi

sectdd_assert_gpu_free() {
  local sectdd_gpu="$1"
  local sectdd_used
  sectdd_used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  if [[ -z "${sectdd_used}" || "${sectdd_used}" -gt 2048 ]]; then
    echo "GPU ${sectdd_gpu} is not free: ${sectdd_used:-unknown} MiB" >&2
    exit 3
  fi
}

sectdd_wait_model() {
  local sectdd_port="$1"
  local sectdd_model="$2"
  local sectdd_pid="$3"
  local sectdd_log="$4"
  local sectdd_attempt
  for sectdd_attempt in $(seq 1 240); do
    if ! kill -0 "${sectdd_pid}" 2>/dev/null; then
      tail -n 120 "${sectdd_log}" >&2 || true
      return 3
    fi
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null \
      | .venv/bin/python -c 'import json,sys; m=sys.argv[1]; print(int(m in {x.get("id") for x in json.load(sys.stdin).get("data", [])}))' "${sectdd_model}" 2>/dev/null \
      | grep -qx 1; then
      echo "Ready: ${sectdd_model} on ${sectdd_port}"
      return
    fi
    sleep 5
  done
  tail -n 120 "${sectdd_log}" >&2 || true
  return 3
}

sectdd_assert_gpu_free 5
sectdd_assert_gpu_free 6
mkdir -p "${sectdd_log_root}"

SECTDD_GPU=5 SECTDD_PORT=18181 scripts/serve_qwen25_coder.sh 14b \
  >"${sectdd_log_root}/sallm-semantic-review-qwen25-14b.log" 2>&1 &
sectdd_14b=$!
sectdd_pids+=("${sectdd_14b}")

SECTDD_GPUS=6 SECTDD_PORT=18183 SECTDD_MAX_MODEL_LEN=16384 \
  scripts/serve_qwen36.sh 27b \
  >"${sectdd_log_root}/sallm-semantic-review-qwen36-27b.log" 2>&1 &
sectdd_27b=$!
sectdd_pids+=("${sectdd_27b}")

sectdd_wait_model 18181 qwen25-coder-14b "${sectdd_14b}" \
  "${sectdd_log_root}/sallm-semantic-review-qwen25-14b.log"
sectdd_wait_model 18183 qwen36-27b "${sectdd_27b}" \
  "${sectdd_log_root}/sallm-semantic-review-qwen36-27b.log"

.venv/bin/python tools/review_sallm_expansion_semantics.py \
  --reviewer qwen25-coder-14b=http://127.0.0.1:18181/v1 \
  --reviewer qwen36-27b=http://127.0.0.1:18183/v1 \
  --max-workers 4 \
  --max-tokens 4096 \
  --timeout-seconds 600 \
  --confirm-machine-review

echo "Semantic machine review completed: ${sectdd_output}/report.json"
