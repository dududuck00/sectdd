#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-status}"
sectdd_workers="${SECTDD_WORKERS:-2}"
sectdd_review_gpu_14b="${SECTDD_REVIEW_GPU_14B:-2}"
sectdd_review_gpu_35b="${SECTDD_REVIEW_GPU_35B:-3}"
sectdd_review_port_14b="${SECTDD_REVIEW_PORT_14B:-19581}"
sectdd_review_port_35b="${SECTDD_REVIEW_PORT_35B:-19583}"
sectdd_review_gpu_qwen3="${SECTDD_REVIEW_GPU_QWEN3:-4}"
sectdd_review_port_qwen3="${SECTDD_REVIEW_PORT_QWEN3:-19585}"
sectdd_server_pids=()

sectdd_cleanup() {
  local pid
  for pid in "${sectdd_server_pids[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then kill "${pid}" 2>/dev/null || true; fi
  done
  wait 2>/dev/null || true
}
trap sectdd_cleanup EXIT INT TERM

sectdd_require_paid_api() {
  [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "DEEPSEEK_API_KEY is required and is never written to disk." >&2; exit 2; }
  [[ "${SECTDD_CONFIRM_PAID_API:-0}" == 1 ]] || { echo "Set SECTDD_CONFIRM_PAID_API=1 to authorize paid API calls and external prompt transfer." >&2; exit 2; }
}

sectdd_wait_model() {
  local port="$1" model="$2" pid="$3" log="$4" attempt
  for attempt in $(seq 1 240); do
    kill -0 "${pid}" 2>/dev/null || { tail -n 120 "${log}" >&2 || true; exit 3; }
    if curl -fsS "http://127.0.0.1:${port}/v1/models" 2>/dev/null | .venv/bin/python -c 'import json,sys; wanted=sys.argv[1]; raise SystemExit(0 if wanted in {x.get("id") for x in json.load(sys.stdin).get("data",[])} else 1)' "${model}" 2>/dev/null; then
      echo "Ready: ${model} on port ${port}"
      return
    fi
    (( attempt % 12 != 0 )) || echo "Still waiting for ${model}..."
    sleep 5
  done
  tail -n 120 "${log}" >&2 || true
  exit 3
}

sectdd_start_reviewers() {
  [[ "${sectdd_review_gpu_14b}" != "${sectdd_review_gpu_35b}" ]] || { echo "Semantic reviewers require distinct GPUs." >&2; exit 2; }
  mkdir -p artifacts/paper-expansion-v1/logs
  local log14="artifacts/paper-expansion-v1/logs/reviewer-qwen14.log"
  local log35="artifacts/paper-expansion-v1/logs/reviewer-qwen36-35b.log"
  SECTDD_GPU="${sectdd_review_gpu_14b}" SECTDD_PORT="${sectdd_review_port_14b}" scripts/serve_qwen25_coder.sh 14b >"${log14}" 2>&1 &
  local pid14=$!; sectdd_server_pids+=("${pid14}")
  SECTDD_GPUS="${sectdd_review_gpu_35b}" SECTDD_PORT="${sectdd_review_port_35b}" SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen36.sh 35b-a3b >"${log35}" 2>&1 &
  local pid35=$!; sectdd_server_pids+=("${pid35}")
  sectdd_wait_model "${sectdd_review_port_14b}" qwen25-coder-14b "${pid14}" "${log14}"
  sectdd_wait_model "${sectdd_review_port_35b}" qwen36-35b-a3b "${pid35}" "${log35}"
}

sectdd_plan() {
  .venv/bin/python tools/build_paper_expansion_v1.py
}

sectdd_cweval_build() {
  local resume=()
  if [[ -f artifacts/paper-expansion-v1/cweval/oracle-construction/run_manifest.json ]]; then
    resume=(--resume)
  else
    sectdd_require_paid_api
  fi
  .venv/bin/python tools/build_cweval_expansion_oracles_v1.py \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --attempts 5 --num-workers "${sectdd_workers}" --repeats 3 \
    --confirm-paid-api "${resume[@]}"
}

