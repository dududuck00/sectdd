#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_tag="${SECTDD_RUN_TAG:-main-003-corrected}"
sectdd_gpu="${SECTDD_GPU_14B:-5}"
sectdd_port="${SECTDD_PORT_14B:-18581}"
sectdd_workers="${SECTDD_MAX_WORKERS:-5}"
sectdd_config="configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.json"
sectdd_lock="configs/experiments/paper_candidate_feedback_v2_main_internal_v3_14b_corrected.lock.json"
sectdd_visible="configs/oracles/cweval_py_paper_candidate_v2_visible.json"
sectdd_hidden="configs/oracles/cweval_py_paper_candidate_v2_hidden.json"
sectdd_model="<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct"
sectdd_shards="artifacts/main_internal/qwen25-coder-14b-${sectdd_tag}-shards"
sectdd_output="artifacts/main_internal/qwen25-coder-14b-${sectdd_tag}"
sectdd_report_json="artifacts/reports/main-internal-${sectdd_tag}.json"
sectdd_report_md="docs/main-internal-${sectdd_tag}.md"
sectdd_server_log="artifacts/logs/server.qwen25-14b.${sectdd_tag}.log"
sectdd_run_log="artifacts/logs/run.qwen25-14b.${sectdd_tag}.log"
sectdd_server_pid=""

sectdd_cleanup() {
  if [[ -n "${sectdd_server_pid}" ]] && kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    kill "${sectdd_server_pid}" 2>/dev/null || true
    wait "${sectdd_server_pid}" 2>/dev/null || true
  fi
}
trap sectdd_cleanup EXIT INT TERM

case "${sectdd_gpu}" in
  4|5|6) ;;
  *)
    echo "SECTDD_GPU_14B must be one of the user-authorized GPUs: 4, 5, or 6." >&2
    exit 2
    ;;
esac
if ! [[ "${sectdd_port}" =~ ^[0-9]+$ ]] || (( sectdd_port < 1024 || sectdd_port > 65535 )); then
  echo "SECTDD_PORT_14B must be an unprivileged TCP port." >&2
  exit 2
fi
if ! [[ "${sectdd_workers}" =~ ^[1-9][0-9]*$ ]] || (( sectdd_workers > 9 )); then
  echo "SECTDD_MAX_WORKERS must be between 1 and 9." >&2
  exit 2
fi

for sectdd_path in \
  "${sectdd_shards}" \
  "${sectdd_output}" \
  "${sectdd_report_json}" \
  "${sectdd_report_md}" \
  "${sectdd_server_log}" \
  "${sectdd_run_log}"; do
  if [[ -e "${sectdd_path}" ]]; then
    echo "Refusing to overwrite existing path: ${sectdd_path}" >&2
    echo "Set a new SECTDD_RUN_TAG and rerun." >&2
    exit 2
  fi
done

test -x .venv/bin/python
test -x scripts/serve_qwen25_coder.sh
test -x /usr/bin/bwrap
test -f "${sectdd_model}/config.json"

.venv/bin/python -m py_compile \
  sectdd/orchestrator.py \
  sectdd/formal_orchestrator.py \
  tools/run_formal_pilot.py \
  tools/run_task_shards.py \
  tools/merge_formal_shards.py \
  tools/validate_formal_pilot.py \
  tools/build_main_internal_14b_correction.py \
  tools/analyze_main_internal_14b_corrected.py

if [[ ! -e "${sectdd_config}" && ! -e "${sectdd_lock}" ]]; then
  .venv/bin/python tools/build_main_internal_14b_correction.py
elif [[ ! -f "${sectdd_config}" || ! -f "${sectdd_lock}" ]]; then
  echo "Correction config and lock must either both exist or both be absent." >&2
  exit 2
fi

# The builder is intentionally strict about the corrected checkpoint identity.
sectdd_config_hash="$(sha256sum "${sectdd_config}" | awk '{print $1}')"
sectdd_lock_config_hash="$(.venv/bin/python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["inputs"]["corrected_config"]["sha256"])' \
  "${sectdd_lock}")"
if [[ "${sectdd_config_hash}" != "${sectdd_lock_config_hash}" ]]; then
  echo "Corrected config no longer matches its pre-run lock." >&2
  exit 2
fi

sectdd_memory_used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
if [[ -z "${sectdd_memory_used}" ]] || (( sectdd_memory_used > 2048 )); then
  echo "GPU ${sectdd_gpu} is not sufficiently idle: ${sectdd_memory_used:-unknown} MiB used." >&2
  exit 2
fi
nvidia-smi \
  --query-gpu=index,name,memory.total,memory.used,utilization.gpu \
  --format=csv,noheader \
  -i "${sectdd_gpu}"

mkdir -p artifacts/logs artifacts/main_internal artifacts/reports docs

SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" \
  scripts/serve_qwen25_coder.sh 14b > "${sectdd_server_log}" 2>&1 &
sectdd_server_pid=$!

for sectdd_attempt in $(seq 1 180); do
  if ! kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    echo "The corrected 14B vLLM server exited before becoming ready." >&2
    tail -n 100 "${sectdd_server_log}" >&2 || true
    exit 3
  fi
  if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null \
    | grep -q '"id":"qwen25-coder-14b"'; then
    echo "Ready: qwen25-coder-14b on port ${sectdd_port}"
    break
  fi
  if (( sectdd_attempt == 180 )); then
    echo "Timed out waiting for the corrected 14B vLLM server." >&2
    tail -n 100 "${sectdd_server_log}" >&2 || true
    exit 3
  fi
  if (( sectdd_attempt % 12 == 0 )); then
    echo "Still waiting for qwen25-coder-14b on port ${sectdd_port}..."
  fi
  sleep 5
done

.venv/bin/python tools/run_task_shards.py \
  --served-model qwen25-coder-14b \
  --api-base "http://127.0.0.1:${sectdd_port}/v1" \
  --tokenizer "${sectdd_model}" \
  --config "${sectdd_config}" \
  --visible-projection "${sectdd_visible}" \
  --hidden-projection "${sectdd_hidden}" \
  --output-root "${sectdd_shards}" \
  --max-workers "${sectdd_workers}" \
  | tee "${sectdd_run_log}"

.venv/bin/python tools/merge_formal_shards.py \
  "${sectdd_shards}" \
  --output "${sectdd_output}"
.venv/bin/python tools/validate_formal_pilot.py "${sectdd_output}"

.venv/bin/python tools/analyze_main_internal_14b_corrected.py \
  artifacts/main_internal/qwen25-coder-7b-main-002 \
  "${sectdd_output}" \
  artifacts/main_internal/qwen3-32b-main-002 \
  --bootstrap-replicates 10000 \
  --bootstrap-seed 20260728 \
  --json-output "${sectdd_report_json}" \
  --markdown-output "${sectdd_report_md}"

echo "Corrected 14B rerun complete: ${sectdd_output}"
echo "Corrected three-model report: ${sectdd_report_json}"
