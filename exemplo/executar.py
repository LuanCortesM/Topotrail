#!/usr/bin/env python3
"""Roda o exemplo do TopoTrail num QGIS sem interface grafica.

    python3 exemplo/executar.py

Nao e preciso instalar o plugin: o script registra o provider a partir do
proprio diretorio do repositorio. O unico requisito e um QGIS 3.22 ou superior
cujo Python consiga importar `qgis.core` -- no Linux normalmente o
/usr/bin/python3 do sistema; no Windows, o `python-qgis.bat` que o instalador
deixa, e no macOS o Python dentro do QGIS.app.

As saidas vao para exemplo/saida/. Os valores conferidos ao final estao
documentados em exemplo/README.md: se eles nao baterem, a mensagem diz qual
divergiu e por quanto.
"""
import json
import os
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)
SAIDA = os.path.join(PASTA, "saida")

# O plugin e importado como pacote pelo nome do diretorio do repositorio, que e
# como o QGIS tambem o importa. Funciona em qualquer checkout, com qualquer nome
# de pasta.
PACOTE = os.path.basename(RAIZ)

# Os valores que esta execucao tem de produzir. Sao os mesmos que estao na
# tabela de exemplo/README.md -- ha um teste que compara as duas listas, para
# que o texto nao envelheca em silencio -- e os mesmos que
# integracao/test_exemplo.py confere a cada alteracao do plugin.
#
# Comprimentos e tempos sao continuos e admitem a ultima casa variar com a
# versao do NumPy ou do GDAL; contagens sao inteiras e tem de bater exatamente.
ESPERADO = {
    "comprimento_m": 14404.5,
    "tempo_h": 6.48,
    "tempo_hms": "6h29",
    "ganho_m": 982.6,
    "perda_m": 663.1,
    "alt_max_m": 1551.1,
    "travessias": 3,
    "zonas": 11,
}

# Tolerancia relativa das grandezas continuas.
TOLERANCIA = 0.001

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("XDG_RUNTIME_DIR"):
    # Sem isto o Qt reclama em toda execucao sem sessao grafica. O diretorio tem
    # de ser exclusivo do usuario e com permissao 0700, ou o aviso volta.
    import tempfile
    _runtime = os.path.join(tempfile.gettempdir(),
                            "topotrail-runtime-{}".format(os.getuid()
                                                          if hasattr(os, "getuid")
                                                          else "user"))
    try:
        os.makedirs(_runtime, mode=0o700, exist_ok=True)
        os.chmod(_runtime, 0o700)
        os.environ["XDG_RUNTIME_DIR"] = _runtime
    except OSError:
        pass


