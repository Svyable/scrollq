"""docs/october-2026.html is a goals page: it must say so, and every
local link it relies on must exist (artifacts, docs, sibling pages)."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "october-2026.html"
REPO_TREE = "https://github.com/Svyable/scrollq/tree/main/"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.extend(v for k, v in attrs if k == "href" and v)


def _hrefs():
    parser = _Links()
    parser.feed(PAGE.read_text(encoding="utf-8"))
    return parser.hrefs


def test_page_is_labelled_as_goals_not_results():
    text = PAGE.read_text(encoding="utf-8")
    assert "goals, not results" in text
    for goal in ("O1", "O2", "O3", "O4", "O5", "O6"):
        assert f'id="{goal.lower()}"' in text


def test_local_and_repo_tree_links_resolve():
    missing = []
    for href in _hrefs():
        if href.startswith(REPO_TREE):
            target = ROOT / href[len(REPO_TREE):]
        elif urlsplit(href).scheme or href.startswith("#"):
            continue
        else:
            path = urlsplit(href).path or "index.html"
            target = PAGE.parent / (path if not path.endswith("/") else path + "index.html")
        if not target.exists():
            missing.append(href)
    assert not missing, missing


def test_dashboard_and_september_page_link_to_october_goals():
    for name in ("index.html", "september-2026.html"):
        assert "./october-2026.html" in (ROOT / "docs" / name).read_text(encoding="utf-8")
