# Security, privacy, and ethics

## Untrusted code

The data contains model-generated programs and intentionally vulnerable mutants. Reading and analyzing the JSONL files is safe; executing embedded code is not. Never use `eval`, `exec`, dynamic imports, or subprocess execution on candidate strings outside a sandbox.

The original study used fresh Bubblewrap sandboxes, minimal read-only mounts, disabled network access, and explicit timeouts. Bubblewrap is defense in depth, not equivalent to a hardened virtual machine. A dedicated research host or disposable VM is recommended for any re-execution.

## Hidden tests

Hidden oracle files are included so reviewers can inspect and reproduce evaluation. They were not available to model generation, feedback selection, or stopping. To reduce future benchmark contamination, keep this review repository private until the end of double-anonymous review and coordinate any public release with the benchmark maintainers and conference artifact process.

## External API data transfer

Prompts sent to the remote DeepSeek endpoint contained benchmark task requirements and, depending on method, visible tests or visible failure feedback. Hidden tests were never sent. No personal or production data was used.

## Credentials and identity

The package contains no API key, author name, affiliation, development Git history, host name, or original absolute path. Placeholder paths such as `<ARTIFACT_ROOT>` and `<MODEL_ROOT>` are documentary and must be configured locally for full regeneration.

## Oracle qualification limitation

SALLM and CodeGuard+ overlays passed executable safe/mutant gates, repeated isolated execution, behavior-family separation, and blinded multi-model semantic review. They have not yet received independent human expert qualification. The artifact and paper consistently call them machine-semantic-qualified.

