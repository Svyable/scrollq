"""Build the ScrollQ leaderboard site from volumes.json.

Generates a single self-contained HTML page: hero stats, score-distribution
histogram, sortable/filterable leaderboard with expandable rows, methodology,
and the label-coverage story. No external assets.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re

REPO = "https://github.com/Svyable/scrollq"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ScrollQ — Train on the best first</title>
<meta name="description" content="Data-quality triage for Vesuvius scroll volumes. 64 volumes scored 0-100 on voxel health.">
<style>
:root{{
  --bg:#0d0b08; --panel:#161310; --panel2:#1c1813; --line:#2c251b;
  --ink:#ece3d2; --muted:#a89880; --dim:#6f6350;
  --ember:#ff7a1a; --gold:#ffd166; --amber:#ffb347;
  --good:#8fd694; --warn:#ff9e5e; --bad:#ff6b6b;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}}
a{{color:var(--amber)}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 1.25rem}}
/* ---------- hero ---------- */
.hero{{position:relative;overflow:hidden;padding:4.5rem 0 3rem;
  background:
    radial-gradient(1200px 500px at 70% -10%, rgba(255,122,26,.14), transparent 60%),
    radial-gradient(800px 400px at 15% 110%, rgba(255,209,102,.08), transparent 60%),
    var(--bg)}}
.eyebrow{{letter-spacing:.28em;font-size:.72rem;color:var(--ember);font-weight:700}}
.hero h1{{font-family:Georgia,"Times New Roman",serif;font-size:clamp(3rem,8vw,5.5rem);
  margin:.4rem 0 .2rem;font-weight:700;letter-spacing:-.02em}}
.hero h1 .q{{color:var(--ember)}}
.tagline{{font-size:1.35rem;color:var(--ink);margin:.2rem 0 1rem}}
.tagline em{{color:var(--amber);font-style:normal;font-weight:600}}
.lede{{color:var(--muted);max-width:44rem;line-height:1.65;font-size:1.02rem}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:.75rem;margin-top:2rem}}
.stat{{background:rgba(22,19,16,.85);border:1px solid var(--line);border-radius:12px;
  padding:1rem 1.1rem;backdrop-filter:blur(4px)}}
.stat .n{{font-size:1.9rem;font-weight:800;color:var(--gold);
  font-variant-numeric:tabular-nums}}
.stat .l{{font-size:.78rem;color:var(--muted);margin-top:.25rem;line-height:1.4}}
/* ---------- insight cards ---------- */
.insights{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:.9rem;margin:2.2rem 0}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:1.25rem 1.35rem}}
.card h3{{margin:0 0 .5rem;font-size:.8rem;letter-spacing:.14em;color:var(--ember);
  text-transform:uppercase}}
.card p{{margin:.35rem 0;color:var(--muted);line-height:1.6;font-size:.94rem}}
.card p b{{color:var(--ink)}}
.card .big{{font-size:1.5rem;font-weight:800;color:var(--gold)}}
/* ---------- panels ---------- */
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:1.5rem;margin:0 0 2rem}}
.panel h2{{margin:.1rem 0 1rem;font-family:Georgia,serif;font-size:1.6rem}}
.panel h2 .sub{{display:block;font-family:inherit;font-size:.85rem;color:var(--muted);
  font-weight:400;margin-top:.3rem}}
/* histogram */
.hist{{display:flex;align-items:flex-end;gap:6px;height:150px;margin:.5rem 0}}
.bar{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;min-width:0;height:100%}}
.bar .fill{{width:100%;border-radius:5px 5px 0 0;
  background:linear-gradient(180deg,var(--ember),#7a3c0e)}}
.bar .bl{{font-size:.62rem;color:var(--dim);margin-top:.35rem;white-space:nowrap}}
.bar .bv{{font-size:.68rem;color:var(--muted);margin-bottom:.25rem;font-variant-numeric:tabular-nums}}
/* ---------- table ---------- */
.controls{{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem}}
.controls input{{background:var(--panel2);border:1px solid var(--line);color:var(--ink);
  border-radius:8px;padding:.55rem .8rem;font-size:.9rem;min-width:220px}}
.tierbtn{{background:var(--panel2);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:.45rem .9rem;font-size:.82rem;cursor:pointer}}
.tierbtn.on{{border-color:var(--ember);color:var(--ink);background:#241a10}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}}
thead th{{text-align:left;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted);padding:.6rem .5rem;border-bottom:1px solid var(--line);
  cursor:pointer;user-select:none;white-space:nowrap;position:sticky;top:0;
  background:var(--panel)}}
thead th:hover{{color:var(--ink)}}
thead th .arr{{color:var(--ember)}}
tbody td{{padding:.55rem .5rem;border-bottom:1px solid #211c14;vertical-align:middle}}
tbody tr.vol{{cursor:pointer}}
tbody tr.vol:hover td{{background:#1e1913}}
.num{{font-variant-numeric:tabular-nums;text-align:right}}
.score{{font-weight:800;font-size:1.02rem}}
.tier{{display:inline-block;font-size:.68rem;font-weight:800;letter-spacing:.08em;
  border-radius:6px;padding:.18rem .5rem}}
.tier.S{{background:rgba(255,209,102,.14);color:var(--gold);border:1px solid rgba(255,209,102,.4)}}
.tier.A{{background:rgba(255,122,26,.12);color:var(--ember);border:1px solid rgba(255,122,26,.35)}}
.tier.B{{background:rgba(168,152,128,.10);color:var(--muted);border:1px solid rgba(168,152,128,.3)}}
.tier.C{{background:rgba(111,99,80,.10);color:var(--dim);border:1px solid rgba(111,99,80,.3)}}
.compbar{{display:flex;height:10px;border-radius:5px;overflow:hidden;min-width:110px;
  background:#0a0906}}
.compbar span{{display:block;height:100%}}
.cb-s{{background:#ffd166}} .cb-t{{background:#ff7a1a}} .cb-d{{background:#c2571b}}
.pen{{color:var(--warn);font-variant-numeric:tabular-nums}}
.flag{{font-size:.78rem;color:var(--gold);font-weight:700;white-space:nowrap}}
.scrollid{{font-weight:700;color:var(--ink)}}
.volsub{{font-size:.72rem;color:var(--dim)}}
tr.detail td{{background:#100d09;font-size:.82rem;color:var(--muted)}}
.detail-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:.6rem;padding:.4rem 0}}
.detail-grid .k{{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}}
.detail-grid .v{{color:var(--ink);font-variant-numeric:tabular-nums}}
.why{{margin-top:.6rem;line-height:1.6}}
code{{font-size:.78rem;color:var(--amber)}}
/* ---------- methodology ---------- */
.method{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}}
.wtable{{width:100%;font-size:.85rem}}
.wtable td{{padding:.35rem .2rem;border-bottom:1px solid #211c14}}
.wtable td:last-child{{text-align:right;font-variant-numeric:tabular-nums;color:var(--gold)}}
.scope{{border-left:3px solid var(--ember);padding:.6rem 1rem;background:#171208;
  border-radius:0 8px 8px 0;color:var(--muted);line-height:1.65;font-size:.93rem}}
/* ---------- suite strip / footer ---------- */
.suite{{display:flex;gap:1rem;flex-wrap:wrap;align-items:stretch}}
.suite .card{{flex:1;min-width:260px}}
footer{{border-top:1px solid var(--line);margin-top:1rem;padding:1.6rem 0 3rem;
  color:var(--dim);font-size:.82rem;line-height:1.7}}
.hidden{{display:none!important}}
@media(max-width:700px){{.compbar{{min-width:70px}}thead th:nth-child(5),tbody td:nth-child(5){{display:none}}}}
</style></head><body>

<header class="hero"><div class="wrap">
  <div class="eyebrow">VESUVIUS CHALLENGE · SEPTEMBER 2026</div>
  <h1>Scroll<span class="q">Q</span></h1>
  <p class="tagline">Data-quality triage for Vesuvius scroll volumes. <em>Train on the best first.</em></p>
  <p class="lede">Every scroll volume's full-resolution level is sampled — four
  128&sup3; chunks, decoded from volcomp over HTTP — and scored 0&ndash;100 on
  signal presence, texture energy, dynamic range, and artifact penalties.
  Click any row for the full breakdown. Method and weights are published in
  the <a href="{repo}">repo</a>; re-weight it however you like.</p>
  <div class="stats">
    <div class="stat"><div class="n">{n}</div><div class="l">scroll volumes scored</div></div>
    <div class="stat"><div class="n">{lo}&ndash;{hi}</div><div class="l">score range (0&ndash;100)</div></div>
    <div class="stat"><div class="n">0</div><div class="l">dead slices found under the strict detector</div></div>
    <div class="stat"><div class="n">{label_next_n} 🎯</div><div class="l">top-quartile volumes with zero ink labels — label next</div></div>
  </div>
</div></header>

<div class="wrap">

<div class="insights">
  <div class="card"><h3>Healthiest volume</h3>
    <p class="big">{top_id}</p>
    <p><b>{top_score}</b> / 100 · {top_spec}<br>Same scanner family
    (9.362&thinsp;&micro;m, 113&thinsp;keV) also produced the <b>lowest</b>
    scores — data condition, not hardware, drives the spread.</p></div>
  <div class="card"><h3>Label-coverage gap</h3>
    <p>All <b>70</b> published ink-detection labels sit on
    <b>PHercParis4</b> — quality rank <b>13 of 39 scrolls</b> (each scroll
    ranked by its best volume). The healthiest volumes (<b>{top_id}</b> {top_score}, <b>PHerc0139</b> 75.9) have
    <b>zero</b> ink labels. Labeling effort goes furthest at the 🎯 rows.</p></div>
  <div class="card"><h3>Stable, not sacred</h3>
    <p>An independent deterministic resample re-scored all 64 volumes:
    rank correlation <b>&rho; = 0.876</b>, mean |&Delta;| <b>3.07</b>,
    top-10 overlap <b>8/10</b>. The ranking is a triage signal — audit the
    weights, don't worship it.</p></div>
</div>

<div class="panel"><h2>Score distribution<span class="sub">64 volumes · 5-point bins</span></h2>
  <div class="hist">{hist}</div>
  <p style="color:var(--muted);font-size:.88rem">Tiers: <span class="tier S">S</span> ≥ 70 ·
  <span class="tier A">A</span> 60&ndash;70 · <span class="tier B">B</span> 45&ndash;60 ·
  <span class="tier C">C</span> &lt; 45</p>
</div>

<div class="panel"><h2>Leaderboard<span class="sub">Click a column to sort · click a row for the full breakdown</span></h2>
  <div class="controls">
    <input id="q" type="search" placeholder="Filter by scroll id, e.g. PHerc0139…" aria-label="filter">
    <button class="tierbtn on" data-t="">all</button>
    <button class="tierbtn" data-t="S">S</button>
    <button class="tierbtn" data-t="A">A</button>
    <button class="tierbtn" data-t="B">B</button>
    <button class="tierbtn" data-t="C">C</button>
    <button class="tierbtn" data-t="label">🎯 label next</button>
  </div>
  <div style="overflow-x:auto"><table id="lb"><thead><tr>
    <th data-k="rank">#</th><th data-k="id">volume</th><th data-k="score">score</th>
    <th data-k="tier">tier</th><th>components</th>
    <th data-k="signal">signal</th><th data-k="tex">texture</th><th data-k="dyn">dynamic</th>
    <th data-k="pen">penalties</th><th data-k="ink">ink labels</th><th data-k="seg">segments</th><th>note</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
</div>

<div class="panel"><h2>How the score works</h2>
<div class="method">
  <div><table class="wtable">
    <tr><td>Signal presence (nonzero voxel fraction)</td><td>40</td></tr>
    <tr><td>Texture / gradient energy</td><td>30</td></tr>
    <tr><td>Dynamic range</td><td>20</td></tr>
    <tr><td>Saturation penalty</td><td>&minus;10</td></tr>
    <tr><td>Dead-slice penalty</td><td>&minus;25</td></tr>
  </table>
  <p style="color:var(--muted);font-size:.88rem;line-height:1.65">The dead-slice
  detector is deliberately strict: a densely populated chunk holding a zero
  plane whose <b>both</b> neighbors are densely populated. A naive rule
  false-positives on mask geometry — that version was caught and corrected
  before shipping.</p></div>
  <div><div class="scope"><b>Honest scope.</b> This is a triage signal, not a
  readability claim. It does not detect ink and does not predict which scroll
  will read first. It tells you which volumes have the healthiest voxels, so
  segmentation and labeling effort goes where the data is strongest. The
  weights are a judgment call, published with every score.</div>
  <p style="color:var(--muted);font-size:.88rem;line-height:1.65;margin-top:1rem">
  Sampling: 4 &times; 128&sup3; chunks per volume, spread per-dimension across
  the shard grid (flat-index spread degenerates to an edge line on non-cubic
  grids). Decoded with the vendored libvolcomp via
  <a href="https://github.com/Svyable/zarr-pyramid-audit">zarr-pyramid-audit</a>.</p></div>
</div></div>

<div class="panel"><h2>One suite, two halves</h2>
<div class="suite">
  <div class="card"><h3>zarr-pyramid-audit</h3>
    <p><b>Don't train on lies.</b> Corruption detection for OME-Zarr pyramids —
    header-only audits, a publish-time gate, and a sampled chunk-content probe.
    Caught a live defective pyramid in the open-data S3 bucket.</p>
    <p><a href="https://github.com/Svyable/zarr-pyramid-audit">repo</a> ·
    <a href="https://svyable.github.io/zarr-pyramid-audit/">dashboard</a></p></div>
  <div class="card"><h3>scrollq-health</h3>
    <p>Runs the integrity audit <b>and</b> the quality score on any volume and
    issues one verdict: <b>TRAIN / CAUTION / DO NOT TRAIN</b>.</p>
    <p><code>scrollq-health --root &lt;volume&gt;</code></p></div>
</div></div>

</div><!-- /wrap -->

<footer><div class="wrap">
  Generated by <a href="{repo}">ScrollQ</a> from public dl.ash2txt.org volumes,
  {stamp}. Scores are heuristic and published with their components — audit the
  weights, don't worship the ranking. Companion:
  <a href="https://github.com/Svyable/zarr-pyramid-audit">zarr-pyramid-audit</a>.
  · <a href="./september-2026.html">September 2026 writeup →</a>
</div></footer>

<script>
(function(){{
  const tb = document.querySelector("#lb tbody");
  const rows = Array.from(tb.querySelectorAll("tr.vol"));
  rows.forEach(r => {{ r._detail = r.nextElementSibling; }});
  let sortK = "rank", asc = true, tierF = "", qF = "";
  function tierOf(r){{ return r.dataset.tier; }}
  function apply(){{
    let vis = rows.filter(r =>
      (!tierF || (tierF === "label" ? r.dataset.label === "1" : tierOf(r) === tierF)) &&
      (!qF || r.dataset.id.toLowerCase().includes(qF)));
    vis.sort((a, b) => {{
      const x = parseFloat(a.dataset[sortK] ?? a.dataset.rank),
            y = parseFloat(b.dataset[sortK] ?? b.dataset.rank);
      const c = (isNaN(x) || isNaN(y))
        ? String(a.dataset[sortK]).localeCompare(String(b.dataset[sortK]))
        : x - y;
      return asc ? c : -c;
    }});
    const frag = document.createDocumentFragment();
    vis.forEach((r, i) => {{
      r.classList.remove("hidden");
      r._detail.classList.add("hidden");
      r.querySelector(".rn").textContent = i + 1;
      frag.append(r, r._detail);
    }});
    rows.forEach(r => {{ if (!vis.includes(r)) {{ r.classList.add("hidden"); r._detail.classList.add("hidden"); }} }});
    tb.append(frag);
  }}
  document.querySelectorAll("#lb thead th[data-k]").forEach(th => {{
    th.addEventListener("click", () => {{
      const k = th.dataset.k;
      if (sortK === k) asc = !asc; else {{ sortK = k; asc = (k === "id" || k === "tier"); }}
      document.querySelectorAll("#lb thead th .arr").forEach(e => e.remove());
      const s = document.createElement("span"); s.className = "arr";
      s.textContent = asc ? " ▲" : " ▼"; th.appendChild(s);
      apply();
    }});
  }});
  document.querySelectorAll(".tierbtn").forEach(b => b.addEventListener("click", () => {{
    document.querySelectorAll(".tierbtn").forEach(x => x.classList.remove("on"));
    b.classList.add("on"); tierF = b.dataset.t; apply();
  }}));
  document.getElementById("q").addEventListener("input", e => {{
    qF = e.target.value.trim().toLowerCase(); apply();
  }});
  rows.forEach(r => r.addEventListener("click", () => {{
    if (r._detail) r._detail.classList.toggle("hidden");
  }}));
  apply();
}})();
</script>
</body></html>
"""

