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
import re
import sys

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


def test_no_orphan_interface_file_is_shipped():
    """A janela foi reescrita em código e parou de carregar o .ui, mas o arquivo
    continuou no repositório -- 460 linhas viajando dentro do pacote do plugin
    sem que nada as lesse."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for ui_file in (root / "ui").glob("*.ui"):
        referencias = [
            path for path in root.rglob("*.py")
            if ui_file.name in path.read_text(encoding="utf-8", errors="ignore")
        ]
        assert referencias, f"{ui_file.name} não é carregado por nenhum módulo"


def test_no_stray_run_logs_are_committed():
    """Um .log de execução foi parar no repositório e seguia para o pacote."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    sobras = [p.name for p in root.glob("*.log")]
    assert not sobras, f"log de execução no repositório: {sobras}"


# What every QGIS installation ships. Anything imported at module level that
# is not in this list (or the standard library, or the plugin itself) makes
# the plugin fail to load on a clean install -- which is exactly what happened
# with geopandas before 0.13.
QGIS_GUARANTEED_MODULES = {"qgis", "osgeo", "numpy", "scipy", "PyQt5", "PyQt6"}
PLUGIN_MODULES = {"processing", "ui", "topotrail", "topotrail_config", "i18n"}


def _is_stdlib(name):
    """Python < 3.10 nao tem sys.stdlib_module_names: decide pelo caminho do modulo.

    A lista escrita a mao que existia aqui esqueceu `logging` e derrubou o CI
    em Python 3.9 -- um teste de dependencias nao pode depender de uma lista
    que alguem precisa lembrar de atualizar.
    """
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return name in names
    if name in sys.builtin_module_names:
        return True
    import importlib.util
    import sysconfig
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    origin = getattr(spec, "origin", None) or ""
    if origin in ("frozen", "built-in"):
        return True
    stdlib = sysconfig.get_paths()["stdlib"]
    return origin.startswith(stdlib) and "site-packages" not in origin


def _top_level_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def test_shipped_code_imports_only_what_qgis_guarantees():
    allowed = QGIS_GUARANTEED_MODULES | PLUGIN_MODULES
    shipped = [path for path in python_files() if "tests" not in path.parts]
    offenders = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in shipped
        for name in _top_level_imports(path)
        if name not in allowed and not _is_stdlib(name)
    )
    assert not offenders, (
        "Import de biblioteca que o QGIS nao garante em instalacao limpa:\n  "
        + "\n  ".join(offenders)
    )


def test_geopandas_and_shapely_are_gone_from_shipped_code():
    banned = ("geopandas", "shapely", "fiona", "pyproj", "pandas")
    shipped = [path for path in python_files() if "tests" not in path.parts]
    hits = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in shipped
        for name in _top_level_imports(path)
        if name in banned
    )
    assert not hits, "\n".join(hits)


def test_stylesheet_font_sizes_are_whole_pixels():
    """Qt ignora `font-size: 12.5px` em silencio -- a declaracao inteira cai.

    Ate a 0.13 dezessete regras da janela usavam meio pixel, e todo esse texto
    vinha no tamanho padrao do QGIS em vez do tamanho desenhado. Confirmado
    medindo QLabel com "10.5px" (ignorado: 12 pt) contra "10px" (aplicado).
    """
    pattern = re.compile(r"font-size:\s*\d+\.\d+\s*(px|pt)")
    offenders = []
    for path in python_files():
        if "ui" not in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_no_try_except_pass_in_shipped_code():
    """O repositorio de plugins do QGIS roda o Bandit e BLOQUEIA a versao por
    B110 (try/except/pass). Aconteceu com a 1.1.0: oito ocorrencias. Toda
    excecao engolida agora deixa rastro via log_quietly() ou logging."""
    offenders = []
    for path in python_files():
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                body = node.body
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "except ... : pass em codigo publicado:\n  " + "\n  ".join(offenders)
