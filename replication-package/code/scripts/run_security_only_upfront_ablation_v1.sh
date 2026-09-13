#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-status}"
sectdd_model="${2:-}"
sectdd_gpu="${SECTDD_GPU:-2}"
sectdd_port="${SECTDD_PORT:-19780}"
sectdd_workers="${SECTDD_MAX_WORKERS:-3}"
sectdd_root_out="artifacts/security-only-upfront-ablation-v1"
sectdd_server_pid=""
sectdd_keep_server=0

sectdd_cleanup() {
  if [[ -n "${sectdd_server_pid}" ]] && kill -0 "${sectdd_server_pid}" 2>/dev/null; then
    kill "${sectdd_server_pid}" 2>/dev/null || true
    wait "${sectdd_server_pid}" 2>/dev/null || true
  fi
}
trap sectdd_cleanup EXIT INT TERM

sectdd_inputs() {
  local benchmark="$1"
  sectdd_config="configs/experiments/${benchmark}_security_only_upfront_ablation_v1.json"
  case "${benchmark}" in
    sallm)
      sectdd_visible="configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json"
      sectdd_hidden="configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json"
      ;;
    codeguardplus)
      sectdd_visible="configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json"
      sectdd_hidden="configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json"
      ;;
    *) echo "Benchmark must be sallm or codeguardplus." >&2; exit 2 ;;
  esac
  for path in "${sectdd_config}" "${sectdd_visible}" "${sectdd_hidden}"; do
    [[ -f "${path}" ]] || { echo "Missing frozen input: ${path}; run '$0 build'." >&2; exit 2; }
  done
}

sectdd_model_inputs() {
  case "${sectdd_model}" in
    qwen25-coder-7b)
      sectdd_provider=local
      sectdd_tokenizer="${SECTDD_MODEL_7B:-<MODEL_ROOT>/Qwen/Qwen2.5-Coder-7B-Instruct}"
      sectdd_server_script=scripts/serve_qwen25_coder.sh
      sectdd_server_variant=7b
      ;;
    qwen25-coder-14b)
      sectdd_provider=local
      sectdd_tokenizer="${SECTDD_MODEL_14B:-<MODEL_ROOT>/Qwen/Qwen2.5-Coder-14B-Instruct}"
      sectdd_server_script=scripts/serve_qwen25_coder.sh
      sectdd_server_variant=14b
      ;;
    qwen36-27b)
      sectdd_provider=local
      sectdd_tokenizer="${SECTDD_MODEL_27B:-<MODEL_ROOT>/Qwen/Qwen3.6-27B}"
      sectdd_server_script=scripts/serve_qwen36.sh
      sectdd_server_variant=27b
      ;;
    deepseek-v4-flash)
      sectdd_provider=deepseek
      sectdd_tokenizer="${SECTDD_MODEL_14B:-<MODEL_ROOT>/Qwen/Qwen2.5-Coder-14B-Instruct}"
      sectdd_server_script=""
      sectdd_server_variant=""
      ;;
    *)
      echo "Model must be qwen25-coder-7b, qwen25-coder-14b, qwen36-27b, or deepseek-v4-flash." >&2
      exit 2
      ;;
  esac
  if [[ "${sectdd_provider}" == local ]]; then
    .venv/bin/python - "${sectdd_tokenizer}" "${sectdd_model}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

checkpoint = Path(sys.argv[1]).resolve()
model = sys.argv[2]
required = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json")
missing = [name for name in required if not (checkpoint / name).is_file()]
if missing:
    raise SystemExit(f"Incomplete checkpoint {checkpoint}: missing {', '.join(missing)}")

index = json.loads((checkpoint / "model.safetensors.index.json").read_text(encoding="utf-8"))
shards = sorted(set(index.get("weight_map", {}).values()))
missing_shards = [name for name in shards if not (checkpoint / name).is_file()]
partial_shards = [name for name in shards if (checkpoint / f"{name}.aria2").exists()]
if not shards or missing_shards or partial_shards:
    details = []
    if not shards:
        details.append("the weight index contains no shards")
    if missing_shards:
        details.append("missing shards: " + ", ".join(missing_shards))
    if partial_shards:
        details.append("downloads still active: " + ", ".join(partial_shards))
    raise SystemExit(f"Incomplete checkpoint {checkpoint}: {'; '.join(details)}")

