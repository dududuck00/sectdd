# Unified paper evidence v4

The 20-task balanced expansion is the primary confirmatory matrix; the earlier 31-task heterogeneous grid is retained as supporting coverage evidence.

## Scope

| Evidence phase | Tasks | Trajectories | Role |
|---|---:|---:|---|
| Legacy heterogeneous evidence | 31 | 2,705 | Supporting/sensitivity |
| Balanced expansion | 20 | 3,200 | Primary confirmatory |
| Combined coverage | 51 | 5,905 | Descriptive only |

Task instances by benchmark: CWEval=17, CodeGuard+=15, SALLM=19.

## Combined paired outcome audit

| Comparison | Task clusters | Pairs | Joint delta | 95% task-bootstrap CI | Wins | Losses |
|---|---:|---:|---:|---:|---:|---:|
| B3 - B0 | 51 | 865 | 16.73% | [9.93%, 23.95%] | 183 | 30 |
| B4 - B0 | 51 | 865 | 15.52% | [8.50%, 23.33%] | 142 | 3 |
| M - B0 | 51 | 865 | 14.77% | [8.24%, 22.58%] | 132 | 0 |
| B6 - B3 | 42 | 730 | 6.07% | [2.50%, 10.24%] | 50 | 0 |
| M - B4 | 51 | 865 | -0.75% | [-2.84%, 1.05%] | 14 | 21 |

The combined rows are robustness summaries over an unbalanced historical grid. They must not replace the balanced 20-task estimates for model or method ranking.

## Interpretation boundary

The balanced 20-task, four-model, eight-method matrix is the primary confirmatory evidence. The combined 51-task/5,905-trajectory view is unbalanced and mixes legacy machine-qualified evidence, so it is used only for coverage and robustness; task is the inference unit.
