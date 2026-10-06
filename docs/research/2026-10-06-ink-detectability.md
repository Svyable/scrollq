# Synthetic detectability and orientation independence

Decision: integrate the local negative-evidence validity gate; retain orientation
failure and harmful preprocessing as adversarial controls. Dual-energy remains
WATCH pending a target-permitted, held-out physical corroboration experiment.

Primary source reviewed at immutable revision:
[axiosdevs/herculaneum-scroll-tools@63a09d4](https://github.com/axiosdevs/herculaneum-scroll-tools/tree/63a09d4fd8a46ac758ff475a8b6389a2c8152cb7).
Read `ink/detectability.py`, `ink/probe.py`, README and MIT LICENSE from that
checkout. This review verifies what the code/report says; ScrolIQ has not
reproduced its community scroll measurements. Villa integration is linked by
the upstream README as [PR 1924](https://github.com/ScrollPrize/villa/pull/1924);
its merge state was not independently verified.

The upstream probe measures thresholded probability lift over baseline on a
synthetic stroke mask, planted along an estimated sheet face. It explicitly
warns that larger amplitudes can invert recovery, that better synthetic
sensitivity can accompany worse known-ink performance, and retracts its
orientation chooser after a published-segment audit. Those failures motivate
ScrolIQ's fixed reference contrast, external face map, off-mask control, paired
known-positive fixture and prohibition on response-selected polarity.

ScrolIQ intentionally does not copy its brightness-based sheet-centre estimate,
orientation ranking, checkpoints or data. The new API/CLI uses a frozen supplied
face map and one identical inference adapter, preserves all contrast/width rows,
and recomputes negative admissibility from artifact bytes. This is diagnostic
machinery tested with synthetic fixtures, not a new ink detector or a real-scroll
negative finding. See [the contract](../ink-detectability.md).

Physical follow-up: co-render registered energy scans on independently verified
known-ink and negative regions; freeze registration without ink inspection;
measure whether ratio signal localizes letters or only mineral inclusions.
Promote only after held-out spatial agreement and target-specific resource-term
and resolution eligibility review. Do not fuse ratios into learned predictions
or equate high-Z material with ink based on the current community result.
