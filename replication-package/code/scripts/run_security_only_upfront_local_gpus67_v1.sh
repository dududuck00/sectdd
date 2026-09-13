#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

# Create the outer user namespace before either vLLM process starts.  On this
# shared host, creating the first uid map after CUDA/vLLM has spawned its worker
# threads intermittently fails with EPERM.  Bubblewrap still creates a separate
# nested user namespace for every candidate below.
if [[ "${SECTDD_BWRAP_OUTER_USERNS:-0}" != 1 ]]; then
  command -v unshare >/dev/null || {
    echo "unshare is required for the Bubblewrap/vLLM compatibility wrapper." >&2
    exit 2
  }
  exec env SECTDD_BWRAP_OUTER_USERNS=1 \
    unshare --user --map-root-user -- \
    /bin/bash \
    "${sectdd_root}/scripts/run_security_only_upfront_local_gpus67_v1.sh" "$@"
fi

sectdd_gpu_7b="${SECTDD_GPU_7B:-6}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-7}"
sectdd_port_7b="${SECTDD_PORT_7B:-19780}"
sectdd_port_14b="${SECTDD_PORT_14B:-19781}"
sectdd_workers="${SECTDD_MAX_WORKERS:-3}"
sectdd_model_7b="${SECTDD_MODEL_7B:-<MODEL_ROOT>/Qwen/Qwen2.5-Coder-7B-Instruct}"
sectdd_model_14b="${SECTDD_MODEL_14B:-<MODEL_ROOT>/Qwen/Qwen2.5-Coder-14B-Instruct}"
sectdd_log_root="artifacts/security-only-upfront-ablation-v1/driver-logs"
sectdd_pid_7b=""
sectdd_pid_14b=""

sectdd_prepare_third_party_repo() {
  local repo="$1" dirty_without_modes
  [[ -d "${repo}/.git" ]] || {
    echo "Missing third-party Git repository: ${repo}" >&2
    exit 2
  }
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

sectdd_cleanup() {
  for pid in "${sectdd_pid_7b}" "${sectdd_pid_14b}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${sectdd_pid_7b}" "${sectdd_pid_14b}"; do
    [[ -z "${pid}" ]] || wait "${pid}" 2>/dev/null || true
  done
}
trap sectdd_cleanup EXIT INT TERM

sectdd_progress() {
  local model="$1" benchmark merged shards count total=0
  for benchmark in sallm codeguardplus; do
    merged="artifacts/security-only-upfront-ablation-v1/${benchmark}/${model}/trajectories"
    shards="artifacts/security-only-upfront-ablation-v1/${benchmark}/${model}-shards/shards"
    if [[ -d "${merged}" ]]; then
      count="$(find "${merged}" -type f -path '*/B7/*/seed_*/trajectory.json' | wc -l)"
    elif [[ -d "${shards}" ]]; then
      count="$(find "${shards}" -type f -path '*/trajectories/B7/*/seed_*/trajectory.json' | wc -l)"
    else
      count=0
    fi
    total=$((total + count))
  done
  echo "${total}"
}

[[ "${sectdd_gpu_7b}" != "${sectdd_gpu_14b}" ]] || {
  echo "7B and 14B must use different GPUs." >&2
  exit 2
}
for path in "${sectdd_model_7b}" "${sectdd_model_14b}"; do
  for file in config.json tokenizer_config.json model.safetensors.index.json; do
    [[ -f "${path}/${file}" ]] || { echo "Incomplete checkpoint: ${path}/${file}" >&2; exit 2; }
  done
done
sectdd_prepare_third_party_repo third_party/SALLM
sectdd_prepare_third_party_repo third_party/CodeGuardPlus
.venv/bin/python tools/build_security_only_upfront_ablation_v1.py
if [[ "${SECTDD_PREFLIGHT_ONLY:-0}" == 1 ]]; then
  echo "Preflight OK: checkpoint identities, relocated configs, ports, and GPU assignments are valid."
  echo "Planned assignments: 7B=GPU ${sectdd_gpu_7b}/port ${sectdd_port_7b}; 14B=GPU ${sectdd_gpu_14b}/port ${sectdd_port_14b}."
  exit 0
fi
for gpu in "${sectdd_gpu_7b}" "${sectdd_gpu_14b}"; do
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${gpu}" | awk 'NF {print int($1); exit}')"
  [[ -n "${used}" && "${used}" -le "${SECTDD_MAX_USED_MIB:-2048}" ]] || {
    echo "GPU ${gpu} is not sufficiently free: ${used:-unknown} MiB." >&2
    exit 3
  }
done
mkdir -p "${sectdd_log_root}"

echo "Starting B7 security-only upfront addendum:"
echo "  7B  -> GPU ${sectdd_gpu_7b}, port ${sectdd_port_7b}, ${sectdd_model_7b}"
echo "  14B -> GPU ${sectdd_gpu_14b}, port ${sectdd_port_14b}, ${sectdd_model_14b}"

SECTDD_GPU="${sectdd_gpu_7b}" \
SECTDD_PORT="${sectdd_port_7b}" \
SECTDD_MAX_WORKERS="${sectdd_workers}" \
SECTDD_MODEL_7B="${sectdd_model_7b}" \
  bash scripts/run_security_only_upfront_ablation_v1.sh both qwen25-coder-7b \
  >"${sectdd_log_root}/qwen25-coder-7b.log" 2>&1 &
sectdd_pid_7b=$!

SECTDD_GPU="${sectdd_gpu_14b}" \
SECTDD_PORT="${sectdd_port_14b}" \
SECTDD_MAX_WORKERS="${sectdd_workers}" \
SECTDD_MODEL_14B="${sectdd_model_14b}" \
  bash scripts/run_security_only_upfront_ablation_v1.sh both qwen25-coder-14b \
  >"${sectdd_log_root}/qwen25-coder-14b.log" 2>&1 &
sectdd_pid_14b=$!

while kill -0 "${sectdd_pid_7b}" 2>/dev/null || kill -0 "${sectdd_pid_14b}" 2>/dev/null; do
  count_7b="$(sectdd_progress qwen25-coder-7b)"
  count_14b="$(sectdd_progress qwen25-coder-14b)"
  echo "B7 progress: 7B ${count_7b}/60; 14B ${count_14b}/60"
  sleep 15
done

set +e
wait "${sectdd_pid_7b}"; status_7b=$?
wait "${sectdd_pid_14b}"; status_14b=$?
set -e
sectdd_pid_7b=""
sectdd_pid_14b=""
if [[ "${status_7b}" -ne 0 || "${status_14b}" -ne 0 ]]; then
  echo "A local model run failed (7B=${status_7b}, 14B=${status_14b})." >&2
  echo "7B log: ${sectdd_log_root}/qwen25-coder-7b.log" >&2
  echo "14B log: ${sectdd_log_root}/qwen25-coder-14b.log" >&2
  tail -n 80 "${sectdd_log_root}/qwen25-coder-7b.log" >&2 || true
  tail -n 80 "${sectdd_log_root}/qwen25-coder-14b.log" >&2 || true
  exit 3
fi

bash scripts/run_security_only_upfront_ablation_v1.sh status
echo "GPU-dependent addendum completed for the available 7B and 14B checkpoints (120/120 trajectories)."
echo "Qwen3.6-27B and DeepSeek are separate resumable stages; use their dedicated one-click scripts."
