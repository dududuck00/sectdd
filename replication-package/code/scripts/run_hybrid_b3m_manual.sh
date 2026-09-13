#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_tag="${SECTDD_RUN_TAG:-hybrid-001}"
sectdd_gpu_7b="${SECTDD_GPU_7B:-4}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-5}"
sectdd_gpu_32b="${SECTDD_GPU_32B:-6}"
sectdd_config="configs/experiments/paper_candidate_hybrid_b3m_development.json"
sectdd_visible="configs/oracles/cweval_py_paper_candidate_v2_visible.json"
sectdd_hidden="configs/oracles/cweval_py_paper_candidate_v2_hidden.json"

sectdd_7b_out="artifacts/hybrid_b3m/qwen25-coder-7b-${sectdd_tag}"
sectdd_14b_out="artifacts/hybrid_b3m/qwen25-coder-14b-${sectdd_tag}"
sectdd_32b_shards="artifacts/hybrid_b3m/qwen3-32b-${sectdd_tag}-shards"
sectdd_32b_out="artifacts/hybrid_b3m/qwen3-32b-${sectdd_tag}"
sectdd_report_json="artifacts/reports/hybrid-b3m-${sectdd_tag}.json"
sectdd_report_md="docs/hybrid-b3m-${sectdd_tag}.md"

sectdd_server_pids=()
sectdd_run_pids=()
sectdd_monitor_pid=""

sectdd_cleanup() {
  local sectdd_pid
  if [[ -n "${sectdd_monitor_pid}" ]] \
    && kill -0 "${sectdd_monitor_pid}" 2>/dev/null; then
    kill "${sectdd_monitor_pid}" 2>/dev/null || true
  fi
  for sectdd_pid in "${sectdd_run_pids[@]:-}"; do
    if kill -0 "${sectdd_pid}" 2>/dev/null; then
      kill "${sectdd_pid}" 2>/dev/null || true
    fi
  done
  for sectdd_pid in "${sectdd_server_pids[@]:-}"; do
    if kill -0 "${sectdd_pid}" 2>/dev/null; then
      kill "${sectdd_pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

for sectdd_gpu in \
  "${sectdd_gpu_7b}" "${sectdd_gpu_14b}" "${sectdd_gpu_32b}"; do
  case "${sectdd_gpu}" in
    4|5|6) ;;
    *)
      echo "All SECTDD_GPU_* values must be one of: 4, 5, 6." >&2
      exit 2
      ;;
  esac
done
if [[ "${sectdd_gpu_7b}" == "${sectdd_gpu_14b}" \
  || "${sectdd_gpu_7b}" == "${sectdd_gpu_32b}" \
  || "${sectdd_gpu_14b}" == "${sectdd_gpu_32b}" ]]; then
  echo "SECTDD_GPU_7B, SECTDD_GPU_14B, and SECTDD_GPU_32B must be distinct." >&2
  exit 2
fi

sectdd_assert_hash() {
  local sectdd_path="$1"
  local sectdd_expected="$2"
  local sectdd_actual
  sectdd_actual="$(sha256sum "${sectdd_path}" | awk '{print $1}')"
  if [[ "${sectdd_actual}" != "${sectdd_expected}" ]]; then
    echo "Hash mismatch: ${sectdd_path}" >&2
    echo "expected=${sectdd_expected}" >&2
    echo "actual=${sectdd_actual}" >&2
    exit 2
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
      echo "Server exited before becoming ready: ${sectdd_model}" >&2
      tail -n 80 "${sectdd_log}" >&2 || true
      exit 3
    fi
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" \
      2>/dev/null | grep -q "\"id\":\"${sectdd_model}\""; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    if (( sectdd_attempt % 12 == 0 )); then
      echo "Still waiting for ${sectdd_model} on port ${sectdd_port}..."
    fi
    sleep 5
  done
  echo "Timed out waiting for ${sectdd_model}" >&2
  tail -n 80 "${sectdd_log}" >&2 || true
  exit 3
}

