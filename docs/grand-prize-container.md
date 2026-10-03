# Grand Prize reviewer container

ScrolIQ ships a reproducible, non-root container for the machine-checkable
Grand Prize evidence layer: ZPA source validation, provenance, submission-image
proofs, legibility auditing, and deterministic reviewer packaging.

This image is the concrete artifact behind the provenance manifest's
`code.docker_image` field. The value used in a submission must be the
immutable **registry digest**, not `:main` and not the commit tag.

## What the image contains

The image installs the complete ScrolIQ console-script surface plus the exact
pinned `zarr-pyramid-audit` companion revision from `pyproject.toml`.
Representative reviewer commands include:

```text
zpa-gate
scroliq-provenance
scroliq-submission-image
scroliq-legibility
scroliq-package
```

The runtime is intentionally non-root (UID/GID 10001) and has no build
toolchain or Git client.

The image **does not bundle the Volume Cartographer / VC3D GUI**. It validates,
renders submission evidence around, and packages outputs from the VC3D-facing
workflow. Seamless VC3D operation must still be documented in the
`VC3D_WORKFLOW.md` material required by `scroliq-package`; this container
does not turn that integration requirement into a claim it cannot prove.

## Reproducibility contract

The Dockerfile pins four layers of the environment:

1. Python is `3.12.15-slim-bookworm` pinned by the Docker Official Image
   multi-platform SHA-256 index digest.
2. ScrolIQ's ZPA dependency is pinned by immutable Git commit in
   `pyproject.toml`.
3. Every PyPI runtime dependency is exact-version constrained in
   `constraints-container.txt`, frozen from the green Python 3.12 CI
   environment.
4. Build tooling uses fixed `setuptools` and `wheel` versions and receives
   `SOURCE_DATE_EPOCH` from the source commit timestamp.

Normal CI builds the image after the Python test matrix passes and smoke-tests
the prize-facing ScrolIQ/ZPA commands inside it.

## Published image

`.github/workflows/container.yml` publishes to:

```text
ghcr.io/svyable/scrollq
```

for changes to the container, package metadata, pinned dependencies, or source
code. Each build gets a commit tag:

```text
ghcr.io/svyable/scrollq:sha-<40-hex-git-commit>
```

and the moving convenience tag `:main`.

The workflow then resolves the pushed registry manifest and emits the value
reviewers and provenance should use:

```text
ghcr.io/svyable/scrollq@sha256:<registry-manifest-digest>
```

That digest is written to the workflow summary and uploaded as the
`grand-prize-container-digest` artifact. The workflow first pulls that exact
digest while authenticated and smoke-tests it. It then logs out of GHCR,
removes the local image references, and pulls the same immutable digest again
**anonymously**. The publish workflow does not pass unless a reviewer without
repository/package credentials can fetch and run the image.

If the anonymous-access step fails after a first publication, make the
`svyable/scrollq` container package public in GitHub Packages and rerun the
workflow. Do not copy the digest into a prize manifest until this anonymous
pull gate is green.

## Reviewer use

Pull the immutable digest recorded in the submission manifest:

```bash
IMAGE='ghcr.io/svyable/scrollq@sha256:<digest>'
docker pull "$IMAGE"
```

Run provenance against an unpacked submission directory:

```bash
docker run --rm \
  -v "$PWD/submission:/work" \
  "$IMAGE" \
  scroliq-provenance \
    --manifest /work/provenance.json \
    --root-dir /work \
    --out /work/provenance.validation.json
```

Verify the frozen reviewer ZIP without the staging directory:

```bash
docker run --rm \
  -v "$PWD:/work" \
  "$IMAGE" \
  scroliq-package verify /work/PHerc0813-grand-prize.zip
```

The package builder already requires its documented Docker reproduction command
to contain the exact digest-pinned `code.docker_image`; a tag such as
`:latest` or `:main` is not sufficient.

## System requirements

The published image targets Linux containers and is continuously built and
tested on GitHub's `ubuntu-latest` amd64 runner. A reviewer needs a Docker-
compatible OCI runtime and enough local storage for the submission artifacts
being mounted. Memory, storage, GPU, and network requirements for full CT
processing or VC3D are workload-specific and must be stated in the submitted
`SYSTEM_REQUIREMENTS.md`; the evidence container itself does not manufacture
a one-size-fits-all hardware claim.

Network access is required only for commands that intentionally read public
remote data. Provenance verification and `scroliq-package verify` can operate
against the local frozen artifacts they are given.
