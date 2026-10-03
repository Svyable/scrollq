# Credits and acknowledgments

ScrolIQ is built on years of scientific, papyrological, engineering, open-source, and community work. This file is intentionally expansive: if you helped create the Vesuvius Challenge ecosystem, the data, the software, the annotations, the scholarship, or the experiments that make this project possible, thank you.

Third-party projects named here remain under their own licenses. This acknowledgment does not relicense their code, data, models, or documentation.

## ScrolIQ

- **Sven Hardy Benson / Svyable** — project author and maintainer.
- **Muse (AI assistant)** — credited in the project README for AI-assisted development; AI-assisted changes remain subject to the same human review, testing, provenance, and evidence standards as other work.
- **Every contributor, tester, issue reporter, reviewer, and user** who improves the project or catches a claim that is too strong.

## Vesuvius Challenge / Scroll Prize

Roster snapshot checked 2026-10-03 against https://scrollprize.org/. Roles change; the official site is the source of truth.

### Founders and leadership

- Nat Friedman — Instigator, Director & Founding Sponsor
- Daniel Gross — Founding Sponsor
- Brent Seales — Principal Advisor
- Giorgio Angelotti — Project & Tech Team Lead

### Tech Team

- Sean Johnson
- Hendrik Schilling
- Paul Henderson
- Elian Rafael Dal Prá
- Johannes Rudolph

### Papyrology Team

- Federica Nicolardi
- Marzia D'Angelo
- Kilian Fleischer
- Alessia Lavorante
- Michael McOsker
- Maria Chiara Robustelli
- Claudio Vergara
- Rossella Villa

### Annotation Team

- David Josey
- Kendra Brown
- Laura Trojak

### EduceLab partners

- Brent Seales
- Seth Parker
- Christy Chapman
- Mami Hayashida
- James Brusuelas
- Beth Lutin
- Roger Macfarlane

### Advisors and alumni

- JP Posma
- Stephen Parsons
- Youssef Nader
- Ben Kyles
- Julian Schilliger
- Forrest McDonald
- Adrionna Fey
- Cooper Miller
- Eric Thvedt
- Konrad Rosenberg
- Raymond Gasper
- Sarah Morejohn
- Sergei Pnev
- Techjays
- Daniel Havíř
- Ian Janicki
- Chris Frangione
- Garrett Ryan
- Dejan Gotić
- Jonny Hyman

### Papyrology advisors

- Daniel Delattre
- Gianluca Del Mastro
- Robert Fowler
- Richard Janko
- Tobias Reinhardt

### Sponsors and donors

Thank you to every named and anonymous sponsor. The current public sponsor list includes Nat Friedman, Musk Foundation, Alex Gerko, Joseph Jacks, Daniel Gross, Matt Mullenweg, John and Patrick Collison, Emergent Ventures, Eugene Jhong, Julia DeWahl and Dan Romero, Bastian Lehmann, Tobi Lutke, Arthur Breitman, Guillermo Rauch, Matt Huang, Aaron Levie, Akshay Kothari, Alexa McLain, Anjney Midha, franciscosan.org, John O'Brien, Mark Cummins, Jamie Cox and Gary Wu, Mike Mignano, Aravind Srinivas, Brandon Reeves, Brandon Silverman, Chet Corcos, Ivan Zhao, Katsuya Noguchi, Matias Nisenson, Maya and Taylor Blau, Mikhail Parakhin, Neil Parikh, Raymond Russell, Sahil Chaudhary, Shariq Hashme, Stephanie Sher, Vignan Velivela, Alex Petkas, Amjad Masad, Conor White-Sullivan, Will Fitzgerald, and the anonymous donors listed by the Challenge.

### The wider community

Thank you to every prize winner and entrant, Kaggle competitor, Discord participant, open-source maintainer, annotator, papyrologist, classicist, scanner and beamline scientist, data curator, systems engineer, reviewer, donor, volunteer, educator, and person who shared a negative result, reported a bug, released a model, labeled a surface, or published a reproducible experiment.

