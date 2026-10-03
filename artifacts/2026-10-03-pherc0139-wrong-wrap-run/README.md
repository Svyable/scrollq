# PHerc0139 wrong-wrap geometry observation — 2026-10-03

**Status before this campaign runs:** frozen geometry-source rule exists; no
sheetness response has been consulted.

This campaign is the irreversible observation step after
`artifacts/2026-10-03-pherc0139-wrong-wrap-prereg/` in issue #105.

It applies the already-frozen
`normal-ray-supported-surface-v1` rule to the Challenge-published PHerc0139
m7 surface-prediction volume and the exact masked CT named in the frozen spec.

## What is frozen already

The upstream artifact fixes, before prediction values at the 32 probes are
read:

- the exact w035 reference-plan SHA-256;
- the exact PHerc0139 source CT identity;
- the exact published m7 level-0 prediction identity;
- threshold 127;
- normal-ray search range 12–64 voxels;
- 3-voxel independent-geometry separation gap;
- minimum 2-voxel supported prediction run;
- nearest-run selection with deterministic negative-normal tie break;
- no randomness;
- no sheetness response.

This campaign does **not** change any of those choices.

## Command

The workflow runs exactly:

```bash
scroliq-wrong-wrap-plan run \
  --spec artifacts/2026-10-03-pherc0139-wrong-wrap-prereg/wrong-wrap-spec.json \
  --reference-plan artifacts/2026-10-03-pherc0139-sheetness-prereg/reference-plan.json \
  --out artifacts/2026-10-03-pherc0139-wrong-wrap-run/wrong-wrap-result.json
```

The output is create-only. Reruns stop if the measured result already exists.

## Acceptance semantics

Both `complete` and `partial` are valid scientific outcomes.

A missing competing-sheet proposal stays missing. The workflow must never
hand-pick a substitute probe merely to improve completeness.

The post-run checks require:

- schema `scroliq-wrong-wrap-plan/1`;
- exactly 32 frozen groups;
- found + missing = 32;
- `sheetness_response_consulted: false`;
- the exact frozen reference-plan file SHA-256;
- the exact frozen wrong-wrap spec file SHA-256;
- no group status other than `found` or
  `no-independent-competing-sheet-found`.

No assertion is made about how many controls *should* be found before the
result is observed.

## Outputs

The workflow commits:

- `wrong-wrap-result.json` — measured proposals and completeness;
- `run.log` — command output;
- `inputs.sha256` — byte hashes of the frozen spec/reference inputs;
- `environment.txt` — Python/package environment.

## Claim boundary

A found control is a CT-supported location nominated by an independently
published surface-prediction volume along a frozen reference normal. It is not
ground truth for neighboring-winding identity.

This campaign measures only whether the preregistered independent-geometry
proposal rule can nominate separated controls at the frozen probes. It does
not test sheetness.

## Next irreversible step

After this result is committed, use the measured coordinates exactly as emitted
— including any missing controls — to freeze the CT cutout manifests and the
v3 sheetness benchmark specification. Only after that freeze may
`scroliq-sheetness` be run for issue #105.
