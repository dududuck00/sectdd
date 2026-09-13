#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_pairs="benchmarks/manifests/codeguardplus-reserve-breadth-wave3-pairs.json"
sectdd_lock="configs/experiments/codeguardplus_reserve_breadth_wave3.lock.json"
sectdd_root_out="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3"
sectdd_generation="${sectdd_root_out}/generation/deepseek-v4-flash"
sectdd_qualification="${sectdd_root_out}/qualification"
sectdd_oracle_root="oracles/codeguardplus_reserve_breadth_wave3"
sectdd_visible="configs/oracles/codeguardplus_reserve_breadth_wave3_visible.json"
sectdd_hidden="configs/oracles/codeguardplus_reserve_breadth_wave3_hidden.json"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave3-freeze.json"
sectdd_report="docs/codeguardplus-reserve-breadth-wave3.md"

sectdd_build_count=0
for sectdd_path in "${sectdd_pairs}" "${sectdd_lock}"; do
  [[ -e "${sectdd_path}" ]] && sectdd_build_count=$((sectdd_build_count + 1))
done
if [[ "${sectdd_build_count}" -eq 0 ]]; then
  "${sectdd_python}" tools/build_codeguardplus_reserve_breadth_wave3.py
elif [[ "${sectdd_build_count}" -ne 2 ]]; then
  echo "Partial breadth-wave3 selection freeze detected; refusing to mix inputs." >&2
  exit 2
else
  echo "Resume: breadth-wave3 selection inputs already exist."
fi
"${sectdd_python}" tools/build_codeguardplus_reserve_breadth_wave3.py --verify-only

sectdd_generation_ready=false
if [[ -f "${sectdd_generation}/summary.json" ]]; then
  if "${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if d.get("complete") and d.get("success_count")==15 and d.get("failed_count")==0 else 1)' "${sectdd_generation}/summary.json"; then
    sectdd_generation_ready=true
  fi
fi

if [[ "${sectdd_generation_ready}" == false ]]; then
  if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    if [[ ! -t 0 ]]; then
      echo "DEEPSEEK_API_KEY is required for a non-interactive run." >&2
      exit 2
    fi
    read -r -s -p "DeepSeek API key: " DEEPSEEK_API_KEY
    echo
    export DEEPSEEK_API_KEY
  fi
  sectdd_resume=()
  [[ -f "${sectdd_generation}/run_manifest.json" ]] && sectdd_resume=(--resume)
  "${sectdd_python}" tools/generate_codeguardplus_partitioned_oracles.py \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --pairs "${sectdd_pairs}" --benchmark benchmarks/manifests/codeguardplus-v1.json \
    --attempts 3 --temperature 0.35 --top-p 0.95 --max-tokens 12288 \
    --thinking enabled --reasoning-effort high --num-workers 2 \
    --timeout-seconds 600 --max-retries 4 --confirm-paid-api \
    --output "${sectdd_generation}" "${sectdd_resume[@]}"
else
  echo "Resume: all 15 DeepSeek oracle candidates already generated."
fi

"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(d,indent=2)); raise SystemExit(0 if d.get("complete") and d.get("success_count")==15 and d.get("failed_count")==0 else 3)' "${sectdd_generation}/summary.json"

sectdd_qualification_count=0
for sectdd_path in "${sectdd_qualification}/summary.json" "${sectdd_oracle_root}/manifest.json" "${sectdd_visible}" "${sectdd_hidden}" "${sectdd_freeze}" "${sectdd_report}"; do
  [[ -e "${sectdd_path}" ]] && sectdd_qualification_count=$((sectdd_qualification_count + 1))
done
if [[ "${sectdd_qualification_count}" -eq 0 ]]; then
  "${sectdd_python}" tools/qualify_codeguardplus_partitioned_oracles.py \
    --generation-run "${sectdd_generation}" --pairs "${sectdd_pairs}" \
    --output "${sectdd_qualification}" --oracle-root "${sectdd_oracle_root}" \
    --visible-projection "${sectdd_visible}" --hidden-projection "${sectdd_hidden}" \
    --freeze "${sectdd_freeze}" --report "${sectdd_report}" \
    --oracle-set-id codeguardplus-reserve-breadth-wave3 \
    --freeze-id codeguardplus-reserve-breadth-wave3 \
    --repeats 3 --num-workers 4
elif [[ "${sectdd_qualification_count}" -ne 6 ]]; then
  echo "Partial breadth-wave3 qualification detected; refusing to overwrite evidence." >&2
  exit 2
else
  echo "Resume: breadth-wave3 qualification already complete."
fi

"${sectdd_python}" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])),indent=2))' "${sectdd_qualification}/summary.json"
echo "CodeGuard+ reserve breadth wave3 completed: ${sectdd_freeze}"
