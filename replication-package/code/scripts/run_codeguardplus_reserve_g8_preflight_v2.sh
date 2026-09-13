#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_gpu_7b="${SECTDD_GPU_7B:-4}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-5}"
sectdd_port_7b="${SECTDD_PORT_7B:-18680}"
sectdd_port_14b="${SECTDD_PORT_14B:-18681}"
sectdd_config="configs/experiments/codeguardplus_reserve_preflight_v2.json"
sectdd_lock="configs/experiments/codeguardplus_reserve_preflight_v2.lock.json"
sectdd_visible="configs/oracles/codeguardplus_reserve_preflight_visible_v2.json"
sectdd_hidden="configs/oracles/codeguardplus_reserve_preflight_hidden_v2.json"
sectdd_prompts="configs/prompts/codeguardplus_reserve_preflight_v2"
sectdd_qualified="configs/benchmarks/codeguardplus_reserve_preflight_qualified_v2.json"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-preflight-v2-freeze.json"
sectdd_root_out="artifacts/codeguardplus-reserve-expansion-v1/g8-preflight-v2"
sectdd_report="${sectdd_root_out}/report.json"
sectdd_markdown="docs/codeguardplus-reserve-g8-preflight-v2.md"
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
    *) echo "G8 GPUs must be selected from 2, 3, 4, 5, 6." >&2; exit 2 ;;
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

sectdd_complete_model_run() {
  local sectdd_model="$1"
  [[ -f "${sectdd_root_out}/${sectdd_model}/run_manifest.json" \
    && -f "${sectdd_root_out}/${sectdd_model}/summary.json" ]]
}

sectdd_trajectory_count() {
  local sectdd_model="$1"
  local sectdd_directory="${sectdd_root_out}/${sectdd_model}/trajectories"
  if [[ ! -d "${sectdd_directory}" ]]; then
    echo 0
    return
  fi
  find "${sectdd_directory}" -type f -name trajectory.json | wc -l
}

sectdd_build_count=0
for sectdd_path in "${sectdd_config}" "${sectdd_lock}" "${sectdd_visible}" "${sectdd_hidden}" "${sectdd_prompts}"; do
  [[ -e "${sectdd_path}" ]] && sectdd_build_count=$((sectdd_build_count + 1))
done
if [[ "${sectdd_build_count}" -eq 0 ]]; then
  "${sectdd_python}" tools/build_codeguardplus_reserve_preflight_v2.py
elif [[ "${sectdd_build_count}" -ne 5 ]]; then
  echo "Partial G8 input freeze detected; refusing to mix inputs." >&2
  exit 2
else
  echo "Resume: frozen G8 inputs already exist."
fi

mkdir -p "${sectdd_root_out}" artifacts/logs
sectdd_need_7b=true
sectdd_need_14b=true
sectdd_complete_model_run qwen25-coder-7b && sectdd_need_7b=false
sectdd_complete_model_run qwen25-coder-14b && sectdd_need_14b=false
if [[ "${sectdd_need_7b}" == true && "${sectdd_need_14b}" == true ]]; then
  if [[ "${sectdd_gpu_7b}" == "${sectdd_gpu_14b}" ]]; then
    echo "The two concurrent G8 model services require different GPUs." >&2
    exit 2
  fi
  if [[ "${sectdd_port_7b}" == "${sectdd_port_14b}" ]]; then
    echo "The two concurrent G8 model services require different ports." >&2
    exit 2
  fi
fi

