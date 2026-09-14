"""`validation/` tem de rodar na maquina de outra pessoa.

Os scripts apresentados em docs/BATERIA_TESTES.md e docs/VALIDACAO.md como a
evidencia empirica do trabalho traziam caminhos absolutos da maquina de
desenvolvimento (`/home/claude/work/exp`, `/mnt/user-data/uploads/...`) e
`bateria_regioes.py` importava `qgis_env`, um modulo que nao existe no
repositorio: nem o `import` resolvia para quem clonasse o projeto. Para a JOSS
isso e diretamente checavel -- o revisor precisa conseguir rodar os exemplos.
"""
import os
import pathlib
import re
import subprocess
import sys

import pytest

# O script antigo subia o QGIS e rodava a bateria inteira quando por acaso
# achava os dados da maquina de quem o escreveu. Um teste nao pode ficar
# pendurado nisso: passar do tempo aqui ja e a falha.
LIMITE_SEGUNDOS = 120

ROOT = pathlib.Path(__file__).resolve().parent.parent
BATERIA = ROOT / "validation" / "bateria_regioes.py"
ENTORNO = ROOT / "validation" / "entorno.py"

# Raizes de caminho que so existem na maquina de quem escreveu o script.
CAMINHOS_DE_OUTRA_MAQUINA = re.compile(
    r'["\'](?:/home/[^"\']+|/mnt/user-data/[^"\']+|[A-Za-z]:\\\\[^"\']+)["\']')


def _fonte(caminho):
    return caminho.read_text(encoding="utf-8")


def test_a_bateria_nao_importa_modulo_que_nao_existe_no_repositorio():
    fonte = _fonte(BATERIA)
    assert "import qgis_env" not in fonte
    ausentes = [nome for nome in ("qgis_env",)
                if not (ROOT / f"{nome}.py").exists()
                and re.search(r"^\s*import\s+%s\b" % nome, fonte, re.MULTILINE)]
    assert not ausentes, ausentes
    assert ENTORNO.is_file(), "validation/entorno.py nao existe"


def test_a_bateria_nao_tem_caminho_absoluto_de_outra_maquina():
    for arquivo in (BATERIA, ENTORNO):
        encontrados = [achado for achado in
                       CAMINHOS_DE_OUTRA_MAQUINA.findall(_fonte(arquivo))]
        assert not encontrados, f"{arquivo.name}: {encontrados}"


def test_sem_os_dados_a_bateria_diz_o_que_falta_e_como_informar(tmp_path):
    """Sem dado nenhum o script tem de parar com instrucao, nao com traceback."""
    ambiente = {chave: valor for chave, valor in os.environ.items()
                if not chave.startswith("TOPOTRAIL_")}
    ambiente["HOME"] = str(tmp_path)
    try:
        concluido = subprocess.run(
            [sys.executable, str(BATERIA)], capture_output=True, text=True,
            cwd=str(tmp_path), env=ambiente, timeout=LIMITE_SEGUNDOS)
    except subprocess.TimeoutExpired:
        pytest.fail("sem dados, a bateria tem de parar na hora, com instrucao")

    saida = concluido.stdout + concluido.stderr
    assert concluido.returncode != 0
    assert "Traceback" not in saida, saida[-1500:]
    for argumento in ("--cartas=", "--trilhas=", "--caatinga=", "--extremos=",
                      "--entradas="):
        assert argumento in saida, (argumento, saida[-1500:])
    for variavel in ("TOPOTRAIL_CARTAS", "TOPOTRAIL_TRILHAS",
                     "TOPOTRAIL_CAATINGA", "TOPOTRAIL_EXTREMOS",
                     "TOPOTRAIL_ENTRADAS"):
        assert variavel in saida, variavel
    assert "22S465ZN.tif" in saida, "nao diz que arquivo procurava"


def test_sem_os_dados_nada_e_escrito_no_repositorio(tmp_path):
    """Parar por falta de dado nao pode deixar diretorio de saida para tras."""
    antes = {caminho.name for caminho in ROOT.iterdir()}
    ambiente = {chave: valor for chave, valor in os.environ.items()
                if not chave.startswith("TOPOTRAIL_")}
    try:
        subprocess.run([sys.executable, str(BATERIA)], capture_output=True,
                       text=True, cwd=str(tmp_path), env=ambiente,
                       timeout=LIMITE_SEGUNDOS)
    except subprocess.TimeoutExpired:
        pytest.fail("sem dados, a bateria tem de parar na hora, com instrucao")
    assert {caminho.name for caminho in ROOT.iterdir()} == antes
