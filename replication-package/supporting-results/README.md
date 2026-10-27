# Supporting results and analyses

[Read the current JSS supplementary PDF](supplementary-tables.pdf). This document accompanies **Security Tests Guided Code Generation: An Empirical Study** and the archived replication evidence.

## Contents and evidence

| Analysis | Recorded evidence | Reproduction script |
| --- | --- | --- |
| Original and balanced benchmark results | `../data/index.json`, `../data/legacy-trajectories.jsonl.gz`, `../data/primary-trajectories.jsonl.gz` | `../scripts/reproduce_results.py` |
| Fixed two-revision comparisons and project aggregates | `../artifacts/reports/feedback-mechanism-v1.json`, `../artifacts/reports/seccodebench-external-v1.json` | `../scripts/reproduce_revision_results.py` |
| Project-level task effects | `../artifacts/reports/external-task-analysis-v1.json` | `../scripts/reproduce_external_tasks.py` |
| Specification representation | `../artifacts/reports/representation-v1.json` | `../scripts/reproduce_representation.py` |
| Functional-only versus combined feedback | `../artifacts/reports/security-feedback-v1.json` | `../scripts/reproduce_security_feedback.py` |
| Initial-state opportunity strata | `../artifacts/reports/feedback-opportunity-v1.json` | `../scripts/reproduce_feedback_opportunity.py` |
| Case mechanisms | `../artifacts/reports/feedback-case-ledger.json`, `../artifacts/reports/feedback-mechanism-audit.json` | `../scripts/reproduce_feedback_mechanisms.py` |

Run the analysis commands from the package root with Python 3.11+ and `requirements-analysis.txt`. Case annotations link source-record hashes, code excerpts, and recorded test failures. Automated checks verify case selection and evidence correspondence. The tables retain the archived outcome scores and statistical results.

## Rebuild the document

The document uses Elsevier CAS with `cas-sc.cls`, `cas-common.sty`, and `preamble.tex`. The `generated/` directory contains the included tables and analysis text. `figures/fixed-call-effects.pdf` is the displayed figure; the SVG remains available for editing.

Build outside this curated package so that compiler output does not enter its integrity manifest. Copy this directory to a separate working folder and run:

```sh
mkdir -p build
tectonic --outdir build supplementary-tables.tex
```

The first build may need network access for standard TeX dependencies. The archived PDF is the compiled JSS version supplied with this release.
