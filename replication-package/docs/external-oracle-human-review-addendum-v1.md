# External-oracle human-review addendum v1

This addendum records the human semantic review performed after the frozen
machine-assisted qualification of the balanced-primary SALLM and CodeGuard+
overlays. The source freezes are not rewritten because their hashes are inputs
to the completed experiment; their `independent_human_review_complete=false`
field describes the earlier machine-freeze state, not the later review stage.

Three software-engineering doctoral students reviewed every one of the 12
external qualification packets retained in the balanced primary experiment.
The packets contained the task contract, secure implementation, targeted
vulnerability mutant, visible and hidden oracle cases and behavior-family
labels, and three-repeat sandbox evidence. Experiment method outcomes were not
part of the packet.

The common rubric asked whether:

1. the executable oracle matched the task contract;
2. the secure implementation preserved the intended behavior;
3. the mutant remained functional while reinstating the declared CWE;
4. the attacks were realistic for that CWE; and
5. visible and hidden mechanisms were materially distinct and did not disclose
   concrete hidden material.

All 12 listed packets remained in the balanced-primary task set after review.
For anonymity and evidentiary precision, the public record does not contain
identity-bearing ballots and does not claim unanimity, reviewer independence,
or inter-rater reliability. The exact scope, task keys, and hashes of the
reviewed machine freezes and projections are recorded in
`benchmarks/manifests/external-oracle-human-review-addendum-v1.json`.
