# SecTDD

Reproduction repository for **Security Tests Guided Code Generation: An Empirical Study**.

The study examines how functional and security tests guide code generation and revision, how both properties change during repair, and how visible-test coverage affects transfer to hidden tests.

## Reproduce recorded results

The self-contained [replication package](replication-package/README.md) includes archived trajectories, evaluation code, partitioned tests, experiment settings, analysis scripts, and supporting results. Python 3.11+ is required.

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

Recorded-result analysis uses the archived responses and execution outcomes and requires no GPU, model download, API key, or execution of generated code. Generation and evaluation have separate model, dependency, and sandbox requirements described in the [reproduction guide](replication-package/docs/REPRODUCIBILITY.md).

## Evidence and metrics

The package contains 8,625 unique trajectory records across seven evidence groups. The [data dictionary](replication-package/docs/DATA_DICTIONARY.md) and indexes identify shared initial candidates and reused observations; trajectory counts are not counts of independent statistical samples.

| Metric | Definition |
| --- | --- |
| Pass@1 | All hidden functional tests pass |
| Secure@1 | All hidden security tests pass |
| Secure-Pass@1 | Both sets of hidden tests pass |

Each trajectory contributes one final candidate. Security is evaluated through dynamic tests. The primary metric is Secure-Pass@1; functional regressions are reported separately.

## Repository contents

| Location | Contents |
| --- | --- |
| [Code](replication-package/code/) | Archived generation, evaluation, and analysis implementations |
| [Data](replication-package/data/) | Recorded trajectories and dataset indexes |
| [Analysis scripts](replication-package/scripts/) | Verification and reproduction entry points |
| [Configurations](replication-package/configs/) | Archived experiment settings |
| [Reports](replication-package/artifacts/reports/) | Aggregate, per-task, and case analyses |
| [Supporting results](replication-package/supporting-results/README.md) | Current JSS supplementary PDF and editable sources |

Case interpretations link archived code and execution failures to source-record hashes. Automated checks verify case selection and evidence correspondence. Frozen inputs and evaluation-correction records retain their original provenance under `benchmarks/manifests/` and `revision-provenance/`.

## Licenses

See the [package license terms](replication-package/LICENSE_REVIEW_ONLY.md) and [upstream licenses](replication-package/LICENSES/) before reusing or redistributing code and data.
