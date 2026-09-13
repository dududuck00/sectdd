#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_python="${SECTDD_PYTHON:-.venv/bin/python}"
sectdd_action="${1:-prepare}"
sectdd_submission="${SECTDD_G7_SUBMISSION:-artifacts/codeguardplus-final-g7-v1/reviewer_bundle/review_submission.json}"

case "${sectdd_action}" in
  prepare)
    "${sectdd_python}" tools/prepare_codeguardplus_final_g7_v1.py
    ;;
  validate)
    "${sectdd_python}" tools/freeze_codeguardplus_final_g7_v1.py \
      --review-submission "${sectdd_submission}" \
      --confirm-independent-human-review
    ;;
  status)
    "${sectdd_python}" - <<'PY'
import json
from pathlib import Path

packet = Path("benchmarks/manifests/codeguardplus-final-g7-packet-v1-freeze.json")
final = Path("benchmarks/manifests/codeguardplus-final-g7-v1-freeze.json")
if final.is_file():
    data = json.loads(final.read_text())
elif packet.is_file():
    data = json.loads(packet.read_text())
else:
    data = {"status": "not_prepared", "formal_experiment_ready": False}
print(json.dumps(data, indent=2, sort_keys=True))
PY
    ;;
  *)
    echo "Usage: $0 {prepare|validate|status}" >&2
    exit 2
    ;;
esac
