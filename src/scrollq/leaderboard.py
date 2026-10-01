"""Build the ScrolIQ leaderboard site from volumes.json.

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
<title>ScrolIQ — Diagnostics for reading Herculaneum scrolls</title>
<meta name="description" content="Challenge-aligned diagnostics for Vesuvius scrolls: scan health, TIFXYZ/OBJ mesh QA, native VC3D fiber auditing, label quality, ink reliability, held-out validation, and reproducibility.">
<meta name="theme-color" content="#0d0b08">
<meta name="color-scheme" content="dark">
<link rel="canonical" href="https://svyable.github.io/scrollq/">
<meta property="og:type" content="website">
<meta property="og:title" content="ScrolIQ — Evidence for reading Herculaneum scrolls">
<meta property="og:description" content="Reproducible scan diagnostics, exact-volume Grand Prize qualification, held-out geometry, and ink falsification controls.">
<meta property="og:url" content="https://svyable.github.io/scrollq/">
<style>
:root{{
  --bg:#0d0b08; --panel:#161310; --panel2:#1c1813; --line:#2c251b;
  --ink:#ece3d2; --muted:#a89880; --dim:#6f6350;
  --ember:#ff7a1a; --gold:#ffd166; --amber:#ffb347;
  --good:#8fd694; --warn:#ff9e5e; --bad:#ff6b6b;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}}
a{{color:var(--amber)}}
a:focus-visible,button:focus-visible,input:focus-visible{{outline:2px solid var(--gold);outline-offset:3px}}
.skip{{position:fixed;left:1rem;top:1rem;z-index:1000;transform:translateY(-180%);
  background:var(--gold);color:#171008;padding:.55rem .8rem;border-radius:8px;font-weight:800;text-decoration:none}}
.skip:focus{{transform:none}}
.wrap{{max-width:1200px;margin:0 auto;padding:0 1.25rem}}
.topbar{{position:sticky;top:0;z-index:50;background:rgba(13,11,8,.88);
  backdrop-filter:blur(16px);border-bottom:1px solid rgba(44,37,27,.78)}}
.navinner{{max-width:1200px;margin:0 auto;padding:.7rem 1.25rem;display:flex;align-items:center;gap:1rem}}
.brand{{display:flex;align-items:center;gap:.6rem;color:var(--ink);text-decoration:none;font-weight:800}}
.brandmark{{width:26px;height:26px;border-radius:7px;border:1px solid #6f3b18;display:grid;place-items:center;
  color:var(--ember);font-family:Georgia,serif;background:#17110c;font-size:.72rem}}
.navlinks{{display:flex;gap:.2rem;margin-left:auto;align-items:center;flex-wrap:wrap}}
.navlinks a{{color:var(--muted);text-decoration:none;font-size:.82rem;padding:.38rem .58rem;border-radius:7px}}
.navlinks a:hover{{color:var(--ink);background:var(--panel2)}}
.navstatus{{font-size:.72rem;color:var(--good);border:1px solid rgba(143,214,148,.24);
  background:rgba(143,214,148,.06);padding:.3rem .55rem;border-radius:999px;white-space:nowrap}}
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

.problem-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem}}
.problem{{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:1rem}}
.problem>div{{display:flex;justify-content:space-between;gap:.5rem;align-items:center}}
.problem h3{{margin:0;font-size:.92rem;color:var(--ink)}}
.problem p{{margin:.55rem 0 0;color:var(--muted);line-height:1.5;font-size:.84rem}}
.state{{font-size:.62rem;font-weight:800;letter-spacing:.08em;border-radius:999px;padding:.18rem .45rem}}
.state.live{{color:var(--good);border:1px solid rgba(143,214,148,.4)}}
.state.next{{color:var(--gold);border:1px solid rgba(255,209,102,.4)}}
.state.plan{{color:var(--muted);border:1px solid var(--line)}}
.alignment-links{{color:var(--muted);font-size:.88rem;margin:.9rem 0 0}}
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
.actiongrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}}
.actiongrid h3{{margin:.1rem 0 .5rem;font-size:.95rem;color:var(--ink)}}
.actiongrid p{{color:var(--muted);line-height:1.6;font-size:.9rem}}
.evidence-link{{font-size:.84rem}}
/* ---------- suite strip / footer ---------- */
.suite{{display:flex;gap:1rem;flex-wrap:wrap;align-items:stretch}}
.suite .card{{flex:1;min-width:260px}}
footer{{border-top:1px solid var(--line);margin-top:1rem;padding:1.6rem 0 3rem;
  color:var(--dim);font-size:.82rem;line-height:1.7}}
.hidden{{display:none!important}}
@media(max-width:700px){{.compbar{{min-width:70px}}thead th:nth-child(5),tbody td:nth-child(5){{display:none}}
  .navstatus{{display:none}}.navlinks a{{padding:.34rem .42rem}}}}
/* ---------- analytics + creature comforts ---------- */
.analytics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:.7rem}}
.metric{{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:.85rem 1rem;min-width:0}}
.metric .n{{font-size:1.45rem;font-weight:800;color:var(--gold);font-variant-numeric:tabular-nums;white-space:nowrap}}
.metric .n.compact{{font-size:1.08rem}}
.metric .l{{font-size:.73rem;color:var(--muted);margin-top:.25rem;line-height:1.35}}
.actionbtn,.copybtn{{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:.45rem .75rem;font-size:.78rem;cursor:pointer}}
.actionbtn:hover,.copybtn:hover{{border-color:var(--ember);color:var(--ink)}}
.control-meta{{margin-left:auto;color:var(--dim);font-size:.78rem;font-variant-numeric:tabular-nums}}
.candidate-note{{margin:-.2rem 0 1rem;color:var(--muted);font-size:.82rem;line-height:1.55}}
.candidate-note b{{color:var(--ink)}}
.copybtn{{margin-left:.6rem;padding:.3rem .55rem;vertical-align:middle}}
.dist-meta{{color:var(--muted);font-size:.88rem;margin:.4rem 0 .8rem}}
tbody tr.vol:focus-visible{{outline:2px solid var(--ember);outline-offset:-2px}}
.detail-grid code{{overflow-wrap:anywhere}}
@media(max-width:700px){{.control-meta{{width:100%;margin-left:0}}.actionbtn{{flex:1}}.analytics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}

</style></head><body>

<a class="skip" href="#main">Skip to evidence</a>
<nav class="topbar" aria-label="Primary"><div class="navinner">
  <a class="brand" href="./"><span class="brandmark">IQ</span><span>ScrolIQ</span></a>
  <div class="navlinks">
    <a href="#grand-prize">Grand Prize</a><a href="#evidence">Evidence</a>
    <a href="#leaderboard">Survey</a><a href="#method">Method</a>
    <a href="./september-2026.html">Writeup</a><a href="./october-2026.html">October goals</a><a href="{repo}">GitHub</a>
  </div>
  <span class="navstatus">● reproducible evidence</span>
</div></nav>

<header class="hero"><div class="wrap">
  <div class="eyebrow">VESUVIUS CHALLENGE · EVIDENCE THROUGH OCTOBER 1, 2026</div>
  <h1>Scrol<span class="q">IQ</span></h1>
  <p class="tagline">Diagnostics for reading Herculaneum scrolls. <em>Find the bottleneck.</em></p>
  <p class="lede">ScrolIQ is evolving from a scan-quality survey into an observability layer for the Vesuvius Challenge pipeline. The current score still measures sampled CT health from real level-0 voxels, and downstream state is never inferred from that score. Volume-bound passports can now attach spatial scan evidence, winding-input audits, native TIFXYZ Mesh IQ, exact-volume Fiber IQ, and ink leakage/provenance audits. Fiber IQ reads native VC3D fiber JSON, binds the report to the exact CT root, and audits persisted trace/fallback provenance plus line continuity; unbound or cross-volume evidence is excluded, while physical fiber/sheet identity, spiral-fit accuracy, label localization, and biological ink identity remain unknown until direct evidence exists. See the <a href="https://scrollprize.org/2026_open_problems">official open problems</a>, the <a href="https://github.com/Svyable/scrollq/blob/main/docs/open-problems-alignment.md">alignment roadmap</a>, and the <a href="#grand-prize">2027 Grand Prize campaign →</a></p>
  <div class="stats">
    <div class="stat"><div class="n">{n}</div><div class="l">scroll volumes scored</div></div>
    <div class="stat"><div class="n">{lo}&ndash;{hi}</div><div class="l">score range (0&ndash;100)</div></div>
    <div class="stat"><div class="n">0</div><div class="l">dead slices found under the strict detector</div></div>
    <div class="stat"><div class="n">{label_next_n}</div><div class="l">label-coverage candidates<br>top-quartile scan health · 0 published ink labels</div></div>
  </div>
</div></header>

<main id="main" class="wrap">


<div class="panel alignment" id="pipeline"><h2>Open-problem diagnostics<span class="sub">ScrolIQ maps evidence to the Vesuvius Challenge pipeline instead of treating one score as readiness.</span></h2>
<div class="problem-grid">
  <div class="problem"><div><h3>Scan diagnostics</h3><span class="state live">LIVE</span></div><p>Real-voxel health and coordinate-preserving spatial scan maps. Next: validated layer-separability and decohesion diagnostics.</p></div>
  <div class="problem"><div><h3>Surface topology</h3><span class="state next">NEXT</span></div><p>CT support, competing sheets, topology risk, and surface-placement uncertainty.</p></div>
  <div class="problem"><div><h3>Mesh connectivity</h3><span class="state live">LIVE</span></div><p><code>scroliq-mesh</code> audits native TIFXYZ and can bind official Villa CT-support and VC3D self-intersection reports to the exact surface; <code>scroliq-obj</code> covers triangular meshes. Both expose advisory findings or explicit <code>--fail-on-findings</code> CI gates. Sheet identity remains unproven.</p></div>
  <div class="problem"><div><h3>Fiber connectivity</h3><span class="state live">LIVE</span></div><p><code>scroliq-fiber</code> reads VC3D <code>vc3d_fiber</code> JSON v1/v3/v4 or CSV, hashes the exact input, validates persisted span/tracer metadata, and checks rendered continuity plus control-point/render consistency. A SHA-256-pinned public PHercParis4 run covers <b>8 fibers / 53,828 points</b>: 11 gap and 26 sharp-turn review candidates, with 0 control-line offsets/order inversions. With <code>--volume-root</code>, passports accept only exact-volume Fiber IQ; the public directory is not asserted to identify one exact CT volume, so that campaign is not passport evidence. <a href="https://github.com/Svyable/scrollq/tree/main/artifacts/2026-10-01-public-fiber-audit">Frozen evidence →</a></p></div>
  <div class="problem"><div><h3>Winding annotations</h3><span class="state live">LIVE</span></div><p><code>scroliq-winding</code> validates PointCollections structure, exact-file provenance, volume binding, winding semantics, and axial coverage, and checks winding numbers against the umbilicus before any fit. On the published PHercParis4 annotations: <b>2 of 13,700</b> comparable pairs out of radial order, both under 0.1 voxel; an injection control catches 89.5% of ±3 and 85.5% of ±5 single-point mis-numberings, and ±2 errors are undetectable by design. Next: patch attachment, graph consistency, and holonomy.</p></div>
  <div class="problem"><div><h3>Spiral fitting</h3><span class="state plan">PLANNED</span></div><p>Held-out constraint residuals, sensitivity, and under-constrained regions.</p></div>
  <div class="problem"><div><h3>Label quality</h3><span class="state live">LIVE</span></div><p>Label–volume coverage join: all 70 published ink-detection labels sit on PHercParis4 while {label_next_n} top-quartile volumes have zero published ink labels and are flagged as <b>label-coverage candidates</b> for review. This is a coverage gap, not evidence of ink or surface readiness. Next: physical label offset, snapping candidates, review queues.</p></div>
  <div class="problem"><div><h3>Ink reliability</h3><span class="state live">LIVE</span></div><p><code>scroliq-ink-audit</code> fails closed on declared train/evaluation overlap and audits checkpoint, seed, held-out-run, and falsification-control provenance. It is an evidence audit, not an ink verdict. Next: attach measured perturbation and cross-scroll results.</p></div>
  <div class="problem"><div><h3>Data scale</h3><span class="state live">LIVE</span></div><p>Cloud-native partial reads, decode provenance, exact coordinate bindings, file hashes, and machine-readable artifacts keep evidence inspectable across stages.</p></div>
  <div class="problem"><div><h3>Grand Prize</h3><span class="state plan">TARGET</span></div><p>One evidence trail from full recto coverage to TIFXYZ, renders, validation, and VC3D.</p></div>
</div>
<p class="alignment-links"><a href="https://scrollprize.org/2026_open_problems">Official 2026 Open Problems</a> · <a href="https://github.com/Svyable/scrollq/blob/main/docs/open-problems-alignment.md">ScrolIQ alignment roadmap</a></p>
</div>

<div class="panel" id="contracts"><h2>Evidence contracts<span class="sub">What a passing diagnostic proves — and what it deliberately leaves unknown.</span></h2>
  <div class="actiongrid">
    <div><h3>Mesh IQ</h3><p><b>Proves:</b> native TIFXYZ structure/provenance and selected grid-local geometry checks; validated upstream reports can additionally bind CT support and transverse self-intersection evidence. <b>Does not prove:</b> correct sheet identity.</p></div>
    <div><h3>Fiber IQ</h3><p><b>Proves:</b> exact-file/native-format provenance plus rendered-line continuity and control-point/render consistency checks when supplied; a pinned 8-fiber PHercParis4 campaign demonstrates the checks on public data. <b>Does not prove:</b> physical fiber identity, one-sheet continuity, exact CT-volume binding for that public campaign, or local CT orientation support.</p></div>
    <div><h3>Winding IQ</h3><p><b>Proves:</b> volume-bound PointCollections input integrity, descriptive axial coverage, and (with an umbilicus) radial-order review candidates with a measured recall. <b>Does not prove:</b> patch attachment, consistent cycles, ±1/±2 winding errors, or spiral-fit accuracy.</p></div>
    <div><h3>Ink IQ</h3><p><b>Proves:</b> declared spatial separation, checkpoint/seed provenance, and falsification-control coverage. <b>Does not prove:</b> that a prediction is ink.</p></div>
    <div><h3>Passport</h3><p>Cross-volume artifacts are excluded and failed audits block their stage. A passing component remains partial until the next direct evidence layer exists.</p></div>
  </div>
  <p class="alignment-links"><a href="https://github.com/Svyable/scrollq#mesh-iq-native-tifxyz-audit">Mesh IQ usage</a> · <a href="https://github.com/Svyable/scrollq#winding-annotation-audit">Winding IQ usage</a> · <a href="https://github.com/Svyable/scrollq#ink-iq-leakage-and-falsification-evidence-audit">Ink IQ usage</a></p>
</div>

<div class="panel" id="grand-prize"><h2>2027 Grand Prize campaign<span class="sub">Exact eligible inputs, held-out geometry, and ink falsification before whole-scroll commitment.</span></h2>
  <div class="actiongrid">
    <div><h3>Exact-volume eligibility</h3>
      <p><b>13 prize targets</b> are matched by exact volume ID. Same-scroll higher-resolution scans are explicitly excluded rather than silently substituted.</p>
      <p class="evidence-link"><a href="https://github.com/Svyable/scrollq/tree/main/artifacts/2026-09-30-grand-prize-qualifier">Frozen qualifier artifacts →</a></p></div>
    <div><h3>Blind geometry first</h3>
      <p>Each first-wave target gets the same deterministic <b>24-region</b> sample: 18 fit regions and <b>6 held-out</b> regions. Failed regions stay in the denominator.</p>
      <p class="evidence-link"><a href="https://github.com/Svyable/scrollq/blob/main/docs/grand-prize-probe-protocol.md">Blind probe protocol →</a></p></div>
    <div><h3>Try to falsify the ink</h3>
      <p>Promising signals are checked on the correct surface, <b>&plusmn;3 voxel</b> normal offsets, an adjacent winding, perturbed geometry, and an independent checkpoint/fold.</p></div>
    <div><h3>Reproducibility ledger</h3>
      <p>Exact inputs, hashes, fixed seeds, held-out splits, failure counts, experiment artifacts, and human-input time are part of the evidence trail — not cleanup work at submission time.</p></div>
  </div>
  <div class="scope"><b>No opaque winner score.</b> The frozen two-axis qualifier exposes a Pareto frontier rather than claiming readability. Its current frontier contains <b>PHerc0813</b> and <b>PHerc1447</b>; <b>PHerc0800</b> remains in the first-wave blind probe as a deliberately different geometry hypothesis.</div>
</div>

<div class="insights" id="evidence">
  <div class="card"><h3>Healthiest volume</h3>
    <p class="big">{top_id}</p>
    <p><b>{top_score}</b> / 100 · {top_spec}<br>Same scanner family
    (9.362&thinsp;&micro;m, 113&thinsp;keV) also produced the <b>lowest</b>
    scores — data condition, not hardware, drives the spread.</p></div>
  <div class="card"><h3>Label-coverage gap</h3>
    <p>All <b>70</b> published ink-detection labels sit on
    <b>PHercParis4</b> — quality rank <b>13 of 39 scrolls</b> (each scroll
    ranked by its best volume). The healthiest volumes (<b>{top_id}</b> {top_score}, <b>PHerc0139</b> 75.9) have
    <b>zero</b> ink labels. The published campaign exposes <b>{label_next_n}</b>
    top-quartile zero-label volumes as <b>label-coverage candidates</b> for review.
    This is a prioritization signal only: it does not claim that ink is present
    or that surface geometry is ready for annotation.</p></div>
  <div class="card"><h3>Failed the gate, fixed the experiment</h3>
    <p>The first 4-sample resample missed our own stability gate
    (<b>&rho; = 0.76</b>). We did not lower the threshold: we tripled the
    sampling budget and re-ran all 64 volumes. The frozen 12-sample result is
    <b>&rho; = 0.9948</b>, mean |&Delta;| <b>0.556</b>, top-10 overlap
    <b>10/10</b> — above the &rho; &ge; 0.85 gate. Caveat: dense-grid
    diagnostics show that sparse volumes can re-read shards, so achieved sample
    counts remain visible rather than being hidden behind the headline metric.
    <a href="https://github.com/Svyable/scrollq/blob/main/artifacts/2026-09-30-resampling-stability/stability-n12.json">Frozen stability JSON →</a></p></div>
</div>

<div class="panel"><h2>Scan-quality distribution<span class="sub">64 volumes · 5-point bins</span></h2>
  {hist}
  <p class="dist-meta" id="distMeta"></p>
  <p style="color:var(--muted);font-size:.88rem">Legacy triage bands: <span class="tier S">S</span> ≥ 70 ·
  <span class="tier A">A</span> 60&ndash;70 · <span class="tier B">B</span> 45&ndash;60 ·
  <span class="tier C">C</span> &lt; 45</p>
</div>

<div class="panel analytics-panel"><h2>Scan-quality analytics<span class="sub" id="analyticsSub">Updates with the current view</span></h2>
  <div class="analytics">
    <div class="metric"><div class="n" id="meanScore">—</div><div class="l">mean score</div></div>
    <div class="metric"><div class="n" id="medianScore">—</div><div class="l">median score</div></div>
    <div class="metric"><div class="n" id="topQuartile">—</div><div class="l">top-quartile cutoff</div></div>
    <div class="metric"><div class="n" id="uniqueScrolls">—</div><div class="l">unique scrolls</div></div>
    <div class="metric"><div class="n compact" id="tierMix">—</div><div class="l">S / A / B / C volumes</div></div>
    <div class="metric"><div class="n compact" id="segmentCoverage">—</div><div class="l">with segment roots</div></div>
  </div>
</div>

<div class="panel" id="leaderboard"><h2>Scan-quality survey<span class="sub">Click a column to sort · click a row for the full breakdown</span></h2>
  <div class="controls">
    <input id="q" type="search" placeholder="Filter by scroll id…  / to focus" aria-label="filter leaderboard">
    <button class="tierbtn on" data-t="">all</button>
    <button class="tierbtn" data-t="S">S</button>
    <button class="tierbtn" data-t="A">A</button>
    <button class="tierbtn" data-t="B">B</button>
    <button class="tierbtn" data-t="C">C</button>
    <button class="tierbtn" data-t="label">label-coverage candidates</button>
    <button class="tierbtn" data-t="unlabeled">0 labels</button>
    <button class="tierbtn" data-t="segments">has segments</button>
    <button class="actionbtn" id="reset" type="button">reset</button>
    <button class="actionbtn" id="csv" type="button">export CSV</button>
    <span class="control-meta" id="resultCount" aria-live="polite"></span>
  </div>
  {band_note}<p class="candidate-note"><b>Label-coverage candidate:</b> a volume in the top quartile of this scan-health survey with zero published ink-detection labels. It is a review-priority flag, not evidence that ink is present or that a usable surface is available.</p>
  <div style="overflow-x:auto"><table id="lb"><thead><tr>
    {rank_th}<th data-k="id">volume</th><th data-k="score">score</th>
    <th data-k="tier">tier</th><th>components</th>
    <th data-k="signal">signal</th><th data-k="tex">texture</th><th data-k="dyn">dynamic</th>
    <th data-k="pen">penalties</th><th data-k="ink">ink labels</th><th data-k="seg">segments</th><th>note</th>
  </tr></thead><tbody>{rows}</tbody></table></div>
</div>

<div class="panel" id="method"><h2>Scan-health score (one diagnostic)</h2>
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
  Campaign request: up to <b>12 &times; 128&sup3;</b> chunks per volume,
  spread across the shard grid. Sparse volumes may decode fewer; the achieved
  count and sampling provenance stay attached to every result. Decoded with the
  vendored libvolcomp via
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
    issues one verdict: <b>TRAIN / CAUTION / DO NOT TRAIN</b>. Fails closed: unreadable or missing integrity evidence is DO NOT TRAIN, never a pass.</p>
    <p><code>scrollq-health --root &lt;volume&gt;</code></p></div>
</div></div>

</main>

<footer><div class="wrap">
  Generated by <a href="{repo}">ScrolIQ</a> from public dl.ash2txt.org volumes,
  {stamp}. Scores are heuristic and published with their components — audit the
  weights, don't worship the ranking. Companion:
  <a href="https://github.com/Svyable/zarr-pyramid-audit">zarr-pyramid-audit</a>.
  · <a href="./september-2026.html">September 2026 writeup →</a>
  · <a href="./october-2026.html">October 2026 goals →</a>
</div></footer>

<script>
(function dashboard(){{
  const tb = document.querySelector("#lb tbody");
  const rows = Array.from(tb.querySelectorAll("tr.vol"));
  rows.forEach(r => {{ r._detail = r.nextElementSibling; }});

  const q = document.getElementById("q");
  const resultCount = document.getElementById("resultCount");
  let sortK = "score", asc = false, tierF = "", qF = "", currentRows = rows.slice();

  function tierOf(r){{ return r.dataset.tier; }}
  function scoreStats(sample){{
    const values = sample.map(r => Number(r.dataset.score)).filter(Number.isFinite).sort((a,b) => a-b);
    if (!values.length) return null;
    const mean = values.reduce((a,b) => a+b, 0) / values.length;
    const mid = Math.floor(values.length / 2);
    const median = values.length % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
    const desc = values.slice().reverse();
    const qIndex = Math.max(0, Math.ceil(desc.length * .25) - 1);
    return {{ mean, median, topQ: desc[qIndex] }};
  }}
  function updateAnalytics(sample){{
    const stats = scoreStats(sample);
    const scrolls = new Set(sample.map(r => r.querySelector(".scrollid")?.textContent.trim()).filter(Boolean));
    const tiers = {{S:0,A:0,B:0,C:0}};
    sample.forEach(r => {{ if (tiers[r.dataset.tier] !== undefined) tiers[r.dataset.tier]++; }});
    const segmented = sample.filter(r => Number(r.dataset.seg) > 0).length;
    document.getElementById("analyticsSub").textContent =
      sample.length ? `${{sample.length}} visible volumes · ${{scrolls.size}} scrolls` : "No rows match the current view";
    document.getElementById("meanScore").textContent = stats ? stats.mean.toFixed(1) : "—";
    document.getElementById("medianScore").textContent = stats ? stats.median.toFixed(1) : "—";
    document.getElementById("topQuartile").textContent = stats ? `≥ ${{stats.topQ.toFixed(1)}}` : "—";
    document.getElementById("uniqueScrolls").textContent = scrolls.size || "—";
    document.getElementById("tierMix").textContent = `${{tiers.S}} / ${{tiers.A}} / ${{tiers.B}} / ${{tiers.C}}`;
    document.getElementById("segmentCoverage").textContent = `${{segmented}} / ${{sample.length}}`;
  }}
  function matchesFilter(r){{
    if (!tierF) return true;
    if (tierF === "label") return r.dataset.label === "1";
    if (tierF === "unlabeled") return Number(r.dataset.ink) === 0;
    if (tierF === "segments") return Number(r.dataset.seg) > 0;
    return tierOf(r) === tierF;
  }}
  const BANDS = {bands_js};
  function apply(){{
    let vis = rows.filter(r =>
      matchesFilter(r) &&
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
      r.setAttribute("aria-expanded", "false");
      if (!BANDS) r.querySelector(".rn").textContent = i + 1;
      frag.append(r, r._detail);
    }});
    rows.forEach(r => {{
      if (!vis.includes(r)) {{
        r.classList.add("hidden");
        r._detail.classList.add("hidden");
        r.setAttribute("aria-expanded", "false");
      }}
    }});
    tb.append(frag);
    currentRows = vis;
    resultCount.textContent = `${{vis.length}} of ${{rows.length}} shown`;
    updateAnalytics(vis);
  }}
  function resetView(){{
    sortK = "score"; asc = false; tierF = ""; qF = ""; q.value = "";
    document.querySelectorAll(".tierbtn").forEach(x => x.classList.toggle("on", x.dataset.t === ""));
    document.querySelectorAll("#lb thead th .arr").forEach(e => e.remove());
    apply();
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
  q.addEventListener("input", e => {{
    qF = e.target.value.trim().toLowerCase(); apply();
  }});
  document.getElementById("reset").addEventListener("click", resetView);

  function csvCell(value){{
    const s = String(value ?? "").replace(/"/g, '""');
    return '"' + s + '"';
  }}
  document.getElementById("csv").addEventListener("click", () => {{
    const head = [BANDS ? "rank_band" : "view_rank","volume","acquisition","score","tier","signal","texture","dynamic","penalty","ink_labels","segments","label_coverage_candidate","root"];
    const lines = [head.map(csvCell).join(",")];
    currentRows.forEach((r, i) => {{
      const root = r._detail.querySelector("code")?.textContent.trim() || "";
      const values = [
        BANDS ? (r.dataset.band || "") : i + 1,
        r.querySelector(".scrollid")?.textContent.trim() || "",
        r.querySelector(".volsub")?.textContent.trim() || "",
        r.dataset.score, r.dataset.tier, r.dataset.signal, r.dataset.tex,
        r.dataset.dyn, r.dataset.pen, r.dataset.ink, r.dataset.seg,
        r.dataset.label === "1" ? "yes" : "no", root
      ];
      lines.push(values.map(csvCell).join(","));
    }});
    const blob = new Blob([lines.join("\n")], {{type:"text/csv;charset=utf-8"}});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "scrollq-filtered.csv";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  }});

  rows.forEach(r => {{
    r.tabIndex = 0;
    r.setAttribute("role", "button");
    r.setAttribute("aria-expanded", "false");
    const toggle = () => {{
      if (!r._detail) return;
      const opening = r._detail.classList.contains("hidden");
      r._detail.classList.toggle("hidden");
      r.setAttribute("aria-expanded", opening ? "true" : "false");
    }};
    r.addEventListener("click", toggle);
    r.addEventListener("keydown", e => {{
      if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); toggle(); }}
    }});
    const rootCode = r._detail?.querySelector("code");
    if (rootCode) {{
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "copybtn"; btn.textContent = "copy root";
      btn.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText(rootCode.textContent.trim());
          btn.textContent = "copied";
          setTimeout(() => {{ btn.textContent = "copy root"; }}, 1200);
        }} catch {{
          btn.textContent = "copy failed";
          setTimeout(() => {{ btn.textContent = "copy root"; }}, 1400);
        }}
      }});
      rootCode.parentElement.appendChild(btn);
    }}
  }});

  const full = scoreStats(rows);
  if (full) {{
    document.getElementById("distMeta").textContent =
      `Full corpus: mean ${{full.mean.toFixed(1)}} · median ${{full.median.toFixed(1)}} · top quartile ≥ ${{full.topQ.toFixed(1)}}.`;
  }}
  document.addEventListener("keydown", e => {{
    const tag = document.activeElement?.tagName;
    if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {{
      e.preventDefault(); q.focus();
    }} else if (e.key === "Escape" && (qF || tierF)) {{
      resetView(); q.blur();
    }}
  }});
  const scoreTh = document.querySelector('#lb thead th[data-k="score"]');
  if (scoreTh) {{ const s0 = document.createElement("span"); s0.className = "arr"; s0.textContent = " ▼"; scoreTh.appendChild(s0); }}
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


def _band_note(data: dict, ranked: int, published: dict[str, float]) -> str:
    d = data["decision"]
    rho = d.get("rho")
    pooled = data.get("pooled_scores", {})
    common = [r for r in pooled if r in published]
    mad = (sum(abs(pooled[r] - published[r]) for r in common) / len(common)
           if common else None)
    bias = ("" if mad is None else
            f' Those scores came from a sample that can sit in one or two slabs '
            f'of a scroll: across these {len(common)} volumes they differ from '
            f'the stability test\u2019s pooled 96-chunk score by {mad:.1f} points '
            'on average, so treat a single score as approximate too.')
    return (
        '<p class="candidate-note"><b>Ranks are bands.</b> The pre-registered '
        f'stability test (<a href="./stability-v2-protocol.md">protocol</a>) '
        f'returned <b>{html.escape(d["verdict"])}</b>: Spearman \u03c1 = '
        f'{rho:.3f} between two disjoint 48-chunk samples, against a gate of '
        f'{d["gate_rho"]}. So each volume shows the best\u2013worst rank it takes '
        f'across the two runs and their pool, among the {ranked} volumes dense '
        'enough for the test; \u2014 marks a volume too sparse to rank. Scores '
        f'are the published September campaign.{bias}</p>')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--coverage", default=None)
    ap.add_argument(
        "--rank-bands", default=None,
        help="stability-v2.json from bin/stability_v2.py; replaces the rank "
             "column with each volume's rank band (docs/stability-v2-protocol.md)")
    args = ap.parse_args()
    bands_data = (json.load(open(args.rank_bands, encoding="utf-8"))
                  if args.rank_bands else None)
    bands = bands_data["rank_bands"] if bands_data else None
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
    aria = "Score distribution, 5-point bins: " + ", ".join(
        f"{b0}\u2013{b0 + 5}: {c}" for (b0, _), c in zip(bins, counts))
    hist = "".join(
        f'<div class="bar"><div class="bv">{c}</div>'
        f'<div class="fill" style="height:{100 * c / cmax:.0f}%"></div>'
        f'<div class="bl" aria-hidden="false">{b0}</div></div>'
        for (b0, _), c in zip(bins, counts))
    hist = f'<div class="hist" role="img" aria-label="{html.escape(aria)}">{hist}</div>'

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
        flag = ('<span class="flag" title="Top-quartile scan health with zero published ink-detection labels">'
                'label-coverage candidate</span>') if is_label else ""
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
            bits.append("label-coverage candidate — top-quartile scan health with zero "
                        "published ink-detection labels; prioritization flag only, "
                        "not evidence of ink or surface readiness")
        why = " · ".join(html.escape(b) for b in bits)
        if bands is None:
            band_attr, rn_cell = "", f'<td class="num rn">{i}</td>'
        elif v["root"] in bands:
            b = bands[v["root"]]
            text = (f'{b["best"]}' if b["best"] == b["worst"]
                    else f'{b["best"]}\u2013{b["worst"]}')
            band_attr = f' data-band="{text}"'
            rn_cell = (f'<td class="num rn" title="best\u2013worst rank of '
                       f'{len(bands)} across two disjoint 48-chunk runs and '
                       f'their pool">{text}</td>')
        else:
            band_attr = ' data-band=""'
            rn_cell = ('<td class="num rn" title="too sparse for two disjoint '
                       '48-chunk samples; not ranked">\u2014</td>')
        rows.append(
            f'<tr class="vol" data-rank="{i}" data-id="{html.escape(scroll.lower())} {html.escape(fname.lower())}"'
            f' data-score="{v["score"]:.1f}" data-tier="{t}"'
            f' data-signal="{s40:.1f}" data-tex="{t30:.1f}" data-dyn="{d20:.1f}"'
            f' data-pen="{pen:.1f}" data-ink="{ink}" data-seg="{seg}"'
            f' data-label="{"1" if is_label else "0"}"'
            f'{band_attr}>'
            f'{rn_cell}'
            f'<td><span class="scrollid">{html.escape(scroll)}</span><br>'
            f'<span class="volsub">{html.escape(spec)}</span></td>'
            f'<td class="num score" style="color:{score_color(v["score"])}"'
            f' title="chunk scores: {v.get("score_min", 0):.0f}–{v.get("score_max", 0):.0f} (std {v.get("score_std", 0):.1f})">'
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
            f'<div><div class="k">chunk score spread</div><div class="v">'
            f'{v.get("score_min", 0):.0f}–{v.get("score_max", 0):.0f} '
            f'(std {v.get("score_std", 0):.1f})</div></div>'
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
        hist=hist, rows="\n".join(rows), stamp=stamp,
        rank_th=(
            '<th data-k="rank">#</th>' if bands is None else
            '<th data-k="rank" title="rank band from the pre-registered '
            'stability v2 test">rank band</th>'),
        band_note=("" if bands_data is None else
                   _band_note(bands_data, len(bands),
                              {v["root"]: v["score"] for v in ok})),
        bands_js="true" if bands is not None else "false")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.out} ({len(ok)} volumes)")