SPEC_RE = re.compile(r"(\d+\.\d+)um-.*?(\d+)keV")


def short_name(root: str) -> tuple[str, str, str]:
    parts = root.split("/")
    scroll = parts[-3] if len(parts) >= 3 else "?"
    fname = parts[-1].replace(".zarr", "")
    m = SPEC_RE.search(fname)
    spec = f"{m.group(1)}µm · {m.group(2)}keV" if m else fname[:40]
    return scroll, spec, fname


def tier(score: float) -> str:
    if score >= 70:
        return "S"
    if score >= 60:
        return "A"
    if score >= 45:
        return "B"
    return "C"


def score_color(score: float) -> str:
    # ember ramp: dim tan -> gold
    t = max(0.0, min(1.0, (score - 25) / 55))
    r = int(138 + t * (255 - 138))
    g = int(127 + t * (209 - 127))
    b = int(106 + t * (102 - 106))
    return f"rgb({r},{g},{b})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--coverage", default=None)
    args = ap.parse_args()
    vols = json.load(open(args.inp, encoding="utf-8"))
    cov = json.load(open(args.coverage, encoding="utf-8")) if args.coverage else {}
    ok = sorted((v for v in vols if v.get("ok")),
                key=lambda v: v["score"], reverse=True)
    scores = [v["score"] for v in ok]
    lo, hi = min(scores), max(scores)

    label_next = [v for v in ok
                  if cov.get(v["root"], {}).get("label_next")]
    top = ok[0]
    top_scroll, top_spec, _ = short_name(top["root"])

    # histogram, 5-point bins from 25 to 80
    bins = [(25 + 5 * i, 25 + 5 * (i + 1)) for i in range(11)]
    counts = [sum(1 for s in scores if b0 <= s < b1 or (b1 == 80 and s == b1))
              for b0, b1 in bins]
    cmax = max(counts) or 1
    hist = "".join(
        f'<div class="bar"><div class="bv">{c}</div>'
        f'<div class="fill" style="height:{100 * c / cmax:.0f}%"></div>'
        f'<div class="bl">{b0}</div></div>'
        for (b0, _), c in zip(bins, counts))

    rows = []
    for i, v in enumerate(ok, 1):
        c = v["components"]
        m = v["metrics"]
        scroll, spec, fname = short_name(v["root"])
        t = tier(v["score"])
        cc = cov.get(v["root"], {}) if cov else {}
        ink = cc.get("ink_labels", 0)
        seg = cc.get("segments", 0)
        is_label = bool(cc.get("label_next"))
        flag = '<span class="flag">🎯 label next</span>' if is_label else ""
        dead = m.get("dead_slices", 0)
        pen = c.get("pen_sat", 0) + c.get("pen_dead", 0)
        s40, t30, d20 = c["signal_40"], c["texture_30"], c["dynamic_20"]
        compbar = (
            f'<div class="compbar" title="signal {s40:.1f} / texture {t30:.1f} / '
            f'dynamic {d20:.1f}">'
            f'<span class="cb-s" style="width:{100 * s40 / 90:.1f}%"></span>'
            f'<span class="cb-t" style="width:{100 * t30 / 90:.1f}%"></span>'
            f'<span class="cb-d" style="width:{100 * d20 / 90:.1f}%"></span></div>')
        # why-this-score narrative
        bits = []
        bits.append(f"signal {s40:.1f}/40 — nonzero voxel fraction "
                    f"{m['nonzero_frac']:.3f}")
        bits.append(f"texture {t30:.1f}/30 — gradient energy "
                    f"{m['grad_energy']:.2f}")
        bits.append(f"dynamic {d20:.1f}/20 — range {m['dyn_range']:.0f}")
        if c.get("pen_sat"):
            bits.append(f"saturation penalty −{c['pen_sat']:.1f}")
        if dead:
            bits.append(f"dead slices: {dead}")
        if ink:
            bits.append(f"{ink} published ink-detection labels on this scroll")
        if seg:
            bits.append(f"{seg} segment roots in open data")
        if is_label:
            bits.append("🎯 top-quartile quality with zero ink labels — "
                        "label next")
        why = " · ".join(html.escape(b) for b in bits)
        rows.append(
            f'<tr class="vol" data-rank="{i}" data-id="{html.escape(scroll.lower())} {html.escape(fname.lower())}"'
            f' data-score="{v["score"]:.1f}" data-tier="{t}"'
            f' data-signal="{s40:.1f}" data-tex="{t30:.1f}" data-dyn="{d20:.1f}"'
            f' data-pen="{pen:.1f}" data-ink="{ink}" data-seg="{seg}"'
            f' data-label="{"1" if is_label else "0"}">'
            f'<td class="num rn">{i}</td>'
            f'<td><span class="scrollid">{html.escape(scroll)}</span><br>'
            f'<span class="volsub">{html.escape(spec)}</span></td>'
            f'<td class="num score" style="color:{score_color(v["score"])}">'
            f'{v["score"]:.1f}</td>'
            f'<td><span class="tier {t}">{t}</span></td>'
            f'<td>{compbar}</td>'
            f'<td class="num">{s40:.1f}</td>'
            f'<td class="num">{t30:.1f}</td>'
            f'<td class="num">{d20:.1f}</td>'
            f'<td class="num pen">−{pen:.1f}</td>'
            f'<td class="num">{ink}</td>'
            f'<td class="num">{seg}</td>'
            f'<td>{flag}</td></tr>'
            f'<tr class="detail hidden"><td colspan="12">'
            f'<div class="detail-grid">'
            f'<div><div class="k">full root</div><div class="v"><code>'
            f'{html.escape(v["root"])}</code></div></div>'
            f'<div><div class="k">nonzero fraction</div><div class="v">'
            f'{m["nonzero_frac"]:.4f}</div></div>'
            f'<div><div class="k">gradient energy</div><div class="v">'
            f'{m["grad_energy"]:.3f}</div></div>'
            f'<div><div class="k">dynamic range</div><div class="v">'
            f'{m["dyn_range"]:.0f}</div></div>'
            f'<div><div class="k">chunks decoded</div><div class="v">'
            f'{m.get("chunks_decoded", "?")}</div></div>'
            f'<div><div class="k">dead slices</div><div class="v">{dead}</div></div>'
            f'</div><div class="why">{why}</div>'
            f'</td></tr>')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")
    page = PAGE.format(
        repo=REPO, n=len(ok), lo=f"{lo:.1f}", hi=f"{hi:.1f}",
        label_next_n=len(label_next),
        top_id=html.escape(top_scroll), top_score=f"{top['score']:.1f}",
        top_spec=html.escape(top_spec),
        hist=hist, rows="\n".join(rows), stamp=stamp)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.out} ({len(ok)} volumes)")
