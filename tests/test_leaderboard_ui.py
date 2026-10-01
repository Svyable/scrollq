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
    'label-coverage candidates',
    'Label-coverage candidate:',
    'Winding annotations',
    'scroliq-mesh',
    'scroliq-fiber',
    'vc3d_fiber',
    '--fail-on-findings',
    '--volume-root',
    'cross-volume evidence',
    'scroliq-ink-audit',
    'Evidence contracts',
    'Data scale',
)


def test_generator_preserves_interactive_audit_features():
    for marker in MARKERS:
        assert marker in PAGE


def test_committed_pages_output_preserves_interactive_audit_features():
    page = Path("docs/index.html").read_text(encoding="utf-8")
    for marker in MARKERS:
        assert marker in page


def test_generator_does_not_expose_internal_label_next_copy():
    assert "label next" not in PAGE.lower()
    assert "label-coverage candidate" in PAGE


def test_committed_pages_copy_is_clean_and_not_duplicated():
    page = Path("docs/index.html").read_text(encoding="utf-8")
    assert "label next" not in page.lower()
    assert "label-coverage candidate" in page
    assert page.count('id="grand-prize"') == 1
