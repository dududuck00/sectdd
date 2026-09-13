#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

for sectdd_input in \
  benchmarks/manifests/paper-evidence-v3-results-freeze.json \
  benchmarks/manifests/paper-expansion-full-v1-results-freeze.json \
  artifacts/reports/unified-paper-evidence-v3.json \
  artifacts/reports/paper-expansion-full-v1.json; do
  [[ -f "${sectdd_input}" ]] || {
    echo "Missing frozen input: ${sectdd_input}" >&2
    exit 2
  }
done

.venv/bin/python tools/analyze_paper_evidence_v4.py

echo "Combined evidence report: artifacts/reports/unified-paper-evidence-v4.json"
echo "Readable summary: docs/unified-paper-evidence-v4.md"
echo "Results freeze: benchmarks/manifests/paper-evidence-v4-results-freeze.json"
