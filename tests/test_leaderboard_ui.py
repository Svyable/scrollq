from pathlib import Path

from scrollq.leaderboard import PAGE


MARKERS = (
    'id="meanScore"',
    'id="medianScore"',
    'id="topQuartile"',
    'data-t="unlabeled"',
    'data-t="segments"',
    'id="csv"',
    'copy root',
    'e.key === "/"',
    'e.key === "Escape"',
)


def test_generator_preserves_interactive_audit_features():
    for marker in MARKERS:
        assert marker in PAGE


def test_committed_pages_output_preserves_interactive_audit_features():
    page = Path("docs/index.html").read_text(encoding="utf-8")
    for marker in MARKERS:
        assert marker in page
