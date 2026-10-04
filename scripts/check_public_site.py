#!/usr/bin/env python3
"""Fail CI when the public README/Pages surface has broken local paths or JS."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REQUIRED = [
    DOCS / "index.html",
    DOCS / "progress.html",
    DOCS / "favicon.svg",
    ROOT / "README.md",
]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.inline_scripts: list[str] = []
        self._script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if values.get("name"):
            self.ids.add(values["name"])
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(values[key])
        if tag == "script" and not values.get("src"):
            self._script = []

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.inline_scripts.append("".join(self._script))
            self._script = None


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def resolve_local(source: Path, raw: str) -> tuple[Path | None, str]:
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or raw.startswith("//"):
        return None, ""
    path = unquote(parts.path)
    if not path:
        return source, parts.fragment
    if path.startswith("/scrollq/"):
        target = DOCS / path[len("/scrollq/") :]
    elif path.startswith("/"):
        return None, ""
    else:
        target = source.parent / path
    target = target.resolve()
    try:
        target.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise AssertionError(f"{source}: local link escapes repository: {raw}") from exc
    if target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def check_html() -> list[str]:
    errors: list[str] = []
    pages = sorted(DOCS.glob("*.html"))
    parsed = {page.resolve(): parse_page(page) for page in pages}

    for page, parser in parsed.items():
        for raw in parser.links:
            target, fragment = resolve_local(page, raw)
            if target is None:
                continue
            if not target.exists():
                errors.append(f"{page.relative_to(ROOT)}: missing local target {raw}")
                continue
            if fragment and target.suffix.lower() == ".html":
                target_parser = parsed.get(target.resolve()) or parse_page(target)
                if fragment not in target_parser.ids:
                    errors.append(
                        f"{page.relative_to(ROOT)}: missing anchor #{fragment} in "
                        f"{target.relative_to(ROOT)}"
                    )

    node = shutil.which("node")
    if not node:
        errors.append("node is required to syntax-check inline JavaScript")
        return errors

    for page, parser in parsed.items():
        for idx, script in enumerate(parser.inline_scripts, start=1):
            if not script.strip():
                continue
            with tempfile.NamedTemporaryFile(
                "w", suffix=".js", encoding="utf-8", delete=False
            ) as handle:
                handle.write(script)
                tmp = Path(handle.name)
            try:
                proc = subprocess.run(
                    [node, "--check", str(tmp)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if proc.returncode:
                    detail = (proc.stderr or proc.stdout).strip()
                    errors.append(
                        f"{page.relative_to(ROOT)} inline script {idx} is invalid JS:\n{detail}"
                    )
            finally:
                tmp.unlink(missing_ok=True)
    return errors


def check_readme() -> list[str]:
    errors: list[str] = []
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for raw in re.findall(r"!?(?:\[[^\]]*\])\(([^)]+)\)", text):
        raw = raw.strip()
        parts = urlsplit(raw)
        if parts.scheme or parts.netloc or raw.startswith("#") or raw.startswith("//"):
            continue
        path = unquote(parts.path)
        if not path:
            continue
        target = (ROOT / path).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"README.md: local link escapes repository: {raw}")
            continue
        if not target.exists():
            errors.append(f"README.md: missing local target {raw}")
    return errors


def main() -> int:
    errors = [f"missing required public file: {p.relative_to(ROOT)}" for p in REQUIRED if not p.exists()]
    errors.extend(check_html())
    errors.extend(check_readme())
    if errors:
        print("public-site validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("public-site validation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
