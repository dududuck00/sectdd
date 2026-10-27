# Artifact inventory and scope

## Archived evidence

The package contains seven compressed trajectory files and two data indexes. There are 8,625 unique trajectory records: 2,705 original, 3,200 balanced, 240 security-only, 1,200 fixed-call, 400 project-level, 480 specification-representation, and 400 security-feedback records.

Records preserve task/model/condition identities, prompts and responses, candidate code, case-level outcomes, budgets, stopping information, shared-candidate metadata, and source-record hashes. The upfront factorial reuses 720 balanced observations and adds 240 security-only observations; those 960 cells are already represented in the archive total.

## Inputs, code, and analyses

Included material covers frozen experiment settings, visible and hidden tests, secure implementations and targeted mutants, input/result freezes, execution and analysis code, dependency records, schemas, aggregate reports, and case evidence. `benchmarks/manifests/test-input-bindings-v1.json` links the balanced-study test files and task membership to their source and exported hashes.

Runtime identities, input freezes, evaluation-correction records, and pre-correction execution sources are retained in `revision-provenance/`. Its export map distinguishes original input hashes from exported bytes. `supporting-results/` contains the current JSS supplementary PDF and editable sources.

## Outside the curated package

Model checkpoints, credentials, virtual environments, local caches, sandbox workspaces, compiler output, submission letters, and editorial working notes are not needed to reproduce the archived analyses. The full paper and submission forms are supplied through the journal submission system.

## Integrity and provenance

`MANIFEST.sha256` covers the files in this published package. A trajectory's `_artifact.source_record_sha256` identifies its original pre-anonymization source record; the package manifest identifies the distributed bytes. These hashes serve different roles. Frozen data, test inputs, configurations, reports, and correction records retain their original content.
