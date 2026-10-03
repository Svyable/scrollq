# Submission embargo and publication boundary

A qualifying unread-scroll discovery is not treated like an ordinary public
research artifact. Generic code, public datasets, checkpoints, experiment
tracking, negative controls, and reproducibility infrastructure can remain
public as required. Reviewer-facing qualifying text, final column renders,
deciphered content, and the assembled Grand Prize submission remain private
until the Challenge has authorized public release.

## Repository rule

Do **not** place embargoed submission material in:

- `docs/` (GitHub Pages source),
- committed `artifacts/`,
- issue or pull-request attachments,
- public model/dataset release pages,
- README screenshots,
- workflow artifacts from public runs.

Local embargoed work belongs under `submission-private/` or
`private-submission/`; both are git-ignored. The final deterministic package
may be copied out of those locations for direct submission, but it should not
be committed merely to prove that the packager works.

## Public / private split

Public and continuously testable:

- source code and schemas;
- synthetic fixtures;
- generic evaluation protocols;
- public training datasets and checkpoints required by the prize rules;
- public experiment-tracking runs;
- held-out validation on already-public ground truth;
- negative-control methodology;
- Docker/reproduction machinery;
- non-discovery-specific benchmark artifacts.

Embargoed until release is authorized:

- final unread-scroll column renders that expose newly recovered text;
- the full-scroll banner containing that text;
- decipherments/transcriptions derived from the qualifying result;
- reviewer packages that contain those images or text;
- private correspondence with the Challenge about the submission.

## Release discipline

The release event should be explicit and auditable. Before making embargoed
material public:

1. record the Challenge authorization / announcement reference;
2. freeze the submitted package SHA-256;
3. copy only the intended release artifacts into a new dated public directory;
4. verify that model/data licenses and third-party notices travel with it;
5. preserve the original private package unchanged.

This document is an operational safeguard, not a substitute for the official
competition rules.