if model == "qwen36-27b":
    relocation_path = Path("benchmarks/manifests/security-only-upfront-ablation-v1-qwen36-checkpoint-relocation.json")
    relocation = json.loads(relocation_path.read_text(encoding="utf-8"))
    for name, expected in relocation["checkpoint_identity_sha256"][model].items():
        path = checkpoint / name
        if not path.is_file():
            raise SystemExit(f"Checkpoint identity file is absent: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"Checkpoint identity mismatch for {path}: expected {expected}, got {actual}"
            )
PY
  else
    for name in config.json tokenizer.json tokenizer_config.json; do
      [[ -f "${sectdd_tokenizer}/${name}" ]] || {
        echo "Incomplete tokenizer proxy: ${sectdd_tokenizer}/${name}" >&2
        exit 2
      }
    done
  fi
}

sectdd_assert_gpu() {
  local count used
  count="$(nvidia-smi -L | wc -l)"
  [[ "${sectdd_gpu}" =~ ^[0-9]+$ && "${sectdd_gpu}" -lt "${count}" ]] || { echo "Invalid GPU ${sectdd_gpu}; server exposes ${count}." >&2; exit 2; }
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i "${sectdd_gpu}" | awk 'NF {print int($1); exit}')"
  [[ -n "${used}" && "${used}" -le "${SECTDD_MAX_USED_MIB:-2048}" ]] || { echo "GPU ${sectdd_gpu} is not sufficiently free: ${used:-unknown} MiB." >&2; exit 3; }
}

sectdd_wait_model() {
  local attempt
  for attempt in $(seq 1 240); do
    kill -0 "${sectdd_server_pid}" 2>/dev/null || { tail -n 120 "${sectdd_server_log}" >&2 || true; exit 3; }
    if curl -fsS "http://127.0.0.1:${sectdd_port}/v1/models" 2>/dev/null | .venv/bin/python -c 'import json,sys; wanted=sys.argv[1]; raise SystemExit(0 if wanted in {x.get("id") for x in json.load(sys.stdin).get("data",[])} else 1)' "${sectdd_model}" 2>/dev/null; then
      echo "Ready: ${sectdd_model} on port ${sectdd_port}"
      return
    fi
    (( attempt % 12 != 0 )) || echo "Still waiting for ${sectdd_model}..."
    sleep 5
  done
  tail -n 120 "${sectdd_server_log}" >&2 || true
  exit 3
}

sectdd_start_server() {
  [[ "${sectdd_provider}" == local ]] || return
  sectdd_assert_gpu
  mkdir -p "${sectdd_root_out}/logs"
  sectdd_server_log="${sectdd_root_out}/logs/server-${sectdd_model}-${sectdd_port}.log"
  if [[ "${sectdd_server_script}" == scripts/serve_qwen25_coder.sh ]]; then
    SECTDD_GPU="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=8192 \
      "${sectdd_server_script}" "${sectdd_server_variant}" >"${sectdd_server_log}" 2>&1 &
  else
    SECTDD_GPUS="${sectdd_gpu}" SECTDD_PORT="${sectdd_port}" SECTDD_MAX_MODEL_LEN=16384 SECTDD_MAX_NUM_SEQS=32 \
      "${sectdd_server_script}" "${sectdd_server_variant}" >"${sectdd_server_log}" 2>&1 &
  fi
  sectdd_server_pid=$!
  sectdd_wait_model
}

sectdd_count() {
  local run="$1"
  [[ -d "${run}/trajectories" ]] || { echo 0; return; }
  find "${run}/trajectories" -type f -name trajectory.json | wc -l
}

