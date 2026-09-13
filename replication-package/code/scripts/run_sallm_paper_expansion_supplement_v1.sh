#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "${sectdd_root}"
action="${1:-status}"; workers="${SECTDD_WORKERS:-2}"
gpu14="${SECTDD_REVIEW_GPU_14B:-4}"; gpu35="${SECTDD_REVIEW_GPU_35B:-5}"; gpu3="${SECTDD_REVIEW_GPU_QWEN3:-4}"
port14="${SECTDD_REVIEW_PORT_14B:-19681}"; port35="${SECTDD_REVIEW_PORT_35B:-19683}"; port3="${SECTDD_REVIEW_PORT_QWEN3:-19685}"
pids=()
cleanup(){ local p; for p in "${pids[@]:-}"; do if kill -0 "${p}" 2>/dev/null; then kill "${p}" 2>/dev/null || true; fi; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM
require_paid(){ [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "DEEPSEEK_API_KEY is required." >&2; exit 2; }; [[ "${SECTDD_CONFIRM_PAID_API:-0}" == 1 ]] || { echo "Set SECTDD_CONFIRM_PAID_API=1." >&2; exit 2; }; }
wait_model(){ local port="$1" model="$2" pid="$3" log="$4" n; for n in $(seq 1 240); do kill -0 "${pid}" 2>/dev/null || { tail -n 120 "${log}" >&2; exit 3; }; if curl -fsS "http://127.0.0.1:${port}/v1/models" 2>/dev/null | .venv/bin/python -c 'import json,sys; m=sys.argv[1]; raise SystemExit(0 if m in {x.get("id") for x in json.load(sys.stdin).get("data",[])} else 1)' "${model}" 2>/dev/null; then echo "Ready: ${model} on port ${port}"; return; fi; ((n%12!=0)) || echo "Still waiting for ${model}..."; sleep 5; done; tail -n 120 "${log}" >&2; exit 3; }
start_panel(){
  [[ "${gpu14}" != "${gpu35}" ]] || { echo "Reviewers require distinct GPUs." >&2; exit 2; }
  mkdir -p artifacts/paper-expansion-v1/logs
  local l14="artifacts/paper-expansion-v1/logs/sallm-supplement-qwen14.log" l35="artifacts/paper-expansion-v1/logs/sallm-supplement-qwen35.log"
  SECTDD_GPU="${gpu14}" SECTDD_PORT="${port14}" scripts/serve_qwen25_coder.sh 14b >"${l14}" 2>&1 & local p14=$!; pids+=("${p14}")
  SECTDD_GPUS="${gpu35}" SECTDD_PORT="${port35}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen36.sh 35b-a3b >"${l35}" 2>&1 & local p35=$!; pids+=("${p35}")
  wait_model "${port14}" qwen25-coder-14b "${p14}" "${l14}"; wait_model "${port35}" qwen36-35b-a3b "${p35}" "${l35}"
}
plan(){ .venv/bin/python tools/build_sallm_paper_expansion_supplement_v1.py; }
generate(){ require_paid; local out="artifacts/paper-expansion-v1/sallm-supplement/secure-generation/deepseek-v4-flash" resume=(); [[ -f "${out}/run_manifest.json" ]] && resume=(--resume); .venv/bin/python tools/generate_sallm_secure_candidates.py --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com --task-file configs/benchmarks/sallm_paper_expansion_supplement_v1_tasks.json --candidates-per-task 6 --base-seed 20261401 --temperature 0.35 --top-p 0.95 --max-tokens 8192 --num-workers "${workers}" --thinking enabled --reasoning-effort high --confirm-paid-api --output "${out}" "${resume[@]}"; }
qualify(){
  local selection="benchmarks/manifests/sallm-paper-expansion-supplement-v1-safe-selection.json"
  [[ ! -f "${selection}" ]] || { echo "Resume: supplement secure references already qualified."; return; }
  .venv/bin/python tools/qualify_sallm_expansion.py --plan configs/benchmarks/sallm_paper_expansion_supplement_v1_tasks.json --generation artifacts/paper-expansion-v1/sallm-supplement/secure-generation/deepseek-v4-flash --manifest benchmarks/manifests/sallm-v1.json --overlay configs/benchmarks/sallm_audit_overlay_v1.json --output artifacts/paper-expansion-v1/sallm-supplement/safe-qualification --oracle-root oracles/sallm_paper_expansion_supplement_v1 --selection "${selection}" --qualified-task-file configs/benchmarks/sallm_paper_expansion_supplement_v1_safe_qualified.json --selection-id sallm-paper-expansion-supplement-v1-safe-selection --mutation-set-id sallm-paper-expansion-supplement-v1-primary --repeats 3
}
partition(){
  require_paid; local out="artifacts/paper-expansion-v1/sallm-supplement/partitioned-construction" resume=(); [[ -d "${out}" ]] && resume=(--resume)
  .venv/bin/python tools/build_sallm_expansion_partitioned.py --task-file configs/benchmarks/sallm_paper_expansion_supplement_v1_safe_qualified.json --selection benchmarks/manifests/sallm-paper-expansion-supplement-v1-safe-selection.json --benchmark benchmarks/manifests/sallm-v1.json --base-overlay configs/benchmarks/sallm_audit_overlay_v1.json --oracle-root oracles/sallm_paper_expansion_supplement_v1 --output "${out}" --oracle-set-id sallm-paper-expansion-supplement-v1 --visible-overlay configs/benchmarks/sallm_paper_expansion_supplement_v1_visible.json --hidden-overlay configs/benchmarks/sallm_paper_expansion_supplement_v1_hidden.json --visible-config configs/oracles/sallm_paper_expansion_supplement_v1_visible.json --hidden-config configs/oracles/sallm_paper_expansion_supplement_v1_hidden.json --freeze benchmarks/manifests/sallm-paper-expansion-supplement-v1-partition-freeze.json --final-tasks configs/benchmarks/sallm_paper_expansion_supplement_v1_partition_qualified.json --oracle-manifest oracles/sallm_paper_expansion_supplement_v1/manifest.json --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com --attempts 5 --num-workers "${workers}" --repeats 3 --confirm-paid-api "${resume[@]}"
}
review(){
  local out="artifacts/paper-expansion-v1/sallm-supplement/semantic-review"; [[ ! -f "${out}/report.json" ]] || { echo "Resume: supplement semantic panel complete."; return; }
  start_panel
  .venv/bin/python tools/review_sallm_expansion_semantics.py --task-file configs/benchmarks/sallm_paper_expansion_supplement_v1_partition_qualified.json --benchmark benchmarks/manifests/sallm-v1.json --oracle-manifest oracles/sallm_paper_expansion_supplement_v1/manifest.json --output "${out}" --reviewer "qwen25-coder-14b=http://127.0.0.1:${port14}/v1" --reviewer "qwen36-35b-a3b=http://127.0.0.1:${port35}/v1" --max-workers 2 --max-tokens 4096 --timeout-seconds 600 --report-id sallm-paper-expansion-supplement-v1-semantic-panel --confirm-machine-review
}
dispute(){
  .venv/bin/python tools/build_sallm_paper_expansion_supplement_dispute_v1.py
  local count; count="$(.venv/bin/python -c 'import json; print(len(json.load(open("configs/benchmarks/sallm_paper_expansion_supplement_v1_disputed.json"))["tasks"]))')"
  [[ "${count}" -gt 0 ]] || { echo "No split supplement decisions require a third reviewer."; return; }
  local out="artifacts/paper-expansion-v1/sallm-supplement/semantic-dispute-review"; [[ ! -f "${out}/report.json" ]] || { echo "Resume: supplement dispute review complete."; return; }
  mkdir -p artifacts/paper-expansion-v1/logs; local log="artifacts/paper-expansion-v1/logs/sallm-supplement-qwen3.log"
  SECTDD_GPU="${gpu3}" SECTDD_PORT="${port3}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen25_coder.sh qwen3-32b >"${log}" 2>&1 & local pid=$!; pids+=("${pid}"); wait_model "${port3}" qwen3-32b "${pid}" "${log}"
  .venv/bin/python tools/review_sallm_expansion_semantics.py --task-file configs/benchmarks/sallm_paper_expansion_supplement_v1_disputed.json --benchmark benchmarks/manifests/sallm-v1.json --oracle-manifest oracles/sallm_paper_expansion_supplement_v1_dispute/manifest.json --output "${out}" --reviewer "qwen3-32b=http://127.0.0.1:${port3}/v1" --allow-single-reviewer --max-workers 1 --max-tokens 8192 --timeout-seconds 600 --report-id sallm-paper-expansion-supplement-v1-semantic-dispute --confirm-machine-review
}
freeze(){ .venv/bin/python tools/freeze_sallm_paper_expansion_combined_v1.py; }
status(){
  .venv/bin/python - <<'PY'
import json
from pathlib import Path
for name,path in {
 "candidate":"benchmarks/manifests/sallm-paper-expansion-supplement-v1-candidate-freeze.json",
 "safe":"benchmarks/manifests/sallm-paper-expansion-supplement-v1-safe-selection.json",
 "partition":"benchmarks/manifests/sallm-paper-expansion-supplement-v1-partition-freeze.json",
 "panel":"artifacts/paper-expansion-v1/sallm-supplement/semantic-review/report.json",
 "dispute":"artifacts/paper-expansion-v1/sallm-supplement/semantic-dispute-review/report.json",
 "combined":"benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json",
}.items():
 p=Path(path)
 if not p.is_file(): print(f"{name}: pending"); continue
 d=json.loads(p.read_text()); summary=d.get("summary",d)
 count=summary.get("qualified_task_count",summary.get("three_repeat_qualified_task_count",summary.get("partition_repeat_qualified_task_count",summary.get("unanimous_machine_accept_count",d.get("candidate_task_count")))))
 print(f"{name}: ready ({count})")
PY
}
case "${action}" in
 plan) plan;; generate) plan; generate;; qualify) qualify;; partition) partition;; review) review;; dispute-review) dispute;; freeze) freeze;; status) status;; all) for stage in plan generate qualify partition review dispute-review freeze; do "${BASH_SOURCE[0]}" "${stage}"; done;; *) echo "Usage: $0 {plan|generate|qualify|partition|review|dispute-review|freeze|status|all}" >&2; exit 2;; esac
