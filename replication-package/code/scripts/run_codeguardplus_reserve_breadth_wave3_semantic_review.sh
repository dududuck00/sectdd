#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_task_file="benchmarks/manifests/codeguardplus-reserve-breadth-wave3-freeze.json"
sectdd_oracle_manifest="oracles/codeguardplus_reserve_breadth_wave3/manifest.json"
sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3/semantic-review"
sectdd_report_id="codeguardplus-reserve-breadth-wave3-semantic-machine-panel-v1"
sectdd_reviewer_lock="configs/experiments/codeguardplus_reserve_breadth_wave3_semantic_reviewer_recovery_v1.json"
sectdd_gpu_14b="${SECTDD_GPU_14B:-2}"
sectdd_gpu_qwen3="${SECTDD_GPU_QWEN3:-${SECTDD_GPU_35B:-3}}"
sectdd_port_14b="${SECTDD_PORT_14B:-18781}"
sectdd_port_qwen3="${SECTDD_PORT_QWEN3:-${SECTDD_PORT_35B:-18782}}"
sectdd_log_root="artifacts/logs"
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
  local sectdd_gpu="$1" sectdd_used
  case "${sectdd_gpu}" in
    2|3|4|5|6) ;;
    *) echo "Semantic-review GPUs must be selected from 2, 3, 4, 5, 6." >&2; exit 2 ;;
  esac
  sectdd_used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  if [[ -z "${sectdd_used}" || "${sectdd_used}" -gt 2048 ]]; then
    echo "GPU ${sectdd_gpu} is not free: ${sectdd_used:-unknown} MiB" >&2
    exit 3
  fi
}

sectdd_wait_model() {
  local sectdd_port="$1" sectdd_model="$2" sectdd_pid="$3" sectdd_log="$4" sectdd_attempt
  for sectdd_attempt in $(seq 1 240); do
    if ! kill -0 "${sectdd_pid}" 2>/dev/null; then
      tail -n 120 "${sectdd_log}" >&2 || true
      return 3
    fi
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null \
      | "${sectdd_python}" -c 'import json,sys; m=sys.argv[1]; print(int(m in {x.get("id") for x in json.load(sys.stdin).get("data", [])}))' "${sectdd_model}" 2>/dev/null \
      | grep -qx 1; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    sleep 5
  done
  tail -n 120 "${sectdd_log}" >&2 || true
  return 3
}

sectdd_review_count() {
  local sectdd_model="$1"
  if [[ ! -d "${sectdd_output}/reviews/${sectdd_model}" ]]; then
    echo 0
    return
  fi
  find "${sectdd_output}/reviews/${sectdd_model}" -maxdepth 1 -type f -name '*.json' | wc -l
}

"${sectdd_python}" -c '
import json, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
assert d.get("formal_experiment_ready") is False
assert d["qualified_task_ids"] == ["cwe-022/1-py", "cwe-078/2-py", "cwe-079/2-py", "cwe-377/1-py"]
assert d["counts"]["repeat_observations"] == 48
' "${sectdd_task_file}"
"${sectdd_python}" -c '
import json, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
assert d["outcome_blinding"]["qwen25_coder_14b_review_verdicts_read_for_replacement"] is False
assert d["frozen_reviewers"] == ["qwen25-coder-14b", "qwen3-32b"]
assert d["replacement"]["missing_weight_shards"] == 0
' "${sectdd_reviewer_lock}"

if [[ ! -f "${sectdd_output}/packet_manifest.json" ]]; then
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_task_file}" \
    --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle_manifest}" \
    --output "${sectdd_output}" --report-id "${sectdd_report_id}" \
    --prepare-only --confirm-machine-review
else
  echo "Resume: blinded semantic packets already prepared."
fi

sectdd_task_count="$("${sectdd_python}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_count"])' "${sectdd_output}/packet_manifest.json")"
sectdd_need_14b=true
sectdd_need_qwen3=true
[[ "$(sectdd_review_count qwen25-coder-14b)" -eq "${sectdd_task_count}" ]] && sectdd_need_14b=false
[[ "$(sectdd_review_count qwen3-32b)" -eq "${sectdd_task_count}" ]] && sectdd_need_qwen3=false

if [[ "${sectdd_need_14b}" == true && "${sectdd_need_qwen3}" == true ]]; then
  [[ "${sectdd_gpu_14b}" != "${sectdd_gpu_qwen3}" ]] || { echo "Reviewers require different GPUs." >&2; exit 2; }
  [[ "${sectdd_port_14b}" != "${sectdd_port_qwen3}" ]] || { echo "Reviewers require different ports." >&2; exit 2; }
fi

mkdir -p "${sectdd_log_root}"
if [[ "${sectdd_need_14b}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_14b}"
  SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=16384 \
    scripts/serve_qwen25_coder.sh 14b \
    >"${sectdd_log_root}/codeguardplus-breadth-wave3-semantic-qwen25-14b.log" 2>&1 &
  sectdd_pid_14b=$!
  sectdd_pids+=("${sectdd_pid_14b}")
fi
if [[ "${sectdd_need_qwen3}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_qwen3}"
  SECTDD_GPU="${sectdd_gpu_qwen3}" SECTDD_PORT="${sectdd_port_qwen3}" SECTDD_MAX_MODEL_LEN=16384 \
    scripts/serve_qwen25_coder.sh qwen3-32b \
    >"${sectdd_log_root}/codeguardplus-breadth-wave3-semantic-qwen3-32b.log" 2>&1 &
  sectdd_pid_qwen3=$!
  sectdd_pids+=("${sectdd_pid_qwen3}")
fi

if [[ "${sectdd_need_14b}" == true ]]; then
  sectdd_wait_model "${sectdd_port_14b}" qwen25-coder-14b "${sectdd_pid_14b}" \
    "${sectdd_log_root}/codeguardplus-breadth-wave3-semantic-qwen25-14b.log"
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_task_file}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle_manifest}" --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" \
    --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_port_14b}/v1" \
    --local-thinking disabled --max-workers 2 --max-tokens 8192 \
    --timeout-seconds 600 --confirm-machine-review
else
  echo "Resume: qwen25-coder-14b already completed ${sectdd_task_count}/${sectdd_task_count}."
fi

if [[ "${sectdd_need_qwen3}" == true ]]; then
  sectdd_wait_model "${sectdd_port_qwen3}" qwen3-32b "${sectdd_pid_qwen3}" \
    "${sectdd_log_root}/codeguardplus-breadth-wave3-semantic-qwen3-32b.log"
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_task_file}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle_manifest}" --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" \
    --reviewer "qwen3-32b=http://127.0.0.1:${sectdd_port_qwen3}/v1" \
    --local-thinking disabled --max-workers 2 --max-tokens 8192 \
    --timeout-seconds 600 --confirm-machine-review
else
  echo "Resume: qwen3-32b already completed ${sectdd_task_count}/${sectdd_task_count}."
fi

test -f "${sectdd_output}/report.json"
"${sectdd_python}" -c '
import json, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
models={x["model"] for x in d["reviewers"]}
assert models == {"qwen25-coder-14b", "qwen3-32b"}, models
print(json.dumps(d["summary"], indent=2, sort_keys=True))
' "${sectdd_output}/report.json"
echo "Breadth-wave3 machine semantic panel completed: ${sectdd_output}/report.json"
