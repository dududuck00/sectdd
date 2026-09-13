#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_gpu_7b="${SECTDD_GPU_7B:-2}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-3}"
sectdd_port_7b="${SECTDD_PORT_7B:-18880}"
sectdd_port_14b="${SECTDD_PORT_14B:-18881}"
sectdd_config="${SECTDD_G8_CONFIG:-configs/experiments/codeguardplus_reserve_breadth_wave3_preflight_v1.json}"
sectdd_lock="${SECTDD_G8_LOCK:-configs/experiments/codeguardplus_reserve_breadth_wave3_preflight_v1.lock.json}"
sectdd_visible="${SECTDD_G8_VISIBLE:-configs/oracles/codeguardplus_reserve_breadth_wave3_preflight_visible_v1.json}"
sectdd_hidden="${SECTDD_G8_HIDDEN:-configs/oracles/codeguardplus_reserve_breadth_wave3_preflight_hidden_v1.json}"
sectdd_prompts="${SECTDD_G8_PROMPTS:-configs/prompts/codeguardplus_reserve_breadth_wave3_preflight_v1}"
sectdd_qualified="${SECTDD_G8_QUALIFIED:-configs/benchmarks/codeguardplus_reserve_breadth_wave3_preflight_qualified_v1.json}"
sectdd_freeze="${SECTDD_G8_FREEZE:-benchmarks/manifests/codeguardplus-reserve-breadth-wave3-preflight-v1-freeze.json}"
sectdd_out="${SECTDD_G8_OUTPUT:-artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3/g8-preflight-v1}"
sectdd_report="${sectdd_out}/report.json"
sectdd_markdown="${SECTDD_G8_MARKDOWN:-docs/codeguardplus-reserve-breadth-wave3-g8-preflight-v1.md}"
sectdd_builder="${SECTDD_G8_BUILDER:-tools/build_codeguardplus_breadth_wave3_preflight_v1.py}"
sectdd_freezer="${SECTDD_G8_FREEZER:-tools/freeze_codeguardplus_breadth_wave3_preflight_v1.py}"
sectdd_report_id="${SECTDD_G8_REPORT_ID:-codeguardplus-reserve-breadth-wave3-preflight-v1}"
sectdd_title="${SECTDD_G8_TITLE:-CodeGuard+ reserve breadth-wave3 G8 preflight v1}"
sectdd_per_model="${SECTDD_G8_PER_MODEL:-24}"
sectdd_log_tag="${SECTDD_G8_LOG_TAG:-codeguardplus-breadth-wave3-g8}"
sectdd_completion_label="${SECTDD_G8_COMPLETION_LABEL:-Breadth-wave3}"
sectdd_pids=()

sectdd_cleanup() { local p; for p in "${sectdd_pids[@]}"; do kill -0 "${p}" 2>/dev/null && kill "${p}" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap sectdd_cleanup EXIT INT TERM
sectdd_assert_gpu() { local g="$1" u; case "${g}" in 1|2|3|4|5|6) ;; *) echo "G8 GPU must be one of 1,2,3,4,5,6." >&2; exit 2;; esac; u="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${g}" | awk 'NF {print int($1); exit}')"; [[ -n "${u}" && "${u}" -le 2048 ]] || { echo "GPU ${g} is not free: ${u:-unknown} MiB" >&2; exit 3; }; }
sectdd_wait() { local port="$1" model="$2" pid="$3" log="$4" n; for n in $(seq 1 240); do kill -0 "${pid}" 2>/dev/null || { tail -n 120 "${log}" >&2 || true; return 3; }; if curl -fsS "http://127.0.0.1:${port}/v1/models" 2>/dev/null | "${sectdd_python}" -c 'import json,sys; m=sys.argv[1]; print(int(m in {x.get("id") for x in json.load(sys.stdin).get("data",[])}))' "${model}" 2>/dev/null | grep -qx 1; then echo "Ready: ${model} on port ${port}"; return; fi; sleep 5; done; tail -n 120 "${log}" >&2 || true; return 3; }
sectdd_count() { local m="$1" d="${sectdd_out}/${m}/trajectories"; [[ -d "${d}" ]] || { echo 0; return; }; find "${d}" -type f -name trajectory.json | wc -l; }
sectdd_complete() { [[ -f "${sectdd_out}/$1/run_manifest.json" && -f "${sectdd_out}/$1/summary.json" && "$(sectdd_count "$1")" -eq "${sectdd_per_model}" ]]; }

