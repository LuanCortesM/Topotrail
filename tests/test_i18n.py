"""Os arquivos de idioma: paridade de chaves, marcadores e integridade.

Um idioma incompleto não quebra nada de forma visível -- a chave que falta
aparece na língua de reserva, ou pior, aparece como o próprio nome da chave no
meio da tela. E um marcador perdido na tradução (`{n}`, `{path}`) só estoura em
tempo de execução, no idioma que ninguém da equipe testa. São exatamente os
erros que um teste pega e uma revisão manual não.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"
REFERENCE = "en"
TRANSLATIONS = ["pt", "es", "fr", "zh", "ja"]


def _load(code):
    return json.loads((I18N / f"{code}.json").read_text(encoding="utf-8"))


def _codes():
    return sorted(path.stem for path in I18N.glob("*.json"))


def _placeholders(value):
    text = " ".join(value) if isinstance(value, list) else value
    return set(re.findall(r"\{(\w+)\}", text))


def test_the_expected_languages_are_shipped():
    assert set(_codes()) == {"pt", "en", "es", "fr", "zh", "ja"}


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_every_language_has_every_key(code):
    reference, translated = _load(REFERENCE), _load(code)
    missing = sorted(set(reference) - set(translated))
    extra = sorted(set(translated) - set(reference))
    assert not missing, f"{code}: faltam {len(missing)} chaves, ex.: {missing[:5]}"
    assert not extra, f"{code}: chaves inexistentes em {REFERENCE}: {extra[:5]}"


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_placeholders_survive_translation(code):
    """`{n}` perdido na tradução vira KeyError no format(), só naquele idioma."""
    reference, translated = _load(REFERENCE), _load(code)
    for key, value in reference.items():
        assert _placeholders(value) == _placeholders(translated[key]), (
            f"{code}/{key}: marcadores diferentes")


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_lists_keep_their_shape(code):
    """`steps` é uma lista de quatro nomes de etapa, e precisa continuar sendo."""
    reference, translated = _load(REFERENCE), _load(code)
    for key, value in reference.items():
        assert isinstance(translated[key], type(value)), f"{code}/{key}: tipo mudou"
        if isinstance(value, list):
            assert len(translated[key]) == len(value), f"{code}/{key}: tamanho mudou"


@pytest.mark.parametrize("code", ["pt", "en", "es", "fr", "zh", "ja"])
def test_nothing_is_left_empty(code):
    for key, value in _load(code).items():
        parts = value if isinstance(value, list) else [value]
        for part in parts:
            assert part and part.strip(), f"{code}/{key} está vazio"


@pytest.mark.parametrize("code", ["es", "fr", "zh", "ja"])
def test_the_new_languages_are_actually_translated(code):
    """Uma tradução copiada do inglês passaria em todos os testes acima sem
    traduzir nada. O critério aqui é grosseiro de propósito: se quase todo texto
    longo for idêntico ao inglês, ninguém traduziu."""
    reference, translated = _load(REFERENCE), _load(code)
    longos = [k for k, v in reference.items() if isinstance(v, str) and len(v) > 40]
    iguais = [k for k in longos if translated[k] == reference[k]]
    assert len(iguais) < 0.1 * len(longos), (
        f"{code}: {len(iguais)} de {len(longos)} textos longos idênticos ao inglês")


def test_every_algorithm_label_has_a_key():
    """Os rótulos do Processing passaram de self.tr("texto em português") para
    self.tr("chave"). Um rótulo esquecido apareceria em português em qualquer
    idioma -- que era exatamente o estado anterior."""
    source = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
    usadas = set(re.findall(r'self\.tr\("([^"]+)"\)', source))
    usadas |= set(re.findall(r'\(\s*self\.[A-Z_]+,\s*"(alg_\w+)"', source))
    sem_chave = {u for u in usadas if not u.startswith("alg_") and u not in _load(REFERENCE)}
    assert not sem_chave, f"rótulos ainda com texto literal: {sorted(sem_chave)}"
    disponiveis = set(_load(REFERENCE))
    assert not (usadas - disponiveis), (
        f"chaves usadas sem tradução: {sorted(usadas - disponiveis)}")


def test_no_qt_translation_machinery_is_left_behind():
    """QCoreApplication.translate exige .qm compilado, que nunca chegou a ser
    gerado -- era por isso que a Caixa de Ferramentas ficava em português em
    qualquer idioma."""
    source = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
    # A chamada, e nao a mencao: o proprio docstring do metodo tr() explica por
    # que o mecanismo antigo saiu, e citar o nome ali nao pode reprovar o teste.
    assert "QCoreApplication.translate(" not in source


def test_the_files_are_utf8_and_valid_json():
    for code in _codes():
        raw = (I18N / f"{code}.json").read_bytes()
        raw.decode("utf-8")
        json.loads(raw)


def test_the_loader_falls_back_instead_of_showing_the_key():
    import sys
    sys.path.insert(0, str(ROOT))
    from ui import i18n
    assert i18n.text("es", "run") == _load("es")["run"]
    assert i18n.text("es", "chave_que_nao_existe") == "chave_que_nao_existe"
    assert set(i18n.LANGUAGE_CODES) == set(_codes())
    assert i18n.REVIEWED <= set(_codes())


def test_the_transitability_legend_is_translated_too():
    """Os rótulos das classes não ficam só na tela: vão gravados na legenda do
    próprio raster de saída, via SetCategoryNames.

    Ficaram de fora quando o resto da interface foi traduzido, e o resultado era
    um usuário japonês abrindo o mapa no QGIS e vendo a legenda em português --
    e continuando assim depois de enviar o arquivo a outra pessoa, porque o
    rótulo viaja dentro dele.
    """
    for code in ["pt", "en", "es", "fr", "zh", "ja"]:
        data = _load(code)
        for numero in range(1, 6):
            chave = f"class_{numero}"
            assert chave in data, f"{code}: falta {chave}"
            assert str(numero) in data[chave], (
                f"{code}/{chave} deve começar pelo número da classe")
    source = (ROOT / "processing" / "algorithm.py").read_text(encoding="utf-8")
    assert "_class_labels()" in source
    assert "labels=_class_labels()" in source


def test_no_label_is_clipped_in_any_language():
    """Nenhum rótulo pode ficar cortado, em nenhum dos seis idiomas.

    Este defeito já apareceu três vezes, sempre pelo mesmo motivo: uma largura
    calculada com o texto de um idioma, ou com o peso normal da fonte quando o
    estado ativo usa semibold. "Produtos" virava "Produto" e "データ" virava
    "デー" -- e, sendo silencioso, só se descobre olhando.

    Precisa de Qt, então é pulado onde não houver (o CI roda sem QGIS).
    """
    import os
    pytest.importorskip("qgis.PyQt.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.PyQt.QtWidgets import QApplication, QLabel, QPushButton

    import sys
    sys.path.insert(0, str(ROOT))
    application = QApplication.instance() or QApplication([])
    from ui.topotrail_dialog import TopotrailDialog

    dialog = TopotrailDialog()
    dialog.resize(940, 720)          # o tamanho mínimo declarado da janela
    dialog.show()
    application.processEvents()
    try:
        for code in ["pt", "en", "es", "fr", "zh", "ja"]:
            index = dialog.language_box.findData(code)
            if index < 0:
                continue
            dialog.language_box.setCurrentIndex(index)
            dialog.want_route.setChecked(True)
            application.processEvents()
            for step in range(4):
                dialog.stack.setCurrentIndex(step)
                application.processEvents()
                for widget in (dialog.findChildren(QLabel)
                               + dialog.findChildren(QPushButton)):
                    texto = widget.text()
                    if not texto or not widget.isVisible():
                        continue
                    if isinstance(widget, QLabel) and widget.wordWrap():
                        continue
                    assert widget.width() >= widget.sizeHint().width() - 1, (
                        f"{code}, passo {step + 1}: '{texto[:30]}' cortado "
                        f"({widget.width()} px para {widget.sizeHint().width()})")
    finally:
        dialog.close()
