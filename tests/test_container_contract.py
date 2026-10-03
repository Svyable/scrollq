from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _constraint_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (ROOT / "constraints-container.txt").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"container constraint is not exact: {line}"
        name, version = line.split("==", 1)
        pins[name.lower().replace("_", "-")] = version
    return pins


def _requirement_name(requirement: str) -> str:
    head = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0]
    return head.strip().lower().replace("_", "-")


def test_container_constraints_pin_every_pypi_runtime_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pins = _constraint_pins()

    for requirement in pyproject["project"]["dependencies"]:
        if " @ " in requirement:
            # zarr-pyramid-audit is pinned by immutable Git commit in pyproject
            # and separately guarded by tests/test_packaging_pins.py.
            continue
        name = _requirement_name(requirement)
        assert name in pins, f"missing exact container pin for {requirement!r}"
        assert pins[name], f"empty version pin for {requirement!r}"


def test_dockerfile_pins_base_and_runs_non_root():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert (
        "python:3.12.15-slim-bookworm@sha256:"
        "54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3"
    ) in dockerfile
    assert "setuptools==80.9.0" in dockerfile
    assert "wheel==0.45.1" in dockerfile
    assert "--constraint constraints-container.txt" in dockerfile
    assert "--no-index" in dockerfile
    assert "--no-deps" in dockerfile
    assert "/wheels/*.whl" in dockerfile
    assert "SOURCE_DATE_EPOCH" in dockerfile
    assert 'org.opencontainers.image.revision="${VCS_REF}"' in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_ci_builds_and_smoke_tests_reviewer_container():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "name: reviewer container" in workflow
    assert "docker build" in workflow
    assert 'SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"' in workflow
    assert '--build-arg SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH"' in workflow
    assert 'test "$(docker run --rm "$IMAGE" id -u)" = "10001"' in workflow
    for command in (
        "scroliq-provenance --help",
        "scroliq-package --help",
        "scroliq-submission-image --help",
        "scroliq-legibility --help",
        "zpa-gate --help",
    ):
        assert command in workflow


def test_publish_workflow_uses_commit_tag_and_emits_immutable_digest():
    workflow = (
        ROOT / ".github" / "workflows" / "container.yml"
    ).read_text()

    assert "packages: write" in workflow
    assert "      - README.md" in workflow
    assert "      - LICENSE" in workflow
    assert 'SHA_TAG="${IMAGE}:sha-${GITHUB_SHA}"' in workflow
    assert 'docker push "$SHA_TAG"' in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert 'PINNED="${IMAGE}@${DIGEST}"' in workflow
    assert "grand-prize-container-digest" in workflow
    assert "Smoke-test pushed digest" in workflow
