"""Compatibilidade com o QGIS 4, que roda sobre Qt6.

O Qt6 removeu o acesso solto a enums: `Qt.PointingHandCursor` deixa de existir e
vira `Qt.CursorShape.PointingHandCursor`. Código escrito no Qt5 continua
importando sem erro e só estoura quando a linha roda -- ou seja, quando o
usuário clica. E o `metadata.txt` declara `qgisMaximumVersion=4.99`, isto é, o
plugin promete QGIS 4: prometer e quebrar é pior que não prometer.

O projeto já tinha os auxiliares `qt_enum`, `class_enum` e `size_policy` para
isso; o que faltava era usá-los sem exceção, e um teste que cobrasse.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = sorted(
    list((ROOT / "ui").glob("*.py"))
    + list((ROOT / "processing").glob("*.py"))
    + [ROOT / "topotrail.py", ROOT / "__init__.py"]
)


def _code_without_text(source):
    """Remove comentários e literais, para não acusar o que só é documentação."""
    source = re.sub(r'"""(?:.|\n)*?"""', '""', source)
    source = re.sub(r"'''(?:.|\n)*?'''", "''", source)
    source = re.sub(r"#.*", "", source)
    source = re.sub(r'"[^"\n]*"', '""', source)
    source = re.sub(r"'[^'\n]*'", "''", source)
    return source


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_unscoped_qt_enum_survives(module):
    code = _code_without_text(module.read_text(encoding="utf-8"))
    # Qt.AlgumaCoisa que não seja um grupo conhecido acessado por getattr
    encontrados = re.findall(r"\bQt\.([A-Z][A-Za-z_]+)", code)
    assert not encontrados, (
        f"{module.name}: enum solto do Qt, quebra no QGIS 4: {sorted(set(encontrados))}")


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_unscoped_class_enum_survives(module):
    code = _code_without_text(module.read_text(encoding="utf-8"))
    # QgsColorRampShader.Interpolated foi o que o verificador de Qt6 do
    # repositorio de plugins apontou na 1.1.1 -- em QGIS 4 e
    # QgsColorRampShader.Type.Interpolated. ColorRampItem e classe aninhada,
    # nao enum, e fica de fora.
    padrao = (r"\b(QFrame|QPalette|QSizePolicy|QComboBox|QgsProcessingParameterNumber"
              r"|QgsProcessingParameterFile|QgsColorRampShader|QgsRasterShader|Qgis)\.([A-Z][A-Za-z_]+)")
    achados = [f"{c}.{v}" for c, v in re.findall(padrao, code)
               if v not in ("Shape", "ColorRole", "Policy", "Type", "Behavior", "MessageLevel",
                            "SizeAdjustPolicy", "ColorRampItem")]
    assert not achados, (
        f"{module.name}: enum de classe sem escopo, quebra no QGIS 4: {sorted(set(achados))}")


def test_every_enum_the_plugin_asks_for_exists_in_qt6():
    """A verificação que importa: os nomes passados aos auxiliares resolvem de
    fato sob Qt6, e não só sob Qt5.

    Um grupo escrito errado -- "Cursor" em vez de "CursorShape" -- passaria nos
    testes acima e continuaria funcionando no Qt5, porque o auxiliar recorre ao
    próprio Qt quando não acha o grupo. Só o Qt6 revela o engano. Pulado se
    PyQt6 não estiver instalado.
    """
    PyQt6 = pytest.importorskip("PyQt6")
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QFrame, QSizePolicy

    fonte = "\n".join(m.read_text(encoding="utf-8") for m in MODULES)
    faltando = []

    for group, value in set(re.findall(r'qt_enum\(\s*"(\w+)",\s*"(\w+)"', fonte)):
        if not hasattr(getattr(Qt, group, Qt), value):
            faltando.append(f"Qt.{group}.{value}")
    for group, value in set(re.findall(r'_qt\(\s*"(\w+)",\s*"(\w+)"', fonte)):
        if not hasattr(getattr(Qt, group, Qt), value):
            faltando.append(f"Qt.{group}.{value}")
    for value in set(re.findall(r'size_policy\(\s*"(\w+)"', fonte)):
        if not hasattr(QSizePolicy.Policy, value):
            faltando.append(f"QSizePolicy.Policy.{value}")
    for cls, group, value in set(
            re.findall(r'class_enum\(\s*(\w+),\s*"(\w+)",\s*"(\w+)"', fonte)):
        alvo = {"QFrame": QFrame, "QPalette": QPalette,
                "QSizePolicy": QSizePolicy}.get(cls)
        if alvo and not hasattr(getattr(alvo, group, alvo), value):
            faltando.append(f"{cls}.{group}.{value}")

    assert not faltando, f"não existem no Qt6: {sorted(faltando)}"


def test_the_declared_qgis_range_matches_what_the_code_supports():
    metadata = (ROOT / "metadata.txt").read_text(encoding="utf-8")
    assert "qgisMinimumVersion=3.22" in metadata
    assert "qgisMaximumVersion=4.99" in metadata, (
        "se o suporte a QGIS 4 for retirado, o metadata precisa dizer isso")


def test_qaction_is_imported_the_way_both_versions_allow():
    """No Qt6 o QAction saiu de QtWidgets para QtGui."""
    source = (ROOT / "topotrail.py").read_text(encoding="utf-8")
    assert "from qgis.PyQt.QtGui import QAction" in source
    assert "from qgis.PyQt.QtWidgets import QAction" in source
