#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

.venv/bin/python tools/finalize_codeguardplus_functional_marker_correction_v1.py
bash scripts/run_paper_expansion_full_v1.sh analyze
bash scripts/run_paper_evidence_v4.sh

echo "CodeGuard+ marker correction, balanced analysis, and 51-task synthesis completed."
