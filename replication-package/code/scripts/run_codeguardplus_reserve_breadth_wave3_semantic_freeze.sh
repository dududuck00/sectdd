#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_summary="artifacts/codeguardplus-reserve-expansion-v1/breadth-wave3/semantic-machine-v1/summary.json"
sectdd_freeze="benchmarks/manifests/codeguardplus-reserve-breadth-wave3-semantic-machine-v1-freeze.json"

if [[ ! -e "${sectdd_summary}" && ! -e "${sectdd_freeze}" ]]; then
  "${sectdd_python}" tools/freeze_codeguardplus_breadth_wave3_semantic_machine_v1.py
elif [[ -f "${sectdd_summary}" && -f "${sectdd_freeze}" ]]; then
  echo "Resume: breadth-wave3 machine-semantic freeze already completed."
else
  echo "Partial machine-semantic freeze detected; inspect before retrying." >&2
  exit 2
fi
"${sectdd_python}" -c '
import json, sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
assert d["complete"] and d["replay_observation_count"] == 36
print(json.dumps(d, indent=2, sort_keys=True))
' "${sectdd_summary}"
echo "Breadth-wave3 machine-semantic freeze completed: ${sectdd_freeze}"