sectdd_cweval_review() {
  .venv/bin/python - <<'PY'
import json
from pathlib import Path
path = Path("oracles/cweval_py/paper_expansion_v1/manifest.json")
if not path.is_file():
    raise SystemExit("CWEval oracle manifest is absent; run cweval-build first.")
count = len(json.loads(path.read_text(encoding="utf-8")).get("tasks", {}))
if count == 0:
    raise SystemExit("CWEval qualified task count is zero; rerun cweval-build after fixing construction failures.")
print(f"CWEval semantic-review input: {count} qualified tasks")
PY
  sectdd_start_reviewers
  local resume=()
  [[ -d artifacts/paper-expansion-v1/cweval/semantic-review/reviews ]] && resume=(--resume)
  .venv/bin/python tools/review_cweval_expansion_semantics_v1.py \
    --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_review_port_14b}/v1" \
    --reviewer "qwen36-35b-a3b=http://127.0.0.1:${sectdd_review_port_35b}/v1" \
    --max-workers 2 --confirm-machine-review "${resume[@]}"
}

sectdd_sallm_generate() {
  sectdd_require_paid_api
  local output="artifacts/paper-expansion-v1/sallm/secure-generation/deepseek-v4-flash"
  local resume=(); [[ -f "${output}/run_manifest.json" ]] && resume=(--resume)
  .venv/bin/python tools/generate_sallm_secure_candidates.py \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --task-file configs/benchmarks/sallm_paper_expansion_v1_tasks.json \
    --candidates-per-task 6 --base-seed 20261201 --temperature 0.35 --top-p 0.95 \
    --max-tokens 8192 --num-workers "${sectdd_workers}" --thinking enabled \
    --reasoning-effort high --confirm-paid-api --output "${output}" "${resume[@]}"
}

sectdd_sallm_qualify() {
  local selection="benchmarks/manifests/sallm-paper-expansion-v1-safe-selection.json"
  if [[ -f "${selection}" ]]; then echo "Resume: SALLM secure references already qualified."; return; fi
  .venv/bin/python tools/qualify_sallm_expansion.py \
    --plan configs/benchmarks/sallm_paper_expansion_v1_tasks.json \
    --generation artifacts/paper-expansion-v1/sallm/secure-generation/deepseek-v4-flash \
    --manifest benchmarks/manifests/sallm-v1.json \
    --overlay configs/benchmarks/sallm_audit_overlay_v1.json \
    --output artifacts/paper-expansion-v1/sallm/safe-qualification \
    --oracle-root oracles/sallm_paper_expansion_v1 \
    --selection "${selection}" \
    --qualified-task-file configs/benchmarks/sallm_paper_expansion_v1_safe_qualified.json \
    --selection-id sallm-paper-expansion-v1-safe-selection \
    --mutation-set-id sallm-paper-expansion-v1-primary --repeats 3
}

sectdd_sallm_partition() {
  sectdd_require_paid_api
  local output="artifacts/paper-expansion-v1/sallm/partitioned-construction"
  local resume=(); [[ -d "${output}" ]] && resume=(--resume)
  .venv/bin/python tools/build_sallm_expansion_partitioned.py \
    --task-file configs/benchmarks/sallm_paper_expansion_v1_safe_qualified.json \
    --selection benchmarks/manifests/sallm-paper-expansion-v1-safe-selection.json \
    --benchmark benchmarks/manifests/sallm-v1.json \
    --base-overlay configs/benchmarks/sallm_audit_overlay_v1.json \
    --oracle-root oracles/sallm_paper_expansion_v1 \
    --output "${output}" --oracle-set-id sallm-paper-expansion-v1 \
    --visible-overlay configs/benchmarks/sallm_paper_expansion_v1_visible.json \
    --hidden-overlay configs/benchmarks/sallm_paper_expansion_v1_hidden.json \
    --visible-config configs/oracles/sallm_paper_expansion_v1_visible.json \
    --hidden-config configs/oracles/sallm_paper_expansion_v1_hidden.json \
    --freeze benchmarks/manifests/sallm-paper-expansion-v1-partition-freeze.json \
    --final-tasks configs/benchmarks/sallm_paper_expansion_v1_partition_qualified.json \
    --oracle-manifest oracles/sallm_paper_expansion_v1/manifest.json \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --attempts 5 --num-workers "${sectdd_workers}" --repeats 3 \
    --confirm-paid-api "${resume[@]}"
}

