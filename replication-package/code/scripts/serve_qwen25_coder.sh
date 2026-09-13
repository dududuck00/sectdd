#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sectdd_size="${1:-7b}"
sectdd_gpu="${SECTDD_GPU:-4}"
sectdd_port="${SECTDD_PORT:-18080}"
sectdd_max_model_len="${SECTDD_MAX_MODEL_LEN:-8192}"
sectdd_vllm="<MODEL_ROOT>/anonymous-user/conda/envs/text2test/bin/vllm"

case "${sectdd_gpu}" in
  1|2|3|4|5|6) ;;
  *)
    echo "SECTDD_GPU must be one of the user-authorized GPUs: 1, 2, 3, 4, 5, or 6." >&2
    exit 2
    ;;
esac

sectdd_gpu_uuid="$(
  nvidia-smi \
    --query-gpu=uuid \
    --format=csv,noheader,nounits \
    -i "${sectdd_gpu}" \
  | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}'
)"
if [[ ! "${sectdd_gpu_uuid}" =~ ^GPU- ]]; then
  echo "Could not resolve nvidia-smi GPU index ${sectdd_gpu} to a GPU UUID." >&2
  exit 2
fi

case "${sectdd_size,,}" in
  7b)
    sectdd_model="<MODEL_ROOT>/Qwen2.5-Coder-7B-Instruct"
    sectdd_name="qwen25-coder-7b"
    sectdd_memory="0.82"
    ;;
  14b)
    sectdd_model="<MODEL_ROOT>/Qwen2.5-Coder-14B-Instruct"
    sectdd_name="qwen25-coder-14b"
    sectdd_memory="0.88"
    ;;
  qwen3-32b|32b)
    sectdd_model="<MODEL_ROOT>/models/Qwen3-32B"
    sectdd_name="qwen3-32b"
    sectdd_memory="0.94"
    ;;
  deepseek-llama-8b|ds-llama-8b)
    sectdd_model="<MODEL_ROOT>/deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
    sectdd_name="deepseek-r1-distill-llama-8b"
    sectdd_memory="0.82"
    ;;
  llama31-8b|llama-8b)
    sectdd_model="<MODEL_ROOT>/models/meta-llama/Llama-3.1-8B-Instruct"
    sectdd_name="llama31-8b-instruct"
    sectdd_memory="0.82"
    ;;
  *)
    echo "Usage: $0 {7b|14b|qwen3-32b|deepseek-llama-8b|llama31-8b}" >&2
    exit 2
    ;;
esac

test -x "${sectdd_vllm}"
test -f "${sectdd_model}/config.json"

echo "Serving ${sectdd_name} from ${sectdd_model} on physical GPU ${sectdd_gpu} (${sectdd_gpu_uuid})"
echo "OpenAI-compatible endpoint: http://127.0.0.1:${sectdd_port}/v1"

cd "${sectdd_root}"
exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="${sectdd_gpu}" \
  VLLM_WORKER_MULTIPROC_METHOD=spawn \
  "${sectdd_vllm}" serve "${sectdd_model}" \
  --served-model-name "${sectdd_name}" \
  --host 127.0.0.1 \
  --port "${sectdd_port}" \
  --dtype bfloat16 \
  --max-model-len "${sectdd_max_model_len}" \
  --gpu-memory-utilization "${sectdd_memory}" \
  --generation-config vllm \
  --enable-prefix-caching