def parametros(mde, origem, destino, intermediarios, saida):
    """Os 45 parametros do algoritmo, todos declarados por extenso.

    Nenhum fica implicito de proposito: o valor que produz o resultado tem de
    estar escrito em algum lugar que o leitor possa conferir. Onde o valor e o
    padrao do plugin, o comentario diz isso; onde nao e, diz por que.
    """
    return {
        # --- dado de entrada ---
        "INPUT_DEM": mde,
        "DERIVE_FROM_DEM": True,          # padrao: declividade e curvaturas saem do MDE
        "VERTICAL_UNIT": 0,               # 0 = metros, 1 = pes
        "INPUT_SLOPE": None,              # so e lido se DERIVE_FROM_DEM for False
        "INPUT_CURVH": None,
        "INPUT_CURVV": None,
        "SLOPE_UNIT": 0,                  # 0 = porcentagem, 1 = graus (raster proprio)

        # --- limites do terreno ---
        "ALT_MIN": 0.0,                   # padrao; a cena vai de 791 a 2023 m
        "ALT_MAX": 2600.0,                # padrao
        "SLOPE_MAX": 55.0,                # padrao; acima disto a celula sai da rota
        "SLOPE_SCORE_MAX": 50.0,          # padrao; declividade de nota zero

        # --- pesos dos criterios ---
        "WEIGHT_ALT": 0.0,                # padrao: altitude e restricao, nao preferencia
        "WEIGHT_SLOPE": 1.0,              # padrao
        "WEIGHT_CURVH": 1.0,              # padrao
        "WEIGHT_CURVV": 1.0,              # padrao
        "WEIGHT_WETNESS": 0.0,            # padrao
        "WEIGHT_ROUGHNESS": 0.0,          # padrao

        # --- zonas de acesso potencial ---
        "GENERATE_ZONES": True,           # padrao
        "THRESHOLD": 0.0,                 # padrao: 0 = usar o percentil automatico
        "AUTO_PERCENTILE": 75.0,          # padrao
        "MIN_PATCH_AREA_HA": 50.0,        # padrao
        "ALTITUDE_BAND_THRESHOLD": True,  # padrao
        "ALTITUDE_BAND_SIZE_M": 200.0,    # padrao
        "WALKABILITY_ZONES": False,       # padrao

        # --- rota ---
        "START_POINT_FILE": origem,
        "END_POINT_FILE": destino,
        "VIA_POINTS_FILE": intermediarios,
        "OPTIMISE_ORDER": False,          # padrao: visita na ordem das feicoes
        "ROUTE_COST_MODEL": 2,            # padrao: 2 = tempo de caminhada (Tobler)
        "ROUTE_CONTRAST": 6.0,            # padrao; so vale no modelo exponencial
        "ROUTE_BUFFER_M": 100.0,          # padrao: raio do corredor, 200 m de largura
        "ROUTE_MARGIN_M": 5000.0,         # padrao

        # --- drenagem e travessias ---
        # NAO e o padrao: a extracao de drenagem vem desligada. Aqui esta ligada
        # porque e ela que produz o setimo produto, a camada de travessias.
        "STREAMS_FROM_DEM": True,
        "STREAM_MIN_BASIN_KM2": 1.0,      # padrao
        "STREAM_FORD_MAX_KM2": 50.0,      # padrao: acima disto vira barreira

        # --- restricoes e criterio extra ---
        "CONSTRAINT_LAYER": None,
        "CONSTRAINT_BUFFER_M": 30.0,      # padrao
        "CONSTRAINT_MODE": 0,             # padrao: 0 = evitar, 1 = penalizar
        "EXTRA_CRITERION_LAYER": None,
        "EXTRA_CRITERION_WEIGHT": 0.0,    # padrao
        "EXTRA_CRITERION_DIRECTION": 0,   # padrao: valor baixo e melhor

        # --- transitabilidade ---
        "TRANSITABILITY_BREAKS": "20, 35, 60, 100",   # padrao, em porcentagem

        # --- saida ---
        "OUTPUT_FILE": saida,
        "OUTPUT_FORMAT": 1,               # 0 = Shapefile, 1 = GeoPackage, 2 = KML
        "OUTPUT_CRS": "",                 # vazio = CRS de trabalho do MDE
    }


def _processing_do_qgis():
    """Importa o modulo `processing` do QGIS, e nao o homonimo do plugin.

    O TopoTrail tem um subpacote chamado `processing`. Quando a raiz do
    repositorio esta no sys.path -- e ela esta, por exemplo, sob
    `python -m pytest` executado da raiz --, `import processing` encontra o do
    plugin, que nao tem `core`, e o bootstrap falha com uma mensagem que nao diz
    isso. Aqui a pasta de plugins do QGIS vai para o inicio do sys.path e um
    modulo homonimo ja importado e descartado antes do import.
    """
    candidatos = ("/usr/share/qgis/python/plugins",
                  os.path.join(sys.prefix, "share", "qgis", "python", "plugins"))
    for caminho in candidatos:
        if not os.path.isdir(caminho):
            continue
        if caminho in sys.path:
            sys.path.remove(caminho)
        sys.path.insert(0, caminho)

    ja_importado = sys.modules.get("processing")
    arquivo = getattr(ja_importado, "__file__", "") or ""
    if ja_importado is not None and os.path.abspath(arquivo).startswith(RAIZ + os.sep):
        for nome in [n for n in list(sys.modules)
                     if n == "processing" or n.startswith("processing.")]:
            del sys.modules[nome]

    import processing as processing_qgis
    from processing.core.Processing import Processing
    Processing.initialize()
    return processing_qgis


def subir_qgis():
    from qgis.core import QgsApplication

    aplicacao = QgsApplication.instance()
    if aplicacao is None:
        aplicacao = QgsApplication([], False)
        QgsApplication.setPrefixPath("/usr", True)
        aplicacao.initQgis()

    processing_qgis = _processing_do_qgis()

    pai = os.path.dirname(RAIZ)
    if pai not in sys.path:
        sys.path.insert(0, pai)
    provider = __import__("{}.topotrail".format(PACOTE),
                          fromlist=["topotrail"]).TopotrailProvider()
    QgsApplication.processingRegistry().addProvider(provider)
    # O provider precisa sobreviver ao fim desta funcao: o registro do QGIS
    # guarda uma referencia fraca e o algoritmo some do registro se ele for
    # coletado.
    subir_qgis.provider = provider
    return aplicacao, processing_qgis