sectdd_sallm_review() {
  sectdd_start_reviewers
  .venv/bin/python tools/review_sallm_expansion_semantics.py \
    --task-file configs/benchmarks/sallm_paper_expansion_v1_partition_qualified.json \
    --benchmark benchmarks/manifests/sallm-v1.json \
    --oracle-manifest oracles/sallm_paper_expansion_v1/manifest.json \
    --output artifacts/paper-expansion-v1/sallm/semantic-review \
    --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_review_port_14b}/v1" \
    --reviewer "qwen36-35b-a3b=http://127.0.0.1:${sectdd_review_port_35b}/v1" \
    --max-workers 2 --report-id sallm-paper-expansion-v1-semantic-panel \
    --confirm-machine-review
}

sectdd_sallm_freeze() {
  .venv/bin/python tools/freeze_expansion_semantic_panel_v1.py \
    --benchmark sallm --report artifacts/paper-expansion-v1/sallm/semantic-review/report.json \
    --visible configs/oracles/sallm_paper_expansion_v1_visible.json \
    --hidden configs/oracles/sallm_paper_expansion_v1_hidden.json \
    --output-visible configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json \
    --output-hidden configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json \
    --canonical-output benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-oracle.json \
    --freeze benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json \
    --oracle-set-id sallm-paper-expansion-v1-semantic-machine --minimum-tasks 8
}

sectdd_sallm_dispute_review() {
  local builder="tools/build_sallm_paper_expansion_dispute_v1.py"
  local output="artifacts/paper-expansion-v1/sallm/semantic-dispute-review"
  local report="${output}/report.json"
  if [[ -f benchmarks/manifests/sallm-paper-expansion-v1-semantic-dispute-freeze.json ]]; then
    .venv/bin/python "${builder}" --verify-only
  else
    .venv/bin/python "${builder}"
  fi
  if [[ -f "${report}" ]]; then
    echo "Resume: SALLM Qwen3-32B dispute review already completed."
    return
  fi
  mkdir -p artifacts/paper-expansion-v1/logs
  local log="artifacts/paper-expansion-v1/logs/reviewer-qwen3-32b-dispute.log"
  SECTDD_GPU="${sectdd_review_gpu_qwen3}" SECTDD_PORT="${sectdd_review_port_qwen3}" \
    SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen25_coder.sh qwen3-32b >"${log}" 2>&1 &
  local pid=$!; sectdd_server_pids+=("${pid}")
  sectdd_wait_model "${sectdd_review_port_qwen3}" qwen3-32b "${pid}" "${log}"
  .venv/bin/python tools/review_sallm_expansion_semantics.py \
    --task-file configs/benchmarks/sallm_paper_expansion_v1_disputed.json \
    --benchmark benchmarks/manifests/sallm-v1.json \
    --oracle-manifest oracles/sallm_paper_expansion_v1_dispute/manifest.json \
    --output "${output}" \
    --reviewer "qwen3-32b=http://127.0.0.1:${sectdd_review_port_qwen3}/v1" \
    --allow-single-reviewer --max-workers 1 --max-tokens 8192 \
    --timeout-seconds 600 --report-id sallm-paper-expansion-v1-semantic-dispute \
    --confirm-machine-review
}

