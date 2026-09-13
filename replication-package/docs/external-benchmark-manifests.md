# External benchmark manifests

SALLM and CodeGuard+ are treated as immutable third-party inputs. Their inventory
manifests record the exact Git commit, task/CWE mapping, prompt or reference
files, test entrypoints, declared dependencies, security-oracle declarations,
and file SHA-256 values.

Generate the manifests:

```bash
.venv/bin/pip install -r requirements/external-benchmark-manifests.txt
.venv/bin/python tools/build_external_benchmark_manifests.py
```

Verify that the generated files still match the repositories:

```bash
.venv/bin/python tools/build_external_benchmark_manifests.py --check
.venv/bin/python -m unittest discover \
  -s tests -p 'test_external_benchmark_manifests.py'
```

Outputs:

- `benchmarks/manifests/sallm-v1.json`
- `benchmarks/manifests/codeguardplus-v1.json`
- `benchmarks/manifests/index-v1.json`

The status `inventory_only` is intentional. A task becomes eligible for a
formal experiment only after a later execution audit verifies its vulnerable
and secure references against the declared functional and security oracles.
`candidate_for_oracle_audit` means only that the required inventory is present.

At the currently pinned commits:

- SALLM has 100 tasks. Ninety-six contain both `test_correctness` and
  `test_vulnerability`; four have no test file.
- CodeGuard+ contains 103 tasks (71 Python, 31 C, and one C++). All have
  functional test scripts; 94 declare a CodeQL query and nine do not.

The generator deliberately fails when either third-party checkout is dirty.
This prevents local edits to benchmark data from being silently included in a
formal experiment.
