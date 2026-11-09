# ScrolIQ state-machine inventory

This is an audit map, not a replacement for the frozen scientific protocols. It
records where `state + event -> next state` was previously implicit in flags,
files, button classes, or command ordering. In particular, **no dashboard view
state is Grand Prize evidence** and a successful process is not automatically a
successful measurement.

| Machine | States / transitions | Authoritative owner | Safety invariant |
| --- | --- | --- | --- |
| Survey dashboard | default, filtered, sorted (orthogonal); row collapsed/expanded; reset | `leaderboard.py` renders `docs/index.html` | Validated sort/filter values; URL view parameters `sort`, `dir`, `tier`, `q` never alter survey data; hidden rows close, visible expanded rows survive sorting |
| Scan health | sampled, scored, invalid/unavailable -> reported | `score.py`, `health.py` | Scan-health score is **not** ink readability or Grand Prize readiness; integrity UNKNOWN cannot silently become TRAIN |
| Public evidence/passport | unmeasured -> measured/partial/blocked -> reviewed | `passport.py`, `provenance.py` | Missing evidence remains unknown, not an inferred pass |
| Blind evaluation custody | development -> seal -> prediction commitment -> anchor -> reveal -> report | `blind_control.py` | Create-only ordering, hashes and training/prediction region separation |
| Model evaluation/release | registered -> evaluated -> eligible/ineligible for release | `model_eval.py`, `model_release.py` | Held-out overlap is disqualifying; model/checkpoint provenance and seeds are explicit |
| Geometry / winding review | candidate -> preflight -> reviewed/rejected/accepted -> export | `winding_audit.py`, `winding_review_apply.py`, `vc3d_review_ingest.py` | Evidence and ordering must remain tied to exact volume and mesh identities |
| VC3D producer guard | preflight -> launched -> checked -> producer success/semantic failure | `vc3d_run_guard.py` | Exit code zero alone cannot promote an invalid or unchanged surface |
| Spiral fit | prepared -> running -> successful/failed receipt; smoke is non-promotional | `spiral_preflight.py`, `spiral_run.py`, `spiral_cloud.py` | Exact clean villa commit, dataset preflight, verified supervision and real checkpoint required |
| Reproduction/export | receipt -> verified/blocked -> package | `spiral_reproduction_check.py`, `spiral_export.py`, `submission_package.py` | Never promote a smoke receipt or a missing/mismatched evidence artifact |
| Prize submission | evidence pending/failed -> dry run -> qualifying package | `submission_dry_run.py`, `submission_package.py`, `grand_prize.py` | Complete recto, column-size TIFXYZ, image/mesh traceability, training exclusion and independent legibility checks are separate gates |

## Applied dashboard transition contract

The leaderboard has one canonical `view` object: `sortKey`, `ascending`,
`tier` and `query`. UI events pass through `transition(kind, value)`;
unknown events throw, invalid sort/filter values are ignored, and `reset`
restores the published default. `apply()` alone renders the view and
`updateControls()` updates `aria-pressed`/`aria-sort` and the visual
indicator. Accepted view state is reflected by `history.replaceState` (no
new history entries); unrelated query parameters and the fragment survive.
Loading a copied URL validates the requested sort/filter against the *actual*
rendered controls. Scientific data, scores, candidate labels, exports, and
published evidence are never written back by the view machine.

Expanded evidence rows survive reordering and filters that still include
them. Rows excluded from the view close; when they return, they remain
collapsed. Sort headers accept mouse, Enter and Space. The dashboard is
still usable when URL persistence is blocked by a local preview context.

## Rules for humans and coding agents

1. Keep model/evidence lifecycles **separate** from the presentational
   dashboard machine. Never infer a scientific success from a UI badge.
2. Preserve public commands, receipt fields, file formats, fixed seeds,
   exact-input hashes, and frozen scientific thresholds unless a reviewed
   schema/protocol migration is deliberate.
3. Treat absent, unknown, failed and passed as distinct values. Terminal
   success requires verified artifacts, not just a completed subprocess.
4. Prefer pure state transitions and explicit gates before side effects;
   use create-only writes and reproducible receipts for evidence transitions.
5. Tests: `tests/test_dashboard_state_contract.py` locks the generator to the
   committed page and checks interaction/accessibility hooks. The broader
   Python contract suite guards prize/evidence states.

## Remaining hardening work

The dashboard is now an explicit reducer with validated restoration; other
families above still mix state with file presence or process outcomes.
A future change should isolate transitions per family **without changing
published semantics**. Prioritize cancellation/interruption receipts for
long-running Spiral and VC3D jobs, then machine-readable transition fixtures
for blind custody and submission promotion. Each promotion must be separately
validated on success, expected failure, missing evidence and interrupted runs.
