#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sectdd_variant="${1:-27b}"
sectdd_gpus="${SECTDD_GPUS:-4}"
sectdd_port="${SECTDD_PORT:-18083}"
sectdd_vllm="${SECTDD_VLLM:-<MODEL_ROOT>/anonymous-user/conda/envs/text2test/bin/vllm}"

IFS=',' read -r -a sectdd_gpu_array <<< "${sectdd_gpus}"
for sectdd_gpu in "${sectdd_gpu_array[@]}"; do
  case "${sectdd_gpu}" in
    1|2|3|4|5|6) ;;
    *)
      echo "SECTDD_GPUS may contain only the user-authorized GPUs 1, 2, 3, 4, 5, 6." >&2
      exit 2
      ;;
  esac
done

case "${sectdd_variant,,}" in
  27b|qwen36-27b)
    sectdd_model="<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B"
    sectdd_name="qwen36-27b"
    sectdd_memory="${SECTDD_GPU_MEMORY:-0.92}"
    sectdd_default_tp=1
    ;;
  35b-a3b|qwen36-35b-a3b)
    sectdd_model="<MODEL_ROOT>/Qwen3.6/Qwen3.6-35B-A3B"
    sectdd_name="qwen36-35b-a3b"
    sectdd_memory="${SECTDD_GPU_MEMORY:-0.92}"
    sectdd_default_tp=1
    ;;
  *)
    echo "Usage: $0 {27b|35b-a3b}" >&2
    exit 2
    ;;
esac

sectdd_tp="${SECTDD_TP:-${sectdd_default_tp}}"
if [[ "${#sectdd_gpu_array[@]}" -ne "${sectdd_tp}" ]]; then
  echo "SECTDD_TP=${sectdd_tp} but SECTDD_GPUS names ${#sectdd_gpu_array[@]} GPU(s)." >&2
  exit 2
fi
if [[ ! -x "${sectdd_vllm}" ]]; then
  echo "vLLM executable is missing: ${sectdd_vllm}" >&2
  exit 2
fi
if [[ ! -f "${sectdd_model}/config.json" ]]; then
  echo "Model checkpoint is incomplete: ${sectdd_model}/config.json is absent." >&2
  exit 2
fi

echo "Serving ${sectdd_name} from ${sectdd_model}"
echo "Physical GPU(s): ${sectdd_gpus}; tensor parallel size: ${sectdd_tp}"
echo "OpenAI-compatible endpoint: http://127.0.0.1:${sectdd_port}/v1"

cd "${sectdd_root}"
exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="${sectdd_gpus}" \
  VLLM_WORKER_MULTIPROC_METHOD=spawn \
  "${sectdd_vllm}" serve "${sectdd_model}" \
  --served-model-name "${sectdd_name}" \
  --host 127.0.0.1 \
  --port "${sectdd_port}" \
  --dtype bfloat16 \
  --max-model-len "${SECTDD_MAX_MODEL_LEN:-16384}" \
  --max-num-seqs "${SECTDD_MAX_NUM_SEQS:-64}" \
  --gpu-memory-utilization "${sectdd_memory}" \
  --tensor-parallel-size "${sectdd_tp}" \
  --generation-config vllm \
  --reasoning-parser qwen3 \
  --language-model-only \
  --enable-prefix-caching
