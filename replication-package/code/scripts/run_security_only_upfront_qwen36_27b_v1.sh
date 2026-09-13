#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"
sectdd_action="${1:-run}"
sectdd_gpu="${SECTDD_GPU:-6}"
sectdd_port="${SECTDD_PORT:-19782}"
sectdd_workers="${SECTDD_MAX_WORKERS:-3}"
sectdd_model="${SECTDD_MODEL_27B:-<MODEL_ROOT>/Qwen/Qwen3.6-27B}"

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
}

sectdd_preflight() {
  sectdd_prepare_third_party_repo third_party/SALLM
  sectdd_prepare_third_party_repo third_party/CodeGuardPlus
  .venv/bin/python tools/build_security_only_upfront_ablation_v1.py
  SECTDD_GPU="${sectdd_gpu}" SECTDD_MODEL_27B="${sectdd_model}" \
    bash scripts/run_security_only_upfront_ablation_v1.sh preflight qwen36-27b
}

case "${sectdd_action}" in
  status)
    bash scripts/run_security_only_upfront_ablation_v1.sh status
    ;;
  preflight)
    sectdd_preflight
    ;;
  run)
    if [[ "${SECTDD_BWRAP_OUTER_USERNS:-0}" != 1 ]]; then
      command -v unshare >/dev/null || { echo "unshare is required for sandbox execution." >&2; exit 2; }
      exec env SECTDD_BWRAP_OUTER_USERNS=1 \
        unshare --user --map-root-user -- \
        /bin/bash "${sectdd_root}/scripts/run_security_only_upfront_qwen36_27b_v1.sh" run
    fi
    sectdd_preflight
    echo "Starting Qwen3.6-27B B7 on physical GPU ${sectdd_gpu}, port ${sectdd_port}."
    SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" \
    SECTDD_MAX_WORKERS="${sectdd_workers}" SECTDD_MODEL_27B="${sectdd_model}" \
      bash scripts/run_security_only_upfront_ablation_v1.sh both qwen36-27b
    bash scripts/run_security_only_upfront_ablation_v1.sh status
    echo "Qwen3.6-27B B7 supplement completed (60/60 trajectories)."
    ;;
  *)
    echo "Usage: $0 {run|preflight|status}" >&2
    exit 2
    ;;
esac