cg_root="artifacts/paper-expansion-v1/codeguardplus"
cg_plan="configs/benchmarks/codeguardplus_paper_expansion_v1_plan.json"
cg_manifest="benchmarks/manifests/codeguardplus-v1.json"
cg_generation="${cg_root}/secure-generation/deepseek-v4-flash"
cg_screen="${cg_root}/safe-screen"
cg_selection="benchmarks/manifests/codeguardplus-paper-expansion-v1-safe-selection.json"
cg_repeats="${cg_root}/safe-repeats3"
cg_stable="benchmarks/manifests/codeguardplus-paper-expansion-v1-stable-safe.json"
cg_mutants="${cg_root}/mutants/deepseek-v4-flash"
cg_mutant_screen="${cg_root}/mutant-screen"
cg_mutant_selection="benchmarks/manifests/codeguardplus-paper-expansion-v1-mutant-selection.json"
cg_mutant_repeats="${cg_root}/mutant-repeats3"
cg_pairs="benchmarks/manifests/codeguardplus-paper-expansion-v1-oracle-pairs.json"
cg_partition_gen="${cg_root}/partitioned-generation/deepseek-v4-flash"
cg_partition_qual="${cg_root}/partitioned-qualification"
cg_oracle="oracles/codeguardplus_paper_expansion_v1"
cg_visible="configs/oracles/codeguardplus_paper_expansion_v1_visible.json"
cg_hidden="configs/oracles/codeguardplus_paper_expansion_v1_hidden.json"
cg_partition_freeze="benchmarks/manifests/codeguardplus-paper-expansion-v1-partition-freeze.json"

sectdd_codeguard_generate() {
  sectdd_require_paid_api
  local resume=(); [[ -f "${cg_generation}/run_manifest.json" ]] && resume=(--resume)
  .venv-codeguardplus/bin/python tools/generate_codeguardplus_secure_candidates.py \
    --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com \
    --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --selection-state primary \
    --candidates-per-task 6 --base-seed 20261301 --temperature 0.35 --top-p 0.95 \
    --max-tokens 8192 --num-workers "${sectdd_workers}" --thinking enabled \
    --reasoning-effort high --confirm-paid-api --output "${cg_generation}" "${resume[@]}"
}

sectdd_codeguard_safe() {
  local resume=(); [[ -f "${cg_screen}/run_manifest.json" ]] && resume=(--resume)
  .venv-codeguardplus/bin/python tools/run_codeguardplus_qualification.py --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --selection-state primary --generation-run "${cg_generation}" --output "${cg_screen}" --repeats 1 --num-workers "${sectdd_workers}" "${resume[@]}"
  if [[ ! -f "${cg_selection}" ]]; then .venv-codeguardplus/bin/python tools/select_codeguardplus_safe_references.py --plan "${cg_plan}" --selection-state primary --generation-run "${cg_generation}" --evaluation-run "${cg_screen}" --selection-id codeguardplus-paper-expansion-v1-safe-selection --output "${cg_selection}" --report docs/codeguardplus-paper-expansion-v1-safe-selection.md; fi
  resume=(); [[ -f "${cg_repeats}/run_manifest.json" ]] && resume=(--resume)
  .venv-codeguardplus/bin/python tools/run_codeguardplus_qualification.py --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --safe-selection "${cg_selection}" --output "${cg_repeats}" --repeats 3 --num-workers "${sectdd_workers}" "${resume[@]}"
  if [[ ! -f "${cg_stable}" ]]; then .venv-codeguardplus/bin/python tools/freeze_codeguardplus_safe_references.py --selection "${cg_selection}" --evaluation-run "${cg_repeats}" --selection-id codeguardplus-paper-expansion-v1-stable-safe --output "${cg_stable}" --report docs/codeguardplus-paper-expansion-v1-stable-safe.md; fi
}

