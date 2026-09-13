#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_tag="${SECTDD_RUN_TAG:-main-002}"
sectdd_gpu_7b="${SECTDD_GPU_7B:-5}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-6}"
sectdd_gpu_27b="${SECTDD_GPU_27B:-5}"
sectdd_workers="${SECTDD_MAX_WORKERS:-3}"
sectdd_config="configs/experiments/sallm_partitioned_main_v1_1.json"

sectdd_7b_shards="artifacts/sallm_formal_main/qwen25-coder-7b-${sectdd_tag}-shards"
sectdd_7b_output="artifacts/sallm_formal_main/qwen25-coder-7b-${sectdd_tag}"
sectdd_14b_shards="artifacts/sallm_formal_main/qwen25-coder-14b-${sectdd_tag}-shards"
sectdd_14b_output="artifacts/sallm_formal_main/qwen25-coder-14b-${sectdd_tag}"
sectdd_27b_shards="artifacts/sallm_formal_main/qwen36-27b-${sectdd_tag}-shards"
sectdd_27b_output="artifacts/sallm_formal_main/qwen36-27b-${sectdd_tag}"
sectdd_report_json="artifacts/reports/sallm-main-${sectdd_tag}.json"
sectdd_report_md="docs/sallm-main-${sectdd_tag}.md"

sectdd_server_pids=()
sectdd_cleanup() {
  local sectdd_pid
  for sectdd_pid in "${sectdd_server_pids[@]:-}"; do
    if kill -0 "${sectdd_pid}" 2>/dev/null; then
      kill "${sectdd_pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

for sectdd_gpu in "${sectdd_gpu_7b}" "${sectdd_gpu_14b}" "${sectdd_gpu_27b}"; do
  case "${sectdd_gpu}" in
    4|5|6) ;;
    *)
      echo "All GPUs must be one of 4, 5, or 6." >&2
      exit 2
      ;;
  esac
done
if [[ "${sectdd_gpu_7b}" == "${sectdd_gpu_14b}" ]]; then
  echo "7B and 14B require distinct GPUs for concurrent execution." >&2
  exit 2
fi

for sectdd_path in \
  "${sectdd_7b_shards}" "${sectdd_7b_output}" \
  "${sectdd_14b_shards}" "${sectdd_14b_output}" \
  "${sectdd_27b_shards}" "${sectdd_27b_output}" \
  "${sectdd_report_json}" "${sectdd_report_md}"; do
  if [[ -e "${sectdd_path}" ]]; then
    echo "Refusing to overwrite ${sectdd_path}; choose a new run tag." >&2
    exit 2
  fi
done

sectdd_assert_free_gpu() {
  local sectdd_gpu="$1"
  local sectdd_used
  sectdd_used="$(
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits \
      -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}'
  )"
  if [[ -z "${sectdd_used}" || "${sectdd_used}" -gt 2048 ]]; then
    echo "GPU ${sectdd_gpu} is not free: used=${sectdd_used:-unknown} MiB" >&2
    exit 3
  fi
}

sectdd_wait_model() {
  local sectdd_port="$1"
  local sectdd_model="$2"
  local sectdd_pid="$3"
  local sectdd_log="$4"
  local sectdd_attempt
  for sectdd_attempt in $(seq 1 180); do
    if ! kill -0 "${sectdd_pid}" 2>/dev/null; then
      echo "Server exited before readiness: ${sectdd_model}" >&2
      tail -n 100 "${sectdd_log}" >&2 || true
      exit 3
    fi
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" \
      2>/dev/null | grep -q "\"id\":\"${sectdd_model}\""; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    if (( sectdd_attempt % 12 == 0 )); then
      echo "Still waiting for ${sectdd_model}..."
    fi
    sleep 5
  done
  echo "Timed out waiting for ${sectdd_model}" >&2
  tail -n 100 "${sectdd_log}" >&2 || true
  exit 3
}

mkdir -p artifacts/logs artifacts/sallm_formal_main
test -x .venv/bin/python
test -x .venv-sallm/bin/python
test -x /usr/bin/bwrap

.venv/bin/python tools/verify_sallm_main_v1_1_lock.py
.venv-sallm/bin/python tools/verify_sallm_partitioned_oracles_v3.py

sectdd_assert_free_gpu "${sectdd_gpu_7b}"
sectdd_assert_free_gpu "${sectdd_gpu_14b}"
nvidia-smi \
  --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu \
  --format=csv,noheader \
  -i "${sectdd_gpu_7b},${sectdd_gpu_14b}"

