"""Guard: the four October evidence surfaces stay independently revertable.

Each surface may depend only on the modules listed below, and nothing outside a
surface may depend on it, so deleting one surface's files (and its console
script) cannot break the others. This enforces the import graph statically;
``docs`` of the pull request record the scratch-copy revert simulation that
demonstrates it dynamically.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "scrollq"

# surface -> (its modules, the scrollq modules it may import)
SURFACES = {
    "bucket helpers": ({"bucket"}, set()),
    "OME-Zarr reader + registration": ({"omezarr", "registration"}, set()),
    "chunk-size audit": ({"chunk_audit"}, {"bucket"}),
    "prize manifests": ({"prize_manifest"}, {"bucket", "grand_prize"}),
    "protocol pairs": ({"protocol_pairs"},
                       {"bucket", "omezarr", "registration", "metrics",
                        "score"}),
    "stability protocol v2": ({"stability_protocol"}, {"score"}),
    "seam fingerprint": ({"seam_fingerprint"}, set()),
    # reads ink maps through the existing validator's loaders and nothing else
    "threshold persistence": (
        {"persistence", "persistence_audit", "persistence_controls"},
        {"ink_validation"},
    ),
}


def _exists(module: str) -> bool:
    return (SRC / f"{module}.py").exists()


def _internal_imports(module: str) -> set[str]:
    """Names of sibling ``scrollq`` modules imported anywhere in ``module``."""
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                if node.module:
                    found.add(node.module.split(".")[0])
                else:  # ``from . import x``
                    found.update(a.name for a in node.names)
            elif node.module and node.module.split(".")[0] == "scrollq":
                parts = node.module.split(".")
                found.update([parts[1]] if len(parts) > 1
                             else [a.name for a in node.names])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "scrollq" and len(parts) > 1:
                    found.add(parts[1])
    return found


def test_each_surface_imports_only_its_declared_dependencies():
    for name, (modules, allowed) in SURFACES.items():
        for module in sorted(m for m in modules if _exists(m)):
            extra = _internal_imports(module) - allowed - modules
            assert not extra, (
                f"{name}: {module}.py imports {sorted(extra)}, outside its "
                f"declared dependencies {sorted(allowed)}")


def test_nothing_outside_a_surface_imports_it():
    owned = {m for modules, _ in SURFACES.values() for m in modules
             if _exists(m)}
    for path in sorted(SRC.glob("*.py")):
        module = path.stem
        if module in owned or module == "__init__":
            continue
        used = _internal_imports(module) & owned
        assert not used, (
            f"{module}.py imports {sorted(used)}; a surface must be revertable "
            "without touching existing modules")


def test_surfaces_do_not_import_each_other_except_declared_stacking():
    # protocol pairs may build on the reader; no other cross-surface edges
    edges = {(name, other_name)
             for name, (modules, _) in SURFACES.items()
             for other_name, (other, _) in SURFACES.items()
             if name != other_name
             for m in modules if _exists(m) and _internal_imports(m) & other}
    allowed = {("protocol pairs", "bucket helpers"),
               ("protocol pairs", "OME-Zarr reader + registration"),
               ("chunk-size audit", "bucket helpers"),
               ("prize manifests", "bucket helpers")}
    assert edges <= allowed, f"unexpected surface dependencies: {edges - allowed}"


def test_the_leaf_modules_import_nothing_from_scrollq():
    for module in ("bucket", "omezarr", "registration", "seam_fingerprint",
                   "persistence"):
        if _exists(module):  # absent when its surface has been reverted
            assert not _internal_imports(module), module
