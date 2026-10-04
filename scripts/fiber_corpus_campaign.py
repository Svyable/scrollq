#!/usr/bin/env python3
"""Census every public PHercParis4 VC3D fiber with ScrolIQ Fiber IQ (October goal O4).

The 2026-10-01 campaign (`public_fiber_campaign.py`) audited eight hash-pinned
fibers.  This campaign lists the whole public ``fibers/`` directory, audits
every ``.json`` object in it, and records each object's SHA-256 so the census
itself becomes a frozen manifest.

Fail-closed rules (AGENTS.md lessons 9 and 12):

* listings are parsed with a real parser (JSON API or ``html.parser``), never
  a regex over raw HTML;
* a source is accepted only if its listing contains all eight pinned objects
  from the 2026-10-01 campaign *and* their downloaded bytes match the pinned
  SHA-256 -- that is the positive control that the listing really is the
  public fiber directory;
* zero listed objects, a failed positive control, or any download / parse
  failure makes the campaign exit non-zero with status ``unverified``.

No CT volume binding is asserted, so outputs are not passport evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_fiber_campaign import EXPECTED_SHA256 as PINNED_SHA256  # noqa: E402
from public_fiber_campaign import _compact  # noqa: E402
from scrollq.fiber_audit import audit_vc3d_json  # noqa: E402

CAMPAIGN_SCHEMA_VERSION = 1
USER_AGENT = "scrollq-fiber-corpus-campaign/1"

HF_API_TREE = (
    "https://huggingface.co/api/buckets/scrollprize/datasets/tree/"
    "spiral/PHercParis4/fibers"
)
HF_HTML_TREE = (
    "https://huggingface.co/buckets/scrollprize/datasets/tree/"
    "spiral/PHercParis4/fibers"
)
HF_RESOLVE = (
    "https://huggingface.co/buckets/scrollprize/datasets/resolve/"
    "spiral/PHercParis4/fibers"
)
DL_INDEX = "https://dl.ash2txt.org/datasets/spiral_datasets/PHercParis4/fibers/"


def _get(url: str, timeout: int = 120) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.hrefs.append(value)


def json_names_from_html(html: str, base_url: str) -> list[str]:
    """Return basenames of ``.json`` links that live directly under *base_url*."""
    parser = _AnchorParser()
    parser.feed(html)
    base = urllib.parse.urlparse(base_url.rstrip("/") + "/")
    names: set[str] = set()
    for href in parser.hrefs:
        target = urllib.parse.urlparse(urllib.parse.urljoin(base.geturl(), href))
        path = urllib.parse.unquote(target.path)
        # Accept the directory's own children, and HF-style blob/resolve links
        # whose path ends in .../fibers/<name>.json.
        if not path.endswith(".json"):
            continue
        parent, _, name = path.rpartition("/")
        if parent.rstrip("/").endswith("/fibers") and name:
            names.add(name)
    return sorted(names)


def json_names_from_hf_api(pages: list[Any]) -> list[str]:
    names: set[str] = set()
    for page in pages:
        entries = page if isinstance(page, list) else page.get("entries") or page.get("files") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") not in (None, "file"):
                continue
            path = str(entry.get("path") or entry.get("name") or "")
            if path.endswith(".json"):
                names.add(path.rpartition("/")[2])
    return sorted(names)


def _next_link(headers: dict[str, str]) -> str | None:
    for part in headers.get("link", "").split(","):
        section = part.split(";")
        if len(section) >= 2 and 'rel="next"' in section[1].strip():
            return section[0].strip().strip("<>")
    return None


def list_hf_api() -> list[str]:
    pages: list[Any] = []
    url: str | None = HF_API_TREE + "?recursive=false"
    while url:
        body, headers = _get(url)
        pages.append(json.loads(body))
        url = _next_link(headers)
    return json_names_from_hf_api(pages)


def list_hf_html() -> list[str]:
    body, _ = _get(HF_HTML_TREE)
    return json_names_from_html(body.decode("utf-8", "replace"), HF_HTML_TREE)


def list_dl_index() -> list[str]:
    body, _ = _get(DL_INDEX)
    return json_names_from_html(body.decode("utf-8", "replace"), DL_INDEX)


SOURCES: tuple[tuple[str, Callable[[], list[str]], str], ...] = (
    ("huggingface-api", list_hf_api, HF_RESOLVE),
    ("huggingface-html", list_hf_html, HF_RESOLVE),
    ("dl.ash2txt.org", list_dl_index, DL_INDEX.rstrip("/")),
)


def _resolve_url(base: str, name: str) -> str:
    url = f"{base}/{urllib.parse.quote(name)}"
    return url + "?download=true" if "huggingface.co" in base else url


def positive_control(names: list[str]) -> list[str]:
    """Pinned 2026-10-01 objects absent from a listing."""
    return sorted(set(PINNED_SHA256) - set(names))


def _audit_one(base: str, name: str, tmpdir: Path) -> dict[str, Any]:
    url = _resolve_url(base, name)
    try:
        payload, _ = _get(url)
    except Exception as exc:  # network errors are recorded, never dropped
        return {"file": name, "source_url": url, "status": "download-fail",
                "error": f"{type(exc).__name__}: {exc}"}
    digest = hashlib.sha256(payload).hexdigest()
    pinned = PINNED_SHA256.get(name)
    if pinned is not None and digest != pinned:
        return {"file": name, "source_url": url, "status": "hash-mismatch",
                "sha256": digest, "expected_sha256": pinned, "bytes": len(payload)}
    path = tmpdir / name
    path.write_bytes(payload)
    try:
        audit = audit_vc3d_json(path)
    except Exception as exc:
        return {"file": name, "source_url": url, "status": "audit-error", "sha256": digest,
                "bytes": len(payload), "error": f"{type(exc).__name__}: {exc}"}
    row = _compact(name, audit)
    row["source_url"] = url.split("?")[0]
    row["pinned_control"] = pinned is not None
    return row


def summarize(rows: list[dict[str, Any]], *, source: str | None,
              attempts: list[dict[str, Any]], listed: int,
              control_missing: list[str]) -> dict[str, Any]:
    statuses = Counter(str(r.get("status", "unknown")) for r in rows)
    kinds: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    for r in rows:
        kinds.update(r.get("finding_kinds") or {})
        prefixes[r["file"].split("_", 1)[0]] += 1
    audited = [r for r in rows if r.get("status") in ("pass", "caution", "fail")]

    def total(key: str) -> int:
        return sum(int(r.get(key) or 0) for r in audited)

    controls = [r for r in rows if r.get("pinned_control")]
    control_ok = (
        bool(source) and not control_missing
        and len(controls) == len(PINNED_SHA256)
        and all(r.get("status") in ("pass", "caution") for r in controls)
    )
    failures = sum(statuses.get(k, 0) for k in ("audit-error", "download-fail", "hash-mismatch"))
    if not rows or not control_ok:
        verdict = "unverified"
    elif failures:
        verdict = "incomplete"
    else:
        verdict = "complete"
    return {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign": "PHercParis4-public-vc3d-fiber-corpus",
        "verdict": verdict,
        "source": {
            "accepted": source,
            "attempts": attempts,
            "volume_binding": "none: no exact CT volume root is inferred",
        },
        "positive_control": {
            "rule": "all 8 objects pinned by the 2026-10-01 campaign must be listed and hash-match",
            "pinned": len(PINNED_SHA256),
            "missing_from_listing": control_missing,
            "passed": control_ok,
        },
        "parameters": {"gap_factor": 4.0, "turn_degrees": 60.0, "control_line_factor": 4.0},
        "listed": listed,
        "audited": len(audited),
        "status_counts": dict(sorted(statuses.items())),
        "annotator_prefix_counts": dict(sorted(prefixes.items())),
        "totals": {
            "bytes": total("bytes"),
            "line_points": total("line_points"),
            "control_points": total("control_points"),
            "segments": total("segments"),
            "native_trace_segments": total("native_trace_segments"),
            "fallback_segments": total("fallback_segments"),
            "gaps": total("gaps"),
            "sharp_turns": total("sharp_turns"),
            "control_line_offsets": total("control_line_offsets"),
            "control_order_inversions": total("control_order_inversions"),
        },
        "fibers_with_any_finding": sum(1 for r in audited if r.get("finding_kinds")),
        "finding_kind_totals": dict(sorted(kinds.items())),
        "manifest_sha256": hashlib.sha256(
            "".join(f"{r['file']}\t{r.get('sha256')}\n" for r in sorted(rows, key=lambda r: r["file"])).encode()
        ).hexdigest(),
        "rows": sorted(rows, key=lambda r: r["file"]),
        "limitations": [
            "Census of the public fibers/ directory as listed on the run date; later uploads are not covered.",
            "No exact CT volume binding is asserted, so these reports are not passport evidence.",
            "Gaps and sharp turns are review candidates, not proof of a sheet switch or wrong fiber.",
            "CT-conditioned support (the second half of O4) is not measured here.",
        ],
    }


def run_campaign(workers: int = 8) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for label, lister, base in SOURCES:
        try:
            names = lister()
        except Exception as exc:
            attempts.append({"source": label, "error": f"{type(exc).__name__}: {exc}"})
            continue
        missing = positive_control(names)
        attempts.append({"source": label, "listed": len(names), "control_missing": len(missing)})
        if not names or missing:
            continue
        with tempfile.TemporaryDirectory(prefix="scrollq-fiber-corpus-") as tmp:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(lambda n: _audit_one(base, n, Path(tmp)), names))
        return summarize(rows, source=label, attempts=attempts, listed=len(names),
                         control_missing=missing)
    return summarize([], source=None, attempts=attempts, listed=0,
                     control_missing=sorted(PINNED_SHA256))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    summary = run_campaign(args.workers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    head = {k: v for k, v in summary.items() if k != "rows"}
    print(json.dumps(head, indent=2))
    return 0 if summary["verdict"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