def ler_atributos(caminho):
    from osgeo import ogr

    fonte = ogr.Open(caminho)
    if fonte is None:
        raise SystemExit("nao foi possivel abrir {}".format(caminho))
    camada = fonte.GetLayer(0)
    definicao = camada.GetLayerDefn()
    feicoes = []
    for feicao in camada:
        feicoes.append({definicao.GetFieldDefn(i).GetName(): feicao.GetField(i)
                        for i in range(definicao.GetFieldCount())})
    quantidade = camada.GetFeatureCount()
    fonte = None
    return quantidade, feicoes


def conferir(medido, esperado=None):
    """Devolve a lista de divergencias entre o medido e o esperado."""
    esperado = ESPERADO if esperado is None else esperado
    divergencias = []
    for chave, alvo in sorted(esperado.items()):
        obtido = medido.get(chave)
        if isinstance(alvo, float):
            # Grandeza continua: a ultima casa pode variar com a versao do NumPy
            # ou do GDAL.
            igual = (obtido is not None
                     and abs(float(obtido) - alvo) <= TOLERANCIA * abs(alvo))
        else:
            # Contagem ou texto: tem de bater exatamente.
            igual = obtido == alvo
        if not igual:
            divergencias.append("{}: esperado {!r}, obtido {!r}".format(chave, alvo, obtido))
    return divergencias


def main():
    mde = os.path.join(PASTA, "mde.tif")
    if not os.path.isfile(mde):
        print("MDE ausente; gerando com exemplo/gerar_mde.py")
        sys.path.insert(0, PASTA)
        import gerar_mde
        gerar_mde.main()

    os.makedirs(SAIDA, exist_ok=True)
    saida = os.path.join(SAIDA, "exemplo.gpkg")

    aplicacao, processing_qgis = subir_qgis()

    from osgeo import gdal, ogr
    gdal.UseExceptions()
    ogr.UseExceptions()

    from qgis.core import QgsProcessingFeedback, QgsSettings

    # O idioma decide os rotulos gravados dentro do GeoTIFF de
    # transitabilidade. Fixado aqui para que a saida do exemplo seja a mesma em
    # qualquer maquina, e nao a do idioma do sistema de quem executa.
    QgsSettings().setValue("TopoTrail/language", "pt")

    class Registro(QgsProcessingFeedback):
        def __init__(self):
            super().__init__()
            self.linhas = []

        def pushInfo(self, mensagem):
            self.linhas.append(mensagem)

        def pushWarning(self, mensagem):
            self.linhas.append("AVISO: " + mensagem)

        def reportError(self, mensagem, fatal=False):
            self.linhas.append("ERRO: " + mensagem)

    registro = Registro()
    resultado = processing_qgis.run(
        "topotrail:topotrail",
        parametros(mde,
                   os.path.join(PASTA, "origem.geojson"),
                   os.path.join(PASTA, "destino.geojson"),
                   os.path.join(PASTA, "intermediario.geojson"),
                   saida),
        feedback=registro)

    _, rota = ler_atributos(resultado["OUTPUT_ROUTE"])
    travessias, _ = ler_atributos(resultado["OUTPUT_CROSSINGS"])
    zonas, _ = ler_atributos(resultado["OUTPUT_VECTOR"])
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

    print("")
    print("Produtos gerados em {}:".format(SAIDA))
    for chave in ("OUTPUT_SCORE_RASTER", "OUTPUT_RISK_RASTER",
                  "OUTPUT_TRANSITABILITY", "OUTPUT_VECTOR", "OUTPUT_ROUTE",
                  "OUTPUT_CORRIDOR", "OUTPUT_CROSSINGS", "OUTPUT_DEBUG_LOG"):
        print("  {:24s} {}".format(chave, os.path.basename(resultado[chave])))

    print("")
    print("Valores da rota (os mesmos estao em exemplo/README.md):")
    for chave, valor in sorted(medido.items()):
        alvo = ESPERADO.get(chave)
        print("  {:16s} {:<12} esperado {}".format(chave, valor, alvo))

    with open(os.path.join(SAIDA, "valores.json"), "w", encoding="utf-8") as arquivo:
        json.dump(medido, arquivo, ensure_ascii=False, indent=2, sort_keys=True)
        arquivo.write("\n")

    divergencias = conferir(medido)
    print("")
    if divergencias:
        print("NAO CONFERE com os valores documentados:")
        for linha in divergencias:
            print("  " + linha)
        raise SystemExit(1)
    print("CONFERE: todos os valores batem com exemplo/README.md.")
    return medido


if __name__ == "__main__":
    main()
