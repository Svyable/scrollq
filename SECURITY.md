# Security policy

## Supported version

Security fixes are applied to the current `main` branch. Frozen research
artifacts are retained for reproducibility and should not be assumed to receive
backported fixes.

## Reporting a vulnerability

Please do not publish an exploitable vulnerability, credential, embargoed
submission image, private Challenge correspondence, or other sensitive material
in a public issue.

Use GitHub's private vulnerability-reporting / Security Advisory interface for
this repository when available. If private reporting is unavailable, contact
the maintainer through the repository owner's GitHub profile before posting
technical details publicly.

Treat the following as security-relevant:

- path traversal or package-root escape;
- arbitrary code execution from untrusted manifests, meshes, models, or data;
- credential or private-artifact exposure;
- unsafe archive handling;
- hash/provenance bypasses;
- train/prediction leakage checks that can be bypassed by malformed input;
- a publication path that can expose embargoed Grand Prize material without an
  explicit release action.

Scientific disagreement or a weak metric is normally an ordinary bug, but a
false PASS in a fail-closed provenance/package gate may be security-relevant
because downstream review automation can rely on it.