sectdd_codeguard_mutants() {
  local resume=()
  if [[ ! -f "${cg_mutant_selection}" ]]; then
    sectdd_require_paid_api
    [[ -f "${cg_mutants}/run_manifest.json" ]] && resume=(--resume)
    .venv-codeguardplus/bin/python tools/generate_codeguardplus_mutants.py --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --safe-selection "${cg_stable}" --mutants-per-task 5 --base-seed 20261321 --temperature 0.35 --top-p 0.95 --max-tokens 8192 --num-workers "${sectdd_workers}" --thinking enabled --reasoning-effort high --confirm-paid-api --output "${cg_mutants}" "${resume[@]}"
    resume=(); [[ -f "${cg_mutant_screen}/run_manifest.json" ]] && resume=(--resume)
    .venv-codeguardplus/bin/python tools/run_codeguardplus_qualification.py --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --mutant-run "${cg_mutants}" --output "${cg_mutant_screen}" --repeats 1 --num-workers "${sectdd_workers}" "${resume[@]}"
    .venv-codeguardplus/bin/python tools/select_codeguardplus_vulnerability_mutants.py --plan "${cg_plan}" --safe-selection "${cg_stable}" --mutant-run "${cg_mutants}" --evaluation-run "${cg_mutant_screen}" --selection-id codeguardplus-paper-expansion-v1-mutant-selection --output "${cg_mutant_selection}" --report docs/codeguardplus-paper-expansion-v1-mutant-selection.md
  else
    echo "Resume: frozen CodeGuard+ mutant selection exists; skipping generation and screen."
  fi
  resume=(); [[ -f "${cg_mutant_repeats}/run_manifest.json" ]] && resume=(--resume)
  .venv-codeguardplus/bin/python tools/run_codeguardplus_qualification.py --plan "${cg_plan}" --benchmark-manifest "${cg_manifest}" --mutant-selection "${cg_mutant_selection}" --output "${cg_mutant_repeats}" --repeats 3 --num-workers "${sectdd_workers}" "${resume[@]}"
  if [[ ! -f "${cg_pairs}" ]]; then .venv-codeguardplus/bin/python tools/freeze_codeguardplus_oracle_pairs.py --plan "${cg_plan}" --safe-selection "${cg_stable}" --mutant-selection "${cg_mutant_selection}" --mutant-evaluation-run "${cg_mutant_repeats}" --freeze-id codeguardplus-paper-expansion-v1-oracle-pairs --output "${cg_pairs}" --report docs/codeguardplus-paper-expansion-v1-oracle-pairs.md; fi
}

sectdd_codeguard_partition() {
  sectdd_require_paid_api
  local resume=(); [[ -f "${cg_partition_gen}/run_manifest.json" ]] && resume=(--resume)
  .venv-codeguardplus/bin/python tools/generate_codeguardplus_partitioned_oracles.py --provider deepseek --model deepseek-v4-flash --api-base https://api.deepseek.com --pairs "${cg_pairs}" --benchmark "${cg_manifest}" --attempts 5 --base-seed 20261341 --temperature 0.35 --top-p 0.95 --max-tokens 12288 --thinking enabled --reasoning-effort high --num-workers "${sectdd_workers}" --confirm-paid-api --output "${cg_partition_gen}" "${resume[@]}"
  if [[ ! -f "${cg_partition_freeze}" ]]; then .venv-codeguardplus/bin/python tools/qualify_codeguardplus_partitioned_oracles.py --generation-run "${cg_partition_gen}" --pairs "${cg_pairs}" --output "${cg_partition_qual}" --oracle-root "${cg_oracle}" --visible-projection "${cg_visible}" --hidden-projection "${cg_hidden}" --freeze "${cg_partition_freeze}" --report docs/codeguardplus-paper-expansion-v1-partition.md --oracle-set-id codeguardplus-paper-expansion-v1 --freeze-id codeguardplus-paper-expansion-v1 --repeats 3 --num-workers "${sectdd_workers}"; fi
}

