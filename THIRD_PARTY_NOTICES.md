# Third-party notices

ScrolIQ is MIT licensed. Third-party software, data, models, standards, and
community artifacts remain under their own licenses and terms.

The dependency versions actually used for a result are part of that result's
reproducibility record. This document records the material upstream projects
used directly by the repository.

## Direct runtime dependencies

- NumPy — https://github.com/numpy/numpy
- Pillow — https://github.com/python-pillow/Pillow
- tifffile — https://github.com/cgohlke/tifffile
- Requests — https://github.com/psf/requests
- Numcodecs — https://github.com/zarr-developers/numcodecs

## Pinned integrity companion

### Svyable/zarr-pyramid-audit

Source: https://github.com/Svyable/zarr-pyramid-audit

The package metadata and CI pin an immutable tested commit. The Svyable
repository in turn descends from James Ryan's MIT-licensed
https://github.com/sgsllc-jr/zarr-pyramid-audit and vendors a documented
MIT-licensed volcomp decoder from
https://github.com/superoptimizer/volume-compressor.

The exact companion Git revision in `pyproject.toml` and
`requirements-ci.txt` is the authoritative version for the current build.

## Vesuvius Challenge ecosystem

ScrolIQ interoperates with and derives formats, eligibility metadata, or public
evidence from:

- ScrollPrize/villa — https://github.com/ScrollPrize/villa
- ScrollPrize/open-data — https://github.com/ScrollPrize/open-data
- VC3D / Volume Cartographer and related Vesuvius tooling
- OME-NGFF / OME-Zarr conventions

Community projects used for independent comparisons or methodology are credited
where their evidence is consumed; examples include TIFXYZ Doctor,
tifxyz-repair, windcheck, spiralcheck, scroll-data-audit, and public
ink-detectability work. Their code and outputs are not relicensed by ScrolIQ.

For authoritative Vesuvius dataset citations and licenses, use:
https://scrollprize.org/data

## Development, packaging, and CI

- pytest — https://github.com/pytest-dev/pytest
- build — https://github.com/pypa/build
- setuptools — https://github.com/pypa/setuptools
- Docker Official Images / Python image maintainers
- actions/checkout — https://github.com/actions/checkout
- actions/setup-python — https://github.com/actions/setup-python
- actions/upload-artifact — https://github.com/actions/upload-artifact

## AI-assisted development

Project documentation credits Muse (AI assistant) for AI-assisted development.
AI assistance does not change authorship, licensing, evidence, or review
requirements: committed work must still be testable, attributable, and
reviewed under the same repository rules.

If code, a model, dataset, or binary is newly redistributed in this repository,
add its exact source revision, license, and redistribution notice here in the
same change.
