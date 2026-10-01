from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _companion_requirement(lines: list[str]) -> str:
    matches = [
        line.strip()
        for line in lines
        if line.strip().startswith("zarr-pyramid-audit @ ")
    ]
    assert len(matches) == 1
    return matches[0]


def _git_ref(requirement: str) -> str:
    prefix = (
        "zarr-pyramid-audit @ "
        "git+https://github.com/Svyable/zarr-pyramid-audit.git@"
    )
    assert requirement.startswith(prefix)
    return requirement.removeprefix(prefix)


def test_public_metadata_and_ci_pin_same_immutable_companion_commit():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package_requirement = _companion_requirement(pyproject["project"]["dependencies"])
    ci_requirement = _companion_requirement(
        (ROOT / "requirements-ci.txt").read_text().splitlines()
    )

    package_ref = _git_ref(package_requirement)
    ci_ref = _git_ref(ci_requirement)

    assert FULL_SHA.fullmatch(package_ref)
    assert package_ref == ci_ref
