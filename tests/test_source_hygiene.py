"""Source-level checks that need neither QGIS nor a DEM.

They guard against three failure modes that have actually occurred in this
code base and that are invisible until a user hits them:

* UTF-8 text accidentally re-encoded as Latin-1 and saved back ("mojibake"),
  which reached users as garbled accented characters in interface tooltips;
* bare `except:` clauses, which swallow `KeyboardInterrupt` and hide real
  failures behind an apparently successful run;
* Python files that no longer compile.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

SOURCE_DIRS = ["processing", "ui", "tests"]
ROOT_MODULES = ["topotrail.py", "__init__.py", "topotrail_config.py"]

# Sequences that appear when UTF-8 is decoded as Latin-1 and saved back.
# Built from code points so this file does not itself contain the pattern it
# looks for.
MOJIBAKE_MARKERS = tuple(
    character.encode("utf-8").decode("latin-1")
    for character in "\u00e1\u00e9\u00ed\u00f3\u00fa\u00e7\u00e3\u00f5\u00e2\u00ea\u00f4\u00e0"
)


def python_files():
    files = [ROOT / name for name in ROOT_MODULES]
    for folder in SOURCE_DIRS:
        files.extend(sorted((ROOT / folder).rglob("*.py")))
    return [path for path in files if path.is_file()]


def text_files():
    files = python_files()
    files.append(ROOT / "metadata.txt")
    files.extend(sorted(ROOT.glob("*.md")))
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.is_file()]


def test_every_text_file_is_valid_utf8():
    broken = []
    for path in text_files():
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            broken.append(path.relative_to(ROOT).as_posix())
    assert not broken, f"not valid UTF-8: {broken}"


def test_no_mojibake_in_sources():
    offenders = []
    for path in text_files():
        content = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), start=1):
            if any(marker in line for marker in MOJIBAKE_MARKERS):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert not offenders, (
        "UTF-8 text was re-encoded as Latin-1 at: "
        + ", ".join(offenders)
        + ". Fix with: line.encode('latin-1').decode('utf-8')"
    )


def test_all_python_files_parse():
    failures = []
    for path in python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            failures.append(f"{path.relative_to(ROOT).as_posix()}: {error}")
    assert not failures, failures


def test_no_bare_except_clauses():
    offenders = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not offenders, f"bare `except:` at: {offenders}"


def test_plugin_entry_point_is_declared():
    """QGIS calls `classFactory(iface)` in the package `__init__`."""
    source = (ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert "classFactory" in names, "__init__.py must define classFactory(iface)"
