# Reproducibility guide

## Package and base-evidence verification

```bash
python scripts/verify_artifact.py
```

The verifier checks manifest membership and hashes, 3,200 balanced plus 2,705 original plus 240 security-only trajectories, canonical identities, hidden-test isolation, factorial reuse accounting, and frozen test-input bindings. It also runs the configured path, identity, and credential scan. The test-input check compares task membership with the frozen benchmark lists and validates file-link hashes.

## Reproduce archived analyses

```bash
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

The base verifier covers 6,145 records. The additional analyses cover 1,200 fixed-call, 400 project-level, 480 representation, and 400 security-feedback records, giving 8,625 unique trajectories in the complete release. Shared initial candidates are retained across the paired branches. The core and original cohorts remain separate, and the 960-cell factorial includes 720 reused observations.

`reproduce_results.py` checks the core and original evidence; `reproduce_b7_results.py` recomputes the upfront factorial. The later scripts reproduce their respective comparisons and case checks. Statistical calculations use the recorded dependencies in `requirements-analysis.txt`. Archived-result analysis requires no GPU, model download, API key, or candidate-code execution.

## Regenerate model outputs

Configure a separate rerun checkout from the archived sources, settings, test files, dependency records, and runtime identities. Install the relevant model checkpoints or configure the remote endpoint and preserve Linux/Bubblewrap isolation. Original generation settings remain recorded under `configs/experiments/` and `revision-provenance/`.

Input freezes and the export map distinguish original experiment inputs from sanitized distributed files. Create a new input freeze for any rerun after configuring host paths. Remote model services can change, so regenerated outputs need not equal the archived responses. Execute generated candidates only in a fresh sandbox with the network and filesystem restrictions specified by the archived evaluator.
