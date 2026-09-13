# Artifact inventory and scope

## Included

### Complete structured evidence

The three compressed JSONL files contain one final trajectory record per
experimental cell. Records preserve identities, prompts and responses,
candidate code, visible and hidden case-level outcomes, budgets, stopping,
shared-candidate metadata, hidden-isolation audits, and a SHA-256 digest of the
pre-anonymization source JSON.

- balanced primary: 3,200 records over 20 tasks;
- disjoint supporting grids: 2,705 records over 31 tasks;
- post-primary security-only-upfront condition B7: 240 records over 12 primary
  tasks.

Thus the archive contains 6,145 unique trajectories. The 960-observation
upfront factorial reuses 720 B0/B2/B3 primary records and adds 240 B7 records;
960 must not be added again to the archive total.

### Experiment inputs, implementation, and review evidence

The package includes frozen primary and B7 configs, visible/hidden oracle
projections, secure subjects and targeted mutants, result/input freezes,
analysis and execution code, dependency locks, schemas, paper-facing aggregate
reports and tables, and the human-review addendum. The addendum records that
three software-engineering doctoral students reviewed every retained external
qualification packet using a common semantic rubric. It records scope and
criteria, not identity-bearing ballots or undocumented agreement statistics.

## Intentionally excluded

| Excluded material | Reason |
|---|---|
| `.git` history | It can expose identities, emails, remotes, and chronology. |
| Model checkpoints and API credentials | Large or secret; unnecessary for archived-response analysis. |
| Virtual environments and third-party repository copies | Machine-specific or redundant with locks and provenance. |
| Raw server logs, shard workspaces, and exploded sandboxes | Redundant and can expose local paths. |
| Failed/quarantined runs and development notes | Not used by the reported analysis. |
| Manuscript PDF/LaTeX and draft protocols | Submitted separately and outside the artifact evidence boundary. |

The exclusion of redundant runtime files does not remove any of the 6,145
analyzed observations.

## Trust boundary

`MANIFEST.sha256` verifies packaged files. Each trajectory's
`_artifact.source_record_sha256` identifies its confidential pre-anonymization
source record. Sanitization changes packaged bytes, so the two hashes serve
different purposes.
