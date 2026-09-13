#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_model_root="<MODEL_ROOT>/Qwen3.6/Qwen3.6-35B-A3B"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave3-semantic-dispute-v1.json"
sectdd_oracle="oracles/codeguardplus_reserve_breadth_wave3_dispute_v1/manifest.json"
sectdd_output="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3/semantic-dispute-review"
sectdd_report_id="codeguardplus-reserve-breadth-wave3-semantic-dispute-v1"
sectdd_gpu="${SECTDD_GPU_QWEN36:-3}"
sectdd_port="${SECTDD_PORT_QWEN36:-18783}"
sectdd_log="artifacts/logs/codeguardplus-breadth-wave3-dispute-qwen36-35b-a3b.log"
sectdd_pid=""

sectdd_cleanup() {
  if [[ -n "${sectdd_pid}" ]] && kill -0 "${sectdd_pid}" 2>/dev/null; then
    kill "${sectdd_pid}" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

case "${sectdd_gpu}" in
  2|3|4|5|6) ;;
  *) echo "Dispute-review GPU must be selected from 2, 3, 4, 5, 6." >&2; exit 2 ;;
esac
test -f "${sectdd_model_root}/config.json"
test -f "${sectdd_model_root}/model.safetensors.index.json"
if find "${sectdd_model_root}" -maxdepth 1 -type f -name '*.aria2' | grep -q .; then
  echo "Qwen3.6-35B-A3B download is incomplete; .aria2 control files remain:" >&2
  find "${sectdd_model_root}" -maxdepth 1 -type f -name '*.aria2' -printf '  %f\n' >&2
  exit 4
fi
"${sectdd_python}" -c '
import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); d=json.load(open(p/"model.safetensors.index.json"))
missing=sorted({x for x in d["weight_map"].values() if not (p/x).is_file()})
assert not missing, missing
' "${sectdd_model_root}"

sectdd_count=0
for sectdd_path in "${sectdd_freeze}" "${sectdd_oracle}"; do
  [[ -e "${sectdd_path}" ]] && sectdd_count=$((sectdd_count + 1))
done
if [[ "${sectdd_count}" -eq 0 ]]; then
  "${sectdd_python}" tools/build_codeguardplus_breadth_wave3_semantic_dispute_v1.py
elif [[ "${sectdd_count}" -ne 2 ]]; then
  echo "Partial semantic-dispute freeze detected." >&2
  exit 2
else
  "${sectdd_python}" tools/build_codeguardplus_breadth_wave3_semantic_dispute_v1.py --verify-only
fi

if [[ ! -f "${sectdd_output}/packet_manifest.json" ]]; then
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_freeze}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" --prepare-only --confirm-machine-review
else
  echo "Resume: blinded CWE-22 dispute packet already prepared."
fi

sectdd_review="${sectdd_output}/reviews/qwen36-35b-a3b/cwe-022__1-py.json"
if [[ ! -f "${sectdd_review}" ]]; then
  sectdd_used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  if [[ -z "${sectdd_used}" || "${sectdd_used}" -gt 2048 ]]; then
    echo "GPU ${sectdd_gpu} is not free: ${sectdd_used:-unknown} MiB" >&2
    exit 3
  fi
  mkdir -p artifacts/logs
  SECTDD_GPUS="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=16384 \
    scripts/serve_qwen36.sh 35b-a3b >"${sectdd_log}" 2>&1 &
  sectdd_pid=$!
  for sectdd_attempt in $(seq 1 240); do
    if ! kill -0 "${sectdd_pid}" 2>/dev/null; then
      tail -n 120 "${sectdd_log}" >&2 || true
      exit 3
    fi
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null \
      | "${sectdd_python}" -c 'import json,sys; print(int("qwen36-35b-a3b" in {x.get("id") for x in json.load(sys.stdin).get("data", [])}))' 2>/dev/null \
      | grep -qx 1; then
      echo "Ready: qwen36-35b-a3b on port ${sectdd_port}"
      break
    fi
    [[ "${sectdd_attempt}" -lt 240 ]] || { tail -n 120 "${sectdd_log}" >&2 || true; exit 3; }
    sleep 5
  done
  "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
    --task-file "${sectdd_freeze}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --oracle-manifest "${sectdd_oracle}" --output "${sectdd_output}" \
    --report-id "${sectdd_report_id}" \
    --reviewer "qwen36-35b-a3b=http://127.0.0.1:${sectdd_port}/v1" \
    --local-thinking disabled --max-workers 1 --max-tokens 8192 \
    --timeout-seconds 600 --confirm-machine-review
else
  echo "Resume: Qwen3.6 CWE-22 dispute review already completed."
fi

"${sectdd_python}" -c '
import json, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
assert d["reviewer"]["model"] == "qwen36-35b-a3b"
print(json.dumps({"task_id":"cwe-022/1-py", "verdict":d["review"]["verdict"], "confidence":d["review"]["confidence"], "summary":d["review"]["summary"]}, ensure_ascii=False, indent=2))
' "${sectdd_review}"
echo "CWE-22 blinded dispute review completed: ${sectdd_review}"
