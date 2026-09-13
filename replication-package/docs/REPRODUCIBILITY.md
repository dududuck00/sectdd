# Reproducibility guide

## Level 1: integrity, anonymity, and qualification metadata

```bash
python3 scripts/verify_artifact.py
```

This checks manifest membership/hashes, the 3,200 + 2,705 + 240 record grids,
canonical identities, hidden-test isolation, B7 accounting, and the conservative
human-review addendum, then runs the anonymity/credential scan.

## Level 2: reproduce archived metrics

```bash
python3 scripts/reproduce_results.py
python3 scripts/reproduce_b7_results.py
```

The first command recomputes the balanced-primary and 51-task descriptive
results from 5,905 pre-addendum observations. The second joins the 240 B7
records with the archived B0/B2/B3 subset and recomputes the 960-observation
2x2 upfront factorial, including task-cluster bootstrap intervals and
benchmark--model strata. The files are intentionally analyzed separately so
the 720 reused primary records cannot be double-counted.

## Level 3: regenerate model outputs

Full regeneration requires separately obtained Qwen checkpoints, access to the
named DeepSeek-compatible endpoint, Linux/Bubblewrap, benchmark dependencies,
and substantial compute. Generation settings are frozen in
`configs/experiments/`. DeepSeek uses `thinking.type=disabled`; its repetition
identifiers are request slots and are not provider-side deterministic seeds.
Archived responses are the reproducible analysis boundary because providers
may update remote backends.

Do not execute generated candidates without a fresh network-isolated sandbox.

## Invariants

- balanced-primary trajectories: 3,200;
- supporting trajectories: 2,705;
- new B7 trajectories: 240 (SALLM 160; CodeGuard+ 80; 60 per model);
- all unique trajectories: 6,145;
- upfront factorial: 960 = 720 reused primary + 240 new B7;
- primary tasks / all task instances / distinct CWEs: 20 / 51 / 24;
- B3-B0 primary hidden-joint delta: +17.00 percentage points;
- B3-B2 factorial hidden-joint delta: +7.50 points, with a task-cluster
  95% interval that crosses zero.
