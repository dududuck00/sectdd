#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_gpu_7b="${SECTDD_GPU_7B:-5}"
sectdd_gpu_14b="${SECTDD_GPU_14B:-6}"
sectdd_max_used_mib="${SECTDD_MAX_USED_MIB:-2048}"
sectdd_poll_seconds="${SECTDD_POLL_SECONDS:-30}"

while true; do
  sectdd_used_7b="$(
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits \
      -i "${sectdd_gpu_7b}" | awk 'NF {print int($1); exit}'
  )"
  sectdd_used_14b="$(
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits \
      -i "${sectdd_gpu_14b}" | awk 'NF {print int($1); exit}'
  )"
  sectdd_now="$(date --iso-8601=seconds)"
  echo "${sectdd_now} waiting: GPU${sectdd_gpu_7b}=${sectdd_used_7b}MiB GPU${sectdd_gpu_14b}=${sectdd_used_14b}MiB"
  if [[ "${sectdd_used_7b}" -le "${sectdd_max_used_mib}" \
    && "${sectdd_used_14b}" -le "${sectdd_max_used_mib}" ]]; then
    echo "Required GPUs are free; starting frozen SALLM external main."
    exec bash scripts/run_sallm_main_local.sh
  fi
  sleep "${sectdd_poll_seconds}"
done
