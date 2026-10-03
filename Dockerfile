# syntax=docker/dockerfile:1
#
# Reproducible ScrolIQ reviewer/evidence image for the 2027 Grand Prize.
# The Python base is pinned to the Docker Official Image multi-platform
# index digest for python:3.12.15-slim-bookworm as observed 2026-10-03.
ARG PYTHON_BASE=python:3.12.15-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3

FROM ${PYTHON_BASE} AS builder

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG SOURCE_DATE_EPOCH=0

ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

COPY constraints-container.txt pyproject.toml README.md LICENSE ./
COPY src ./src

# Keep build tooling deterministic too. --no-build-isolation makes the
# pinned setuptools/wheel pair serve both ScrolIQ and the pinned ZPA source.
RUN python -m pip install \
      "setuptools==80.9.0" \
      "wheel==0.45.1" \
    && python -m pip wheel \
      --no-build-isolation \
      --constraint constraints-container.txt \
      --wheel-dir /wheels \
      .

FROM ${PYTHON_BASE} AS runtime

ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="ScrolIQ" \
      org.opencontainers.image.description="Grand Prize evidence, provenance, validation and deterministic packaging tools for Vesuvius scroll submissions" \
      org.opencontainers.image.source="https://github.com/Svyable/scrollq" \
      org.opencontainers.image.url="https://svyable.github.io/scrollq/" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/scroliq

RUN useradd --uid 10001 --create-home --home-dir /home/scroliq --shell /usr/sbin/nologin scroliq

COPY --from=builder /wheels /wheels
# Install the complete wheelhouse as explicit local artifacts. --no-deps is
# intentional: resolving the ScrolIQ wheel's PEP 508 direct-URL ZPA pin would
# otherwise invoke Git in the runtime stage, defeating the Git-free image.
# The builder already resolved that immutable commit into a wheel; pip check
# then verifies that the installed distributions satisfy the declared graph.
RUN python -m pip install \
      --no-index \
      --no-deps \
      /wheels/*.whl \
    && python -m pip check \
    && rm -rf /wheels

WORKDIR /work
USER 10001:10001

# No ENTRYPOINT: callers can invoke any installed ScrolIQ/ZPA console script
# directly, e.g. "docker run ... scroliq-package verify submission.zip".
CMD ["scroliq-provenance", "--help"]
