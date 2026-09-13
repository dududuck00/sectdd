#!/usr/bin/env bash
set -euo pipefail

sectdd_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${sectdd_root}"

sectdd_action="${1:-status}"
sectdd_python="${SECTDD_PYTHON:-.venv-codeguardplus/bin/python}"
sectdd_plan="configs/benchmarks/codeguardplus_qualification_candidates_v2.json"
sectdd_benchmark="benchmarks/manifests/codeguardplus-v1.json"
sectdd_model_path="<MODEL_ROOT>/Qwen3.6/Qwen3.6-27B"
sectdd_api="${SECTDD_API_BASE:-http://127.0.0.1:18083/v1}"
sectdd_workers="${SECTDD_WORKERS:-4}"
sectdd_root_out="artifacts/codeguardplus-reserve-expansion-v1"
sectdd_generation_primary="${sectdd_root_out}/generation/qwen36-27b-safe"
sectdd_generation_fallback="${sectdd_root_out}/generation/qwen36-27b-safe-fallback-01"
sectdd_generation="${sectdd_root_out}/generation/qwen36-27b-safe-merged"
sectdd_safe_screen="${sectdd_root_out}/qualification/safe-screen"
sectdd_safe_selection="benchmarks/manifests/codeguardplus-reserve-safe-selection-v1.json"
sectdd_safe_repeats="${sectdd_root_out}/qualification/safe-repeats3"
sectdd_stable_safe="benchmarks/manifests/codeguardplus-reserve-stable-safe-v1.json"
sectdd_mutants="${sectdd_root_out}/generation/qwen36-27b-mutants"
sectdd_mutant_screen="${sectdd_root_out}/qualification/mutant-screen"
sectdd_mutant_selection="benchmarks/manifests/codeguardplus-reserve-mutant-selection-v1.json"
sectdd_mutant_repeats="${sectdd_root_out}/qualification/mutant-repeats3"
sectdd_pairs="benchmarks/manifests/codeguardplus-reserve-oracle-pairs-v1.json"
sectdd_partition_generation="${sectdd_root_out}/partitioned-generation/qwen36-27b"
sectdd_partition_qualification="${sectdd_root_out}/partitioned-qualification"
sectdd_oracle_root="oracles/codeguardplus_reserve_partitioned_v1"
sectdd_partition_freeze="benchmarks/manifests/codeguardplus-reserve-partitioned-v1-freeze.json"

sectdd_resume_flag() {
  if [[ -f "$1/run_manifest.json" ]]; then
    printf '%s\n' --resume
  fi
}

