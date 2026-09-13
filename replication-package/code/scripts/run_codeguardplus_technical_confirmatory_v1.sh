#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_gpu_7b="${SECTDD_GPU_7B:-4}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-5}"
sectdd_gpu_27b="${SECTDD_GPU_27B:-4}"
sectdd_port_7b="${SECTDD_PORT_7B:-19180}"
sectdd_port_14b="${SECTDD_PORT_14B:-19181}"
sectdd_port_27b="${SECTDD_PORT_27B:-19183}"
sectdd_config="configs/experiments/codeguardplus_technical_confirmatory_no_g7_v1.json"
sectdd_visible="configs/oracles/codeguardplus_technical_confirmatory_no_g7_visible_v1.json"
sectdd_hidden="configs/oracles/codeguardplus_technical_confirmatory_no_g7_hidden_v1.json"
sectdd_output="artifacts/codeguardplus-technical-confirmatory-no-g7-v1"
sectdd_report="${sectdd_output}/report.json"
sectdd_markdown="docs/codeguardplus-technical-confirmatory-no-g7-v1.md"
sectdd_expected=75
sectdd_pids=()

sectdd_cleanup() {
  local p
  for p in "${sectdd_pids[@]:-}"; do
    kill -0 "${p}" 2>/dev/null && kill "${p}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

sectdd_assert_gpu() {
  local gpu="$1" used
  case "${gpu}" in 1|2|3|4|5|6) ;; *) echo "GPU must be one of 1,2,3,4,5,6." >&2; exit 2;; esac
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${gpu}" | awk 'NF {print int($1); exit}')"
  [[ -n "${used}" && "${used}" -le 2048 ]] || { echo "GPU ${gpu} is not free: ${used:-unknown} MiB" >&2; exit 3; }
}

sectdd_wait() {
  local port="$1" model="$2" pid="$3" log="$4" attempt
  for attempt in $(seq 1 240); do
    kill -0 "${pid}" 2>/dev/null || { tail -n 120 "${log}" >&2 || true; return 3; }
    if curl -fsS "http://127.0.0.1:${port}/v1/models" 2>/dev/null | "${sectdd_python}" -c 'import json,sys; m=sys.argv[1]; print(int(m in {x.get("id") for x in json.load(sys.stdin).get("data",[])}))' "${model}" 2>/dev/null | grep -qx 1; then
      echo "Ready: ${model} on port ${port}"
      return
    fi
    (( attempt % 12 != 0 )) || echo "Still waiting for ${model}..."
    sleep 5
  done
  tail -n 120 "${log}" >&2 || true
  return 3
}

sectdd_count() {
  local model="$1" dir="${sectdd_output}/${model}/trajectories"
  [[ -d "${dir}" ]] || { echo 0; return; }
  find "${dir}" -type f -name trajectory.json | wc -l
}

sectdd_complete() {
  local model="$1"
  [[ -f "${sectdd_output}/${model}/run_manifest.json" && -f "${sectdd_output}/${model}/summary.json" && "$(sectdd_count "${model}")" -eq "${sectdd_expected}" ]]
}

sectdd_run() {
  local model="$1" port="$2" tokenizer="$3" resume=()
  [[ -d "${sectdd_output}/${model}" ]] && resume=(--resume)
  "${sectdd_python}" tools/run_codeguardplus_preflight.py \
    --served-model "${model}" \
    --api-base "http://127.0.0.1:${port}/v1" \
    --tokenizer "${tokenizer}" \
    --config "${sectdd_config}" \
    --visible "${sectdd_visible}" \
    --hidden "${sectdd_hidden}" \
    --output "${sectdd_output}/${model}" \
    "${resume[@]}" \
    >"artifacts/logs/codeguardplus-technical-run-${model}.log" 2>&1
}

sectdd_wait_runs() {
  local p alive failed=false
  local -a runpids=("$@")
  while [[ "${#runpids[@]}" -gt 0 ]]; do
    alive=false
    for p in "${runpids[@]}"; do kill -0 "${p}" 2>/dev/null && alive=true; done
    [[ "${alive}" == true ]] || break
    echo "Technical confirmatory progress: 7B $(sectdd_count qwen25-coder-7b)/75; 14B $(sectdd_count qwen25-coder-14b)/75; 27B $(sectdd_count qwen36-27b)/75"
    sleep 20
  done
  for p in "${runpids[@]}"; do wait "${p}" || failed=true; done
  [[ "${failed}" == false ]]
}

mkdir -p "${sectdd_output}" artifacts/logs
"${sectdd_python}" tools/build_codeguardplus_technical_confirmatory_v1.py

need7=true; need14=true
sectdd_complete qwen25-coder-7b && need7=false
sectdd_complete qwen25-coder-14b && need14=false
if [[ "${need7}" == true && "${need14}" == true && "${sectdd_gpu_7b}" == "${sectdd_gpu_14b}" ]]; then
  echo "Concurrent 7B and 14B runs require distinct GPUs." >&2
  exit 2
