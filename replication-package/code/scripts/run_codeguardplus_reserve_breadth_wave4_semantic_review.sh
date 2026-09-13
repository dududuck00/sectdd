#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_tasks="benchmarks/manifests/codeguardplus-reserve-breadth-wave4-freeze.json"
sectdd_oracle="oracles/codeguardplus_reserve_breadth_wave4/manifest.json"
sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-review"
sectdd_report_id="codeguardplus-reserve-breadth-wave4-semantic-machine-panel-v1"
sectdd_gpu_14b="${SECTDD_GPU_14B:-1}"
sectdd_gpu_35b="${SECTDD_GPU_35B:-2}"
sectdd_port_14b="${SECTDD_PORT_14B:-18981}"
sectdd_port_35b="${SECTDD_PORT_35B:-18982}"
sectdd_pids=()

cleanup() { local p; for p in "${sectdd_pids[@]}"; do kill -0 "${p}" 2>/dev/null && kill "${p}" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM
assert_gpu() { local g="$1" u; case "${g}" in 1|2|3|4|5|6) ;; *) echo "Semantic GPU must be one of 1,2,3,4,5,6." >&2; exit 2;; esac; u="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${g}" | awk 'NF {print int($1); exit}')"; [[ -n "${u}" && "${u}" -le 2048 ]] || { echo "GPU ${g} is not free: ${u:-unknown} MiB" >&2; exit 3; }; }
wait_model() { local port="$1" model="$2" pid="$3" log="$4" n; for n in $(seq 1 240); do kill -0 "${pid}" 2>/dev/null || { tail -n 120 "${log}" >&2 || true; return 3; }; if curl -fsS "http://127.0.0.1:${port}/v1/models" 2>/dev/null | "${sectdd_python}" -c 'import json,sys; m=sys.argv[1]; print(int(m in {x.get("id") for x in json.load(sys.stdin).get("data",[])}))' "${model}" 2>/dev/null | grep -qx 1; then echo "Ready: ${model} on port ${port}"; return; fi; sleep 5; done; tail -n 120 "${log}" >&2 || true; return 3; }
review_count() { local m="$1"; [[ -d "${sectdd_output}/reviews/${m}" ]] || { echo 0; return; }; find "${sectdd_output}/reviews/${m}" -maxdepth 1 -type f -name '*.json' | wc -l; }

"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["qualified_task_ids"]==["cwe-327/0-py","cwe-117/2-py"]; assert d["counts"]["repeat_observations"]==24' "${sectdd_tasks}"
if [[ ! -f "${sectdd_output}/packet_manifest.json" ]]; then
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py --task-file "${sectdd_tasks}" --benchmark benchmarks/manifests/codeguardplus-v1.json --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" --report-id "${sectdd_report_id}" --prepare-only --confirm-machine-review
else echo "Resume: blinded wave4 semantic packets already prepared."; fi
task_count="$("${sectdd_python}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_count"])' "${sectdd_output}/packet_manifest.json")"
need14=true; need35=true; [[ "$(review_count qwen25-coder-14b)" -eq "${task_count}" ]] && need14=false; [[ "$(review_count qwen36-35b-a3b)" -eq "${task_count}" ]] && need35=false
if [[ "${need14}" == true && "${need35}" == true ]]; then [[ "${sectdd_gpu_14b}" != "${sectdd_gpu_35b}" && "${sectdd_port_14b}" != "${sectdd_port_35b}" ]] || { echo "Reviewers require distinct GPUs and ports." >&2; exit 2; }; fi
mkdir -p artifacts/logs
if [[ "${need14}" == true ]]; then assert_gpu "${sectdd_gpu_14b}"; SECTDD_GPU="${sectdd_gpu_14b}" SECTDD_PORT="${sectdd_port_14b}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen25_coder.sh 14b >artifacts/logs/codeguardplus-wave4-semantic-14b.log 2>&1 & pid14=$!; sectdd_pids+=("${pid14}"); fi
if [[ "${need35}" == true ]]; then assert_gpu "${sectdd_gpu_35b}"; SECTDD_GPUS="${sectdd_gpu_35b}" SECTDD_PORT="${sectdd_port_35b}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen36.sh 35b-a3b >artifacts/logs/codeguardplus-wave4-semantic-35b.log 2>&1 & pid35=$!; sectdd_pids+=("${pid35}"); fi
if [[ "${need14}" == true ]]; then wait_model "${sectdd_port_14b}" qwen25-coder-14b "${pid14}" artifacts/logs/codeguardplus-wave4-semantic-14b.log; "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py --task-file "${sectdd_tasks}" --benchmark benchmarks/manifests/codeguardplus-v1.json --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" --report-id "${sectdd_report_id}" --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_port_14b}/v1" --local-thinking disabled --max-workers 2 --max-tokens 8192 --timeout-seconds 600 --confirm-machine-review; else echo "Resume: 14B reviews complete."; fi
if [[ "${need35}" == true ]]; then wait_model "${sectdd_port_35b}" qwen36-35b-a3b "${pid35}" artifacts/logs/codeguardplus-wave4-semantic-35b.log; "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py --task-file "${sectdd_tasks}" --benchmark benchmarks/manifests/codeguardplus-v1.json --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" --report-id "${sectdd_report_id}" --reviewer "qwen36-35b-a3b=http://127.0.0.1:${sectdd_port_35b}/v1" --local-thinking disabled --max-workers 2 --max-tokens 8192 --timeout-seconds 600 --confirm-machine-review; else echo "Resume: 35B reviews complete."; fi
test -f "${sectdd_output}/report.json"
"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert {x["model"] for x in d["reviewers"]}=={"qwen25-coder-14b","qwen36-35b-a3b"}; print(json.dumps(d["summary"],indent=2,sort_keys=True))' "${sectdd_output}/report.json"
echo "Wave4 semantic panel completed: ${sectdd_output}/report.json"
