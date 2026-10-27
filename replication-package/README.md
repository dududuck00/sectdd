# SecTDD replication package

This package accompanies **Security Tests Guided Code Generation: An Empirical Study**. It contains 8,625 unique archived trajectory records and the code, tests, configurations, and reports used to reproduce their analysis.

| Evidence group | Trajectories |
| --- | ---: |
| Original benchmark study | 2,705 |
| Balanced core study | 3,200 |
| Security-only upfront condition | 240 |
| Fixed two-revision comparison | 1,200 |
| Project-level study | 400 |
| Specification representation | 480 |
| Security-feedback comparison | 400 |
| Total | 8,625 |

Shared initial responses and reused observations remain identified in the records. The 960-observation upfront factorial combines 720 existing core-study observations with the 240 security-only observations; it is not added again to the total. `data/index.json` indexes the 6,145-record base and `data/revision-index.json` indexes the later evidence groups. Historical `primary` and `legacy` filenames identify the balanced and original cohorts, respectively.

## Reproduce recorded results

Use Python 3.11+ and the dependencies in `requirements-analysis.txt`. Statistical reproduction uses the recorded NumPy version specified there.

```sh
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

`verify_artifact.py` checks package hashes and membership, the base trajectory grids, hidden-test isolation, reuse accounting, and frozen test-input bindings. The remaining scripts recompute the archived metrics, paired comparisons, uncertainty estimates, opportunity strata, and case-evidence checks. These commands read recorded responses and outcomes without executing candidate programs.

The specification comparison retains matched test bodies and prose with shared fixture/helper context. The feedback studies retain their recorded shared initial candidates, stopping rules, and call budgets. Post-hoc strata, case analyses, and oracle-exclusion sensitivity use the original outcome scores.

## Rerun generation

Execution sources, configurations, project scaffolds, partitioned tests, and dependency records are included. Configure placeholder paths on the new host and install the benchmark-specific dependencies. Sources under `code/` preserve the original relative project layout; place those directories beside `configs/`, `oracles/`, and `third_party/` in a separate rerun checkout.

Original input freezes bind the execution inputs before anonymization. `revision-provenance/export-map.json` distinguishes original hashes from exported bytes, and `benchmarks/manifests/test-input-bindings-v1.json` links the frozen test files and task lists. The original freeze records remain unchanged. A new generation run requires a fresh input freeze after host paths are configured.

Runtime identities and correction records are retained in `revision-provenance/`. The representation study preserves its original responses across the archived sandbox-launch recovery. The security-feedback correction preserves its original responses and pre-correction sources. For hosts requiring the same user-namespace compatibility mode, follow the archived protocol and retain per-candidate Bubblewrap isolation. Model services and remote providers may differ from their archived versions.

## Supporting results

The [current JSS supplementary PDF](supporting-results/supplementary-tables.pdf) contains the original-study tables, controlled comparisons, project-level analyses, and case evidence. Editable CAS sources and the fixed-call vector figure are included. See the [supporting-results guide](supporting-results/README.md) and [reproduction guide](docs/REPRODUCIBILITY.md).
