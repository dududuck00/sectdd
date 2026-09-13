#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_tag="${SECTDD_RUN_TAG:-preflight-v1}"
sectdd_workers="${SECTDD_MAX_WORKERS:-2}"
sectdd_config="configs/experiments/sallm_wave2_preflight_v1.json"
sectdd_visible="configs/oracles/sallm_wave2_preflight_visible_v1.json"
sectdd_hidden="configs/oracles/sallm_wave2_preflight_hidden_v1.json"
sectdd_qualified="configs/benchmarks/sallm_wave2_preflight_qualified_v1.json"
sectdd_root_out="artifacts/sallm-wave2-preflight/${sectdd_tag}"
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

if [[ -e "${sectdd_root_out}" || -e "${sectdd_config}" || -e "${sectdd_qualified}" ]]; then
  echo "Wave-2 preflight output/config already exists; refusing to mix runs." >&2
  exit 2
fi

sectdd_assert_free_gpu() {
  local sectdd_gpu="$1"
  local sectdd_used
  sectdd_used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  if [[ -z "${sectdd_used}" || "${sectdd_used}" -gt 2048 ]]; then
    echo "GPU ${sectdd_gpu} is not free: ${sectdd_used:-unknown} MiB" >&2
    exit 3
  fi
}

sectdd_wait_model() {
  local sectdd_port="$1" sectdd_model="$2" sectdd_pid="$3" sectdd_log="$4"
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

for sectdd_gpu in 4 5 6; do sectdd_assert_free_gpu "${sectdd_gpu}"; done
mkdir -p artifacts/logs "$(dirname "${sectdd_root_out}")"
.venv/bin/python tools/build_sallm_wave2_preflight.py
mkdir -p "${sectdd_root_out}"

SECTDD_GPU=4 SECTDD_PORT=18480 scripts/serve_qwen25_coder.sh 7b >"artifacts/logs/sallm-wave2-preflight-7b-${sectdd_tag}.log" 2>&1 &
sectdd_server_7b=$!; sectdd_pids+=("${sectdd_server_7b}")
SECTDD_GPU=5 SECTDD_PORT=18481 scripts/serve_qwen25_coder.sh 14b >"artifacts/logs/sallm-wave2-preflight-14b-${sectdd_tag}.log" 2>&1 &
sectdd_server_14b=$!; sectdd_pids+=("${sectdd_server_14b}")
SECTDD_GPUS=6 SECTDD_PORT=18483 SECTDD_MAX_MODEL_LEN=16384 SECTDD_MAX_NUM_SEQS=16 scripts/serve_qwen36.sh 27b >"artifacts/logs/sallm-wave2-preflight-27b-${sectdd_tag}.log" 2>&1 &
sectdd_server_27b=$!; sectdd_pids+=("${sectdd_server_27b}")

sectdd_wait_model 18480 qwen25-coder-7b "${sectdd_server_7b}" "artifacts/logs/sallm-wave2-preflight-7b-${sectdd_tag}.log"
sectdd_wait_model 18481 qwen25-coder-14b "${sectdd_server_14b}" "artifacts/logs/sallm-wave2-preflight-14b-${sectdd_tag}.log"
sectdd_wait_model 18483 qwen36-27b "${sectdd_server_27b}" "artifacts/logs/sallm-wave2-preflight-27b-${sectdd_tag}.log"

sectdd_run_model() {
  local sectdd_model="$1" sectdd_port="$2" sectdd_tokenizer="$3" sectdd_short="$4"
  .venv/bin/python tools/run_sallm_task_shards.py \
    --served-model "${sectdd_model}" --api-base "http://127.0.0.1:${sectdd_port}/v1" \
    --tokenizer "${sectdd_tokenizer}" --config "${sectdd_config}" \
    --visible-projection "${sectdd_visible}" --hidden-projection "${sectdd_hidden}" \
    --output-root "${sectdd_root_out}/${sectdd_short}-shards" --max-workers "${sectdd_workers}" \
    >"artifacts/logs/sallm-wave2-preflight-run-${sectdd_short}-${sectdd_tag}.log" 2>&1
  .venv/bin/python tools/merge_sallm_formal_shards.py "${sectdd_root_out}/${sectdd_short}-shards" --output "${sectdd_root_out}/${sectdd_short}"
  .venv/bin/python tools/validate_sallm_formal.py "${sectdd_root_out}/${sectdd_short}"
}

sectdd_run_model qwen25-coder-7b 18480 <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct qwen25-coder-7b & sectdd_run_7b=$!
sectdd_run_model qwen25-coder-14b 18481 <MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct qwen25-coder-14b & sectdd_run_14b=$!
sectdd_run_model qwen36-27b 18483 <MODEL_ROOT>/Qwen3.6/Qwen3.6-27B qwen36-27b & sectdd_run_27b=$!
wait "${sectdd_run_7b}"; wait "${sectdd_run_14b}"; wait "${sectdd_run_27b}"

.venv/bin/python tools/analyze_sallm_expansion_preflight.py \
  "${sectdd_root_out}/qwen25-coder-7b" "${sectdd_root_out}/qwen25-coder-14b" "${sectdd_root_out}/qwen36-27b" \
  --json-output "${sectdd_root_out}/report.json" \
  --markdown-output "docs/sallm-wave2-preflight-${sectdd_tag}.md" \
  --qualified-task-file "${sectdd_qualified}" \
  --report-id "sallm-wave2-preflight-v1" \
  --title "SALLM wave-2 model preflight v1" \
  --remaining-gate "independent second-researcher semantic review (G7)"

echo "SALLM wave-2 preflight completed: ${sectdd_root_out}/report.json"
