# Paper expansion full v1 protocol

## Objective

Increase the paper from 31 benchmark task instances to at least 63 without
counting repeated trajectories as independent data and without selecting tasks
because a method happens to improve on them.

The frozen construction pools are:

- CWEval: all 16 remaining tasks from the Python-25 subset;
- SALLM: 32 result-blind construction candidates, target at least 8 retained;
- CodeGuard+: all 20 previously unexposed, eligible construction candidates,
  target at least 8 retained.

The final expansion retains every task that passes the gates. It requires at
least eight retained SALLM tasks, at least eight retained CodeGuard+ tasks, and
at least 32 retained tasks in total; extra valid external tasks can offset an
invalid CWEval oracle without lowering the total expansion target. It does not drop
universal ceilings, universal floors, no-feedback-trigger tasks, or tasks on
which M fails to improve.

## Oracle gates

A task enters the full experiment only after all applicable checks pass:

1. secure reference is F+S+;
2. benchmark vulnerable subject or targeted mutant is F+S-;
3. visible and hidden partitions each contain functionality and security cases;
4. partitions use materially different behavior families;
5. all subject/partition observations repeat in three fresh Bubblewrap runs;
6. two blinded reviewer models unanimously accept the task semantics;
7. the task was never filtered using B0--B6/M or G8 outcomes.

Machine review is recorded separately from independent human review. The paper
must continue to disclose that the latter is incomplete unless it is actually
performed.

## Full experimental grid

Every retained expansion task runs all eight methods:

- B0: requirement only;
- B1: security reminder;
- B2: functionality tests up front;
- B3: all visible tests up front;
- B4: B0 initial candidate plus fixed raw feedback;
- B5: B0 initial candidate plus randomized raw feedback;
- M: B0 initial candidate plus structured security-prioritized feedback;
- B6: B3 initial candidate plus structured security-prioritized feedback.

Every task runs five fresh seeds/request slots on four models:

- Qwen2.5-Coder-7B-Instruct;
- Qwen2.5-Coder-14B-Instruct;
- Qwen3.6-27B;
- DeepSeek V4 Flash.

At the minimum 32-task retained target, this is 5,120 new trajectories. Shared
initial candidates are physically reused: B4/B5/M reuse B0 and B6 reuses B3.
The DeepSeek endpoint receives request slots, not unsupported seed parameters.

## Stage 1: freeze result-blind candidate pools

```bash
bash scripts/run_paper_expansion_construction_v1.sh plan
bash scripts/run_paper_expansion_construction_v1.sh status
```

The freeze is
`benchmarks/manifests/paper-expansion-v1-candidate-freeze.json`.

## Stage 2: construct and qualify oracles

Before paid API stages, set the credential in the current shell and explicitly
authorize paid requests. The scripts never write the credential to disk.

```bash
export DEEPSEEK_API_KEY='your-current-key'
export SECTDD_CONFIRM_PAID_API=1
export SECTDD_WORKERS=2
export SECTDD_REVIEW_GPU_14B=2
export SECTDD_REVIEW_GPU_35B=3
```

Run the complete resumable construction sequence:

```bash
bash scripts/run_paper_expansion_construction_v1.sh all
```

Or run it stage by stage:

```bash
bash scripts/run_paper_expansion_construction_v1.sh cweval-build
bash scripts/run_paper_expansion_construction_v1.sh cweval-review

bash scripts/run_paper_expansion_construction_v1.sh sallm-generate
bash scripts/run_paper_expansion_construction_v1.sh sallm-qualify
bash scripts/run_paper_expansion_construction_v1.sh sallm-partition
bash scripts/run_paper_expansion_construction_v1.sh sallm-review
bash scripts/run_paper_expansion_construction_v1.sh sallm-freeze

bash scripts/run_paper_expansion_construction_v1.sh codeguard-generate
bash scripts/run_paper_expansion_construction_v1.sh codeguard-safe
bash scripts/run_paper_expansion_construction_v1.sh codeguard-mutants
bash scripts/run_paper_expansion_construction_v1.sh codeguard-partition
bash scripts/run_paper_expansion_construction_v1.sh codeguard-review
bash scripts/run_paper_expansion_construction_v1.sh codeguard-freeze

bash scripts/run_paper_expansion_construction_v1.sh full-config
```

All generative and sandbox stages are resumable. Selection/freeze stages refuse
to overwrite contradictory evidence.

If an external benchmark retains fewer than eight tasks, the semantic-freeze
stage stops. Do not lower the threshold or select using method outcomes; retain
the rejection evidence and construct another frozen wave from the unused pool.

## Stage 3: run the complete matrices

The local sweep runs three checkpoints sequentially on one GPU, so it does not
require three free GPUs at once:

```bash
SECTDD_GPU=2 SECTDD_MAX_WORKERS=3 \
  bash scripts/run_paper_expansion_full_v1.sh all-local
```

Run the remote-model sweep:

```bash
SECTDD_CONFIRM_PAID_API=1 SECTDD_MAX_WORKERS=2 \
  bash scripts/run_paper_expansion_full_v1.sh all-deepseek
```

Individual resumable runs are also available:

```bash
SECTDD_GPU=2 bash scripts/run_paper_expansion_full_v1.sh cweval qwen25-coder-14b
SECTDD_GPU=2 bash scripts/run_paper_expansion_full_v1.sh sallm qwen36-27b
SECTDD_CONFIRM_PAID_API=1 bash scripts/run_paper_expansion_full_v1.sh codeguardplus deepseek-v4-flash
```

Check progress at any time:

```bash
bash scripts/run_paper_expansion_full_v1.sh status
```

## Stage 4: validate and analyze

```bash
bash scripts/run_paper_expansion_full_v1.sh analyze
```

The analyzer requires all 12 benchmark/model runs, verifies the full task ×
method × repetition grid, hidden-test isolation, provider identity, and shared
initial candidates, then writes:

- `artifacts/reports/paper-expansion-full-v1.json`;
- `docs/paper-expansion-full-v1.md`;
- `benchmarks/manifests/paper-expansion-full-v1-results-freeze.json`.

Confidence intervals use task-cluster bootstrap resampling. Seeds and request
slots are repeated observations, not independent inferential units.
