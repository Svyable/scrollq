"""Prove the score/sampling refactor did not change scores or sample selection.

Compares the current ``scrollq.score`` against its source at a baseline git
ref (default 3352966, the commit before the refactor) two ways:

1. Formula: ``score_from_metrics`` and the rounded ``components`` breakdown
   on 200,000 seeded random metric sets must be exactly equal.
2. Sampling: ``score_volume`` run on 300 seeded, randomized fake volumes with
   injected faults (404s, 503s, invalid shard indexes, missing chunks, chunk
   read failures, decoder rejections). Every field except the three new
   sampling counters must be identical, and the extended error string must
   begin with the old one.

Synthetic volumes only: this shows the logic is unchanged, not that any live
dl.ash2txt.org number was re-measured. Exits non-zero on any mismatch.

Run from the repository root:  python artifacts/2026-10-01-score-equivalence/verify.py
"""
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "src")

BASELINE = sys.argv[1] if len(sys.argv) > 1 else "3352966"
N_FORMULA = 200_000
N_VOLUMES = 300
NEW_KEYS = {"shard_index_invalid", "chunk_read_failures",
            "chunk_decode_failures"}


def load_baseline():
    src = subprocess.run(
        ["git", "show", f"{BASELINE}:src/scrollq/score.py"],
        check=True, capture_output=True, text=True).stdout
    src = src.replace("from .metrics import", "from scrollq.metrics import")
    path = Path(tempfile.mkdtemp()) / "score_baseline.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("score_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not hasattr(mod, "score_components"), "baseline is not pre-refactor"
    return mod


old = load_baseline()
import scrollq.score as new  # noqa: E402

vc = new.vc
assert old.vc is vc  # both modules are driven through the same zpa module


def old_components(m):
    return {
        "signal_40": round(40.0 * min(1.0, m["nonzero_frac"] / 0.9), 1),
        "texture_30": round(30.0 * min(1.0, m["grad_energy"] / 12.0), 1),
        "dynamic_20": round(20.0 * min(1.0, m["dyn_range"] / 200.0), 1),
        "pen_sat": round(25.0 * min(1.0, m["sat_frac"] / 0.05), 1),
        "pen_dead": round(min(30.0, 15.0 * m["dead_slices"]), 1),
    }


def check_formula() -> int:
    rng = random.Random(0)
    bad = 0
    for _ in range(N_FORMULA):
        m = dict(nonzero_frac=rng.random(), grad_energy=rng.uniform(0, 40),
                 dyn_range=rng.uniform(0, 255), sat_frac=rng.random() ** 3,
                 dead_slices=rng.randint(0, 6))
        new_c = {k: round(v, 1) for k, v in new.score_components(m).items()}
        if (old.score_from_metrics(m) != new.score_from_metrics(m)
                or old_components(m) != new_c):
            bad += 1
    print(f"formula: cases={N_FORMULA} mismatches={bad}")
    return bad


def h(*parts) -> int:  # stable across processes, unlike hash()
    return zlib.crc32("|".join(map(str, parts)).encode())


def run_volume(mod, seed):
    rng = random.Random(seed)
    grid = tuple(rng.randint(1, 6) for _ in range(3))
    cps = tuple(rng.randint(1, 3) for _ in range(3))
    inner = (128, 128, 128)
    outer = tuple(inner[d] * cps[d] for d in range(3))
    shape = tuple(outer[d] * grid[d] - rng.randint(0, 50) for d in range(3))
    info = SimpleNamespace(shape=shape, outer_chunks=outer, inner_chunks=inner,
                           inner_codec="volcomp", index_codecs=[])

    def p(*key):
        return (h(seed, *key) % 100) / 100.0

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.content = b"idx" + str(code).encode()

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http")

    class Sess:
        def get(self, url, **kw):
            r = p("shard", url)
            return Resp(404 if r < 0.15 else 503 if r < 0.25 else 206)

    class Store:
        def get_json(self, path):
            return {}

        def _session(self):
            return Sess()

        def get_range(self, key, off, ln):
            if p("rd", key, off) < 0.12:
                raise RuntimeError("range")
            return f"blob:{key}:{off}".encode()

    def parse_index(raw, n, codecs):
        if p("idx", raw) < 0.10:
            return None
        return [(vc.MISSING, vc.MISSING) if p("m", raw, i) < 0.45
                else (i * 7 + 1, 5) for i in range(n)]

    def decode_chunk(blob):
        if p("dec", blob) < 0.12:
            return None
        return bytes([h(blob) % 250 + 1]) * (128 ** 3)

    def chunk_metrics(vox):
        k = int(vox.flat[0])
        return {"nonzero_frac": (k % 100) / 100, "std": 1.0 + k % 7,
                "dyn_range": float(k), "sat_frac": (k % 9) / 100,
                "grad_energy": (k % 30) / 2, "dead_slices": k % 4 // 3}

    mod.open_store = lambda base: Store()
    vc.available = lambda: (True, None)
    vc.parse_zarr_json = lambda meta: info
    vc.shard_key = lambda root, level, sc: f"{root}/{level}/{sc}"
    vc.inner_chunks_per_shard = lambda i, sc: cps
    vc.index_encoded_size = lambda n, codecs: 16 * n
    vc.parse_index = parse_index
    vc.decode_chunk = decode_chunk
    mod.chunk_metrics = chunk_metrics
    return mod.score_volume("https://x", "root", samples=rng.randint(1, 30),
                            rotate=rng.randint(0, 40),
                            spread=rng.randint(1, 5))


def check_sampling() -> int:
    mismatches = ok_volumes = events = 0
    for seed in range(N_VOLUMES):
        a, b = run_volume(old, seed), run_volume(new, seed)
        b_cmp = dict(b)
        if "sampling" in b_cmp:
            b_cmp["sampling"] = {k: v for k, v in b["sampling"].items()
                                 if k not in NEW_KEYS}
            events += sum(b["sampling"][k] for k in NEW_KEYS)
        a_cmp = dict(a)
        ea, eb = a_cmp.pop("error", None), b_cmp.pop("error", None)
        # The error string is intentionally extended; the old text (minus
        # its closing parenthesis) must remain a prefix of the new one.
        errors_ok = (ea is None and eb is None) or (
            ea is not None and eb is not None and eb.startswith(ea[:-1]))
        if not errors_ok or a_cmp != b_cmp:
            mismatches += 1
            print(f"MISMATCH seed={seed}: {json.dumps(a)[:200]} "
                  f"!= {json.dumps(b)[:200]}")
            continue
        ok_volumes += bool(a.get("ok"))
    print(f"sampling: volumes={N_VOLUMES} mismatches={mismatches} "
          f"ok_volumes={ok_volumes} failure_events_newly_recorded={events}")
    return mismatches


if __name__ == "__main__":
    print(f"baseline: {BASELINE}")
    failed = check_formula() + check_sampling()
    print("RESULT:", "IDENTICAL" if failed == 0 else "DIFFERENCES FOUND")
    sys.exit(1 if failed else 0)
