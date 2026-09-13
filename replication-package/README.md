# SecTDD replication package

This package accompanies the paper “Security Tests as Executable Specifications for LLM Code Generation: Benefits, Trade-offs, and Coverage Limits.” It contains 8,625 unique trajectory records: 2,705 original, 3,200 balanced, 240 security-only, 1,200 fixed-call feedback, 400 external-project, 480 matched-information, and 400 security-feedback ablation trajectories. Shared initials and reused observations are identified explicitly; trajectory records are not independent statistical samples.

## Reproduce recorded results

Python 3.11+ is required; the revision analysis uses NumPy 2.4.6. No API key, model download or generated-code execution is needed.

```sh
python -m pip install -r requirements-analysis.txt
python scripts/verify_artifact.py
python scripts/reproduce_results.py
python scripts/reproduce_b7_results.py
python scripts/reproduce_revision_results.py
python scripts/reproduce_oracle_sensitivity.py
```

The first verification script checks the original 6,145-record base and all manifest files. The revision script separately checks the 1,600 new records, shared initial responses, task means, bootstrap intervals and corrected tests. `data/index.json` describes the base; `data/revision-index.json` describes the additions. The historical name `primary` in base files refers to the later balanced experiment, while `legacy` identifies the selected arXiv v2 evidence.

## Rerun generation

Execution sources, configurations, project scaffolds and partitioned tests are included. Generation requires separately installed checkpoints, local model serving and the benchmark-specific Python dependencies. Paths have been anonymized and must be configured for the new host. The new experiments used bf16 Qwen2.5-Coder 7B/14B, a 32,768-token server context, and the recorded vLLM/runtime versions. Read the two experiment protocols and runtime identity records before executing. Sources under `code/` preserve the original relative project layout; place these directories beside `configs/`, `oracles/` and `third_party/` in a separate rerun checkout. The original input freeze hashes bind the execution inputs before anonymization; `revision-provenance/export-map.json` distinguishes those hashes from exported bytes. New generation must create a fresh freeze after host paths are configured. The fixed-call study uses archived B0 responses; the portable records contain these responses and prompts. A generation rerun is a new experiment, particularly for remotely served historical models.

The external experiment contains ten eligible Python project tasks, not the official full multilingual score. Upstream security test methods may share attack families. Qualification results are machine checks, not new human annotations. The old oracle exclusion sensitivity is post hoc and leaves historical trajectories unchanged. 

## Unified-RQ revision

The external per-task decomposition and matched-information study reproduce with:

```sh
python scripts/reproduce_external_tasks.py --artifact-directory .
python scripts/reproduce_representation.py --artifact-directory .
```

The representation study contains all 480 planned trajectories. Tests compare code and operational prose with identical fixture/helper context, at two content levels. Protocol, translation ledger, prompts, responses and all three planned statistical contrasts are included. Before the security-feedback addition, evidence totals 8,225 trajectory identifiers; shared initials and 80 quarantined infrastructure-error evaluations are not additional observations. The original responses were retained when restoring the existing outer user-namespace launch for sandbox evaluation. See docs/rq-revision-status.md.

To run the local evaluator on hosts requiring the same user-namespace compatibility mode, launch with `env SECTDD_BWRAP_OUTER_USERNS=1 unshare --user --map-root-user -- python tools/run_representation_v1.py --model MODEL --workers 12`. This retains the per-candidate inner Bubblewrap isolation.

The security-feedback ablation adds 400 trajectories (800 new revision calls), sharing 200 archived initial candidates. Compare functional-only with functional-plus-security feedback using `python scripts/reproduce_security_feedback.py --artifact-directory .`. Functional channels and two-call budgets are matched; security information and delivered token counts are not matched. Candidate-load failures are retained as failed outcomes, with NOT RUN feedback; the execution correction and original source files are retained in revision-provenance/security-feedback-v1. No response was resampled for this correction. The complete release has 8,625 unique trajectories.

Post-hoc opportunity strata and all 28 selected mechanism cases reproduce with `python scripts/reproduce_feedback_opportunity.py --artifact-directory .` and `python scripts/reproduce_feedback_mechanisms.py --artifact-directory .`. The original 20-task scores are preserved alongside a whole-task sensitivity for the arithmetic oracle status convention. Annotations are machine-assisted source/log interpretations; automated checks verify selection and evidence linkage, not independent human semantic correctness. No new generations were added.

## Supporting results and analyses

[Read the results document](supporting-results/supplementary-tables.pdf) or consult the [evidence and reproduction guide](supporting-results/README.md). Editable LaTeX sources and the vector figure are included. This document is part of the replication package.
