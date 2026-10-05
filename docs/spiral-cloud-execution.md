# Spiral baseline cloud execution (PHerc0826, one NVIDIA L4)

**Status:** infrastructure, frozen 2026-10-05 before any VM exists. Nothing here
changes the experiment. The frozen recipe
(`artifacts/2026-10-03-spiral-baseline-target/pherc0826_baseline_recipe.json`),
its 30,000-step seed-1 bounded fit, the 480,117-track / zero-patch receipt and
the 12.6 % / 41.6 % reproduction check all stay as they are.
`scroliq-spiral-cloud check` fails any manifest that would move them.

This page covers how the run is executed: as few paid L4 minutes as possible,
no setup work on the GPU clock, and evidence that outlives the VM.

## Shape of the run

One persistent data disk and four short-lived VMs, run strictly one after another.
Each VM verifies its inputs, does one job, uploads its evidence, and deletes
itself (power-off is the fallback). Every VM also has a platform-enforced
`--max-run-duration` with `--instance-termination-action=DELETE`. That is the
hard cost guard, and it does not depend on our scripts working.

| # | role | machine | what it does | L4 time |
|---|---|---|---|---|
| 1 | `stage-env` | `e2-standard-8` (CPU) | pinned uv tarball (sha256-checked), exact clean clones of villa / assembler, villa `uv sync --locked` on the data disk, **CPU import gate** (torch, Triton, the four compiled `vc_spiral` modules, `fit_spiral`) | 0 |
| 2 | `gpu-gate` | `g2-standard-4` (L4) | GPU name, driver ≥ R570 (CUDA 12.8 torch build), torch CUDA matmul, a compiled Triton kernel, villa's own `FitContext.check_cuda_ready`, villa's three CUDA/headless/progress tests. **No large data has been downloaded yet.** | ≤ 30 min (watchdog) |
| 3 | `stage-data` | `e2-standard-8` (CPU) | assembler small files (hash-pinned), tracks DBM + crossings straight from dl.ash2txt.org, crossings mtime repair, Lasagna group 2 straight from the open bucket with every object size/MD5-verified, resident-pool packing, `scroliq-spiral-preflight` | 0 |
| 4 | `gpu-run` | `g2-standard-*` (L4), host RAM picked from measured pool size | re-gate, preflight equality with stage 3, **smoke run**, runtime projection, smoke deletion, preflight equality again, then the **untouched frozen fit**, reproduction check, official export | the fit |

This is how the plan addresses each point raised before launch:

1. **Frozen cloud execution manifest:**
   `artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json` records
   the VM types, zone rule, image rule, boot and data disk sizes and types, max
   runtimes, deletion action, CUDA expectations and the villa/assembler pins.
   Values that only exist at launch (project, zone, exact image name, bucket,
   scrollq commit, uv pin) are explicitly `null`. `check` lists them as
   unresolved, and `plan` refuses to emit commands until each one is supplied.
   They are never guessed.
2. **Hash-pinned startup:** `cloud/spiral-gcp/bootstrap.sh` is the GCE
   startup script. It checks out the scrollq commit from instance metadata,
   refuses a dirty tree, requires the manifest bytes at that commit to match the
   `scroliq-manifest-sha256` metadata, and checks `common.sh` and the role
   script against the manifest's `scripts` hashes before it runs anything.
   `plan` checks the same bytes at the commit before printing any command.
   Every clone must be at its exact commit with a clean tree.
3. **GPU clock vs data-prep clock:** all downloads, env builds and packing run
   on CPU VMs (stages 1 and 3). The L4 is attached only for the gate and the run.
4. **Public sources straight into GCP:** the tracks come from dl.ash2txt.org
   (`curl -C -`, size-checked against the 5,422,211,072-byte DBM signature) and
   Lasagna from the open S3 bucket. Nothing passes through a laptop.
5. **Storage budget:** every component has a size and a stated source
   (exact, upper bound, or estimate). Each checkpoint has a free-space floor
   (`before_villa_env`, `before_tracks`, `before_lasagna`, `before_pack`,
   `before_fit`, `before_export`) at least as large as everything still to be
   written; `check` enforces that arithmetic, and `disk-floor` stops a role when
   the real disk is below the floor. The Lasagna and pool figures are upper
   bounds: 3 × 16.44 GiB is the dense uint8 size of the group-2 arrays
   `[4230, 2043, 2043]`. The stored chunks are blosc-compressed and sparse.
6. **Process-independent cost guard:** max-run DELETE on every VM (12 h for
   the L4), plus an in-VM `systemd-run` watchdog. If the frozen fit has not
   started within 90 minutes of boot (30 for the gate-only VM), the watchdog
   writes a failure bundle and halts the VM. Budget alerts are visibility only.
7. **CUDA before big data:** stage 2 runs before stage 3. A broken
   driver/torch/Triton/`vc_spiral` combination costs at most one short L4 boot
   and no large download.