sectdd_progress_monitor() {
  while true; do
    sleep 60
    echo "---- hybrid experiment progress ----"
    for sectdd_log in \
      "artifacts/logs/run.hybrid.qwen25-7b.${sectdd_tag}.log" \
      "artifacts/logs/run.hybrid.qwen25-14b.${sectdd_tag}.log" \
      "artifacts/logs/run.hybrid.qwen3-32b.${sectdd_tag}.log"; do
      if [[ -s "${sectdd_log}" ]]; then
        printf '%s: ' "$(basename "${sectdd_log}")"
        tail -n 1 "${sectdd_log}"
      fi
    done
  done
}

mkdir -p artifacts/logs artifacts/hybrid_b3m artifacts/reports docs

for sectdd_path in \
  "${sectdd_7b_out}" \
  "${sectdd_14b_out}" \
  "${sectdd_32b_shards}" \
  "${sectdd_32b_out}" \
  "${sectdd_report_json}" \
  "${sectdd_report_md}"; do
  if [[ -e "${sectdd_path}" ]]; then
    echo "Refusing to overwrite existing path: ${sectdd_path}" >&2
    echo "Set a new SECTDD_RUN_TAG and rerun." >&2
    exit 2
  fi
done

test -x .venv/bin/python
test -x <MODEL_ROOT>/anonymous-user/conda/envs/text2test/bin/vllm
test -x /usr/bin/bwrap
test -f <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct/config.json
test -f <MODEL_ROOT>/models/Qwen2.5-Coder-14B-Instruct/config.json
test -f <MODEL_ROOT>/models/Qwen3-32B/config.json

sectdd_assert_hash \
  "${sectdd_config}" \
  "2b85d26f4a4043869e1dc764c530f35168478ac14e525df4495c8198e1ae1094"
sectdd_assert_hash \
  "${sectdd_visible}" \
  "9b770ba64da23aa06bf545620b02022d6819fe95630c3fe236cd709766e7a82f"
sectdd_assert_hash \
  "${sectdd_hidden}" \
  "0c793e82d0baec7a8a816604568f334c9da374efead7f7a55dc756e08e71388a"

.venv/bin/python -m py_compile \
  sectdd/orchestrator.py \
  sectdd/formal_orchestrator.py \
  tools/run_formal_pilot.py \
  tools/run_task_shards.py \
  tools/merge_formal_shards.py \
  tools/validate_formal_pilot.py \
  tools/analyze_hybrid_b3m.py

nvidia-smi \
  --query-gpu=index,name,memory.total,memory.used,utilization.gpu \
  --format=csv,noheader \
  -i "${sectdd_gpu_7b},${sectdd_gpu_14b},${sectdd_gpu_32b}"

SECTDD_GPU="${sectdd_gpu_7b}" SECTDD_PORT=18080 \
  scripts/serve_qwen25_coder.sh 7b \
  > "artifacts/logs/server.hybrid.qwen25-7b.${sectdd_tag}.log" 2>&1 &
sectdd_server_7b=$!
sectdd_server_pids+=("${sectdd_server_7b}")
sectdd_wait_model \
  18080 qwen25-coder-7b "${sectdd_server_7b}" \
  "artifacts/logs/server.hybrid.qwen25-7b.${sectdd_tag}.log"

SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT=18081 \
  scripts/serve_qwen25_coder.sh 14b \
  > "artifacts/logs/server.hybrid.qwen25-14b.${sectdd_tag}.log" 2>&1 &
sectdd_server_14b=$!
sectdd_server_pids+=("${sectdd_server_14b}")
sectdd_wait_model \
  18081 qwen25-coder-14b "${sectdd_server_14b}" \
  "artifacts/logs/server.hybrid.qwen25-14b.${sectdd_tag}.log"