sectdd_inputs=0
for p in "${sectdd_config}" "${sectdd_lock}" "${sectdd_visible}" "${sectdd_hidden}" "${sectdd_prompts}"; do [[ -e "${p}" ]] && sectdd_inputs=$((sectdd_inputs+1)); done
if [[ "${sectdd_inputs}" -eq 0 ]]; then "${sectdd_python}" "${sectdd_builder}"; elif [[ "${sectdd_inputs}" -ne 5 ]]; then echo "Partial G8 input freeze detected." >&2; exit 2; else echo "Resume: frozen G8 inputs already exist."; fi
mkdir -p "${sectdd_out}" artifacts/logs
need7=true; need14=true; sectdd_complete qwen25-coder-7b && need7=false; sectdd_complete qwen25-coder-14b && need14=false
if [[ "${need7}" == true && "${need14}" == true ]]; then [[ "${sectdd_gpu_7b}" != "${sectdd_gpu_14b}" && "${sectdd_port_7b}" != "${sectdd_port_14b}" ]] || { echo "Concurrent models require distinct GPUs and ports." >&2; exit 2; }; fi
if [[ "${need7}" == true ]]; then sectdd_assert_gpu "${sectdd_gpu_7b}"; SECTDD_GPU="${sectdd_gpu_7b}" SECTDD_PORT="${sectdd_port_7b}" SECTDD_MAX_MODEL_LEN=8192 scripts/serve_qwen25_coder.sh 7b >"artifacts/logs/${sectdd_log_tag}-7b.log" 2>&1 & pid7=$!; sectdd_pids+=("${pid7}"); fi
if [[ "${need14}" == true ]]; then sectdd_assert_gpu "${sectdd_gpu_14b}"; SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=8192 scripts/serve_qwen25_coder.sh 14b >"artifacts/logs/${sectdd_log_tag}-14b.log" 2>&1 & pid14=$!; sectdd_pids+=("${pid14}"); fi
[[ "${need7}" == false ]] || sectdd_wait "${sectdd_port_7b}" qwen25-coder-7b "${pid7}" "artifacts/logs/${sectdd_log_tag}-7b.log"
[[ "${need14}" == false ]] || sectdd_wait "${sectdd_port_14b}" qwen25-coder-14b "${pid14}" "artifacts/logs/${sectdd_log_tag}-14b.log"
sectdd_run() { local m="$1" port="$2" tok="$3" resume=(); [[ -d "${sectdd_out}/${m}" ]] && resume=(--resume); "${sectdd_python}" tools/run_codeguardplus_preflight.py --served-model "${m}" --api-base "http://127.0.0.1:${port}/v1" --tokenizer "${tok}" --config "${sectdd_config}" --visible "${sectdd_visible}" --hidden "${sectdd_hidden}" --output "${sectdd_out}/${m}" "${resume[@]}" >"artifacts/logs/${sectdd_log_tag}-run-${m}.log" 2>&1; }
runpids=()
if [[ "${need7}" == true ]]; then sectdd_run qwen25-coder-7b "${sectdd_port_7b}" <MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct & r7=$!; runpids+=("${r7}"); sectdd_pids+=("${r7}"); else echo "Resume: 7B run complete."; fi
if [[ "${need14}" == true ]]; then sectdd_run qwen25-coder-14b "${sectdd_port_14b}" <MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct & r14=$!; runpids+=("${r14}"); sectdd_pids+=("${r14}"); else echo "Resume: 14B run complete."; fi
while [[ "${#runpids[@]}" -gt 0 ]]; do alive=false; for p in "${runpids[@]}"; do kill -0 "${p}" 2>/dev/null && alive=true; done; [[ "${alive}" == true ]] || break; echo "G8 progress: 7B $(sectdd_count qwen25-coder-7b)/${sectdd_per_model}; 14B $(sectdd_count qwen25-coder-14b)/${sectdd_per_model}"; sleep 20; done
failed=false; for p in "${runpids[@]}"; do wait "${p}" || failed=true; done
if [[ "${failed}" == true ]]; then tail -n 120 "artifacts/logs/${sectdd_log_tag}-run-qwen25-coder-7b.log" 2>/dev/null || true; tail -n 120 "artifacts/logs/${sectdd_log_tag}-run-qwen25-coder-14b.log" 2>/dev/null || true; exit 3; fi
analysis=0; for p in "${sectdd_report}" "${sectdd_markdown}" "${sectdd_qualified}"; do [[ -e "${p}" ]] && analysis=$((analysis+1)); done
if [[ "${analysis}" -eq 0 ]]; then "${sectdd_python}" tools/analyze_sallm_expansion_preflight.py "${sectdd_out}/qwen25-coder-7b" "${sectdd_out}/qwen25-coder-14b" --json-output "${sectdd_report}" --markdown-output "${sectdd_markdown}" --qualified-task-file "${sectdd_qualified}" --report-id "${sectdd_report_id}" --title "${sectdd_title}" --remaining-gate "independent human G7 and final freeze"; elif [[ "${analysis}" -ne 3 ]]; then echo "Partial G8 analysis detected." >&2; exit 2; else echo "Resume: G8 analysis complete."; fi
if [[ ! -f "${sectdd_freeze}" ]]; then "${sectdd_python}" "${sectdd_freezer}"; else echo "Resume: G8 freeze complete."; fi
"${sectdd_python}" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["summary"],indent=2,sort_keys=True))' "${sectdd_report}"
echo "${sectdd_completion_label} G8 preflight completed: ${sectdd_report}"
