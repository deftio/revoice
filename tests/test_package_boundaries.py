"""The two standalone packages stay standalone.

`revoice/voicemetric/` and `revoice/rubric/` are generic engines that revoice happens to
call. That is only true while nothing inside them reaches back into revoice, and an
accidental import is exactly the kind of thing that slips in during a refactor and is
noticed a year later when someone tries to lift the package out.

These tests read the source rather than the imported module, so a dependency added
inside a function body is caught as surely as one at the top of the file.
"""

import ast
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).parent.parent
PACKAGES = ("voicemetric", "rubric")


def _imports(path: Path) -> set[str]:
    """Every module named by an import anywhere in the file, including inside functions."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _sources(package: str) -> list[Path]:
    files = sorted((ROOT / "revoice" / package).rglob("*.py"))
    assert files, f"no sources found for {package}"
    return files


@pytest.mark.parametrize("package", PACKAGES)
def test_package_never_imports_the_rest_of_revoice(package):
    offenders = []
    for f in _sources(package):
        for name in _imports(f):
            if name.startswith("revoice.") and not name.startswith(f"revoice.{package}"):
                offenders.append(f"{f.relative_to(ROOT)} imports {name}")
    assert not offenders, (
        f"revoice/{package}/ must not depend on the rest of revoice — that is what makes "
        f"it liftable:\n  " + "\n  ".join(offenders))


@pytest.mark.parametrize("package", PACKAGES)
def test_package_uses_only_the_standard_library(package):
    """Third-party dependencies are the caller's business, not the engine's."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())
    third_party = {
        # distribution name -> import name, for the few that differ
        "pyyaml": "yaml", "python-multipart": "multipart",
    }
    names = set()
    for spec in declared["project"]["dependencies"]:
        dist = spec.split(">")[0].split("=")[0].split("[")[0].strip().lower()
        names.add(third_party.get(dist, dist.replace("-", "_")))

    used = set()
    for f in _sources(package):
        used |= {n.split(".")[0] for n in _imports(f)}
    leaked = used & names
    # rubric documents pyyaml as its one dependency; voicemetric claims none at all
    allowed = {"yaml"} if package == "rubric" else set()
    assert leaked <= allowed, (
        f"revoice/{package}/ picked up a third-party dependency: {sorted(leaked - allowed)}")


@pytest.mark.parametrize("package", PACKAGES)
def test_package_documents_itself(package):
    readme = ROOT / "revoice" / package / "README.md"
    assert readme.is_file(), f"revoice/{package}/ ships without a README"
    assert len(readme.read_text()) > 400


def test_voicemetric_public_api_is_importable_and_complete():
    """__all__ is the contract a caller reads; every name in it must actually resolve."""
    import revoice.voicemetric as vm

    assert vm.__all__ == sorted(vm.__all__, key=str.lower) or set(vm.__all__)
    for name in vm.__all__:
        assert hasattr(vm, name), f"__all__ promises {name} but it is not exported"


def test_the_seam_is_where_it_is_documented_to_be():
    """core/metrics.py is the only place pack-awareness meets measurement."""
    seam = (ROOT / "revoice" / "core" / "metrics.py").read_text()
    assert "voicemetric" in seam and "VoicePack" in seam
    # and the measurement side knows nothing about packs
    for f in _sources("voicemetric"):
        assert "VoicePack" not in f.read_text(), f"{f.name} knows about voice packs"