SECTDD_GPU="${sectdd_gpu_32b}" SECTDD_PORT=18082 \
  scripts/serve_qwen25_coder.sh qwen3-32b \
  > "artifacts/logs/server.hybrid.qwen3-32b.${sectdd_tag}.log" 2>&1 &
sectdd_server_32b=$!
sectdd_server_pids+=("${sectdd_server_32b}")
sectdd_wait_model \
  18082 qwen3-32b "${sectdd_server_32b}" \
  "artifacts/logs/server.hybrid.qwen3-32b.${sectdd_tag}.log"

.venv/bin/python tools/run_formal_pilot.py \
  --served-model qwen25-coder-7b \
  --api-base http://127.0.0.1:18080/v1 \
  --tokenizer <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct \
  --config "${sectdd_config}" \
  --visible-projection "${sectdd_visible}" \
  --hidden-projection "${sectdd_hidden}" \
  --output "${sectdd_7b_out}" \
  > "artifacts/logs/run.hybrid.qwen25-7b.${sectdd_tag}.log" 2>&1 &
sectdd_run_7b=$!
sectdd_run_pids+=("${sectdd_run_7b}")

.venv/bin/python tools/run_formal_pilot.py \
  --served-model qwen25-coder-14b \
  --api-base http://127.0.0.1:18081/v1 \
  --tokenizer <MODEL_ROOT>/models/Qwen2.5-Coder-14B-Instruct \
  --config "${sectdd_config}" \
  --visible-projection "${sectdd_visible}" \
  --hidden-projection "${sectdd_hidden}" \
  --output "${sectdd_14b_out}" \
  > "artifacts/logs/run.hybrid.qwen25-14b.${sectdd_tag}.log" 2>&1 &
sectdd_run_14b=$!
sectdd_run_pids+=("${sectdd_run_14b}")

.venv/bin/python tools/run_task_shards.py \
  --served-model qwen3-32b \
  --api-base http://127.0.0.1:18082/v1 \
  --tokenizer <MODEL_ROOT>/models/Qwen3-32B \
  --config "${sectdd_config}" \
  --visible-projection "${sectdd_visible}" \
  --hidden-projection "${sectdd_hidden}" \
  --output-root "${sectdd_32b_shards}" \
  --max-workers 5 \
  > "artifacts/logs/run.hybrid.qwen3-32b.${sectdd_tag}.log" 2>&1 &
sectdd_run_32b=$!
sectdd_run_pids+=("${sectdd_run_32b}")

sectdd_progress_monitor &
sectdd_monitor_pid=$!

wait "${sectdd_run_32b}"
.venv/bin/python tools/merge_formal_shards.py \
  "${sectdd_32b_shards}" \
  --output "${sectdd_32b_out}"
.venv/bin/python tools/validate_formal_pilot.py "${sectdd_32b_out}"
kill "${sectdd_server_32b}"
wait "${sectdd_server_32b}" 2>/dev/null || true

wait "${sectdd_run_7b}"
wait "${sectdd_run_14b}"
.venv/bin/python tools/validate_formal_pilot.py "${sectdd_7b_out}"
.venv/bin/python tools/validate_formal_pilot.py "${sectdd_14b_out}"

if kill -0 "${sectdd_monitor_pid}" 2>/dev/null; then
  kill "${sectdd_monitor_pid}" 2>/dev/null || true
  wait "${sectdd_monitor_pid}" 2>/dev/null || true
fi
sectdd_monitor_pid=""

.venv/bin/python tools/analyze_hybrid_b3m.py \
  "${sectdd_7b_out}" \
  "${sectdd_14b_out}" \
  "${sectdd_32b_out}" \
  --bootstrap-replicates 10000 \
  --bootstrap-seed 20260729 \
  --json-output "${sectdd_report_json}" \
  --markdown-output "${sectdd_report_md}"

echo "Hybrid report: ${sectdd_report_md}"
echo "Machine-readable report: ${sectdd_report_json}"
