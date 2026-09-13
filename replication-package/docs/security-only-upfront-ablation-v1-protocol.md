# Security-only upfront ablation v1

## Motivation and evidentiary role

The balanced primary matrix already contains requirement-only (B0), visible
functional-tests-only (B2), and all-visible-tests-upfront (B3), but no condition
that exposes only visible security tests. B1 is a natural-language security
reminder and is not a substitute for executable security tests.

This post-primary, hypothesis-driven addendum fills the missing cell with B7.
The design is frozen before observing any B7 model response. It is not described
as part of the original preregistered primary matrix.

| Functional tests upfront | Security tests upfront | Condition |
|---|---|---|
| No | No | B0 (archived primary result) |
| Yes | No | B2 (archived primary result) |
| No | Yes | B7 (new generation) |
| Yes | Yes | B3 (archived primary result) |

## Frozen scope

- Benchmarks: SALLM and CodeGuard+.
- Tasks: all 8 SALLM and all 4 CodeGuard+ tasks from the balanced primary grid.
- Models: Qwen2.5-Coder-7B, Qwen2.5-Coder-14B, Qwen3.6-27B, and DeepSeek V4 Flash.
- Repetitions/request slots: the same five identifiers used in the primary grid.
- New trajectories/model calls: 240.
- Complete four-cell factorial analysis: 960 trajectories, including 720
  already-frozen B0/B2/B3 trajectories.
- B7 is one-shot, temperature 0.2, with the same completion and total budget as
  B0/B2/B3. It receives the natural-language contract and visible security test
  source, but no visible functional tests and no execution feedback.
- Hidden tests remain isolated and execute once after generation.

## Outcomes and contrasts

The primary outcome is hidden joint functional-and-security success. Secondary
outcomes are hidden functionality, hidden security, SAFE@1, and the four F/S
states. Task-cluster bootstrap intervals use 10,000 resamples.

Planned contrasts are B2-B0, B7-B0, B3-B0, B3-B2, and B3-B7. The factorial
analysis additionally reports the average functional-test main effect, average
security-test main effect, and interaction `(B3 - B2 - B7 + B0)`.

## Interpretation

The ablation can distinguish whether the benefit of all visible tests comes
from functional tests, security tests, or their combination. It cannot establish
that visible tests cover unseen attacks, and it remains a post-primary analysis
motivated after the original results were available.

## Execution

Freeze/audit the inputs and inspect the empty run grid:

```bash
bash scripts/run_security_only_upfront_ablation_v1.sh build
bash scripts/run_security_only_upfront_ablation_v1.sh status
```

Run one local model on both benchmarks with one model-server load:

```bash
SECTDD_GPU=4 SECTDD_PORT=19780 SECTDD_MAX_WORKERS=3 \
  bash scripts/run_security_only_upfront_ablation_v1.sh both qwen25-coder-7b
```

When the relocated Qwen2.5 checkpoints and GPUs 6/7 are available, run both
models concurrently with the audited one-click driver:

```bash
bash scripts/run_security_only_upfront_local_gpus67_v1.sh
```

The driver resolves the actual paths
`<MODEL_ROOT>/Qwen/Qwen2.5-Coder-{7B,14B}-Instruct`, validates their
identity hashes against the balanced-primary manifests, assigns 7B to GPU 6
and 14B to GPU 7, uses ports 19780/19781, and resumes completed shards. The
path relocation is recorded without changing methods, tasks, seeds, budgets,
or oracle inputs.

Use distinct GPUs and ports when running local models concurrently. For the
remote model, export `DEEPSEEK_API_KEY`, explicitly authorize paid requests,
then run:

```bash
export SECTDD_CONFIRM_PAID_API=1
SECTDD_MAX_WORKERS=3 \
  bash scripts/run_security_only_upfront_ablation_v1.sh both deepseek-v4-flash
```

After all eight benchmark/model runs are complete:

```bash
bash scripts/run_security_only_upfront_ablation_v1.sh status
bash scripts/run_security_only_upfront_ablation_v1.sh analyze
```
