#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_variant="${1:-v1}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
case "${sectdd_variant}" in
  v1)
    sectdd_task_file="benchmarks/manifests/codeguardplus-reserve-partitioned-v1-freeze.json"
    sectdd_oracle_manifest="oracles/codeguardplus_reserve_partitioned_v1/manifest.json"
    sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/semantic-review"
    sectdd_report_id="codeguardplus-partitioned-semantic-machine-panel-v1"
    ;;
  v2)
    sectdd_task_file="benchmarks/manifests/codeguardplus-reserve-partitioned-v2-freeze.json"
    sectdd_oracle_manifest="oracles/codeguardplus_reserve_partitioned_v2/manifest.json"
    sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/semantic-review-v2"
    sectdd_report_id="codeguardplus-reserve-partitioned-semantic-machine-panel-v2"
    ;;
  *)
    echo "Usage: $0 {v1|v2}" >&2
    exit 2
    ;;
esac
sectdd_log_root="artifacts/logs"
sectdd_gpu_14b="${SECTDD_GPU_14B:-5}"
sectdd_port_14b="${SECTDD_PORT_14B:-18581}"
sectdd_pids=()

sectdd_cleanup() {
  local sectdd_pid
  for sectdd_pid in "${sectdd_pids[@]}"; do
    if kill -0 "${sectdd_pid}" 2>/dev/null; then
      kill "${sectdd_pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

sectdd_assert_gpu() {
  local sectdd_gpu="$1"
  local sectdd_used
  case "${sectdd_gpu}" in
    4|5|6) ;;
    *)
      echo "Reviewer GPUs must be selected from the authorized set 4, 5, 6." >&2
      exit 2
      ;;
  esac
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
      | "${sectdd_python}" -c 'import json,sys; model=sys.argv[1]; print(int(model in {item.get("id") for item in json.load(sys.stdin).get("data", [])}))' "${sectdd_model}" 2>/dev/null \
      | grep -qx 1; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    sleep 5
  done
  tail -n 120 "${sectdd_log}" >&2 || true
  return 3
}

if [[ ! -f "${sectdd_output}/packet_manifest.json" ]]; then
  echo "Missing semantic-review packets. Run semantic-prepare first." >&2
  exit 2
fi
sectdd_task_count="$("${sectdd_python}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["task_count"])' "${sectdd_output}/packet_manifest.json")"
sectdd_completed_reviews() {
  local sectdd_model="$1"
  if [[ ! -d "${sectdd_output}/reviews/${sectdd_model}" ]]; then
    echo 0
    return
  fi
  find "${sectdd_output}/reviews/${sectdd_model}" -maxdepth 1 -type f -name '*.json' | wc -l
}
sectdd_qwen_complete=false
sectdd_deepseek_complete=false
if [[ "$(sectdd_completed_reviews qwen25-coder-14b)" -eq "${sectdd_task_count}" ]]; then
  sectdd_qwen_complete=true
fi
if [[ "$(sectdd_completed_reviews deepseek-v4-flash)" -eq "${sectdd_task_count}" ]]; then
  sectdd_deepseek_complete=true
fi

if [[ "${sectdd_qwen_complete}" == true && "${sectdd_deepseek_complete}" == true && -f "${sectdd_output}/report.json" ]]; then
  "${sectdd_python}" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8")); print(json.dumps(report["summary"], indent=2, sort_keys=True))' "${sectdd_output}/report.json"
  echo "Machine semantic panel already completed: ${sectdd_output}/report.json"
  exit 0
fi

if [[ "${sectdd_deepseek_complete}" == false && -z "${DEEPSEEK_API_KEY:-}" ]]; then
  if [[ ! -t 0 ]]; then
    echo "DEEPSEEK_API_KEY is required for a non-interactive run." >&2
    exit 2
  fi
  read -r -s -p "DeepSeek API key: " DEEPSEEK_API_KEY
  echo
  export DEEPSEEK_API_KEY
fi

mkdir -p "${sectdd_log_root}"

if [[ "${sectdd_qwen_complete}" == false ]]; then
  sectdd_assert_gpu "${sectdd_gpu_14b}"
  SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=16384 \
    scripts/serve_qwen25_coder.sh 14b \
    >"${sectdd_log_root}/codeguardplus-reserve-semantic-${sectdd_variant}-qwen25-14b.log" 2>&1 &
  sectdd_pid_14b=$!
  sectdd_pids+=("${sectdd_pid_14b}")
  sectdd_wait_model "${sectdd_port_14b}" qwen25-coder-14b "${sectdd_pid_14b}" \
    "${sectdd_log_root}/codeguardplus-reserve-semantic-${sectdd_variant}-qwen25-14b.log"

  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_task_file}" \
    --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle_manifest}" \
    --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" \
    --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_port_14b}/v1" \
    --max-workers 2 --max-tokens 4096 --timeout-seconds 600 \
    --confirm-machine-review
else
  echo "Resume: qwen25-coder-14b already completed ${sectdd_task_count}/${sectdd_task_count}; skipping local server."
fi

if [[ "${sectdd_deepseek_complete}" == false ]]; then
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_task_file}" \
    --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle_manifest}" \
    --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" \
    --provider deepseek \
    --reviewer "deepseek-v4-flash=https://api.deepseek.com" \
    --thinking enabled --reasoning-effort high \
    --max-workers 2 --max-tokens 8192 --timeout-seconds 600 \
    --confirm-machine-review
else
  echo "Resume: deepseek-v4-flash already completed ${sectdd_task_count}/${sectdd_task_count}."
fi

test -f "${sectdd_output}/report.json"
"${sectdd_python}" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8")); print(json.dumps(report["summary"], indent=2, sort_keys=True))' "${sectdd_output}/report.json"
echo "Machine semantic panel completed: ${sectdd_output}/report.json"
