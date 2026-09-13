# Supporting results and analyses

[Read the PDF](supplementary-tables.pdf). This document accompanies the replication package; the research paper presents the research questions and core conclusions.

## Contents and evidence

| Analysis | Recorded evidence in the package | Reproduction script |
| --- | --- | --- |
| Fixed two-revision controls and external aggregate results | `../artifacts/reports/feedback-mechanism-v1.json`, `../artifacts/reports/seccodebench-external-v1.json` | `../scripts/reproduce_revision_results.py` |
| External per-task effects | `../artifacts/reports/external-task-analysis-v1.json` | `../scripts/reproduce_external_tasks.py` |
| Matched-information representation | `../artifacts/reports/representation-v1.json` | `../scripts/reproduce_representation.py` |
| Functional-only versus combined feedback | `../artifacts/reports/security-feedback-v1.json` | `../scripts/reproduce_security_feedback.py` |
| Initial-state opportunity strata | `../artifacts/reports/feedback-opportunity-v1.json` | `../scripts/reproduce_feedback_opportunity.py` |
| Case-level mechanism analysis | `../artifacts/reports/feedback-case-ledger.json`, `../artifacts/reports/feedback-mechanism-audit.json` | `../scripts/reproduce_feedback_mechanisms.py` |

Run analysis from the package root using Python 3.11+ and `requirements-analysis.txt`. Follow the root README for the complete reproduction sequence. Recorded-result analysis requires no GPU, model download, API key, or execution of generated code. Rerunning generation has separate model and benchmark requirements.

The metrics are Pass@1 (all hidden functional tests pass), Secure@1 (all hidden security tests pass), and Secure-Pass@1 (both pass). Each trajectory contributes one final candidate, including after revision. F/S candidate states and functional/security feedback conditions are distinct from aggregate rates. Percentages, percentage-point differences, and repair/regression counts have separate units.

The document preserves observed results, including functional regressions. Case annotations are machine-assisted source/log interpretations, not independently completed human semantic validation. Original statistical reports retain their calculations; confidence intervals are omitted from the presentation.

## Rebuild the document

From this directory, run `tectonic supplementary-tables.tex` with Tectonic 0.16.9. The included ACM class is 2.19; the first build may need network access to obtain TeX dependencies. The `generated/` files contain the numeric tables and analysis text; `figures/` includes the fixed-call figure as PDF, editable SVG, and PNG.
