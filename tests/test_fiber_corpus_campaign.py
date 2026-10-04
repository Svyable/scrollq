import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/fiber_corpus_campaign.py"


def _module():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("fiber_corpus_campaign", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_html_listing_uses_real_parser_and_keeps_only_direct_json_children():
    m = _module()
    base = "https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/fibers/"
    html = """
    <html><body>
    <a href="../">../</a>
    <a href="dj_20260717T165249423_000001.json">dj_...json</a>
    <a href='et_2026%2Ba.json'>quoted</a>
    <a href="/datasets/spiral_datasets/PHercParis4/fibers/kb_x.json">abs</a>
    <a href="/buckets/scrollprize/datasets/blob/spiral/PHercParis4/fibers/lt_y.json">hf</a>
    <a href="/datasets/spiral_datasets/PHercParis4/other/z.json">elsewhere</a>
    <a href="notes.txt">txt</a>
    </body></html>
    """
    assert m.json_names_from_html(html, base) == [
        "dj_20260717T165249423_000001.json",
        "et_2026+a.json",
        "kb_x.json",
        "lt_y.json",
    ]


def test_hf_api_listing_skips_directories_and_handles_pages():
    m = _module()
    pages = [
        [{"type": "file", "path": "spiral/PHercParis4/fibers/a.json"},
         {"type": "directory", "path": "spiral/PHercParis4/fibers/sub.json"}],
        {"entries": [{"type": "file", "path": "spiral/PHercParis4/fibers/b.json"},
                     {"type": "file", "path": "spiral/PHercParis4/fibers/readme.md"}]},
    ]
    assert m.json_names_from_hf_api(pages) == ["a.json", "b.json"]
    assert m._next_link({"link": '<https://x/next?c=2>; rel="next"'}) == "https://x/next?c=2"
    assert m._next_link({}) is None


def test_positive_control_requires_every_pinned_object():
    m = _module()
    pinned = sorted(m.PINNED_SHA256)
    assert m.positive_control(pinned + ["extra.json"]) == []
    assert m.positive_control(pinned[1:]) == [pinned[0]]


def test_empty_or_uncontrolled_campaign_is_unverified_not_clean():
    m = _module()
    empty = m.summarize([], source=None, attempts=[], listed=0,
                        control_missing=sorted(m.PINNED_SHA256))
    assert empty["verdict"] == "unverified"
    assert empty["positive_control"]["passed"] is False

    # A listing that audits cleanly but omits the pinned controls is still unverified.
    rows = [{"file": "zz_1.json", "status": "pass", "sha256": "0" * 64}]
    no_control = m.summarize(rows, source="dl.ash2txt.org", attempts=[], listed=1,
                             control_missing=sorted(m.PINNED_SHA256))
    assert no_control["verdict"] == "unverified"


def test_download_failures_mark_campaign_incomplete_and_audit_fail_is_a_finding():
    m = _module()
    controls = [{"file": n, "status": "caution", "sha256": h, "pinned_control": True,
                 "bytes": 1, "gaps": 1, "finding_kinds": {"gap": 1}}
                for n, h in m.PINNED_SHA256.items()]
    broken = {"file": "xx_bad.json", "status": "fail", "sha256": "1" * 64, "bytes": 2}
    complete = m.summarize(controls + [broken], source="dl.ash2txt.org", attempts=[],
                           listed=9, control_missing=[])
    assert complete["verdict"] == "complete"
    assert complete["audited"] == 9
    assert complete["totals"]["gaps"] == 8
    assert complete["fibers_with_any_finding"] == 8

    lost = {"file": "xx_lost.json", "status": "download-fail"}
    incomplete = m.summarize(controls + [lost], source="dl.ash2txt.org", attempts=[],
                             listed=9, control_missing=[])
    assert incomplete["verdict"] == "incomplete"
    assert incomplete["status_counts"]["download-fail"] == 1


def test_frozen_census_is_internally_consistent_and_contains_the_pinned_controls():
    import hashlib
    import json

    m = _module()
    report = json.loads((ROOT / "artifacts/2026-10-04-fiber-corpus-census/summary.json").read_text())
    rows = report["rows"]
    assert report["verdict"] == "complete" and report["positive_control"]["passed"]
    assert report["listed"] == report["audited"] == len(rows) == 136
    assert {r["file"]: r["sha256"] for r in rows if r["file"] in m.PINNED_SHA256} == m.PINNED_SHA256
    assert sum(r["gaps"] for r in rows) == report["totals"]["gaps"] == 388
    assert sum(r["sharp_turns"] for r in rows) == report["totals"]["sharp_turns"] == 519
    assert sum(r["fallback_segments"] for r in rows) == 502
    assert sum(r["gaps"] for r in rows if not r["fallback_segments"]) == 0
    manifest = "".join(f"{r['file']}\t{r['sha256']}\n" for r in sorted(rows, key=lambda r: r["file"]))
    assert hashlib.sha256(manifest.encode()).hexdigest() == report["manifest_sha256"]
