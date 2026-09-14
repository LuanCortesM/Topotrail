"""O zip publicado tem de sair do HEAD, nao da arvore de trabalho.

O pacote da 1.2.0 continha exatamente os arquivos versionados de HEAD **mais**
17 arquivos nao versionados de cache -- `.ruff_cache/` inteiro e
`.pytest_cache/`, com o `v/cache/lastfailed` e os nomes dos testes que falhavam
na maquina de quem empacotou. Nao havia script de release nenhum: o empacotamento
era manual e nao reproduzivel. `tools/empacotar.py` passou a monta-lo com
`git archive HEAD`.
"""
import importlib.util
import pathlib
import subprocess
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _empacotador():
    caminho = ROOT / "tools" / "empacotar.py"
    assert caminho.is_file(), "tools/empacotar.py nao existe"
    spec = importlib.util.spec_from_file_location("tt_empacotar", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _tem_git():
    try:
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def test_o_empacotador_existe_e_e_importavel():
    modulo = _empacotador()
    assert modulo.PASTA_RAIZ_DO_ZIP == "TopoTrail"


def test_o_zip_nao_leva_cache_nem_suites_nem_ferramentas(tmp_path):
    if not _tem_git():
        pytest.skip("sem repositorio git para 'git archive HEAD'")
    modulo = _empacotador()
    caminho_zip, _ = modulo.empacotar(str(tmp_path))

    with zipfile.ZipFile(caminho_zip) as pacote:
        nomes = pacote.namelist()

    assert nomes, "o pacote saiu vazio"
    assert {nome.split("/")[0] for nome in nomes} == {"TopoTrail"}, (
        "o zip precisa de uma unica pasta raiz TopoTrail/")

    lixo = [nome for nome in nomes
            if ".pytest_cache" in nome or ".ruff_cache" in nome
            or "__pycache__" in nome or nome.endswith((".pyc", ".pyo"))]
    assert not lixo, lixo

    publicadas = {nome.split("/")[1] for nome in nomes}
    for pasta in ("tests", "integracao", ".github", "validation", "tools", "exemplo"):
        assert pasta not in publicadas, pasta

    # o que o usuario precisa continua la
    assert "TopoTrail/metadata.txt" in nomes
    assert "TopoTrail/__init__.py" in nomes
    assert "TopoTrail/processing/algorithm.py" in nomes


def test_o_zip_sai_do_head_e_nao_da_arvore_de_trabalho(tmp_path):
    """Um arquivo nao versionado na arvore nao pode aparecer no pacote."""
    if not _tem_git():
        pytest.skip("sem repositorio git para 'git archive HEAD'")
    intruso = ROOT / "_intruso_do_teste_de_empacotamento.txt"
    intruso.write_text("nao versionado\n", encoding="utf-8")
    try:
        modulo = _empacotador()
        caminho_zip, _ = modulo.empacotar(str(tmp_path))
        with zipfile.ZipFile(caminho_zip) as pacote:
            nomes = pacote.namelist()
    finally:
        intruso.unlink()
    assert "TopoTrail/" + intruso.name not in nomes


def test_o_pacote_e_reproduzivel(tmp_path):
    """O mesmo HEAD tem de dar o mesmo zip byte a byte."""
    if not _tem_git():
        pytest.skip("sem repositorio git para 'git archive HEAD'")
    modulo = _empacotador()
    primeiro, _ = modulo.empacotar(str(tmp_path / "a"))
    segundo, _ = modulo.empacotar(str(tmp_path / "b"))
    assert (pathlib.Path(primeiro).read_bytes()
            == pathlib.Path(segundo).read_bytes())