SECTDD_GPU="${sectdd_gpu_7b}" SECTDD_PORT=18080 \
  scripts/serve_qwen25_coder.sh 7b \
  >"artifacts/logs/sallm-main-server-7b-${sectdd_tag}.log" 2>&1 &
sectdd_server_7b=$!
sectdd_server_pids+=("${sectdd_server_7b}")
sectdd_wait_model \
  18080 qwen25-coder-7b "${sectdd_server_7b}" \
  "artifacts/logs/sallm-main-server-7b-${sectdd_tag}.log"

SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT=18081 \
  scripts/serve_qwen25_coder.sh 14b \
  >"artifacts/logs/sallm-main-server-14b-${sectdd_tag}.log" 2>&1 &
sectdd_server_14b=$!
sectdd_server_pids+=("${sectdd_server_14b}")
sectdd_wait_model \
  18081 qwen25-coder-14b "${sectdd_server_14b}" \
  "artifacts/logs/sallm-main-server-14b-${sectdd_tag}.log"

.venv/bin/python tools/run_sallm_task_shards.py \
  --served-model qwen25-coder-7b \
  --api-base http://127.0.0.1:18080/v1 \
  --tokenizer <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct \
  --config "${sectdd_config}" \
  --output-root "${sectdd_7b_shards}" \
  --max-workers "${sectdd_workers}" \
  >"artifacts/logs/sallm-main-run-7b-${sectdd_tag}.log" 2>&1 &
sectdd_run_7b=$!

.venv/bin/python tools/run_sallm_task_shards.py \
  --served-model qwen25-coder-14b \
  --api-base http://127.0.0.1:18081/v1 \
  --tokenizer <MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct \
  --config "${sectdd_config}" \
  --output-root "${sectdd_14b_shards}" \
  --max-workers "${sectdd_workers}" \
  >"artifacts/logs/sallm-main-run-14b-${sectdd_tag}.log" 2>&1 &
sectdd_run_14b=$!

wait "${sectdd_run_7b}"
wait "${sectdd_run_14b}"

.venv/bin/python tools/merge_sallm_formal_shards.py \
  "${sectdd_7b_shards}" --output "${sectdd_7b_output}"
.venv/bin/python tools/validate_sallm_formal.py "${sectdd_7b_output}"
.venv/bin/python tools/merge_sallm_formal_shards.py \
  "${sectdd_14b_shards}" --output "${sectdd_14b_output}"
.venv/bin/python tools/validate_sallm_formal.py "${sectdd_14b_output}"

kill "${sectdd_server_7b}" "${sectdd_server_14b}" 2>/dev/null || true
wait "${sectdd_server_7b}" 2>/dev/null || true
wait "${sectdd_server_14b}" 2>/dev/null || true

sectdd_assert_free_gpu "${sectdd_gpu_27b}"
SECTDD_GPUS="${sectdd_gpu_27b}" SECTDD_PORT=18083 \
SECTDD_MAX_MODEL_LEN=16384 SECTDD_MAX_NUM_SEQS=64 \
  scripts/serve_qwen36.sh 27b \
  >"artifacts/logs/sallm-main-server-27b-${sectdd_tag}.log" 2>&1 &
sectdd_server_27b=$!
sectdd_server_pids+=("${sectdd_server_27b}")
sectdd_wait_model \
  18083 qwen36-27b "${sectdd_server_27b}" \
  "artifacts/logs/sallm-main-server-27b-${sectdd_tag}.log"

.venv/bin/python tools/run_sallm_task_shards.py \
  --served-model qwen36-27b \
  --api-base http://127.0.0.1:18083/v1 \
  --tokenizer <MODEL_ROOT>/Qwen3.6/Qwen3.6-27B \
  --config "${sectdd_config}" \
  --output-root "${sectdd_27b_shards}" \
  --max-workers "${sectdd_workers}" \
  >"artifacts/logs/sallm-main-run-27b-${sectdd_tag}.log" 2>&1

.venv/bin/python tools/merge_sallm_formal_shards.py \
  "${sectdd_27b_shards}" --output "${sectdd_27b_output}"
.venv/bin/python tools/validate_sallm_formal.py "${sectdd_27b_output}"

.venv/bin/python tools/analyze_sallm_main.py \
  "${sectdd_7b_output}" \
  "${sectdd_14b_output}" \
  "${sectdd_27b_output}" \
  --bootstrap-replicates 10000 \
  --bootstrap-seed 20260730 \
  --json-output "${sectdd_report_json}" \
  --markdown-output "${sectdd_report_md}"

echo "Completed local SALLM external main:"
echo "  ${sectdd_7b_output}"
echo "  ${sectdd_14b_output}"
echo "  ${sectdd_27b_output}"
echo "Report: ${sectdd_report_md}"