The Challenge's living records of this community are:

- https://scrollprize.org/winners
- https://github.com/ScrollPrize/villa/blob/main/scrollprize.org/docs/20_community_projects.md

That includes the 2023 Grand Prize team and runners-up; First Letters contributors; open-source prize recipients; VC3D, Khartes, ScrollFiesta, surface-detection, segmentation, fiber, rendering, data-access, and ink-detection contributors; and the people whose public experiments became today's baseline.

## Open-source projects and public infrastructure used directly

- [`ScrollPrize/villa`](https://github.com/ScrollPrize/villa) — Vesuvius Challenge monorepo and source of VC3D / Volume Cartographer work, the `vesuvius` library, prize eligibility metadata, website sources, segmentation, ink-detection, and supporting tooling.
- [`ScrollPrize/open-data`](https://github.com/ScrollPrize/open-data) and the Vesuvius Challenge open-data bucket — public CT/data catalog infrastructure used by validation and reproducibility workflows.
- [`Svyable/zarr-pyramid-audit`](https://github.com/Svyable/zarr-pyramid-audit) — ScrolIQ's pinned integrity-audit companion.
- [`sgsllc-jr/zarr-pyramid-audit`](https://github.com/sgsllc-jr/zarr-pyramid-audit) — James Ryan's MIT-licensed upstream project from which the Svyable companion fork descends.
- [`superoptimizer/volume-compressor`](https://github.com/superoptimizer/volume-compressor) — upstream `volcomp` implementation used through the pinned companion decoder path.
- [`numpy/numpy`](https://github.com/numpy/numpy) — numerical operations.
- [`python-pillow/Pillow`](https://github.com/python-pillow/Pillow) — image I/O and reviewer-image utilities.
- [`cgohlke/tifffile`](https://github.com/cgohlke/tifffile) — TIFF / TIFXYZ handling.
- [`psf/requests`](https://github.com/psf/requests) — HTTP transport.
- [`zarr-developers/numcodecs`](https://github.com/zarr-developers/numcodecs) — codec support.
- [`pytest-dev/pytest`](https://github.com/pytest-dev/pytest), [`pypa/build`](https://github.com/pypa/build), and [`pypa/setuptools`](https://github.com/pypa/setuptools) — testing and packaging.
- [`actions/checkout`](https://github.com/actions/checkout), [`actions/setup-python`](https://github.com/actions/setup-python), and [`actions/upload-artifact`](https://github.com/actions/upload-artifact) — CI plumbing.
- **Docker Official Images / Python image maintainers** — the digest-pinned reviewer container base.
- **OME-NGFF / OME-Zarr contributors** — open multiscale conventions used throughout the data ecosystem.
- **Python contributors** — the runtime and standard library underneath the project.

## Community work that informs the design

ScrolIQ also learns from public Vesuvius Challenge tools and reports even when they are not imported as Python dependencies. In particular, the Challenge's community-project index documents VC3D, the `vesuvius` data library, Segment Browser, Khartes, Volume Cartographer, Thaumato Anakalyptor, ScrollFiesta-related work, `scroll-data-audit`, `vesuvius-repro`, `vesuvius-catalog`, winding tools, ink-validation work, and many other open contributions. Those projects establish formats, failure modes, validation ideas, and baselines that this repository should credit rather than silently rediscover.

## Data, scanning, scholarship, and institutions

Thank you to Vesuvius Challenge, EduceLab / University of Kentucky, the institutions caring for the Herculaneum papyri, the scanning facilities and beamline teams, and everyone responsible for acquiring, preserving, registering, hosting, documenting, and releasing the CT data. Thank you equally to the papyrologists and classicists whose letter-by-letter assessment is the final reality check on whether a technical pipeline has recovered text rather than invented it.

The Challenge's data page provides the authoritative dataset citations and licensing requirements: https://scrollprize.org/data.

## If we missed you

If a person, repository, model, dataset, or tool materially supports ScrolIQ and is missing here, please add it. The intended default is over-crediting, not under-crediting.
