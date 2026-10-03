# Evidence-adapter fixtures (real tool output)

Real outputs, not hand-written examples. They are what `scrollq.evidence`
adapters are tested against.

- `elig/meshes/PHerc0800/z14672_w020/`: a tifxyz mesh from
  [pscamillo/vesuvius-eligible-meshes](https://github.com/pscamillo/vesuvius-eligible-meshes)
  at commit `620769e2e1e70d1e61b588092229cb76d3af4804` (MIT). The directory
  layout matches the path the tools recorded, so path binding is tested for
  real.
- `reports/`: produced on 2026-10-02 by running each tool on that mesh:

| file | tool | commit | command |
|---|---|---|---|
| `windcheck.json` | joe-carr-data/windcheck | `2b0fb2f3d305` | `windcheck check <mesh> --out …` (certificate) |
| `flatcheck.json` | abundantjoe/flatcheck | `948a19d102ed` | `flatcheck report <mesh> --json …` |
| `tifxyz-doctor.json` | aviad12g/tifxyz-doctor | `5ca0444fb318` | `tifxyz-doctor audit <mesh> --json …` |
| `tifxyz-repair.json` | Nieuwlaar/tifxyz-repair | `4d6c98d95b71` | `tifxyz-repair validate --json <mesh>` |
| `scroliq-mesh.json` | this repo | — | `scroliq-mesh --tifxyz <mesh> --volume-root PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr` |
| `spiralcheck-pherc1218.json` | Nicodol/spiralcheck | `d1b50e2957` | copied from `examples/real_run_pherc1218_report.json` (MIT) |

Local absolute paths in `windcheck.json` (engine location) and
`tifxyz-doctor.json` were replaced with `<work>`/`<home>`; adapters do not
read those fields. All tools are MIT licensed.
