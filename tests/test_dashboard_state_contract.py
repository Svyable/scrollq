"""State-transition contract for the generated, public ScrolIQ dashboard."""

from pathlib import Path

from scrollq.leaderboard import PAGE


def _script(page: str) -> str:
    return page.split("<script>", 1)[1].split("</script>", 1)[0]


def test_committed_dashboard_uses_the_same_state_machine_as_generator():
    # Python's .format escapes the JS braces; {bands_js} is the only
    # script-level substitution (the published survey uses rank bands).
    generated = _script(PAGE).replace("{{", "{").replace("}}", "}")
    generated = generated.replace("{bands_js}", "true")
    published = _script(Path("docs/index.html").read_text(encoding="utf-8"))
    assert generated == published


def test_view_transitions_have_accessible_and_shareable_contract():
    js = _script(PAGE)
    for event in ('case "sort":', 'case "tier":', 'case "query":', 'case "reset":'):
        assert event in js
    for guard in ("SORT_KEYS.has(value)", "TIERS.has(value)", "SORT_KEYS.has(sort)", "TIERS.has(tier)"):
        assert guard in js
    assert 'b.setAttribute("aria-pressed", String(selected))' in js
    assert 'th.setAttribute("aria-sort",' in js
    assert 'th.addEventListener("keydown",' in js
    assert 'r.setAttribute("aria-controls",' in js
    assert 'r._detail.classList.toggle("hidden", !expanded)' in js
    assert "window.history.replaceState(" in js
    assert "url.searchParams.delete(k)" in js
    assert "url.pathname + url.search + url.hash" in js
    assert "Object.assign(view, DEFAULT)" in js
