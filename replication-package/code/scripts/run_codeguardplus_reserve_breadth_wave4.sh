#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_pairs="benchmarks/manifests/codeguardplus-reserve-breadth-wave4-pairs.json"
sectdd_lock="configs/experiments/codeguardplus_reserve_breadth_wave4.lock.json"
sectdd_out="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4"
sectdd_generation="${sectdd_out}/generation/deepseek-v4-flash"
sectdd_qualification="${sectdd_out}/qualification"
sectdd_oracle="oracles/codeguardplus_reserve_breadth_wave4"
sectdd_visible="configs/oracles/codeguardplus_reserve_breadth_wave4_visible.json"
sectdd_hidden="configs/oracles/codeguardplus_reserve_breadth_wave4_hidden.json"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave4-freeze.json"
sectdd_report="docs/codeguardplus-reserve-breadth-wave4.md"

count=0; for p in "${sectdd_pairs}" "${sectdd_lock}"; do [[ -e "${p}" ]] && count=$((count+1)); done
if [[ "${count}" -eq 0 ]]; then "${sectdd_python}" tools/build_codeguardplus_reserve_breadth_wave4.py; elif [[ "${count}" -ne 2 ]]; then echo "Partial wave4 selection freeze detected." >&2; exit 2; else echo "Resume: wave4 selection inputs already exist."; fi
"${sectdd_python}" tools/build_codeguardplus_reserve_breadth_wave4.py --verify-only

ready=false
if [[ -f "${sectdd_generation}/summary.json" ]] && "${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if d.get("complete") and d.get("success_count")==12 and d.get("failed_count")==0 else 1)' "${sectdd_generation}/summary.json"; then ready=true; fi
if [[ "${ready}" == false ]]; then
  if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    if [[ ! -t 0 ]]; then echo "DEEPSEEK_API_KEY is required." >&2; exit 2; fi
    read -r -s -p "DeepSeek API key: " DEEPSEEK_API_KEY; echo; export DEEPSEEK_API_KEY
  fi
  resume=(); [[ -f "${sectdd_generation}/run_manifest.json" ]] && resume=(--resume)
  "${sectdd_python}" tools/generate_codeguardplus_partitioned_oracles.py \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --pairs "${sectdd_pairs}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --attempts 3 --temperature 0.35 --top-p 0.95 --max-tokens 12288 \
    --thinking enabled --reasoning-effort high --num-workers 2 \
    --timeout-seconds 600 --max-retries 4 --confirm-paid-api \
    --output "${sectdd_generation}" "${resume[@]}"
else
  echo "Resume: all 12 DeepSeek oracle candidates already generated."
fi
"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(d,indent=2)); raise SystemExit(0 if d.get("complete") and d.get("success_count")==12 and d.get("failed_count")==0 else 3)' "${sectdd_generation}/summary.json"

count=0; for p in "${sectdd_qualification}/summary.json" "${sectdd_oracle}/manifest.json" "${sectdd_visible}" "${sectdd_hidden}" "${sectdd_freeze}" "${sectdd_report}"; do [[ -e "${p}" ]] && count=$((count+1)); done
if [[ "${count}" -eq 0 ]]; then
  "${sectdd_python}" tools/qualify_codeguardplus_partitioned_oracles.py \
    --generation-run "${sectdd_generation}" --pairs "${sectdd_pairs}" \
    --output "${sectdd_qualification}" --oracle-root "${sectdd_oracle}" \
    --visible-projection "${sectdd_visible}" --hidden-projection "${sectdd_hidden}" \
    --freeze "${sectdd_freeze}" --report "${sectdd_report}" \
    --oracle-set-id codeguardplus-reserve-breadth-wave4 \
    --freeze-id codeguardplus-reserve-breadth-wave4 --repeats 3 --num-workers 4
elif [[ "${count}" -ne 6 ]]; then
  echo "Partial wave4 qualification detected; refusing to overwrite evidence." >&2; exit 2
else
  echo "Resume: wave4 qualification already complete."
fi
"${sectdd_python}" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])),indent=2))' "${sectdd_qualification}/summary.json"
echo "CodeGuard+ reserve breadth wave4 completed: ${sectdd_freeze}"
