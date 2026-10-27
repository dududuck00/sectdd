# Security, privacy, and ethics

## Untrusted code

The data contains model-generated programs and intentionally vulnerable mutants. Reading and analyzing the JSONL files is safe; executing embedded code is not. Never use `eval`, `exec`, dynamic imports, or subprocess execution on candidate strings outside a sandbox.

The original study used fresh Bubblewrap sandboxes, minimal read-only mounts, disabled network access, and explicit timeouts. Bubblewrap is defense in depth, not equivalent to a hardened virtual machine. A dedicated research host or disposable VM is recommended for any re-execution.

## Hidden tests

Hidden test files are retained to reproduce evaluation. They were not available to model generation, feedback selection, or stopping. Generation reruns must preserve this separation and the recorded visible/hidden partitions.

## External API data transfer

Prompts sent to the remote DeepSeek endpoint contained benchmark task requirements and, depending on method, visible tests or visible failure feedback. Hidden tests were never sent. No personal or production data was used.

## Credentials and identity

Credentials and original host paths are excluded from the curated package. Placeholder paths such as `<ARTIFACT_ROOT>` and `<MODEL_ROOT>` must be configured locally for regeneration. The current JSS supporting document includes the article authors.

## Test validation

The SALLM and CodeGuard+ test suites are checked with secure implementations and corresponding vulnerable implementations. Secure implementations pass functional and security tests; vulnerable implementations preserve functional passes while failing at least one security test. Repeated isolated executions check outcome stability. Frozen test files, task lists, and input bindings remain available for inspecting these checks.