8. **Evidence outside the VM:** a small evidence bucket with a 30-day delete
   lifecycle. Each role syncs its evidence directory every 10 minutes and at
   exit: receipts, preflights, gate reports, logs, VRAM samples, S3 listings
   and the checkpoint. The TIFXYZ stays `hashes_only` by default; its file hashes are
   in the export receipt.
9. **Failure bundle:** any failing command triggers `scroliq-spiral-cloud
   bundle` before halt. The bundle records the failed gate, the reason, safe
   environment variables, `df`, `/proc/meminfo`, `nvidia-smi -q`, the process
   table, kernel warnings, and the tail and sha256 of each relevant log. It is
   written as JSON plus a tarball and uploaded with `STATUS.json`.
10. **PHerc0826 metadata prepared before launch:** pinned in the manifest and
    checked on the VM:
    - published umbilicus: 3,870 B, sha256 `fc9c54cd…`. Its metadata names
      volume `20250821151701-9.362um-…` at 9.362 µm.
    - expected `spiral-scroll.json`: 240 B, sha256 `7e4234bb…`, derived with the
      pinned assembler's `scroll_spec`.
    - the Lasagna run manifest and the `.zattrs` / `.zgroup` / group-2
      `.zarray` of all three stores.
    - the group-2 multiscale factor (4.0, equal to `lasagna_scale`).
    - the DBM and crossings names and URLs, outward sense `CW`, and the
      contract values: z-range, seed, 480,117 tracks, zero patches.

    The large DBM's sha256 is not published, so stage 3 records it.
11. **Smoke before the 30k run:** `smoke-recipe` derives a copy of the frozen
    recipe that differs only in `optimizer_num_training_steps` (300). It carries a
    `smoke` block (`promotional: false`, base recipe sha256). `scroliq-spiral-run`
    marks its receipt `mode: smoke, promotional: false`, and
    `scroliq-spiral-reproduction-check` and `scroliq-spiral-export` both refuse
    such a receipt. The smoke run uses its own cache directory. It must still pass
    the unchanged supervision receipt (480,117 tracks in the frozen ROI, zero
    patches) and write a checkpoint. `smoke-verdict` then projects the 30k
    runtime from villa's own `PROGRESS … it/s` lines (falling back to a
    wall-clock upper bound), multiplies it by 1.25, and stops if the result would
    not finish before the VM's 12 h deletion with 60 min reserved for export.
    Smoke outputs are uploaded as execution evidence and deleted from the disk.
    A second preflight comparison then proves the smoke run left the inputs
    byte- and mtime-identical.
12. **Contract unchanged:** `check` compares steps, seed, z-range, expected
    tracks, patches, the 12.6/41.6 reference and "ink may not select geometry"
    against the frozen recipe bytes (bound by sha256), and fails on any
    difference. The smoke run cannot be promoted, and the frozen run uses the
    original recipe file.

## Commands

```bash
# Anywhere, no cloud access needed:
scroliq-spiral-cloud check --manifest artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json

# After pushing the commit that carries the manifest + scripts:
scroliq-spiral-cloud plan \
  --manifest artifacts/2026-10-05-spiral-cloud-plan/cloud_execution_manifest.json \
  --run-id pherc0826-a --project <project> --zone <zone with L4 capacity> \
  --image <exact DLVM image name> --evidence-bucket <bucket> \
  --scrollq-commit <40-hex> --uv-version <x.y.z> --uv-sha256 <tarball sha256> \
  --out out/cloud-plan.json
```

`plan` executes nothing. It prints the exact `gcloud` argv for each step in
order: evidence bucket, lifecycle, data disk, then the four VMs. It also prints
what to wait for before each next step (`<evidence>/<role>/STATUS.json` = pass).
After stage 3, re-run `plan` with
`--staged <stage-data state.json>`. The `gpu-run` machine type is then
chosen from the measured resident-pool bytes by the frozen host-RAM rule
(`pools × 1.25 + 16 GiB`, smallest single-L4 G2 type that satisfies it). This
rule is a heuristic against host OOM, not a measurement of villa's peak RSS. The
smoke run is the real memory test.

Run the steps one at a time; the data disk is attached read-write to at most
one VM. Delete the data disk after the evidence in the bucket has been checked.

## What this does not establish

Nothing here measures geometry quality, winding correctness, coverage or ink.
A green `gpu-run` STATUS means the frozen bounded reproduction ran, its
receipts passed, and the official export ran. The existing campaign gates
([runner](spiral-baseline-runner.md),
[reproduction check](spiral-reproduction-check.md),
[campaign](spiral-baseline-campaign.md)) define what that evidence may be used
for.

## Not yet verified

These scripts have not run on GCP. The unit tests use fakes for the bucket,
`nvidia-smi`, the villa probe and villa's fitter, and the shell scripts are
checked with `bash -n` and shellcheck only. The following are expected to
surface on the first real run (cheaply, on the CPU stages where possible):

- whether villa's `uv sync --locked` builds `vc_spiral` with the image's
  toolchain;
- whether the editable install leaves the villa tree clean (if not, the role
  stops);
- the real Lasagna object count and compressed size;
- the measured pool size;
- villa's peak host RAM and VRAM on an L4.