sectdd_codeguard_review() {
  sectdd_start_reviewers
  local common=(--task-file "${cg_partition_freeze}" --benchmark "${cg_manifest}" --oracle-manifest "${cg_oracle}/manifest.json" --output "${cg_root}/semantic-review" --report-id codeguardplus-paper-expansion-v1-semantic-panel --confirm-machine-review)
  if [[ ! -f "${cg_root}/semantic-review/packet_manifest.json" ]]; then
    .venv-codeguardplus/bin/python tools/review_codeguardplus_partitioned_semantics.py "${common[@]}" --prepare-only
  fi
  .venv-codeguardplus/bin/python tools/review_codeguardplus_partitioned_semantics.py "${common[@]}" --reviewer "qwen25-coder-14b=http://127.0.0.1:${sectdd_review_port_14b}/v1" --provider local --local-thinking disabled --max-workers 2
  .venv-codeguardplus/bin/python tools/review_codeguardplus_partitioned_semantics.py "${common[@]}" --reviewer "qwen36-35b-a3b=http://127.0.0.1:${sectdd_review_port_35b}/v1" --provider local --local-thinking disabled --max-workers 2
}

sectdd_codeguard_dispute_review() {
  local builder="tools/build_codeguardplus_paper_expansion_dispute_v1.py"
  local freeze="benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-dispute-freeze.json"
  local oracle="oracles/codeguardplus_paper_expansion_v1_dispute/manifest.json"
  local output="${cg_root}/semantic-dispute-review"
  local report_id="codeguardplus-paper-expansion-v1-semantic-dispute"
  if [[ -f "${freeze}" ]]; then
    .venv/bin/python "${builder}" --verify-only
  else
    .venv/bin/python "${builder}"
  fi
  if [[ ! -f "${output}/packet_manifest.json" ]]; then
    .venv-codeguardplus/bin/python tools/review_codeguardplus_partitioned_semantics.py \
      --task-file "${freeze}" --benchmark "${cg_manifest}" \
      --oracle-manifest "${oracle}" --output "${output}" \
      --report-id "${report_id}" --prepare-only --confirm-machine-review
  else
    echo "Resume: blinded CodeGuard+ dispute packets already prepared."
  fi
  local expected completed
  expected="$(.venv/bin/python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["qualified_task_ids"]))' "${freeze}")"
  if [[ -d "${output}/reviews/qwen3-32b" ]]; then
    completed="$(find "${output}/reviews/qwen3-32b" -type f -name '*.json' | wc -l)"
  else
    completed=0
  fi
  if [[ "${completed}" -lt "${expected}" ]]; then
    mkdir -p artifacts/paper-expansion-v1/logs
    local log="artifacts/paper-expansion-v1/logs/reviewer-codeguard-qwen3-32b-dispute.log"
    SECTDD_GPU="${sectdd_review_gpu_qwen3}" SECTDD_PORT="${sectdd_review_port_qwen3}" \
      SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen25_coder.sh qwen3-32b >"${log}" 2>&1 &
    local pid=$!; sectdd_server_pids+=("${pid}")
    sectdd_wait_model "${sectdd_review_port_qwen3}" qwen3-32b "${pid}" "${log}"
    .venv-codeguardplus/bin/python tools/review_codeguardplus_partitioned_semantics.py \
      --task-file "${freeze}" --benchmark "${cg_manifest}" \
      --oracle-manifest "${oracle}" --output "${output}" \
      --report-id "${report_id}" \
      --reviewer "qwen3-32b=http://127.0.0.1:${sectdd_review_port_qwen3}/v1" \
      --provider local --local-thinking disabled --max-workers 1 --max-tokens 8192 \
      --timeout-seconds 600 --confirm-machine-review
  else
    echo "Resume: Qwen3-32B CodeGuard+ dispute reviews complete."
  fi
  .venv/bin/python - "${freeze}" "${output}" <<'PY'
import json, sys
from pathlib import Path
freeze=json.load(open(sys.argv[1])); root=Path(sys.argv[2])/"reviews/qwen3-32b"
rows=[]
for task in freeze["qualified_task_ids"]:
    review=json.load(open(root/f"{task.replace('/', '__')}.json"))["review"]
    rows.append({"task_id":task,"verdict":review["verdict"],"confidence":review["confidence"],"summary":review["summary"]})
print(json.dumps({"reviewer":"qwen3-32b","task_count":len(rows),"accept_count":sum(x["verdict"]=="accept" for x in rows),"reviews":rows},ensure_ascii=False,indent=2))
PY
}