sectdd_run() {
  local benchmark="$1"
  sectdd_inputs "${benchmark}"
  sectdd_model_inputs
  local expected out shards
  expected="$(.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["tasks"])*len(d["methods"])*len(d["generation_seeds"]))' "${sectdd_config}")"
  out="${sectdd_root_out}/${benchmark}/${sectdd_model}"
  shards="${out}-shards"
  if [[ -f "${out}/run_manifest.json" && "$(sectdd_count "${out}")" -eq "${expected}" ]]; then
    echo "Resume: ${benchmark}/${sectdd_model} already complete (${expected}/${expected})."
    return
  fi
  if [[ "${sectdd_provider}" == deepseek ]]; then
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "DEEPSEEK_API_KEY is required and is never persisted." >&2; exit 2; }
    [[ "${SECTDD_CONFIRM_PAID_API:-0}" == 1 ]] || { echo "Set SECTDD_CONFIRM_PAID_API=1 to authorize 60 paid B7 requests." >&2; exit 2; }
    sectdd_api=https://api.deepseek.com
  else
    [[ -n "${sectdd_server_pid}" ]] || sectdd_start_server
    sectdd_api="http://127.0.0.1:${sectdd_port}/v1"
  fi
  mkdir -p "${sectdd_root_out}/${benchmark}"
  if [[ "${benchmark}" == sallm ]]; then
    .venv/bin/python tools/run_sallm_task_shards.py \
      --served-model "${sectdd_model}" --provider "${sectdd_provider}" --api-base "${sectdd_api}" \
      --tokenizer "${sectdd_tokenizer}" --config "${sectdd_config}" \
      --visible-projection "${sectdd_visible}" --hidden-projection "${sectdd_hidden}" \
      --output-root "${shards}" --max-workers "${sectdd_workers}" --resume
  else
    .venv/bin/python tools/run_codeguardplus_task_shards.py \
      --served-model "${sectdd_model}" --provider "${sectdd_provider}" --api-base "${sectdd_api}" \
      --tokenizer "${sectdd_tokenizer}" --config "${sectdd_config}" \
      --visible "${sectdd_visible}" --hidden "${sectdd_hidden}" \
      --output-root "${shards}" --max-workers "${sectdd_workers}" --resume
  fi
  if [[ "${sectdd_keep_server}" == 0 ]]; then
    sectdd_cleanup
    sectdd_server_pid=""
  fi
  if [[ -e "${out}" ]]; then
    mv "${out}" "${out}.incomplete.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  if [[ "${benchmark}" == sallm ]]; then
    .venv/bin/python tools/merge_sallm_formal_shards.py "${shards}" --output "${out}"
  else
    .venv/bin/python tools/merge_codeguardplus_shards.py "${shards}" --output "${out}"
  fi
  [[ "$(sectdd_count "${out}")" -eq "${expected}" ]] || { echo "Merged count mismatch: ${out}" >&2; exit 3; }
  echo "Completed ${benchmark}/${sectdd_model}: ${expected} B7 trajectories"
}

sectdd_status() {
  local benchmark model config expected run
  for benchmark in sallm codeguardplus; do
    config="configs/experiments/${benchmark}_security_only_upfront_ablation_v1.json"
    if [[ ! -f "${config}" ]]; then
      echo "${benchmark}: configuration not built"
      continue
    fi
    expected="$(.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["tasks"])*len(d["generation_seeds"]))' "${config}")"
    for model in qwen25-coder-7b qwen25-coder-14b qwen36-27b deepseek-v4-flash; do
      run="${sectdd_root_out}/${benchmark}/${model}"
      echo "${benchmark}/${model}: $(sectdd_count "${run}")/${expected}"
    done
  done
}

case "${sectdd_action}" in
  build) .venv/bin/python tools/build_security_only_upfront_ablation_v1.py ;;
  status) sectdd_status ;;
  preflight)
    [[ -n "${sectdd_model}" ]] || { echo "Usage: $0 preflight MODEL" >&2; exit 2; }
    sectdd_model_inputs
    if [[ "${sectdd_provider}" == local ]]; then
      sectdd_assert_gpu
    fi
    echo "Preflight OK: ${sectdd_model}; tokenizer/checkpoint=${sectdd_tokenizer}."
    ;;
  sallm|codeguardplus)
    [[ -n "${sectdd_model}" ]] || { echo "Usage: $0 ${sectdd_action} MODEL" >&2; exit 2; }
    sectdd_run "${sectdd_action}"
    ;;
  both)
    [[ -n "${sectdd_model}" ]] || { echo "Usage: $0 both MODEL" >&2; exit 2; }
    sectdd_model_inputs
    sectdd_keep_server=1
    if [[ "${sectdd_provider}" == local ]]; then
      sectdd_start_server
    fi
    sectdd_run sallm
    sectdd_run codeguardplus
    sectdd_cleanup
    sectdd_server_pid=""
    ;;
  analyze) .venv/bin/python tools/analyze_security_only_upfront_ablation_v1.py ;;
  all-local)
    for model in qwen25-coder-7b qwen25-coder-14b qwen36-27b; do
      bash "${BASH_SOURCE[0]}" both "${model}"
    done
    ;;
  all-deepseek)
    bash "${BASH_SOURCE[0]}" both deepseek-v4-flash
    ;;
  *)
    echo "Usage: $0 {build|status|analyze|all-local|all-deepseek|preflight MODEL|both MODEL|sallm MODEL|codeguardplus MODEL}" >&2
    exit 2
    ;;
esac
