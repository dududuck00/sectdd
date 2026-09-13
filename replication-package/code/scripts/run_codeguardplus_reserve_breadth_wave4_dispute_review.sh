#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_model_root="<MODEL_ROOT>/models/Qwen3-32B"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-dispute-v1.json"
sectdd_oracle="oracles/codeguardplus_reserve_breadth_wave4_dispute_v1/manifest.json"
sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-dispute-review"
sectdd_report_id="codeguardplus-reserve-breadth-wave4-semantic-dispute-v1"
sectdd_gpu="${SECTDD_GPU_QWEN3:-5}"; sectdd_port="${SECTDD_PORT_QWEN3:-18983}"
sectdd_log="artifacts/logs/codeguardplus-wave4-dispute-qwen3-32b.log"; sectdd_pid=""
cleanup() { if [[ -n "${sectdd_pid}" ]] && kill -0 "${sectdd_pid}" 2>/dev/null; then kill "${sectdd_pid}" 2>/dev/null || true; wait "${sectdd_pid}" 2>/dev/null || true; fi; }; trap cleanup EXIT INT TERM
case "${sectdd_gpu}" in 1|2|3|4|5|6) ;; *) echo "Dispute GPU must be one of 1,2,3,4,5,6." >&2; exit 2;; esac
test -f "${sectdd_model_root}/config.json"; test -f "${sectdd_model_root}/model.safetensors.index.json"
count=0; for p in "${sectdd_freeze}" "${sectdd_oracle}"; do [[ -e "${p}" ]] && count=$((count+1)); done
if [[ "${count}" -eq 0 ]]; then "${sectdd_python}" tools/build_codeguardplus_breadth_wave4_semantic_dispute_v1.py; elif [[ "${count}" -ne 2 ]]; then echo "Partial dispute freeze detected." >&2; exit 2; else "${sectdd_python}" tools/build_codeguardplus_breadth_wave4_semantic_dispute_v1.py --verify-only; fi
if [[ ! -f "${sectdd_output}/packet_manifest.json" ]]; then "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py --task-file "${sectdd_freeze}" --benchmark benchmarks/manifests/codeguardplus-v1.json --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" --report-id "${sectdd_report_id}" --prepare-only --confirm-machine-review; else echo "Resume: blinded CWE-117 dispute packet prepared."; fi
review="${sectdd_output}/reviews/qwen3-32b/cwe-117__2-py.json"
if [[ ! -f "${review}" ]]; then
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"; [[ -n "${used}" && "${used}" -le 2048 ]] || { echo "GPU ${sectdd_gpu} is not free: ${used:-unknown} MiB" >&2; exit 3; }
  mkdir -p artifacts/logs; SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen25_coder.sh qwen3-32b >"${sectdd_log}" 2>&1 & sectdd_pid=$!
  for n in $(seq 1 240); do kill -0 "${sectdd_pid}" 2>/dev/null || { tail -n 120 "${sectdd_log}" >&2 || true; exit 3; }; if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null | "${sectdd_python}" -c 'import json,sys; print(int("qwen3-32b" in {x.get("id") for x in json.load(sys.stdin).get("data",[])}))' 2>/dev/null | grep -qx 1; then echo "Ready: qwen3-32b on port ${sectdd_port}"; break; fi; [[ "${n}" -lt 240 ]] || { tail -n 120 "${sectdd_log}" >&2 || true; exit 3; }; sleep 5; done
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py --task-file "${sectdd_freeze}" --benchmark benchmarks/manifests/codeguardplus-v1.json --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" --report-id "${sectdd_report_id}" --reviewer "qwen3-32b=http://127.0.0.1:${sectdd_port}/v1" --local-thinking disabled --max-workers 1 --max-tokens 8192 --timeout-seconds 600 --confirm-machine-review
else echo "Resume: Qwen3-32B CWE-117 dispute review complete."; fi
"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({"task_id":"cwe-117/2-py","reviewer":d["reviewer"]["model"],"verdict":d["review"]["verdict"],"confidence":d["review"]["confidence"],"summary":d["review"]["summary"]},ensure_ascii=False,indent=2))' "${review}"
echo "CWE-117 blinded dispute review completed: ${review}"