sectdd_codeguard_freeze() {
  .venv/bin/python tools/freeze_codeguardplus_paper_expansion_adjudicated_v1.py
}

sectdd_status() {
  .venv/bin/python - <<'PY'
import json
from pathlib import Path
checks = {
    "candidate_freeze": Path("benchmarks/manifests/paper-expansion-v1-candidate-freeze.json"),
    "cweval_dynamic": Path("artifacts/paper-expansion-v1/cweval/oracle-construction/summary.json"),
    "cweval_semantic": Path("benchmarks/manifests/cweval-paper-expansion-v1-semantic-machine-freeze.json"),
    "sallm_partition": Path("benchmarks/manifests/sallm-paper-expansion-v1-partition-freeze.json"),
    "sallm_semantic": Path("benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json"),
    "codeguard_partition": Path("benchmarks/manifests/codeguardplus-paper-expansion-v1-partition-freeze.json"),
    "codeguard_semantic": Path("benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-machine-freeze.json"),
    "full_matrix_input": Path("benchmarks/manifests/paper-expansion-full-v1-input-freeze.json"),
}
for name, path in checks.items():
    if not path.is_file(): print(f"{name}: pending ({path})"); continue
    data=json.loads(path.read_text())
    count=data.get("qualified_task_count", data.get("construction_targets", data.get("complete")))
    if data.get("complete") is False:
        print(f"{name}: infrastructure-blocked ({count})")
    elif name == "cweval_dynamic" and not count:
        print("cweval_dynamic: invalid-zero-qualified (rerun cweval-build)")
    else:
        print(f"{name}: ready ({count})")
PY
}

case "${sectdd_action}" in
  plan) sectdd_plan ;;
  cweval-build) sectdd_plan; sectdd_cweval_build ;;
  cweval-review) sectdd_cweval_review ;;
  sallm-generate) sectdd_plan; sectdd_sallm_generate ;;
  sallm-qualify) sectdd_sallm_qualify ;;
  sallm-partition) sectdd_sallm_partition ;;
  sallm-review) sectdd_sallm_review ;;
  sallm-dispute-review) sectdd_sallm_dispute_review ;;
  sallm-freeze) sectdd_sallm_freeze ;;
  codeguard-generate) sectdd_plan; sectdd_codeguard_generate ;;
  codeguard-safe) sectdd_codeguard_safe ;;
  codeguard-mutants) sectdd_codeguard_mutants ;;
  codeguard-partition) sectdd_codeguard_partition ;;
  codeguard-review) sectdd_codeguard_review ;;
  codeguard-dispute-review) sectdd_codeguard_dispute_review ;;
  codeguard-freeze) sectdd_codeguard_freeze ;;
  full-config) .venv/bin/python tools/build_paper_expansion_full_configs_v1.py --allow-more-tasks --accept-qualified-shortfall ;;
  status) sectdd_status ;;
  all)
    for stage in \
      plan cweval-build cweval-review \
      sallm-generate sallm-qualify sallm-partition sallm-review sallm-freeze \
      codeguard-generate codeguard-safe codeguard-mutants codeguard-partition \
      codeguard-review codeguard-freeze full-config; do
      "${BASH_SOURCE[0]}" "${stage}"
    done
    ;;
  *)
    echo "Usage: $0 {plan|cweval-build|cweval-review|sallm-generate|sallm-qualify|sallm-partition|sallm-review|sallm-dispute-review|sallm-freeze|codeguard-generate|codeguard-safe|codeguard-mutants|codeguard-partition|codeguard-review|codeguard-dispute-review|codeguard-freeze|full-config|status|all}" >&2
    exit 2
    ;;
esac
