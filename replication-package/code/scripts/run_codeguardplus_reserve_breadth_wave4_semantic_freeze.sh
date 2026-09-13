#!/usr/bin/env bash
set -euo pipefail
sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
summary="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave4/semantic-machine-v1/summary.json"
freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave4-semantic-machine-v1-freeze.json"
if [[ ! -e "${summary}" && ! -e "${freeze}" ]]; then "${sectdd_python}" tools/freeze_codeguardplus_breadth_wave4_semantic_machine_v1.py; elif [[ -f "${summary}" && -f "${freeze}" ]]; then echo "Resume: wave4 semantic freeze complete."; else echo "Partial wave4 semantic freeze detected." >&2; exit 2; fi
"${sectdd_python}" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["complete"] and d["replay_observation_count"]==24; print(json.dumps(d,indent=2,sort_keys=True))' "${summary}"
echo "Wave4 machine-semantic freeze completed: ${freeze}"