if [[ "${sectdd_need_7b}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_7b}"
  SECTDD_GPU="${sectdd_gpu_7b}" SECTDD_PORT="${sectdd_port_7b}" SECTDD_MAX_MODEL_LEN=8192 \
    scripts/serve_qwen25_coder.sh 7b \
    >"artifacts/logs/codeguardplus-reserve-g8-v2-qwen25-7b.log" 2>&1 &
  sectdd_server_7b=$!
  sectdd_pids+=("${sectdd_server_7b}")
fi
if [[ "${sectdd_need_14b}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_14b}"
  SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=8192 \
    scripts/serve_qwen25_coder.sh 14b \
    >"artifacts/logs/codeguardplus-reserve-g8-v2-qwen25-14b.log" 2>&1 &
  sectdd_server_14b=$!
  sectdd_pids+=("${sectdd_server_14b}")
fi

if [[ "${sectdd_need_7b}" == true ]]; then
  sectdd_wait_model "${sectdd_port_7b}" qwen25-coder-7b "${sectdd_server_7b}" \
    "artifacts/logs/codeguardplus-reserve-g8-v2-qwen25-7b.log"
fi
if [[ "${sectdd_need_14b}" == true ]]; then
  sectdd_wait_model "${sectdd_port_14b}" qwen25-coder-14b "${sectdd_server_14b}" \
    "artifacts/logs/codeguardplus-reserve-g8-v2-qwen25-14b.log"
fi

sectdd_run_model() {
  local sectdd_model="$1" sectdd_port="$2" sectdd_tokenizer="$3" sectdd_resume=()
  [[ -d "${sectdd_root_out}/${sectdd_model}" ]] && sectdd_resume=(--resume)
  "${sectdd_python}" tools/run_codeguardplus_preflight.py \
    --served-model "${sectdd_model}" \
    --api-base "http://127.0.0.1:${sectdd_port}/v1" \
    --tokenizer "${sectdd_tokenizer}" \
    --config "${sectdd_config}" --visible "${sectdd_visible}" --hidden "${sectdd_hidden}" \
    --output "${sectdd_root_out}/${sectdd_model}" "${sectdd_resume[@]}" \
    >"artifacts/logs/codeguardplus-reserve-g8-v2-run-${sectdd_model}.log" 2>&1
}

sectdd_run_pids=()
if [[ "${sectdd_need_7b}" == true ]]; then
  sectdd_run_model qwen25-coder-7b "${sectdd_port_7b}" <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct &
  sectdd_run_7b=$!
  sectdd_run_pids+=("${sectdd_run_7b}")
  sectdd_pids+=("${sectdd_run_7b}")
else
  echo "Resume: qwen25-coder-7b model run already complete."
fi
if [[ "${sectdd_need_14b}" == true ]]; then
  sectdd_run_model qwen25-coder-14b "${sectdd_port_14b}" <MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct &
  sectdd_run_14b=$!
  sectdd_run_pids+=("${sectdd_run_14b}")
  sectdd_pids+=("${sectdd_run_14b}")
else
  echo "Resume: qwen25-coder-14b model run already complete."
fi
while [[ "${#sectdd_run_pids[@]}" -gt 0 ]]; do
  sectdd_alive=false
  for sectdd_pid in "${sectdd_run_pids[@]}"; do
    kill -0 "${sectdd_pid}" 2>/dev/null && sectdd_alive=true
  done
  [[ "${sectdd_alive}" == false ]] && break
  sectdd_done_7b="$(sectdd_trajectory_count qwen25-coder-7b)"
  sectdd_done_14b="$(sectdd_trajectory_count qwen25-coder-14b)"
  echo "G8 progress: qwen25-coder-7b ${sectdd_done_7b}/16; qwen25-coder-14b ${sectdd_done_14b}/16"
  sleep 20
done
sectdd_run_failed=false
for sectdd_pid in "${sectdd_run_pids[@]}"; do
  if ! wait "${sectdd_pid}"; then
    sectdd_run_failed=true
  fi
done
if [[ "${sectdd_run_failed}" == true ]]; then
  tail -n 120 artifacts/logs/codeguardplus-reserve-g8-v2-run-qwen25-coder-7b.log 2>/dev/null || true
  tail -n 120 artifacts/logs/codeguardplus-reserve-g8-v2-run-qwen25-coder-14b.log 2>/dev/null || true
  exit 3
fi

sectdd_analysis_count=0
for sectdd_path in "${sectdd_report}" "${sectdd_markdown}" "${sectdd_qualified}"; do
  [[ -e "${sectdd_path}" ]] && sectdd_analysis_count=$((sectdd_analysis_count + 1))
done
if [[ "${sectdd_analysis_count}" -eq 0 ]]; then
  "${sectdd_python}" tools/analyze_sallm_expansion_preflight.py \
    "${sectdd_root_out}/qwen25-coder-7b" "${sectdd_root_out}/qwen25-coder-14b" \
    --json-output "${sectdd_report}" --markdown-output "${sectdd_markdown}" \
    --qualified-task-file "${sectdd_qualified}" \
    --report-id codeguardplus-reserve-preflight-v2 \
    --title "CodeGuard+ reserve G8 preflight v2" \
    --remaining-gate "independent second-researcher semantic review (G7) and final freeze"
elif [[ "${sectdd_analysis_count}" -ne 3 ]]; then
  echo "Partial G8 analysis detected; refusing to overwrite evidence." >&2
  exit 2
else
  echo "Resume: G8 analysis already complete."
fi

if [[ ! -f "${sectdd_freeze}" ]]; then
  "${sectdd_python}" tools/freeze_codeguardplus_reserve_preflight_v2.py
else
  echo "Resume: G8 freeze already complete."
fi
echo "CodeGuard+ reserve G8 preflight completed: ${sectdd_report}"
