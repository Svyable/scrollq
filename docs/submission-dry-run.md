# End-to-end Grand Prize submission dry run

`scroliq-submission-dry-run` exercises the **production** Grand Prize package
contract without leaving a reviewer ZIP behind. It exists to catch packaging,
traceability and reproducibility failures before a qualifying result depends on
them.

The command does not maintain a second definition of submission readiness. It
calls `scroliq-package`'s production builder twice in separate temporary
archives and then calls the production self-contained verifier on both.

## Run it

```bash
scroliq-submission-dry-run \
  --manifest submission/provenance.json \
  --root-dir submission \
  --methodology METHODOLOGY.md \
  --system-requirements SYSTEM_REQUIREMENTS.md \
  --human-input-log human-input.json \
  --vc3d-workflow VC3D_WORKFLOW.md \
  --false-positive-mitigation FALSE_POSITIVES.md \
  --legibility-ledger legibility.json \
  --docker-run-command 'docker run --rm ghcr.io/OWNER/PIPELINE@sha256:<digest> ...' \
  --out submission-dry-run.json
```

The output receipt is create-only. A passing run requires all of the following:

1. the first production package build succeeds;
2. the first archive passes `scroliq-package verify`;
3. a second isolated production package build succeeds from the same staging
   tree;
4. the second archive also passes the verifier;
5. both archive SHA-256 digests are identical; and
6. both builds agree on the provenance-manifest hash, canonical provenance
   graph hash and file count.

The temporary archives and their SHA sidecars are deleted automatically when
the run ends. Only the JSON receipt requested with `--out` remains.

## Why build twice?

The final package format promises deterministic bytes. A single successful
build proves that the staging tree is acceptable today; two isolated builds
with the same archive digest also exercise the deterministic-archive claim on
the exact candidate submission tree.

This is deliberately stricter than merely calling the verifier on one ZIP.

## Failure semantics

A failed package build or verifier is preserved in the receipt with a
`failure_stage` such as `build-1`, `verify-1`, or
`deterministic-rebuild`. The command exits non-zero but still writes the
receipt, so a failed dry run is evidence rather than an invitation to reconstruct
what happened later.

The underlying package builder remains authoritative. Fix the failing
production check; do not weaken the dry-run wrapper.

## Scope

PASS means the current staging tree survives the machine-checkable reviewer
contract twice and produces byte-identical verified packages. It does **not**
prove that the surface is physically correct, that apparent ink is biological
ink, that papyrological readings are correct, or that a submission will win the
Grand Prize.

For an actual submission archive, run `scroliq-package build` after the dry
run and preserve the final archive plus its SHA-256 sidecar.
