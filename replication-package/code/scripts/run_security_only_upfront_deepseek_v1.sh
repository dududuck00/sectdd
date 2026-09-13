#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_action="${1:-run}"
sectdd_workers="${SECTDD_MAX_WORKERS:-2}"

sectdd_prepare_third_party_repo() {
  local repo="$1" dirty_without_modes
  [[ -d "${repo}/.git" ]] || { echo "Missing third-party Git repository: ${repo}" >&2; exit 2; }
  if [[ -z "$(git -C "${repo}" status --porcelain)" ]]; then
    return
  fi
  dirty_without_modes="$(git -C "${repo}" -c core.filemode=false status --porcelain)"
  if [[ -n "${dirty_without_modes}" ]]; then
    echo "Third-party repository has content or untracked changes: ${repo}" >&2
    printf '%s\n' "${dirty_without_modes}" | sed -n '1,40p' >&2
    exit 2
  fi
  git -C "${repo}" config core.filemode false
  echo "Normalized permission-only Git changes: ${repo}"
}

sectdd_preflight() {
  sectdd_prepare_third_party_repo third_party/SALLM
  sectdd_prepare_third_party_repo third_party/CodeGuardPlus
  .venv/bin/python tools/build_security_only_upfront_ablation_v1.py
  .venv/bin/python - <<'PY'
import json
from pathlib import Path

expected = {"sallm": 40, "codeguardplus": 20}
for benchmark, count in expected.items():
    path = Path(f"configs/experiments/{benchmark}_security_only_upfront_ablation_v1.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    override = config["generation"]["model_overrides"]["deepseek-v4-flash"]
    if override.get("extra_body", {}).get("thinking") != {"type": "disabled"}:
        raise SystemExit(f"{path}: DeepSeek thinking must remain disabled")
    actual = len(config["tasks"]) * len(config["generation_seeds"])
    if actual != count:
        raise SystemExit(f"{path}: expected {count} requests, found {actual}")
print("DeepSeek preflight OK: thinking=disabled; 40 SALLM + 20 CodeGuard+ requests.")
PY
  SECTDD_MAX_WORKERS="${sectdd_workers}" \
    bash scripts/run_security_only_upfront_ablation_v1.sh preflight deepseek-v4-flash
}

case "${sectdd_action}" in
  preflight)
    sectdd_preflight
    ;;
  status)
    bash scripts/run_security_only_upfront_ablation_v1.sh status
    ;;
  run)
    # Enter the user namespace before the concurrent runner creates threads;
    # every candidate still receives its own nested Bubblewrap sandbox.
    if [[ "${SECTDD_BWRAP_OUTER_USERNS:-0}" != 1 ]]; then
      command -v unshare >/dev/null || { echo "unshare is required for sandbox execution." >&2; exit 2; }
      exec env SECTDD_BWRAP_OUTER_USERNS=1 \
        unshare --user --map-root-user -- \
        /bin/bash "${sectdd_root}/scripts/run_security_only_upfront_deepseek_v1.sh" run
    fi
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || {
      echo "DEEPSEEK_API_KEY is not set. Export it in this shell; the script never writes it to disk." >&2
      exit 2
    }
    sectdd_preflight
    echo "Starting 60 paid DeepSeek B7 requests (thinking disabled; resumable)."
    SECTDD_CONFIRM_PAID_API=1 SECTDD_MAX_WORKERS="${sectdd_workers}" \
      bash scripts/run_security_only_upfront_ablation_v1.sh all-deepseek
    bash scripts/run_security_only_upfront_ablation_v1.sh status
    echo "DeepSeek B7 supplement completed (60/60 trajectories)."
    ;;
  *)
    echo "Usage: $0 {run|preflight|status}" >&2
    exit 2
    ;;
esac
