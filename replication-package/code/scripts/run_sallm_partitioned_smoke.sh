#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_tag="${SECTDD_RUN_TAG:-smoke-001}"
sectdd_gpu="${SECTDD_GPU:-4}"
sectdd_port="${SECTDD_PORT:-18080}"
sectdd_model="qwen25-coder-7b"
sectdd_checkpoint="<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct"
sectdd_output="artifacts/sallm_formal/qwen25-coder-7b-${sectdd_tag}"
sectdd_log="artifacts/logs/sallm-smoke-server-${sectdd_tag}.log"
sectdd_server_pid=""

case "${sectdd_gpu}" in
  4|5|6) ;;
  *)
    echo "SECTDD_GPU must be one of 4, 5, or 6." >&2
    exit 2
    ;;
esac

if [[ -e "${sectdd_output}" ]]; then
  echo "Refusing to overwrite ${sectdd_output}; choose a new SECTDD_RUN_TAG." >&2
  exit 2
fi

sectdd_cleanup() {
  if [[ -n "${sectdd_server_pid}" ]] \
    && kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    kill "${sectdd_server_pid}" 2>/dev/null || true
    wait "${sectdd_server_pid}" 2>/dev/null || true
  fi
}
trap sectdd_cleanup EXIT INT TERM

sectdd_ready() {
  curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null \
    | grep -q "\"id\":\"${sectdd_model}\""
}

mkdir -p artifacts/logs artifacts/sallm_formal

.venv-sallm/bin/python tools/verify_sallm_oracle_overlay_v2.py
.venv-sallm/bin/python tools/verify_sallm_partitioned_oracles_v3.py

if ! sectdd_ready; then
  echo "Starting ${sectdd_model} on GPU ${sectdd_gpu}, port ${sectdd_port}..."
  SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" \
    scripts/serve_qwen25_coder.sh 7b >"${sectdd_log}" 2>&1 &
  sectdd_server_pid=$!
  for sectdd_attempt in $(seq 1 180); do
    if ! kill -0 "${sectdd_server_pid}" 2>/dev/null; then
      echo "Model server exited before readiness." >&2
      tail -n 80 "${sectdd_log}" >&2 || true
      exit 3
    fi
    if sectdd_ready; then
      echo "Ready: ${sectdd_model}"
      break
    fi
    if (( sectdd_attempt % 12 == 0 )); then
      echo "Still waiting for ${sectdd_model}..."
    fi
    sleep 5
  done
fi

if ! sectdd_ready; then
  echo "Timed out waiting for ${sectdd_model}." >&2
  tail -n 80 "${sectdd_log}" >&2 || true
  exit 3
fi

.venv/bin/python tools/run_sallm_formal.py \
  --served-model "${sectdd_model}" \
  --api-base "http://127.0.0.1:${sectdd_port}/v1" \
  --tokenizer "${sectdd_checkpoint}" \
  --output "${sectdd_output}"

.venv/bin/python tools/validate_sallm_formal.py "${sectdd_output}"
echo "SALLM partitioned smoke completed: ${sectdd_output}"
