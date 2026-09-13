# Trajectory data dictionary

Each line of `data/*-trajectories.jsonl.gz` is a JSON object.

## Identity

| Field | Meaning |
|---|---|
| `task` | Benchmark-local task identifier |
| `model` | Frozen served-model identifier |
| `method` | B0--B7 or M, as defined by the frozen method config |
| `generation_seed` | Local seed or DeepSeek request-slot pairing identifier |
| `_artifact.benchmark` | `cweval`, `sallm`, or `codeguardplus` |
| `_artifact.evidence_phase` | `balanced-primary-20`, `legacy-support-31`, or `post-primary-b7-12` |
| `_artifact.source_record_sha256` | Digest of source JSON before path anonymization |

B7 is the one-call, security-tests-only upfront condition. B0/B2/B7/B3 are
independent generation contexts (requirements only, functional tests only,
security tests only, and both test types). B4/B5/M share B0's serialized initial
response; B6 shares B3's. Prompt-effect and same-candidate repair contrasts
therefore answer different questions.

## Generation and feedback

| Field | Meaning |
|---|---|
| `method_config` | Frozen prompting/feedback policy |
| `rounds` | Ordered prompts, responses, extracted code, visible results, and feedback |
| `rounds[].generation_reused` | Whether a serialized reference response was loaded |
| `stop_reason` | Visible-only termination reason |
| `budget_usage` | Calls, tokens, and visible test executions |

## Outcomes

| Field | Meaning |
|---|---|
| `final_visible` | Final visible case-level result |
| `final_hidden.functional` | Hidden functional counts/fraction/all-pass flag |
| `final_hidden.security` | Hidden security counts/fraction/all-pass flag |
| `final_hidden.joint_pass` | Strict functional-and-security conjunction |
| `final_hidden.safe` | SAFE@1-style partial-functionality score for a secure candidate |
| `hidden_leak_audit` | Evidence hidden material was not used for prompting, feedback, or stopping |

Some legacy records use `functional` and others `functionality` as case markers;
the analysis deliberately accepts both aliases.

## Four-state notation

- `F+S+`: functionally correct and secure;
- `F+S-`: functionally correct but insecure;
- `F-S+`: functionally incorrect but passes the specified security oracle;
- `F-S-`: fails both dimensions.

Security-only success is not deployable success. The main endpoint is `F+S+`.
