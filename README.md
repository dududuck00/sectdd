# SecTDD

Reproduction repository for **Security Tests as Executable Specifications for LLM Code Generation: Benefits, Trade-offs, and Coverage Limits**.

The study examines how visible functional and security tests affect code generation and revision, including functionality–security trade-offs, feedback controls, matched-information representations, and transfer to project-level tasks.

## Getting started

The self-contained [replication package](replication-package/README.md) includes recorded trajectories, evaluation code, partitioned tests, experiment configurations, analysis scripts, and supporting results.

To reproduce recorded results, use Python 3.11+:

```bash
cd replication-package
python -m pip install -r requirements-analysis.txt
python scripts/verify_artifact.py
python scripts/reproduce_results.py
python scripts/reproduce_b7_results.py
python scripts/reproduce_revision_results.py
python scripts/reproduce_oracle_sensitivity.py
python scripts/reproduce_external_tasks.py --artifact-directory .
python scripts/reproduce_representation.py --artifact-directory .
python scripts/reproduce_security_feedback.py --artifact-directory .
python scripts/reproduce_feedback_opportunity.py --artifact-directory .
python scripts/reproduce_feedback_mechanisms.py --artifact-directory .
```

Recorded-result analysis requires no GPU, model download, API key, or execution of generated code. Rerunning generation requires model access and benchmark-specific dependencies; see the [package instructions](replication-package/README.md#rerun-generation).

## Evidence and metrics

The package contains 8,625 unique trajectory records. Shared initial candidates and reused experimental observations are identified in the data; trajectory counts are not counts of independent statistical samples.

| Metric | Definition |
| --- | --- |
| Pass@1 | All hidden functional tests pass |
| Secure@1 | All hidden security tests pass |
| Secure-Pass@1 | Both sets of hidden tests pass |

Each trajectory contributes one final candidate, including after revision. Security is evaluated through dynamic tests. The primary metric is Secure-Pass@1; functional regressions are reported separately.

## Repository contents

| Location | Contents |
| --- | --- |
| [Code](replication-package/code/) | Generation and evaluation implementations |
| [Data](replication-package/data/) | Portable recorded trajectories and dataset indexes |
| [Analysis scripts](replication-package/scripts/) | Verification and reproduction entry points |
| [Configurations](replication-package/configs/) | Experiment settings |
| [Reports](replication-package/artifacts/reports/) | Recorded aggregate and per-task analyses |
| [Supporting results](replication-package/supporting-results/README.md) | Detailed tables, case analyses, and editable document sources |

Read the [supporting results PDF](replication-package/supporting-results/supplementary-tables.pdf) for complete numeric tables and mechanism analyses. Case annotations are machine-assisted source/log interpretations; independent human semantic validation is not complete.

## Licenses

See the [package license terms](replication-package/LICENSE_REVIEW_ONLY.md) and [upstream licenses](replication-package/LICENSES/) before reusing or redistributing code and data.
