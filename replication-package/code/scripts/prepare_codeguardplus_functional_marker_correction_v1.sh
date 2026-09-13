#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

.venv/bin/python tools/prepare_codeguardplus_functional_marker_correction_v1.py

echo "Correction prepared. Rerun CodeGuard+ for all four models with the commands provided in the experiment protocol."