fi
if [[ "${need7}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_7b}"
  SECTDD_GPU="${sectdd_gpu_7b}" SECTDD_PORT="${sectdd_port_7b}" SECTDD_MAX_MODEL_LEN=8192 scripts/serve_qwen25_coder.sh 7b >artifacts/logs/codeguardplus-technical-server-7b.log 2>&1 &
  server7=$!; sectdd_pids+=("${server7}")
fi
if [[ "${need14}" == true ]]; then
  sectdd_assert_gpu "${sectdd_gpu_14b}"
  SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=8192 scripts/serve_qwen25_coder.sh 14b >artifacts/logs/codeguardplus-technical-server-14b.log 2>&1 &
  server14=$!; sectdd_pids+=("${server14}")
fi
[[ "${need7}" == false ]] || sectdd_wait "${sectdd_port_7b}" qwen25-coder-7b "${server7}" artifacts/logs/codeguardplus-technical-server-7b.log
[[ "${need14}" == false ]] || sectdd_wait "${sectdd_port_14b}" qwen25-coder-14b "${server14}" artifacts/logs/codeguardplus-technical-server-14b.log
runpids=()
if [[ "${need7}" == true ]]; then sectdd_run qwen25-coder-7b "${sectdd_port_7b}" <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct & run7=$!; runpids+=("${run7}"); sectdd_pids+=("${run7}"); else echo "Resume: 7B complete."; fi
if [[ "${need14}" == true ]]; then sectdd_run qwen25-coder-14b "${sectdd_port_14b}" <MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct & run14=$!; runpids+=("${run14}"); sectdd_pids+=("${run14}"); else echo "Resume: 14B complete."; fi
if [[ "${#runpids[@]}" -gt 0 ]] && ! sectdd_wait_runs "${runpids[@]}"; then
  tail -n 120 artifacts/logs/codeguardplus-technical-run-qwen25-coder-7b.log 2>/dev/null || true
  tail -n 120 artifacts/logs/codeguardplus-technical-run-qwen25-coder-14b.log 2>/dev/null || true
  exit 3
fi
for p in "${server7:-}" "${server14:-}"; do [[ -z "${p}" ]] || { kill "${p}" 2>/dev/null || true; wait "${p}" 2>/dev/null || true; }; done

if ! sectdd_complete qwen36-27b; then
  sectdd_assert_gpu "${sectdd_gpu_27b}"
  SECTDD_GPUS="${sectdd_gpu_27b}" SECTDD_PORT="${sectdd_port_27b}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen36.sh 27b >artifacts/logs/codeguardplus-technical-server-27b.log 2>&1 &
  server27=$!; sectdd_pids+=("${server27}")
  sectdd_wait "${sectdd_port_27b}" qwen36-27b "${server27}" artifacts/logs/codeguardplus-technical-server-27b.log
  sectdd_run qwen36-27b "${sectdd_port_27b}" <MODEL_ROOT>/Qwen3.6/Qwen3.6-27B & run27=$!; sectdd_pids+=("${run27}")
  if ! sectdd_wait_runs "${run27}"; then tail -n 120 artifacts/logs/codeguardplus-technical-run-qwen36-27b.log >&2 || true; exit 3; fi
else
  echo "Resume: 27B complete."
fi

if [[ ! -f "${sectdd_report}" && ! -f "${sectdd_markdown}" ]]; then
  "${sectdd_python}" tools/analyze_codeguardplus_technical_confirmatory_v1.py \
    "${sectdd_output}/qwen25-coder-7b" \
    "${sectdd_output}/qwen25-coder-14b" \
    "${sectdd_output}/qwen36-27b" \
    --json-output "${sectdd_report}" \
    --markdown-output "${sectdd_markdown}"
elif [[ ! -f "${sectdd_report}" || ! -f "${sectdd_markdown}" ]]; then
  echo "Partial technical-confirmatory analysis detected." >&2
  exit 2
else
  echo "Resume: analysis complete."
fi
if [[ ! -f benchmarks/manifests/codeguardplus-technical-confirmatory-no-g7-results-v1-freeze.json ]]; then
  "${sectdd_python}" tools/freeze_codeguardplus_technical_confirmatory_v1.py
else
  echo "Resume: result freeze complete."
fi
"${sectdd_python}" -c 'import json; d=json.load(open("artifacts/codeguardplus-technical-confirmatory-no-g7-v1/report.json")); print(json.dumps({"design":d["design"],"formal_results_use":d["formal_results_use"],"human_g7_status":d["human_g7_status"]},indent=2))'
echo "CodeGuard+ technical confirmatory experiment completed: ${sectdd_report}"
