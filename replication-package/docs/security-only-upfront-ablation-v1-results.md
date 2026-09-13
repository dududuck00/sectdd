# Security-only upfront ablation v1 results

Post-primary hypothesis-driven 2x2 factorial over the 12 SALLM/CodeGuard+ primary tasks.

## Completeness and trajectory accounting

| Model | SALLM B7 | CodeGuard+ B7 | New B7 total |
|---|---:|---:|---:|
| qwen25-coder-7b | 40 | 20 | 60 |
| qwen25-coder-14b | 40 | 20 | 60 |
| qwen36-27b | 40 | 20 | 60 |
| deepseek-v4-flash | 40 | 20 | 60 |
| **All four models** | **160** | **80** | **240** |

Only B7 contributes new trajectories. The 720 B0/B2/B3 records are reused from the 3,200-trajectory balanced primary experiment: 720 archived + 240 new = 960 records in this factorial analysis. The prior 2,705 trajectories are a disjoint legacy evidence set, so the repository-wide unique count changes from 5,905 to 6,145, not to 3,665.

All confidence intervals resample the 12 `benchmark:task` clusters 10,000 times. Models and five request slots are within-task repetitions, never independent inference units.

## Task-balanced outcomes

| Condition | Functional | Security | Joint | SAFE |
|---|---:|---:|---:|---:|
| Requirement only | 46.67% | 62.08% | 37.50% | 37.50% |
| Functional tests only | 60.00% | 68.75% | 51.67% | 51.67% |
| Security tests only | 57.08% | 76.25% | 47.50% | 47.50% |
| Functional + security tests | 66.25% | 76.67% | 59.17% | 59.17% |

## Planned hidden-joint contrasts

| Contrast | Estimate | 95% task-bootstrap CI | Wins | Losses |
|---|---:|---:|---:|---:|
| functional_only_minus_requirement | 14.17 pp | [6.25, 24.17] | 38 | 4 |
| security_only_minus_requirement | 10.00 pp | [-1.67, 22.92] | 30 | 6 |
| both_minus_requirement | 21.67 pp | [9.17, 35.00] | 59 | 7 |
| security_increment_given_functional | 7.50 pp | [-2.08, 17.50] | 31 | 13 |
| functional_increment_given_security | 11.67 pp | [0.00, 25.00] | 38 | 10 |
| functional_tests_main_effect | 12.92 pp | [3.33, 23.96] | -- | -- |
| security_tests_main_effect | 8.75 pp | [-1.25, 19.58] | -- | -- |
| functional_x_security_interaction | -2.50 pp | [-10.00, 5.00] | -- | -- |

## Direct incremental value of security tests given functional tests (B3 - B2)

| Metric | Estimate | 95% task-cluster bootstrap CI |
|---|---:|---:|
| Functional | 6.25 pp | [0.00, 12.50] |
| Security | 7.92 pp | [-2.50, 21.25] |
| Joint | 7.50 pp | [-2.08, 17.50] |

## Benchmark-model stratified hidden-joint results

| Benchmark | Model | B0 | B2 | B7 | B3 | B7-B0 [95% CI] | B3-B2 [95% CI] |
|---|---|---:|---:|---:|---:|---:|---:|
| sallm | qwen25-coder-7b | 30.00% | 50.00% | 25.00% | 57.50% | -5.00 [-15.00, 0.00] | 7.50 [-5.00, 25.00] |
| sallm | qwen25-coder-14b | 37.50% | 47.50% | 42.50% | 50.00% | 5.00 [-22.50, 30.00] | 2.50 [-22.50, 30.00] |
| sallm | qwen36-27b | 65.00% | 75.00% | 87.50% | 82.50% | 22.50 [0.00, 50.00] | 7.50 [-5.00, 20.00] |
| sallm | deepseek-v4-flash | 37.50% | 52.50% | 67.50% | 70.00% | 30.00 [5.00, 62.50] | 17.50 [-12.50, 50.00] |
| codeguardplus | qwen25-coder-7b | 0.00% | 15.00% | 0.00% | 25.00% | 0.00 [0.00, 0.00] | 10.00 [0.00, 30.00] |
| codeguardplus | qwen25-coder-14b | 25.00% | 35.00% | 25.00% | 45.00% | 0.00 [0.00, 0.00] | 10.00 [0.00, 30.00] |
| codeguardplus | qwen36-27b | 35.00% | 50.00% | 50.00% | 50.00% | 15.00 [0.00, 45.00] | 0.00 [0.00, 0.00] |
| codeguardplus | deepseek-v4-flash | 50.00% | 70.00% | 50.00% | 70.00% | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

Stratified intervals contain only eight SALLM or four CodeGuard+ task clusters and are therefore diagnostic. They are not multiplicity-adjusted, and pooled task-cluster contrasts remain the inferential results. B3-B2 has no negative joint point estimate across the eight strata (six positive, two zero). B7-B0 reverses for SALLM/qwen25-coder-7b on joint success (-5.00 pp); its security component also reverses for SALLM qwen25-coder-7b and 14b (-2.50 pp each), so the effect remains model- and benchmark-dependent.

This hypothesis-driven ablation was specified after inspection of the original primary results but before any B7 response. It strengthens RQ1 mechanism decomposition and is reported as a post-primary addendum.
