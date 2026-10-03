# `scroliq-gp-ready`: Grand Prize evidence dossier

`scroliq-gp-ready` compiles one dossier per submission: for every numbered
column mesh, which required checks have passing evidence that is bound to that
exact mesh, and which do not. It runs no reconstruction or ink model itself.
Production stays in VC3D/villa; independent community tools are witnesses;
ScrolIQ records what each witness said, about which artifact, and how sure we
are that the report is about that artifact.

It complements, and does not replace:

- `scroliq-evidence-bind`: binds windcheck's published release index to a
  `scroliq-mesh` audit; `gp-ready` uses the same binding classes for six tools'
  per-mesh reports;
- `scroliq-package`: builds and verifies the final deterministic archive and
  reviewer contract; a ready dossier is meant to be checked before packaging;
- `scroliq-provenance`: the fail-closed submission-graph gate (schema v4);
- `scroliq-passport`: per-volume evidence by Challenge stage;
- `docs/grand-prize-readiness.html`: the reviewer-facing requirement map.

A dossier answers the readiness map's questions for one concrete package.

## Evidence records

Every external or internal report is normalized by an adapter into one or more
records (`schema: scroliq-evidence/1`):

```json
{
  "check": "mesh.self-intersection",
  "subject": {"kind": "mesh", "id": "column_01", "path": "meshes/column_01"},
  "source": {"tool": "windcheck", "tool_version": "0.1.0",
             "pinned_commit": "2b0fb2f3…", "report_path": "…",
             "report_sha256": "…"},
  "binding": "coordinate-exact",
  "status": "pass",
  "verdict_source": "tool",
  "metrics": {"crossing_sites": 0}
}
```

### Status

| status | meaning |
|---|---|
| `pass` | the tool's own verdict, or a declared policy threshold, is met |
| `fail` | the verdict is not met |
| `caution` | the tool raised warnings or review cues; a human must look |
| `measured` | the tool reports metrics but no verdict, and the policy declares no threshold |
| `error` | the report is unreadable, from an unpinned tool version, or about a different artifact |

`measured` is never promoted to `pass`. A threshold has to be declared in the
policy file, which is published with the dossier, exactly like the scan-score
weights.

### Binding

Binding classes are the ones `scroliq-evidence-bind`
(`scrollq.external_mesh_evidence`) already uses, and hash comparison reuses
its implementation, so both commands give the same answer for the same
hashes. Strongest first:

| binding | meaning |
|---|---|
| `semantic-exact` | recorded x/y/z, mask and meta.json hashes all equal the audited files |
| `coordinate-exact` | recorded x/y/z and mask hashes equal the audited files; no meta.json hash |
| `path-grid` | no hashes; the report's path resolves to the audited mesh and its grid shape matches |
| `path-only` | no hashes; only the path matches |
| `unbound` | the report does not say which mesh it describes |
| `mismatch` | recorded hashes contradict the audited files |

A `mismatch` record is always `error`: it describes some other version of the
mesh.

### Pinned tools

An adapter is written against real output of a specific tool commit and is
tested against that output. Reports from other versions are accepted only if
they carry the same schema marker; otherwise they are `error`. Adding a tool
means adding a real fixture, not guessing its format.

## Policy

The policy names the required checks for a column and any thresholds for
`measured` tools. Defaults live in `scrollq.gp_ready.DEFAULT_POLICY`; a
submission can supply its own JSON, which is recorded (with its SHA-256) in
the dossier.

`min_binding` sets the weakest binding that can count as `pass`. The default
is `path-only`, because most community tools identify meshes only by path;
weaker-than-hash bindings are still listed on every passing row so a reviewer
can see them.

## Verdict

A column is `ready` only when every required check is `pass` at or above
`min_binding`. Otherwise the dossier lists the blockers: `missing`, `fail`,
`caution`, `measured`, `error`, or `binding-too-weak`. There is no score and no
partial credit.
