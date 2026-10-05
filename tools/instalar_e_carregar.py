#!/usr/bin/env python3
"""Instala o zip do plugin num perfil limpo e o usa como o QGIS usaria.

    python3 tools/empacotar.py --saida dist
    python3 tools/instalar_e_carregar.py dist/TopoTrail-<versao>.zip

Extrai o pacote numa pasta de plugins temporaria e o carrega por
qgis.utils.loadPlugin/startPlugin -- o caminho do Gerenciador de Plugins --,
roda o exemplo reprodutivel pelo algoritmo instalado, abre a janela e
descarrega o plugin. Falha (saida diferente de zero) se qualquer passo nao
fizer o que deveria, inclusive se o plugin gravar arquivos dentro da propria
pasta de instalacao, que pode ser somente leitura.

Roda com o Python do QGIS (Linux: python3; Windows: python-qgis.bat; macOS: o
Python do QGIS.app).
"""
import os
import shutil
import sys
import tempfile
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOME = "TopoTrail"


def _arquivos(pasta):
    return {os.path.relpath(os.path.join(raiz, nome), pasta)
            for raiz, _, nomes in os.walk(pasta) for nome in nomes
            if "__pycache__" not in raiz}


def main(argv):
    if len(argv) != 1 or not os.path.isfile(argv[0]):
        sys.exit("uso: instalar_e_carregar.py <TopoTrail-versao.zip>")
    trabalho = tempfile.mkdtemp(prefix="topotrail_instalacao_")
    try:
        return _verificar(argv[0], trabalho)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


def _verificar(zip_path, trabalho):
    plugins = os.path.join(trabalho, "python", "plugins")
    os.makedirs(plugins)
    with zipfile.ZipFile(zip_path) as pacote:
        pacote.extractall(plugins)
    instalado = os.path.join(plugins, NOME)
    if not os.path.isfile(os.path.join(instalado, "metadata.txt")):
        sys.exit("o zip nao tem {}/metadata.txt na raiz".format(NOME))
    antes = _arquivos(instalado)

    sys.path.insert(0, os.path.join(RAIZ, "tools"))
    import qgis_headless
    aplicacao = qgis_headless.iniciar(gui=True)
    processing = qgis_headless.processing_do_qgis()

    import qgis.utils
    from qgis.core import Qgis, QgsApplication
    from unittest import mock

    # Nao qgis.testing.mocked.get_iface(): com o QGIS ja aberto ela cria um
    # segundo QgsApplication, cujo exitQgis derruba o processo na saida.
    qgis.utils.iface = mock.MagicMock()
    qgis.utils.iface.mainWindow.return_value = None
    qgis.utils.plugin_paths = [plugins]
    sys.path.insert(0, plugins)
    qgis.utils.updateAvailablePlugins()
    falhas = []

    def conferir(condicao, mensagem):
        print(("ok    " if condicao else "FALHA ") + mensagem)
        if not condicao:
            falhas.append(mensagem)

    print("QGIS", Qgis.version(), "| Python", sys.version.split()[0])
    conferir(NOME in qgis.utils.available_plugins, "o QGIS encontra o plugin na pasta de plugins")
    conferir(qgis.utils.loadPlugin(NOME), "loadPlugin (metadata aceito por esta versao do QGIS)")
    conferir(qgis.utils.startPlugin(NOME), "startPlugin (classFactory e initGui)")
    algoritmo = QgsApplication.processingRegistry().algorithmById("topotrail:topotrail")
    conferir(algoritmo is not None, "algoritmo topotrail:topotrail registrado")
    if algoritmo is not None:
        origem = os.path.abspath(sys.modules[type(algoritmo).__module__].__file__)
        conferir(origem.startswith(os.path.abspath(instalado) + os.sep),
                 "o algoritmo vem do pacote instalado, e nao do checkout")

        exemplo = os.path.join(RAIZ, "exemplo")
        sys.path.insert(0, exemplo)
        import executar
        saida = os.path.join(trabalho, "saida")
        os.makedirs(saida)
        resultado = processing.run("topotrail:topotrail", executar.parametros(
            os.path.join(exemplo, "mde.tif"), os.path.join(exemplo, "origem.geojson"),
            os.path.join(exemplo, "destino.geojson"),
            os.path.join(exemplo, "intermediario.geojson"),
            os.path.join(saida, "exemplo.gpkg")))
        _, rota = executar.ler_atributos(resultado["OUTPUT_ROUTE"])
        travessias, _ = executar.ler_atributos(resultado["OUTPUT_CROSSINGS"])
        zonas, _ = executar.ler_atributos(resultado["OUTPUT_VECTOR"])
        atributos = rota[0]
        medido = {
            "comprimento_m": round(float(atributos["compr_m"]), 1),
            "tempo_h": round(float(atributos["tempo_h"]), 2),
            "tempo_hms": atributos["tempo_hms"],
            "ganho_m": round(float(atributos["ganho_m"]), 1),
            "perda_m": round(float(atributos["perda_m"]), 1),
            "alt_max_m": round(float(atributos["alt_max_m"]), 1),
            "travessias": int(travessias),
            "zonas": int(zonas),
        }
        divergencias = executar.conferir(medido)
        conferir(not divergencias, "o exemplo pelo plugin instalado reproduz exemplo/README.md"
                 + ("" if not divergencias else ": " + "; ".join(divergencias)))

    extensao = qgis.utils.plugins.get(NOME)
    if extensao is not None:
        extensao.run()
        aplicacao.processEvents()
        conferir(extensao.dlg is not None and extensao.dlg.isVisible(), "a janela abre")
        extensao.dlg.close()
    conferir(qgis.utils.unloadPlugin(NOME), "unloadPlugin")
    conferir(QgsApplication.processingRegistry().providerById("topotrail") is None,
             "o provider sai do registro no unload")
    novos = sorted(_arquivos(instalado) - antes)
    conferir(not novos, "nada gravado dentro da pasta do plugin" + (": {}".format(novos) if novos else ""))

    if falhas:
        sys.exit("{} verificacao(oes) falharam.".format(len(falhas)))
    print("Instalacao verificada.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