case "${sectdd_action}" in
  build)
    "${sectdd_python}" tools/build_codeguardplus_reserve_expansion_v1.py
    ;;
  serve)
    exec env SECTDD_GPUS="${SECTDD_GPU:-6}" SECTDD_PORT=18083 \
      SECTDD_MAX_MODEL_LEN=16384 scripts/serve_qwen36.sh 27b
    ;;
  secure-dry-run)
    "${sectdd_python}" tools/generate_codeguardplus_secure_candidates.py \
      --provider local --model qwen36-27b --api-base "${sectdd_api}" \
      --local-model-path "${sectdd_model_path}" --local-thinking disabled \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --candidates-per-task 3 --base-seed 20260910 \
      --temperature 0.4 --top-p 0.95 --max-tokens 8192 \
      --num-workers "${sectdd_workers}" --dry-run \
      --output "${sectdd_generation}-dry-run"
    ;;
  secure-generate)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_generation_primary}")
    "${sectdd_python}" tools/generate_codeguardplus_secure_candidates.py \
      --provider local --model qwen36-27b --api-base "${sectdd_api}" \
      --local-model-path "${sectdd_model_path}" --local-thinking disabled \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --candidates-per-task 3 --base-seed 20260910 \
      --temperature 0.4 --top-p 0.95 --max-tokens 8192 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}" \
      --output "${sectdd_generation_primary}"
    ;;
  freeze-generation-recovery)
    "${sectdd_python}" tools/freeze_codeguardplus_reserve_generation_recovery_v1.py
    ;;
  secure-fallback)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_generation_fallback}")
    "${sectdd_python}" tools/generate_codeguardplus_secure_candidates.py \
      --provider local --model qwen36-27b --api-base "${sectdd_api}" \
      --local-model-path "${sectdd_model_path}" --local-thinking disabled \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --task cwe-078/6-py --candidates-per-task 3 \
      --candidate-index 2 --base-seed 20360910 --temperature 0.4 --top-p 0.95 \
      --max-tokens 8192 --num-workers 1 "${sectdd_resume[@]}" \
      --output "${sectdd_generation_fallback}"
    ;;
  secure-merge)
    "${sectdd_python}" tools/merge_codeguardplus_candidate_runs.py \
      --primary "${sectdd_generation_primary}" \
      --fallback "${sectdd_generation_fallback}" --output "${sectdd_generation}"
    ;;
  safe-screen)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_safe_screen}")
    "${sectdd_python}" tools/run_codeguardplus_qualification.py \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --generation-run "${sectdd_generation}" \
      --output "${sectdd_safe_screen}" --repeats 1 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}"
    ;;
  safe-select)
    "${sectdd_python}" tools/select_codeguardplus_safe_references.py \
      --plan "${sectdd_plan}" --selection-state reserve \
      --selection-id codeguardplus-reserve-safe-selection-v1 \
      --generation-run "${sectdd_generation}" --evaluation-run "${sectdd_safe_screen}" \
      --output "${sectdd_safe_selection}" \
      --report docs/codeguardplus-reserve-safe-selection-v1.md
    ;;
  safe-repeat)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_safe_repeats}")
    "${sectdd_python}" tools/run_codeguardplus_qualification.py \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --safe-selection "${sectdd_safe_selection}" \
      --output "${sectdd_safe_repeats}" --repeats 3 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}"
    ;;
  safe-freeze)
    "${sectdd_python}" tools/freeze_codeguardplus_safe_references.py \
      --selection "${sectdd_safe_selection}" --evaluation-run "${sectdd_safe_repeats}" \
      --selection-id codeguardplus-reserve-stable-safe-v1 \
      --output "${sectdd_stable_safe}" \
      --report docs/codeguardplus-reserve-stable-safe-v1.md
    ;;
  mutant-generate)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_mutants}")
    "${sectdd_python}" tools/generate_codeguardplus_mutants.py \
      --provider local --model qwen36-27b --api-base "${sectdd_api}" \
      --local-model-path "${sectdd_model_path}" --local-thinking disabled \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --safe-selection "${sectdd_stable_safe}" --mutants-per-task 3 \
      --base-seed 20260920 --temperature 0.4 --top-p 0.95 --max-tokens 8192 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}" \
      --output "${sectdd_mutants}"
    ;;
  mutant-screen)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_mutant_screen}")
    "${sectdd_python}" tools/run_codeguardplus_qualification.py \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --mutant-run "${sectdd_mutants}" \
      --output "${sectdd_mutant_screen}" --repeats 1 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}"
    ;;
  mutant-select)
    "${sectdd_python}" tools/select_codeguardplus_vulnerability_mutants.py \
      --plan "${sectdd_plan}" --safe-selection "${sectdd_stable_safe}" \
      --mutant-run "${sectdd_mutants}" --evaluation-run "${sectdd_mutant_screen}" \
      --selection-id codeguardplus-reserve-mutant-selection-v1 \
      --output "${sectdd_mutant_selection}" \
      --report docs/codeguardplus-reserve-mutant-selection-v1.md
    ;;
  mutant-repeat)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_mutant_repeats}")
    "${sectdd_python}" tools/run_codeguardplus_qualification.py \
      --plan "${sectdd_plan}" --benchmark-manifest "${sectdd_benchmark}" \
      --selection-state reserve --mutant-selection "${sectdd_mutant_selection}" \
      --output "${sectdd_mutant_repeats}" --repeats 3 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}"
    ;;
  pair-freeze)
    "${sectdd_python}" tools/freeze_codeguardplus_oracle_pairs.py \
      --plan "${sectdd_plan}" --safe-selection "${sectdd_stable_safe}" \
      --mutant-selection "${sectdd_mutant_selection}" \
      --mutant-evaluation-run "${sectdd_mutant_repeats}" \
      --freeze-id codeguardplus-reserve-oracle-pairs-v1 \
      --output "${sectdd_pairs}" --report docs/codeguardplus-reserve-oracle-pairs-v1.md
    ;;
  partition-generate)
    mapfile -t sectdd_resume < <(sectdd_resume_flag "${sectdd_partition_generation}")
    "${sectdd_python}" tools/generate_codeguardplus_partitioned_oracles.py \
      --provider local --model qwen36-27b --api-base "${sectdd_api}" \
      --local-model-path "${sectdd_model_path}" --local-thinking disabled \
      --pairs "${sectdd_pairs}" --benchmark "${sectdd_benchmark}" \
      --attempts 3 --base-seed 20260930 --temperature 0.35 --max-tokens 12288 \
      --num-workers "${sectdd_workers}" "${sectdd_resume[@]}" \
      --output "${sectdd_partition_generation}"
    ;;
  partition-qualify)
    "${sectdd_python}" tools/qualify_codeguardplus_partitioned_oracles.py \
      --generation-run "${sectdd_partition_generation}" --pairs "${sectdd_pairs}" \
      --output "${sectdd_partition_qualification}" --oracle-root "${sectdd_oracle_root}" \
      --visible-projection configs/oracles/codeguardplus_reserve_partitioned_v1_visible.json \
      --hidden-projection configs/oracles/codeguardplus_reserve_partitioned_v1_hidden.json \
      --freeze "${sectdd_partition_freeze}" \
      --report docs/codeguardplus-reserve-partitioned-v1.md \
      --repeats 3 --num-workers "${sectdd_workers}"
    ;;
  semantic-prepare)
    "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
      --task-file "${sectdd_partition_freeze}" --benchmark "${sectdd_benchmark}" \
      --oracle-manifest "${sectdd_oracle_root}/manifest.json" \
      --output "${sectdd_root_out}/semantic-review" --prepare-only \
      --confirm-machine-review
    ;;
  semantic-review)
    exec scripts/run_codeguardplus_reserve_semantic_machine_review_v1.sh
    ;;
  semantic-repair-qualify)
    "${sectdd_python}" tools/qualify_codeguardplus_reserve_partitioned_v2.py
    ;;
  semantic-repair-prepare)
    "${sectdd_python}" tools/review_codeguardplus_partitioned_semantics.py \
      --task-file benchmarks/manifests/codeguardplus-reserve-partitioned-v2-freeze.json \
      --benchmark "${sectdd_benchmark}" \
      --oracle-manifest oracles/codeguardplus_reserve_partitioned_v2/manifest.json \
      --output "${sectdd_root_out}/semantic-review-v2" \
      --report-id codeguardplus-reserve-partitioned-semantic-machine-panel-v2 \
      --prepare-only --confirm-machine-review
    ;;
  semantic-repair-review)
    exec scripts/run_codeguardplus_reserve_semantic_machine_review_v1.sh v2
    ;;
  semantic-repair-freeze)
    "${sectdd_python}" tools/freeze_codeguardplus_reserve_semantic_machine_v2.py
    ;;
  g8-preflight)
    exec scripts/run_codeguardplus_reserve_g8_preflight_v2.sh
    ;;
  breadth-wave3)
    exec scripts/run_codeguardplus_reserve_breadth_wave3.sh
    ;;
  breadth-wave3-semantic-review)
    exec scripts/run_codeguardplus_reserve_breadth_wave3_semantic_review.sh
    ;;
  breadth-wave3-dispute-review)
    exec scripts/run_codeguardplus_reserve_breadth_wave3_dispute_review.sh
    ;;
  breadth-wave3-semantic-freeze)
    exec scripts/run_codeguardplus_reserve_breadth_wave3_semantic_freeze.sh
    ;;
  breadth-wave3-g8-preflight)
    exec scripts/run_codeguardplus_reserve_breadth_wave3_g8_preflight_v1.sh
    ;;
  breadth-wave4)
    exec scripts/run_codeguardplus_reserve_breadth_wave4.sh
    ;;
  breadth-wave4-semantic-review)
    exec scripts/run_codeguardplus_reserve_breadth_wave4_semantic_review.sh
    ;;
  breadth-wave4-dispute-review)
    exec scripts/run_codeguardplus_reserve_breadth_wave4_dispute_review.sh
    ;;
  breadth-wave4-semantic-freeze)
    exec scripts/run_codeguardplus_reserve_breadth_wave4_semantic_freeze.sh
    ;;
  breadth-wave4-g8-preflight)
    exec scripts/run_codeguardplus_reserve_breadth_wave4_g8_preflight_v1.sh
    ;;
  final-g7-prepare)
    exec scripts/run_codeguardplus_final_g7_v1.sh prepare
    ;;
  final-g7-validate)
    exec scripts/run_codeguardplus_final_g7_v1.sh validate
    ;;
  final-g7-status)
    exec scripts/run_codeguardplus_final_g7_v1.sh status
    ;;
  technical-confirmatory-build)
    exec "${sectdd_python}" tools/build_codeguardplus_technical_confirmatory_v1.py
    ;;
  technical-confirmatory)
    exec scripts/run_codeguardplus_technical_confirmatory_v1.sh
    ;;
  status)
    "${sectdd_python}" tools/codeguardplus_reserve_expansion_status.py
    ;;
  *)
    echo "Unknown action: ${sectdd_action}" >&2
    echo "Actions: build serve secure-dry-run secure-generate freeze-generation-recovery secure-fallback secure-merge safe-screen safe-select safe-repeat safe-freeze mutant-generate mutant-screen mutant-select mutant-repeat pair-freeze partition-generate partition-qualify semantic-prepare semantic-review semantic-repair-qualify semantic-repair-prepare semantic-repair-review semantic-repair-freeze g8-preflight breadth-wave3 breadth-wave3-semantic-review breadth-wave3-dispute-review breadth-wave3-semantic-freeze breadth-wave3-g8-preflight breadth-wave4 breadth-wave4-semantic-review breadth-wave4-dispute-review breadth-wave4-semantic-freeze breadth-wave4-g8-preflight final-g7-prepare final-g7-validate final-g7-status technical-confirmatory-build technical-confirmatory status" >&2
    exit 2
    ;;
esac
