import os
import contextlib
import tempfile
import shutil
import heapq
import logging
import json
import platform
import sys
from datetime import datetime

# QGIS' Python bootstrap may try to register every PATH directory as a DLL
# directory. The Microsoft WindowsApps shim can be unreadable in this setup,
# so keep it out of this process before importing qgis.* modules.
if sys.platform == "win32":
    os.environ["PATH"] = os.pathsep.join(
        path for path in os.environ.get("PATH", "").split(os.pathsep)
        if "Microsoft\\WindowsApps" not in path
    )

import numpy as np  # noqa: E402
from osgeo import gdal, ogr, osr  # noqa: E402
from . import mensagens, morphology  # noqa: E402
from .mensagens import t  # noqa: E402
from .hydrology import analyse_hydrology  # noqa: E402
from .terrain import (  # noqa: E402
    check_terrain_size,
    derive_terrain,
    vector_ruggedness,
)
from .transitability import (  # noqa: E402
    CLASS_COLORS,
    CLASS_LABELS,
    CLASS_LABELS_EN,
    DEFAULT_SLOPE_BREAKS,
    classify as classify_transitability,
    format_class_labels,
    walkable_fraction,
)
from qgis.core import (  # noqa: E402
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterEnum,
    QgsProcessingParameterCrs,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputVectorLayer,
    QgsProcessingOutputRasterLayer,
    QgsProcessingOutputFile,
)

# As excecoes de GDAL/OGR NAO sao ligadas aqui de proposito: UseExceptions()
# no import muda o GDAL do processo QGIS inteiro. Medido na auditoria: antes de
# importar o TopoTrail, gdal.GetUseExceptions() = 0 e gdal.Open de arquivo
# inexistente devolvia None; depois do import passava a 1 e levantava
# RuntimeError -- para todo outro plugin e para o proprio codigo Python do
# QGIS, que ainda espera Open() -> None. Agora isso vale so no escopo do
# algoritmo, em gdal_exceptions_scoped().


_LOG = logging.getLogger("TopoTrail")

PLUGIN_VERSION = "1.5.5"
STRICT_CRS_MODE = True

# Sentinela gravado nas quinas vazias que a reprojecao do MDE cria. Precisa ser
# um valor que nenhum MDE real assume: -9999 m fica muito abaixo do ponto mais
# profundo do planeta.
DEM_FILL_NODATA = -9999.0

# Empirical modelling constants. They preserve the current published behavior,
# but are named so the methodological choices are visible and auditable.
CURVATURE_SCORE_FLOOR = 0.2
CURVATURE_DEVIATION_PERCENTILE = 99.0
CURVATURE_RISK_PERCENTILE = 95.0
SLOPE_RISK_EXPONENT = 1.35
RISK_SLOPE_WEIGHT = 0.75
RISK_CURVATURE_WEIGHT = 0.25
ROUTE_COST_EPSILON = 0.05
MAX_ROUTE_CROP_CELLS = 8000000
# Acima deste valor absoluto nenhum raster de criterio de terreno tem
# significado fisico: curvaturas reais ficam na casa de 1e-2 1/m, declividades
# em 1e2 %, altitudes em 1e4 m. Sentinelas de NoData nao declaradas -- -3.4e38
# (minimo do float32), -9999, 1e30 -- passam de longe, e nenhuma delas e NaN,
# entao nanpercentile nao as descarta.
CRITERION_PLAUSIBLE_ABS = 1e6
NEAREST_VALID_CELL_RADIUS = 30
# Acima deste deslocamento o ponto que o usuario pediu deixa de caber no
# corredor que o plugin entrega por padrao (ROUTE_BUFFER_M = 100 m de raio):
# a rota passa a responder por um lugar que ninguem apontou, e o comprimento,
# o tempo e o ganho anunciados sao todos do trajeto deslocado. Abaixo dele o
# ponto pedido continua dentro do corredor entregue e um aviso so faria ruido.
# Todo deslocamento, de qualquer tamanho, vai ao log de qualquer maneira --
# medido na auditoria: 7.500 m de deslocamento com zero mensagens.
NEAREST_VALID_CELL_WARN_M = 100.0
MIN_ALTITUDE_BAND_SIZE_M = 50.0

# Area minima do fragmento das zonas. O padrao (-1) e automatico: 0,05% da area
# analisada, entre 1 e 50 ha -- 5 ha numa UC de 10 mil ha, 50 ha a partir de
# 100 mil ha. Ate a 1.5.2 eram 50 ha fixos. Medido em 15 UCs de protecao
# integral sorteadas do Cadastro Nacional (500 a 300.000 ha, amplitude de pelo
# menos 300 m): com 50 ha as zonas deixavam faixas de altitude de fora em 7; a
# regra proporcional resolveu 4 delas, nao criou aviso em nenhuma e, nas UCs
# grandes, da o mesmo que os 50 ha. Os 5 ha fixos resolviam as mesmas 4, mas
# picotavam as zonas das UCs grandes em 4 a 9 vezes mais fragmentos.
MIN_PATCH_AREA_AUTO = -1.0
MIN_PATCH_AREA_FRACTION = 0.0005
MIN_PATCH_AREA_BOUNDS_HA = (1.0, 50.0)

# Unidade do raster de declividade fornecido pelo usuario. Internamente o
# TopoTrail trabalha sempre em porcentagem.
SLOPE_UNIT_PERCENT = 0
SLOPE_UNIT_DEGREES = 1

# Unidade vertical do MDE. Metros e o padrao; pes ainda e corrente em dados
# publicos dos Estados Unidos, e um MDE em pes lido como metros faz o plugin
# descartar toda a area e falhar sem mencionar altitude.
VERTICAL_UNIT_METRES = 0
VERTICAL_UNIT_FEET = 1
FEET_TO_METRES = 0.3048

# Como a adequabilidade vira custo de deslocamento.
ROUTE_COST_INVERSE = 0      # 1/(S + eps), comportamento das versoes 0.5.x
ROUTE_COST_EXPONENTIAL = 1  # exp(k(1 - S)), contraste controlado pelo usuario
ROUTE_COST_TOBLER = 2       # tempo de caminhada anisotropico
DEFAULT_ROUTE_CONTRAST = 6.0

# Funcao de caminhada de Tobler (1993), em km/h, para declive S = dz/dx com
# sinal: W = 6 * exp(-3.5 * |S + 0.05|). O maximo de 6 km/h ocorre em S = -0.05,
# uma descida suave, e nao no plano -- e essa assimetria e justamente o que o
# modelo isotropico nao representa.
#
# Os tres valores foram medidos contra 110 horas de GPS de campo em duas
# regioes (docs/VALIDACAO.md). O que se pode afirmar:
#
#   vmax   Superestimado por um fator de 1,7 a 3,1 para levantamento de campo.
#          A pe, com equipamento e parando para procurar animais, a mediana
#          observada na caatinga foi de 2,4 a 3,6 km/h conforme o criterio de
#          parada, nao 6. IMPORTANTE: vmax nao altera a rota. O A* compara
#          custos relativos, entao multiplicar a velocidade por uma constante
#          divide todos os custos pela mesma constante e o caminho escolhido e
#          bit a bit identico (test_routing_math.py fixa essa invariancia). O
#          erro aparece so na duracao estimada, que escala por 6/vmax.
#   decay  Contra velocidade o ajuste da 1,3 a 2,3, abaixo dos 3,5 publicados,
#          com intervalo largo e diluicao de regressao. Mas o decay governa a
#          geometria, entao a medida que vale e a geometrica -- e essa CONFIRMA
#          o valor publicado: a concordancia com sete trilhas reais sobe
#          monotonicamente de 72,4% em decay=1,3 para 84,1% em 3,5, e estabiliza
#          depois. Calibrado contra o objetivo certo, o 3,5 de Tobler se
#          sustenta. Fica no valor publicado, agora por evidencia.
#   otimo  Ajuste em 0,00 contra os 0,05 publicados: nenhuma vantagem de
#          descida suave foi detectada. Evidencia fraca, amostra pequena em
#          declive negativo.
#
# O gradiente explicou apenas 4 a 10% da variancia da velocidade observada
# (R2 no log). Em levantamento de campo o ritmo e determinado pela vegetacao,
# pela carga e pelo comportamento de busca, nao pela topografia. A funcao de
# Tobler continua sendo a melhor base disponivel para *comparar* trechos, que e
# o que a rota precisa, mas a duracao que ela devolve nao deve ser lida como
# previsao de tempo de campo.
TOBLER_MAX_SPEED_KMH = 6.0
TOBLER_DECAY = 3.5
TOBLER_OPTIMUM_SLOPE = 0.05

# Ritmo mediano medido em trajetos de inventario botanico na caatinga, com
# paradas de ate 120 s contadas como caminhada. Os trajetos de GPS que sustentam
# esta constante foram registrados e cedidos por Sabrina Barros da Silva
# (S.B. Silva), em inventario conduzido para a dissertacao dela. E o ritmo de um
# levantamento botanico no semiarido, nao uma constante universal de campo.
# Oferecido como alternativa explicita a 6,0 km/h para quem quer que a duracao
# estimada se pareca com a duracao real.
FIELD_SURVEY_SPEED_KMH = 2.4

# Quanto o terreno ruim retarda a caminhada, alem da inclinacao. Adequabilidade
# 1 nao retarda nada (Tobler puro); adequabilidade 0 multiplica o tempo por
# 1 + este valor.
#
# CALIBRADO CONTRA GEOMETRIA. Duas medicoes, e a ordem entre elas importa.
#
# Contra *velocidade*, o coeficiente sai em -0,32 +- 0,18: indistinguivel de
# zero e de sinal trocado. Isso parecia condenar a constante, mas a pergunta
# estava errada -- prever tempo nunca foi funcao dela. A funcao e escolher por
# onde a rota passa, e e contra isso que ela tem de ser medida.
#
# Contra a *geometria* de sete trajetos reais (concordancia de Goodchild-Hunter
# a 250 m), o termo se sustenta com folga:
#
#     SLOWDOWN   0,0    0,5    1,0    2,0    4,0
#     concord.  72,0%  74,0%  83,5%  84,1%  87,9%
#
# Desligar o termo custa 12 pontos de concordancia. A existencia dele esta
# validada. Ja a magnitude nao: a validacao cruzada leave-one-out da 83,5% para
# o melhor valor escolhido nos outros seis trajetos, contra 84,1% do padrao --
# o ganho aparente de 4,0 nao generaliza, que e a assinatura classica de
# superajuste com sete curvas. Entao 2,0 fica, agora por evidencia e nao por
# arbitrio, e o que falta para separar 2,0 de 4,0 sao mais trilhas, nao mais
# analise. Ver docs/VALIDACAO.md, secao 8.
TERRAIN_SLOWDOWN_MAX = 2.0

# Aviso de desvio pela declividade maxima. Quando a rota existe, mas contorna
# terreno acima do limite, ela pode passar longe da trilha real: em 23 de 95
# trilhas reais a trilha sobe trecho que o MDE de 30 m ve acima de 85% (cabo,
# escada, zigue-zague que a grade nao resolve), e ali a rota a 85% desviava, as
# vezes por quilometros. O plugin compara a rota com a rota sem o limite (que
# ainda respeita rios e restricoes) e avisa quando ela e ao menos 25% e 500 m
# mais longa. Nas 95 trilhas, isso aconteceu em 10, e nas 10 a rota sem o
# limite ficou mais perto da trilha real (testes do artigo, 27/10/2026). O
# limite nao muda: o aviso so informa e diz quanto subir.
DETOUR_WARN_RATIO = 1.25
DETOUR_WARN_MIN_M = 500.0

# ATENCAO ao usar cursos d'agua como restricao em paisagem sazonalmente seca.
# Nos trajetos de campo da caatinga, as trilhas reais cruzaram 1,37 canais por
# km contra 0,68 da linha reta entre os mesmos extremos: os trajetos cruzaram
# DUAS VEZES MAIS drenagem do que o acaso geometrico, e nao menos. Nao ha
# evitacao revelada a calibrar. Em terreno semiarido o leito seco costuma ser a
# melhor superficie de caminhada -- plano, desobstruido e sem a vegetacao
# espinhosa do interfluvio -- e, tratando-se de inventario botanico, a faixa
# marginal de drenagem concentra umidade e flora distintas do interfluvio, sendo
# ali alvo de amostragem e nao obstaculo. As duas explicacoes sao interpretacao;
# o que a medicao sustenta e o fato. Penalizar drenagem por padrao afastaria a
# rota de um terreno que, nesses trajetos, foi procurado e nao evitado. Por isso a restricao e opcional
# e permanece desligada por padrao. Ver docs/VALIDACAO.md, secao 6.
#
# O que fazer com celulas restritas (cursos d'agua, camada vetorial do usuario).
CONSTRAINT_AVOID = 0        # exclusao dura
CONSTRAINT_PENALISE = 1     # encarece sem proibir
# Nao ha evitacao a calibrar, e penalizar tambem nao ajuda a geometria: com as
# sete trilhas reais, a concordancia e 87,9% sem penalidade, 87,7% com fator 2,0
# e 87,7% com fator 8,0. Tratar drenagem como ATRATIVO e claramente pior (69,4%
# com fator 0,5). Ou seja, a melhor politica medida e a que ja esta no padrao:
# desligada. O fator permanece como intensidade declarada pelo usuario para
# quando houver uma restricao real a impor (cerca, area vedada, propriedade
# privada), nao como constante medida.
CONSTRAINT_PENALTY_FACTOR = 8.0

# Travessia de cursos d'agua, graduada pelo tamanho do curso. O MDE nao sabe
# vazao nem estacao; sabe a AREA DE CONTRIBUICAO de cada celula de canal, e a
# geometria hidraulica liga uma coisa a outra: largura e vazao de canal crescem
# com a area de drenagem em lei de potencia (Leopold & Maddock 1953, USGS Prof.
# Paper 252; Faustini, Kaufmann & Herlihy 2009, Geomorphology 108:292-311,
# largura de margens plenas W ~ A^0.5 em rios vadeaveis dos EUA). Um corrego de
# cabeceira de 1 km2 se passa a pe; um rio de 100 km2, nao se presume. As
# classes abaixo sao um proxy declarado, nao uma medida de seguranca: cada
# travessia sai listada num arquivo proprio para ser conferida em campo, e o
# aviso diz que profundidade e corrente mudam com a chuva.
#
# A drenagem INFORMA a rota, nao a desvia: abaixo do teto vadeavel o fator e 1.
# Ate a 1.4.1 as classes custavam 2x, 4x e 8x, cobrados em toda a faixa de
# drenagem -- andar ao longo do rio custava o mesmo que atravessa-lo, e a rota
# fugia dos fundos de vale. Medido em 62 trilhas reais (51 consagradas e 11 da
# dissertacao): com esses fatores a concordancia piorou em 32 e melhorou em 15
# (p = 0,02); nas trilhas de fundo de vale, piorou em 11 de 13. Com fator 1 a
# rota volta ao que seria sem drenagem (igual em 56 de 61) e as travessias
# continuam listadas com a classe. Acima do teto, o curso segue sendo barreira.
FORD_CLASSES = (
    # (area maxima km2, fator de custo na travessia, chave do rotulo)
    (2.0, 1.0, "ford_headwater"),
    (10.0, 1.0, "ford_stream"),
    (float("inf"), 1.0, "ford_river_small"),   # ate o teto vadeavel do usuario
)
DEFAULT_STREAM_FORD_MAX_KM2 = 50.0            # acima disto: barreira para a rota

# Teto de pontos intermediarios para a otimizacao exata de ordem. O custo e
# 2^n * n^2 em tempo e n^2 execucoes do A* para montar a matriz de pares.
MAX_OPTIMISED_WAYPOINTS = 8

# Corredor de alternativas: celulas por onde passa algum caminho ate X% mais
# caro que o otimo. Teto da folga e do tamanho da grade (o calculo percorre a
# grade inteira duas vezes, em vez de parar no destino como o A*).
# Superficie d'agua achatada no MDE: area continua de altitude exatamente
# constante. Copernicus, SRTM e derivados achatam mar, lagos e represas, e para
# o modelo de caminhada isso parece o terreno ideal. Medido em Svalbard
# (Copernicus GLO-30): 45 de 178 vertices da rota sobre o fiorde, a 0 m.
WATER_MIN_AREA_M2 = 500000.0
SEA_LEVEL_MAX_M = 0.5

MAX_ALTERNATIVES_PCT = 50.0
MAX_ALTERNATIVES_CELLS = 4000000

# Sentido de um criterio raster fornecido pelo usuario: valores altos podem ser
# bons (cobertura vegetal densa que dá sombra) ou ruins (pedregosidade).
CRITERION_LOWER_IS_BETTER = 0
CRITERION_HIGHER_IS_BETTER = 1

# Diagnostico de discriminacao do modelo. Em terreno muito ingreme os limites
# absolutos de declividade saturam: acima de SLOPE_SCORE_MAX toda celula recebe
# nota zero no criterio de declividade, e ele deixa de distinguir qualquer coisa.
# Medido no Everest com os valores de fabrica, a adequabilidade ficou constante
# em 1,000 do P05 ao P95 -- o resultado parecia valido e nao continha informacao.
SATURATION_WARNING_FRACTION = 0.40
MIN_SCORE_AMPLITUDE = 0.05


def diagnostic_log_path(output_path):
    base_path, _ = os.path.splitext(output_path)
    return f"{base_path}_diagnostico_topotrail.log"


def array_diagnostics(array):
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return {"shape": list(array.shape), "valid_pixels": 0}
    return {
        "shape": list(array.shape),
        "total_pixels": int(array.size),
        "valid_pixels": int(valid.size),
        "nodata_pixels": int(array.size - valid.size),
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "std": float(np.nanstd(valid)),
        "p05": float(np.nanpercentile(valid, 5)),
        "p25": float(np.nanpercentile(valid, 25)),
        "p50": float(np.nanpercentile(valid, 50)),
        "p75": float(np.nanpercentile(valid, 75)),
        "p95": float(np.nanpercentile(valid, 95)),
    }


def file_diagnostics(path):
    if not path:
        return {"path": path, "exists": False}
    return {
        "path": path,
        "exists": os.path.exists(path),
        "size_bytes": os.path.getsize(path) if os.path.exists(path) else None,
    }


def append_diagnostic_log(log_path, event, **data):
    """Grava um evento no registro de diagnostico da execucao.

    O evento "processamento_iniciado" RECOMECA o arquivo. O registro documenta
    uma execucao -- e a prova de proveniencia que permite reproduzir uma rota a
    partir dele --, e as demais saidas do mesmo conjunto (rasters, camadas) sao
    sobrescritas a cada execucao. Acumulando, o arquivo passava a conter varias
    execucoes sem nada que as separasse, e a leitura mais natural, a primeira
    linha, era a da execucao mais antiga: foi assim que um registro gravado pela
    versao 1.2.0 continuou anunciando 1.2.0 depois de a rota ter sido
    recalculada pela 1.3.0.
    """
    if not log_path:
        return
    output_dir = os.path.dirname(log_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        **data,
    }
    modo = "w" if event == "processamento_iniciado" else "a"
    with open(log_path, modo, encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def dependency_diagnostics():
    """Return lightweight runtime versions for diagnostic JSONL records."""
    try:
        gdal_version = gdal.VersionInfo("--version")
    except Exception:
        gdal_version = "indisponivel"
    return {
        "plugin_version": PLUGIN_VERSION,
        "python": sys.version.replace("\n", " "),
        "gdal": gdal_version,
        "sistema": platform.platform(),
    }


def ogr_memory_driver():
    """Driver vetorial em memoria: 'MEM' no GDAL >= 3.11, 'Memory' antes dele.

    O GDAL 3.11 unificou os dois sob 'MEM' e marcou 'Memory' como obsoleto; ele
    sera removido, e o QGIS 4 ja vem com GDAL 3.11+.
    """
    for nome in ("MEM", "Memory"):
        driver = ogr.GetDriverByName(nome)
        if driver is not None and driver.GetMetadataItem("DCAP_VECTOR") == "YES":
            return driver
    raise _erro(t("msg_gdal_sem_memoria"))


def srs_from_projection(projection, default_crs=None):
    """Build an OSR SpatialReference from WKT or an optional default CRS.

    Parameters are projection WKT from GDAL and an optional fallback such as
    EPSG:4326. The returned SRS uses traditional GIS axis order. Returns None
    when neither projection nor default CRS is available.
    """
    srs = osr.SpatialReference()
    if projection:
        srs.ImportFromWkt(projection)
    elif default_crs:
        if str(default_crs).upper().startswith("EPSG:"):
            srs.ImportFromEPSG(int(str(default_crs).split(":")[1]))
        else:
            srs.SetFromUserInput(str(default_crs))
    else:
        return None
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def srs_from_any(crs):
    """SRS a partir de 'EPSG:32723', WKT ou qualquer entrada que o OSR aceite."""
    srs = osr.SpatialReference()
    text = str(crs)
    if text.upper().startswith("EPSG:"):
        srs.ImportFromEPSG(int(text.split(":")[1]))
    else:
        srs.SetFromUserInput(text)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


class FeatureSet:
    """Camada vetorial em memoria, feita so com OGR.

    Substitui o GeoDataFrame do geopandas nos pontos em que o plugin monta,
    reprojeta, mede e grava vetores. O QGIS garante GDAL/OGR (e com ele o GEOS)
    em toda instalacao; o geopandas, nao -- e um import dele no topo do modulo
    impedia o plugin de carregar em QGIS limpo.

    ``geometries`` sao ogr.Geometry; ``attributes`` uma lista de dicionarios,
    um por feicao, todos com as mesmas chaves; ``crs`` e a string que
    identifica o sistema (WKT ou AUTHORITY:CODE).
    """

    def __init__(self, geometries=(), attributes=(), crs=None):
        self.geometries = [g for g in geometries]
        self.attributes = [dict(a) for a in attributes]
        if len(self.attributes) != len(self.geometries):
            raise ValueError("FeatureSet: geometries and attributes differ in length")
        self.crs = crs

    def __len__(self):
        return len(self.geometries)

    @property
    def columns(self):
        names = []
        for record in self.attributes:
            for key in record:
                if key not in names:
                    names.append(key)
        return names + ["geometry"]

    def column(self, name):
        return [record.get(name) for record in self.attributes]

    def set_column(self, name, values):
        values = list(values)
        if len(values) != len(self.attributes):
            raise ValueError(f"FeatureSet: column {name} has {len(values)} values for {len(self)} features")
        for record, value in zip(self.attributes, values):
            record[name] = value

    def drop_column(self, name):
        for record in self.attributes:
            record.pop(name, None)

    def srs(self):
        return srs_from_any(self.crs) if self.crs else None

    def to_crs(self, target):
        """Nova colecao com as geometrias transformadas para ``target``."""
        source_srs = self.srs()
        target_srs = srs_from_any(target)
        if source_srs is None:
            raise _erro(t("msg_featureset_sem_crs"))
        if source_srs.IsSame(target_srs):
            return FeatureSet([g.Clone() for g in self.geometries], self.attributes, self.crs)
        transformation = osr.CoordinateTransformation(source_srs, target_srs)
        moved = []
        for geometry in self.geometries:
            clone = geometry.Clone()
            if clone.Transform(transformation) != 0:
                raise _erro(t("msg_reprojetar_geometria"))
            moved.append(clone)
        return FeatureSet(moved, self.attributes, str(target))

    def buffer(self, distance):
        return FeatureSet([g.Buffer(float(distance)) for g in self.geometries], self.attributes, self.crs)

    def lengths(self):
        return [float(g.Length()) for g in self.geometries]

    def areas(self):
        return [float(g.GetArea()) for g in self.geometries]

    def total_bounds(self):
        """[minx, miny, maxx, maxy] de todas as geometrias."""
        if not self.geometries:
            return None
        envelopes = [g.GetEnvelope() for g in self.geometries]  # (minx, maxx, miny, maxy)
        return [
            min(e[0] for e in envelopes), min(e[2] for e in envelopes),
            max(e[1] for e in envelopes), max(e[3] for e in envelopes),
        ]

    @staticmethod
    def _field_type(values):
        for value in values:
            if value is None:
                continue
            if isinstance(value, (bool, np.bool_)):
                return ogr.OFTInteger
            if isinstance(value, (int, np.integer)):
                return ogr.OFTInteger64
            if isinstance(value, (float, np.floating)):
                return ogr.OFTReal
            return ogr.OFTString
        return ogr.OFTString

    def to_file(self, path, driver="GPKG", layer_name=None, stringify=False):
        """Grava a colecao. ``stringify`` converte todo atributo em texto (KML)."""
        ogr_driver = ogr.GetDriverByName(driver)
        if ogr_driver is None:
            raise _erro(t("msg_driver_ogr", driver=driver))
        if layer_name is None:
            layer_name = os.path.splitext(os.path.basename(path))[0]
        # "gpkg_*" e prefixo reservado do GeoPackage: um arquivo de saida chamado
        # gpkg_saida.gpkg falhava na criacao da camada.
        if layer_name.lower().startswith("gpkg"):
            layer_name = "topotrail_" + layer_name
        # Um GeoPackage guarda varias camadas, e o usuario costuma ter um so
        # arquivo de projeto com tudo dentro. Recriar o arquivo apagava o
        # trabalho dele inteiro -- pontos de coleta, limites, amostras -- sem
        # aviso e com o algoritmo relatando sucesso. Abrindo para atualizacao,
        # so a camada homonima e substituida e o resto fica onde estava.
        datasource = None
        if driver == "GPKG" and os.path.exists(path):
            try:
                datasource = ogr.Open(path, 1)
            except Exception:
                datasource = None
            if datasource is not None:
                for indice in range(datasource.GetLayerCount() - 1, -1, -1):
                    if datasource.GetLayerByIndex(indice).GetName() == layer_name:
                        datasource.DeleteLayer(indice)
        if datasource is None:
            datasource = ogr_driver.CreateDataSource(path)
        if datasource is None:
            raise _erro(t("msg_criar_vetor", path=path))
        geom_type = ogr.wkbUnknown
        kinds = {ogr.GT_Flatten(g.GetGeometryType()) for g in self.geometries}
        if kinds == {ogr.wkbPolygon} or kinds == {ogr.wkbMultiPolygon} or kinds == {ogr.wkbPolygon, ogr.wkbMultiPolygon}:
            geom_type = ogr.wkbMultiPolygon
        elif kinds == {ogr.wkbLineString}:
            geom_type = ogr.wkbLineString
        elif kinds == {ogr.wkbPoint}:
            geom_type = ogr.wkbPoint
        layer = datasource.CreateLayer(layer_name, srs=self.srs(), geom_type=geom_type)
        if layer is None:
            raise _erro(t("msg_criar_camada", path=path))

        names = [name for name in self.columns if name != "geometry"]
        for name in names:
            values = self.column(name)
            field_type = ogr.OFTString if stringify else self._field_type(values)
            definition = ogr.FieldDefn(name, field_type)
            if field_type == ogr.OFTString:
                definition.SetWidth(254)
            layer.CreateField(definition)
        layer_defn = layer.GetLayerDefn()
        # Shapefile trunca nomes com mais de 10 caracteres: gravamos pelo indice.
        for geometry, record in zip(self.geometries, self.attributes):
            feature = ogr.Feature(layer_defn)
            for index, name in enumerate(names):
                value = record.get(name)
                if value is None or (isinstance(value, (float, np.floating)) and not np.isfinite(value)):
                    if stringify:
                        feature.SetField(index, "")
                    else:
                        feature.SetFieldNull(index)
                    continue
                if stringify:
                    feature.SetField(index, str(value))
                elif isinstance(value, (bool, np.bool_)):
                    feature.SetField(index, int(value))
                elif isinstance(value, np.integer):
                    feature.SetField(index, int(value))
                elif isinstance(value, np.floating):
                    feature.SetField(index, float(value))
                else:
                    feature.SetField(index, value)
            geometry_out = geometry.Clone()
            if geom_type == ogr.wkbMultiPolygon and ogr.GT_Flatten(geometry_out.GetGeometryType()) == ogr.wkbPolygon:
                geometry_out = ogr.ForceToMultiPolygon(geometry_out)
            feature.SetGeometry(geometry_out)
            layer.CreateFeature(feature)
            feature = None
        layer = None
        datasource = None


def srs_label(srs):
    """Return a compact CRS label, preferring AUTHORITY:CODE when available."""
    if not srs:
        return None
    authority = srs.GetAuthorityName(None)
    code = srs.GetAuthorityCode(None)
    if authority and code:
        return f"{authority}:{code}"
    return srs.ExportToProj4() or srs.ExportToWkt()[:120]


def raster_metadata(path):
    """Read raster grid metadata without loading pixel values.

    Returns CRS, dimensions, GeoTransform, pixel size, bounds, NoData and axis
    orientation. Raises a clear exception if GDAL cannot open the raster. The
    dataset handle is explicitly released before returning.
    """
    try:
        dataset = gdal.Open(path)
    except RuntimeError as exc:
        raise _erro(t("msg_raster_metadados", path=path)) from exc
    if dataset is None:
        raise _erro(t("msg_raster_metadados", path=path))
    transform = dataset.GetGeoTransform()
    projection = dataset.GetProjection()
    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue() if band else None
    cols = dataset.RasterXSize
    rows = dataset.RasterYSize
    min_x = transform[0]
    max_y = transform[3]
    max_x = transform[0] + cols * transform[1] + rows * transform[2]
    min_y = transform[3] + cols * transform[4] + rows * transform[5]
    bounds = (min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))
    srs = srs_from_projection(projection)
    metadata = {
        "path": path,
        "cols": cols,
        "rows": rows,
        "transform": tuple(float(value) for value in transform),
        "projection": projection,
        "crs": srs_label(srs),
        "is_geographic": bool(srs and srs.IsGeographic()),
        "is_projected": bool(srs and srs.IsProjected()),
        # Comprimento real do passo de coluna/linha: numa grade rotacionada os
        # termos [2] e [4] entram; abs(transform[1]) sozinho subestima.
        "pixel_size_x": float(np.hypot(transform[1], transform[4])),
        "pixel_size_y": float(np.hypot(transform[2], transform[5])),
        "rotated": bool(abs(transform[2]) > 1e-12 or abs(transform[4]) > 1e-12),
        "bounds": bounds,
        "nodata": nodata,
        "y_axis_orientation": "north_up" if transform[5] < 0 else "south_up_or_unknown",
    }
    dataset = None
    return metadata


def raster_center_from_metadata(metadata):
    """Calculate raster center coordinates from metadata and GeoTransform."""
    transform = metadata["transform"]
    cols = metadata["cols"]
    rows = metadata["rows"]
    center_x = transform[0] + (cols * transform[1]) / 2.0 + (rows * transform[2]) / 2.0
    center_y = transform[3] + (cols * transform[4]) / 2.0 + (rows * transform[5]) / 2.0
    return float(center_x), float(center_y)


def geographic_center_of_raster(metadata):
    """Centro do raster em longitude/latitude (EPSG:4326), qualquer que seja o CRS."""
    center_x, center_y = raster_center_from_metadata(metadata)
    srs = srs_from_projection(metadata.get("projection"))
    if srs is None or srs.IsGeographic():
        return center_x, center_y
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lon, lat, _ = osr.CoordinateTransformation(srs, wgs84).TransformPoint(center_x, center_y)
    return float(lon), float(lat)


def automatic_utm_crs_for_geographic_raster(metadata):
    """Choose an EPSG UTM CRS from the raster center.

    Uses longitude to choose zone 1-60 and latitude to choose hemisphere:
    EPSG:326xx in the north, EPSG:327xx in the south. Works for geographic
    rasters and, through the raster's own CRS, for projected ones that need a
    metric working CRS (feet, Web Mercator). Longitude is normalised to
    [-180, 180) so a 0..360 raster does not land in zone 60.
    """
    lon, lat = geographic_center_of_raster(metadata)
    lon = ((lon + 180.0) % 360.0) - 180.0
    utm_zone = int((lon + 180.0) / 6.0) + 1
    utm_zone = max(1, min(60, utm_zone))
    epsg = (32700 if lat < 0 else 32600) + utm_zone
    return f"EPSG:{epsg}"


def projected_crs_is_metric(srs):
    """True when a projected CRS measures distance in metres without gross distortion.

    Two things disqualify a projected CRS as a working CRS: a linear unit other
    than the metre (US survey foot in State Plane, for instance -- the pixel
    size would be read as metres and every slope, length and area would be off
    by 3.28), and the (pseudo-)Mercator family, whose scale grows as 1/cos(lat)
    -- 8% at 22 degrees, 100% at 60 -- so a "30 m" pixel is not 30 m on the
    ground. Transverse Mercator (UTM) is fine.
    Returns (ok, reason).
    """
    units = srs.GetLinearUnits() or 1.0
    if abs(units - 1.0) > 1e-6:
        return False, t("msg_razao_unidade", unit=srs.GetLinearUnitsName() or "?", metres=units)
    projection = (srs.GetAttrValue("PROJECTION") or "").lower()
    if "mercator" in projection and "transverse" not in projection:
        return False, t("msg_razao_mercator", projection=srs.GetAttrValue("PROJECTION"))
    return True, ""


def copy_raster_with_assigned_crs(input_path, output_path, crs):
    """Create a GeoTIFF copy with an assigned CRS but unchanged pixels/grid.

    This is only used when a CRS-less raster is explicitly handled by the
    default CRS policy. It does not reproject coordinates.
    """
    try:
        dataset = gdal.Open(input_path)
    except RuntimeError as exc:
        raise _erro(t("msg_raster_sem_crs_abrir", path=input_path)) from exc
    if dataset is None:
        raise _erro(t("msg_raster_sem_crs_abrir", path=input_path))
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(output_path):
        driver.Delete(output_path)
    copy = driver.CreateCopy(output_path, dataset, strict=0, options=["COMPRESS=LZW"])
    if copy is None:
        raise _erro(t("msg_raster_copia_crs", path=output_path))
    srs = srs_from_projection(None, crs)
    copy.SetProjection(srs.ExportToWkt())
    copy.FlushCache()
    copy = None
    dataset = None
    return output_path


def warp_raster_checked(input_path, output_path, warp_options, description=None):
    """Run GDAL Warp and fail loudly if the output is not created/openable."""
    description = description or t("msg_etapa_reprojecao")
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    try:
        result = gdal.Warp(output_path, input_path, options=warp_options)
    except Exception as exc:
        raise _erro(t("msg_warp_falhou", step=description, source=input_path, target=output_path,
                      error=exc)) from exc
    if result is None:
        raise _erro(t("msg_warp_vazio", step=description, path=input_path))
    result.FlushCache()
    result = None
    try:
        check = gdal.Open(output_path)
    except RuntimeError as exc:
        raise _erro(t("msg_warp_nao_abre", step=description, path=output_path)) from exc
    if check is None:
        raise _erro(t("msg_warp_nao_abre", step=description, path=output_path))
    check = None
    return output_path


def ensure_projected_working_crs(
    dem_path,
    feedback=None,
    default_crs="EPSG:4326",
    temp_dir=None,
    log_path=None,
    strict_crs_mode=STRICT_CRS_MODE,
    cell_size_m=None,
):
    """Prepare a DEM for metric processing and return path/CRS diagnostics.

    Inputs: DEM path readable by GDAL, optional feedback/log path and fallback
    CRS. Area, distance, route and buffer operations require a projected CRS in
    meters. Geographic DEMs are warped to automatic UTM based on raster center.
    With `cell_size_m`, the working grid has that cell and its edges on
    multiples of it (target-aligned pixels): any clip of the same DEM then gets
    the same cells. Without it the cell size and origin follow the clip extent,
    and two clips of the same area are resampled onto different grids.
    CRS-less DEMs fail in strict_crs_mode, which is the scientific default. If
    strict_crs_mode is False, CRS-less DEMs are assigned default_crs with warning
    and log entry before the same decision. Returns a dict with prepared path,
    original/working CRS, reprojection flag, metadata and messages. Raises when
    the CRS is invalid or GDAL cannot create/open the prepared raster.
    """
    messages = []
    temp_dir = temp_dir or tempfile.mkdtemp(prefix="topotrail_crs_")
    original_metadata = raster_metadata(dem_path)
    source_path = dem_path
    source_projection = original_metadata["projection"]
    original_srs = srs_from_projection(source_projection)
    assigned_default = False

    if original_srs is None:
        if strict_crs_mode:
            message = t("msg_raster_sem_crs_estrito")
            append_diagnostic_log(
                log_path,
                "validacao_falhou",
                erro=message,
                raster=dem_path,
                strict_crs_mode=True,
            )
            raise _erro(message)
        assigned_default = True
        assigned_path = os.path.join(temp_dir, "dem_assumido_crs.tif")
        source_path = copy_raster_with_assigned_crs(dem_path, assigned_path, default_crs)
        messages.append(t("msg_dem_sem_crs", crs=default_crs))
        if feedback:
            feedback.pushWarning(messages[-1])
        original_srs = srs_from_projection(None, default_crs)
        original_metadata = raster_metadata(source_path)

    working_crs = srs_label(original_srs)
    reprojected = False
    prepared_path = source_path
    reason = "CRS ja projetado"

    lon_center, lat_center = geographic_center_of_raster(original_metadata)
    if abs(lat_center) > 84.0:
        messages.append(t("msg_latitude_84"))
        if feedback:
            feedback.pushWarning(messages[-1])

    metric_ok, metric_reason = (True, "")
    if original_srs.IsProjected():
        metric_ok, metric_reason = projected_crs_is_metric(original_srs)

    transform_in = original_metadata["transform"]
    rotated = abs(transform_in[2]) > 1e-12 or abs(transform_in[4]) > 1e-12
    px_in, py_in = original_metadata["pixel_size_x"], original_metadata["pixel_size_y"]
    non_square = abs(px_in - py_in) > 1e-6 * max(px_in, py_in)

    if original_srs.IsProjected() and not metric_ok:
        # Pes ou Mercator: reprojeta para a UTM automatica como se fosse
        # geografico. Antes o CRS era mantido e o pixel lido como metros.
        working_crs = automatic_utm_crs_for_geographic_raster(original_metadata)
        prepared_path = os.path.join(temp_dir, "dem_trabalho_metrico.tif")
        reason = f"CRS projetado nao metrico ({metric_reason}) reprojetado para UTM automatica"
        warp_options = gdal.WarpOptions(
            dstSRS=working_crs, resampleAlg=gdal.GRA_Bilinear, format="GTiff",
            creationOptions=["COMPRESS=LZW"],
            srcNodata=original_metadata.get("nodata"), dstNodata=DEM_FILL_NODATA,
            **_grade_alinhada(cell_size_m),
        )
        warp_raster_checked(source_path, prepared_path, warp_options, t("msg_etapa_reprojecao_metrica"))
        reprojected = True
        messages.append(t("msg_crs_nao_metrico", crs=srs_label(original_srs), reason=metric_reason,
                          working=working_crs))
        if feedback:
            feedback.pushWarning(messages[-1])
    elif original_srs.IsProjected() and (rotated or non_square):
        # Grade rotacionada ou pixel retangular: o roteamento e a transitabilidade
        # assumem passo igual nos dois eixos e norte para cima. Reamostra na
        # mesma CRS para uma grade norte-acima de pixel quadrado (o menor lado).
        side = float(min(px_in, py_in))
        prepared_path = os.path.join(temp_dir, "dem_trabalho_quadrado.tif")
        reason = ("grade rotacionada" if rotated else "pixel retangular") + " reamostrada para pixel quadrado norte-acima"
        warp_options = gdal.WarpOptions(
            dstSRS=original_srs.ExportToWkt(), xRes=side, yRes=side,
            resampleAlg=gdal.GRA_Bilinear, format="GTiff",
            creationOptions=["COMPRESS=LZW"],
            srcNodata=original_metadata.get("nodata"), dstNodata=DEM_FILL_NODATA,
        )
        warp_raster_checked(source_path, prepared_path, warp_options, t("msg_etapa_grade_regular"))
        reprojected = True
        messages.append(t(
            "msg_grade_reamostrada", kind=t("msg_grade_rotacionada" if rotated else "msg_pixel_retangular"),
            px=px_in, py=py_in, side=side))
        if feedback:
            feedback.pushWarning(messages[-1])
    elif original_srs.IsGeographic():
        working_crs = automatic_utm_crs_for_geographic_raster(original_metadata)
        prepared_path = os.path.join(temp_dir, "dem_trabalho_metrico.tif")
        reason = "CRS geografico reprojetado para UTM automatica"
        # dstNodata e obrigatorio aqui. A reprojecao de uma grade geografica
        # para UTM gira o retangulo, e o preenchimento das quinas sai como zero.
        # Ate a 0.5.x isso passava despercebido porque os rasters derivados,
        # alinhados com nodata -9999, excluiam essas celulas de tabela. Quando a
        # declividade e a curvatura passaram a ser derivadas do proprio MDE essa
        # protecao indireta sumiu, e as 211.423 celulas de quina de uma cena de
        # teste entraram na analise como terreno valido ao nivel do mar --
        # visivel na rugosidade, que acusou 1047 m de desnivel entre vizinhos a
        # 30 m de distancia, na fronteira entre o terreno real e o zero.
        warp_options = gdal.WarpOptions(
            dstSRS=working_crs,
            resampleAlg=gdal.GRA_Bilinear,
            format="GTiff",
            creationOptions=["COMPRESS=LZW"],
            srcNodata=original_metadata.get("nodata"),
            dstNodata=DEM_FILL_NODATA,
            **_grade_alinhada(cell_size_m),
        )
        warp_raster_checked(source_path, prepared_path, warp_options, t("msg_etapa_reprojecao_metrica"))
        reprojected = True
        messages.append(t("msg_dem_reprojetado", crs=working_crs))
    elif not original_srs.IsProjected():
        raise _erro(t("msg_crs_invalido"))
    elif cell_size_m and cell_size_m > 0:
        prepared_path = os.path.join(temp_dir, "dem_trabalho_alinhado.tif")
        reason = "CRS projetado mantido; reamostrado para a celula de trabalho pedida"
        warp_options = gdal.WarpOptions(
            dstSRS=working_crs, resampleAlg=gdal.GRA_Bilinear, format="GTiff",
            creationOptions=["COMPRESS=LZW"],
            srcNodata=original_metadata.get("nodata"), dstNodata=DEM_FILL_NODATA,
            **_grade_alinhada(cell_size_m),
        )
        warp_raster_checked(source_path, prepared_path, warp_options, t("msg_etapa_celula_trabalho"))
        messages.append(t("msg_crs_mantido_celula", crs=working_crs, cell=cell_size_m))
    else:
        messages.append(t("msg_crs_mantido", crs=working_crs))
    if cell_size_m and cell_size_m > 0:
        messages.append(t("msg_celula_fixa", cell=cell_size_m))

    prepared_metadata = raster_metadata(prepared_path)
    diagnostics = {
        "dem_path": prepared_path,
        "original_crs": srs_label(srs_from_projection(source_projection)) or (default_crs if assigned_default else None),
        "working_crs": working_crs,
        "reprojected": reprojected,
        "assigned_default_crs": assigned_default,
        "strict_crs_mode": strict_crs_mode,
        "reason": reason,
        "messages": messages,
        "original_metadata": original_metadata,
        "prepared_metadata": prepared_metadata,
        "temp_path": prepared_path if prepared_path != dem_path else None,
    }
    append_diagnostic_log(log_path, "crs_trabalho_definido", **diagnostics)
    for message in messages:
        if feedback:
            feedback.pushInfo(message)
    return diagnostics


def _grade_alinhada(cell_size_m):
    """Opcoes de warp para uma celula fixa com bordas em multiplos dela."""
    if not cell_size_m or cell_size_m <= 0:
        return {}
    return {"xRes": float(cell_size_m), "yRes": float(cell_size_m), "targetAlignedPixels": True}


def validate_raster_grid_compatibility(reference_raster, candidate_raster, tolerance=1e-6):
    """Compare two rasters for same analysis grid.

    Checks CRS, rows, columns, pixel size, full GeoTransform, bounds, NoData and
    Y-axis orientation. Returns a dict with compatible/problemas and both
    metadata snapshots; it does not mutate files.
    """
    reference = raster_metadata(reference_raster)
    candidate = raster_metadata(candidate_raster)
    problems = []

    if reference["crs"] != candidate["crs"]:
        problems.append(t("msg_compat_crs", reference=reference["crs"], candidate=candidate["crs"]))
    if reference["rows"] != candidate["rows"]:
        problems.append(t("msg_compat_linhas", reference=reference["rows"], candidate=candidate["rows"]))
    if reference["cols"] != candidate["cols"]:
        problems.append(t("msg_compat_colunas", reference=reference["cols"], candidate=candidate["cols"]))
    if abs(reference["pixel_size_x"] - candidate["pixel_size_x"]) > tolerance:
        problems.append(t("msg_compat_res_x"))
    if abs(reference["pixel_size_y"] - candidate["pixel_size_y"]) > tolerance:
        problems.append(t("msg_compat_res_y"))
    if reference["y_axis_orientation"] != candidate["y_axis_orientation"]:
        problems.append(t("msg_compat_eixo_y"))
    for index, (ref_value, cand_value) in enumerate(zip(reference["transform"], candidate["transform"])):
        if abs(ref_value - cand_value) > tolerance:
            problems.append(t("msg_compat_geotransform", index=index, reference=ref_value, candidate=cand_value))
    for index, (ref_value, cand_value) in enumerate(zip(reference["bounds"], candidate["bounds"])):
        if abs(ref_value - cand_value) > max(tolerance, reference["pixel_size_x"] * 1e-6):
            problems.append(t("msg_compat_extensao", index=index, reference=ref_value, candidate=cand_value))
    # NoData diferente nao impede o uso: o raster alinhado ja sai com o do MDE.
    blocking = list(problems)
    if reference["nodata"] != candidate["nodata"]:
        problems.append(t("msg_compat_nodata", reference=reference["nodata"], candidate=candidate["nodata"]))

    return {
        "compatible": len(problems) == 0,
        "problems": problems,
        "blocking_problems": blocking,
        "reference_metadata": reference,
        "candidate_metadata": candidate,
    }


def align_raster_to_reference(candidate_path, reference_path, output_path, resampling="bilinear", feedback=None, log_path=None):
    """Warp a candidate raster onto a reference raster grid.

    Uses the reference CRS, bounds and resolution. Resampling defaults to
    bilinear for continuous DEM/slope/curvature surfaces; nearest is available
    for masks/classes. The result is reopened and checked against the reference.
    Raises if blocking grid differences remain.
    """
    reference = raster_metadata(reference_path)
    resampling_map = {
        "bilinear": gdal.GRA_Bilinear,
        "nearest": gdal.GRA_NearestNeighbour,
        "cubic": gdal.GRA_Cubic,
    }
    resampling_alg = resampling_map.get(resampling, gdal.GRA_Bilinear)
    bounds = reference["bounds"]
    warp_options = gdal.WarpOptions(
        dstSRS=reference["projection"],
        outputBounds=bounds,
        xRes=reference["pixel_size_x"],
        yRes=reference["pixel_size_y"],
        resampleAlg=resampling_alg,
        format="GTiff",
        creationOptions=["COMPRESS=LZW"],
        dstNodata=reference["nodata"] if reference["nodata"] is not None else -9999.0,
    )
    if feedback:
        feedback.pushInfo(t("msg_alinhando", name=os.path.basename(candidate_path)))
    warp_raster_checked(candidate_path, output_path, warp_options, t("msg_etapa_alinhamento"))
    compatibility = validate_raster_grid_compatibility(reference_path, output_path)
    blocking_problems = compatibility["blocking_problems"]
    if blocking_problems:
        raise _erro(t("msg_alinhado_incompativel", problems=t("msg_sep_itens").join(blocking_problems)))
    append_diagnostic_log(
        log_path,
        "raster_alinhado",
        entrada=candidate_path,
        saida=output_path,
        referencia=reference_path,
        resampling=resampling,
        compatibilidade=compatibility,
    )
    return output_path


def read_raster(raster_path, feedback=None):
    """Read band 1 as float32, converting NoData to NaN.

    Returns array, GeoTransform and projection WKT. GDAL datasets are explicitly
    closed. Raises clear exceptions for missing/unreadable rasters.
    """
    try:
        dataset = gdal.Open(raster_path)
    except RuntimeError as exc:
        raise _erro(t("msg_raster_abrir", path=raster_path)) from exc
    if dataset is None:
        raise _erro(t("msg_raster_abrir", path=raster_path))

    band = dataset.GetRasterBand(1)
    array = band.ReadAsArray()
    if array is None:
        raise _erro(t("msg_raster_banda", path=raster_path))

    array = array.astype(np.float32)
    nodata = band.GetNoDataValue()
    if nodata is not None:
        array[array == nodata] = np.nan

    transform = dataset.GetGeoTransform()
    proj = dataset.GetProjection()

    if feedback:
        valid = array[~np.isnan(array)]
        if valid.size:
            feedback.pushInfo(t(
                "msg_raster_resumo", name=os.path.basename(raster_path), shape=array.shape,
                min=float(np.nanmin(valid)), max=float(np.nanmax(valid)), mean=float(np.nanmean(valid))))
        else:
            feedback.pushInfo(t("msg_raster_sem_validos", name=os.path.basename(raster_path)))

    dataset = None
    return array, transform, proj


def validate_raster_alignment(reference_shape, reference_transform, rasters, feedback=None):
    """Ensure every input raster shares the DEM grid."""
    for name, array, transform in rasters:
        if array.shape != reference_shape:
            raise _erro(t("msg_dimensoes", name=name, shape=array.shape, reference=reference_shape))

        diffs = [abs(float(transform[i]) - float(reference_transform[i])) for i in range(6)]
        if any(diff > 1e-9 for diff in diffs):
            raise _erro(t("msg_desalinhado", name=name))

        if feedback:
            feedback.pushInfo(t("msg_alinhado", name=name, shape=array.shape))


def slope_to_percent(slope_data, slope_unit, feedback=None, log_path=None):
    """Converte a declividade para porcentagem, a unidade interna do TopoTrail.

    A unidade nao pode ser inferida com seguranca do proprio raster: abaixo de
    45, graus e porcentagem cobrem a mesma faixa numerica e um terreno suave em
    porcentagem e indistinguivel de um terreno ingreme em graus. Por isso ela e
    declarada pelo usuario. Isso importa porque as ferramentas mais usadas nao
    concordam: gdaldem slope e o algoritmo Slope do QGIS devolvem GRAUS por
    padrao, enquanto muitos MDEs nacionais sao distribuidos em PORCENTAGEM.

    Um raster em graus aceito como porcentagem nao gera erro: gera um resultado
    plausivel e errado, porque um limite de 55 em graus quase nao exclui pixel
    algum.
    """
    valid = slope_data[np.isfinite(slope_data)]
    maximum = float(np.nanmax(valid)) if valid.size else float("nan")
    p99 = float(np.nanpercentile(valid, 99)) if valid.size else float("nan")

    convertido = False
    if slope_unit == SLOPE_UNIT_DEGREES:
        if valid.size and maximum > 90.0:
            raise _erro(t("msg_graus_invalido", maximum=maximum))
        with np.errstate(invalid="ignore"):
            radianos = np.deg2rad(np.clip(slope_data, 0.0, 89.9))
            slope_data = (np.tan(radianos) * 100.0).astype(np.float32)
        convertido = True
        if feedback:
            feedback.pushInfo(t("msg_graus_convertido", maximum=maximum,
                                output=float(np.nanmax(slope_data[np.isfinite(slope_data)]))))

    append_diagnostic_log(
        log_path, "unidade_declividade",
        unidade_declarada=("graus" if slope_unit == SLOPE_UNIT_DEGREES else "porcentagem"),
        convertido_para_porcentagem=convertido,
        maximo_entrada=maximum, p99_entrada=p99,
    )
    return slope_data


def rasterize_constraint_layer(layer_source, buffer_m, transform, shape, proj,
                               feedback=None, log_path=None):
    """Converte uma camada vetorial de restricao numa mascara booleana.

    A camada e reprojetada para o CRS metrico de trabalho, dilatada pelo buffer
    pedido e queimada na grade do MDE. Aceita ponto, linha ou poligono: um
    buffer transforma qualquer um deles em area, que e o que a restricao
    significa na pratica -- "fique a tantos metros disto".

    O buffer e a razao de a reprojecao vir antes: em CRS geografico um buffer de
    30 unidades seriam 30 graus.
    """
    # Lido com OGR, e nao com geopandas: o QGIS garante GDAL/OGR, NumPy e SciPy
    # como dependencias, mas nao o geopandas. Com o import de geopandas no topo
    # deste modulo, o plugin nao carregava em instalacao padrao de QGIS -- e o
    # OGR ja traz o GEOS, que e o que faz uniao e buffer.
    # Aceita um caminho de arquivo OU uma QgsVectorLayer. Reabrir layer.source()
    # com o OGR quebrava para toda camada que nao e um arquivo puro -- GeoPackage
    # aberto pelo navegador do QGIS ("...gpkg|layername=x"), camada de memoria,
    # PostGIS. Com a camada em maos, as geometrias vem pelo proprio QGIS em WKB.
    source_geometries = []
    if hasattr(layer_source, "getFeatures"):
        crs = layer_source.crs()
        if not crs.isValid():
            raise _erro(t("msg_restricao_sem_crs"))
        source_srs = osr.SpatialReference()
        source_srs.ImportFromWkt(crs.toWkt())
        for qgs_feature in layer_source.getFeatures():
            qgs_geometry = qgs_feature.geometry()
            if qgs_geometry is None or qgs_geometry.isEmpty():
                continue
            geometry = ogr.CreateGeometryFromWkb(bytes(qgs_geometry.asWkb()))
            if geometry is not None:
                source_geometries.append(geometry)
        layer_source = layer_source.source()
    else:
        try:
            datasource_in = ogr.Open(str(layer_source))
        except RuntimeError as exc:
            raise _erro(t("msg_restricao_abrir", source=layer_source)) from exc
        if datasource_in is None:
            raise _erro(t("msg_restricao_abrir", source=layer_source))
        layer_in = datasource_in.GetLayer(0)
        source_srs = layer_in.GetSpatialRef()
        if source_srs is None:
            raise _erro(t("msg_restricao_sem_crs"))
        for feature_in in layer_in:
            geometry = feature_in.GetGeometryRef()
            if geometry is not None and not geometry.IsEmpty():
                source_geometries.append(geometry.Clone())
        datasource_in = None

    target_srs = osr.SpatialReference()
    if proj:
        target_srs.ImportFromWkt(proj)
    else:
        target_srs.ImportFromEPSG(4326)
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    reproject = None
    if not source_srs.IsSame(target_srs):
        try:
            reproject = osr.CoordinateTransformation(source_srs, target_srs)
        except Exception as exc:
            raise _erro(t("msg_restricao_reprojetar", error=exc))

    # Uniao acumulada: o equivalente ao unary_union, feito pelo GEOS via OGR.
    merged = None
    feature_count = 0
    for geometry in source_geometries:
        if reproject is not None:
            if geometry.Transform(reproject) != 0:
                continue
        feature_count += 1
        merged = geometry if merged is None else merged.Union(geometry)

    if merged is None:
        if feedback:
            feedback.pushWarning(t("msg_restricao_vazia"))
        return None

    if buffer_m > 0:
        merged = merged.Buffer(float(buffer_m))

    rows, cols = shape
    datasource = ogr_memory_driver().CreateDataSource("restricoes")
    layer = datasource.CreateLayer("restricoes", srs=target_srs,
                                   geom_type=ogr.wkbMultiPolygon)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(merged)
    layer.CreateFeature(feature)
    feature = None

    target = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
    target.SetGeoTransform(transform)
    if proj:
        target.SetProjection(proj)
    gdal.RasterizeLayer(target, [1], layer, burn_values=[1])
    mask = target.GetRasterBand(1).ReadAsArray().astype(bool)
    target = None
    datasource = None

    append_diagnostic_log(
        log_path, "camada_restricao",
        origem=str(layer_source), feicoes=int(feature_count),
        buffer_m=float(buffer_m), celulas_restritas=int(mask.sum()),
        proporcao=float(mask.sum() / mask.size),
    )
    if feedback:
        feedback.pushInfo(t(
            "msg_restricao_resumo", features=feature_count, buffer=buffer_m, cells=int(mask.sum()),
            pct=100.0 * mask.sum() / mask.size))
    # Zero celulas com a camada cheia era registrado como informacao e mais
    # nada: como restricted_mask.any() fica falso, o bloco de restricoes
    # inteiro e pulado e nem a linha "Restricoes: ..." chega a sair. Medido na
    # auditoria (caso B1): uma cerca de 5 m atravessando toda a cena num pixel
    # de 30 m deu "0 celulas atingidas (0.00%)" e o comprimento devolvido foi
    # exatamente o da rota sem restricao nenhuma. A causa e sempre a mesma --
    # gdal.RasterizeLayer sem ALL_TOUCHED so queima a celula cujo centro cai
    # dentro da feicao -- entao vale dizer isso e dizer o que fazer.
    pixel_m = max(abs(float(transform[1])), abs(float(transform[5])))
    if feedback and feature_count and not mask.any():
        feedback.pushWarning(t("msg_restricao_sem_efeito", buffer=buffer_m, pixel=pixel_m,
                               suggested=buffer_m + pixel_m))
    return mask


def _cancelado(mensagem):
    """Excecao de cancelamento, no idioma do Processing quando ele existe."""
    try:
        from qgis.core import QgsProcessingException
        return QgsProcessingException(mensagem)
    except Exception:
        return Exception(mensagem)


def _estado_excecoes(modulo):
    """Estado atual de excecoes do modulo GDAL/OGR, ou None se nao der para ler."""
    leitor = getattr(modulo, "GetUseExceptions", None)
    if leitor is None:
        return None
    try:
        return bool(leitor())
    except Exception:
        return None


@contextlib.contextmanager
def gdal_exceptions_scoped():
    """Liga as excecoes de GDAL/OGR apenas enquanto o algoritmo roda.

    Substitui o gdal.UseExceptions()/ogr.UseExceptions() que ficava no import e
    contaminava o processo QGIS inteiro. Prefere gdal.ExceptionMgr()/
    ogr.ExceptionMgr() (GDAL >= 3.7) e cai no par GetUseExceptions/
    DontUseExceptions nas versoes mais antigas.

    O gdal.ErrorReset() antes de sair nao e cosmetico: medido no GDAL 3.8.4
    deste ambiente, o __exit__ do ExceptionMgr chama _SetExceptionsLocal, que
    re-levanta o ultimo erro CPL ainda pendente -- sair do contexto depois de um
    gdal.Open() que falhou levantava RuntimeError de dentro do finally e
    mascarava o erro verdadeiro. A restauracao inteira fica sob try/except pelo
    mesmo motivo: sair nunca pode inventar um erro novo.
    """
    anteriores = [(modulo, _estado_excecoes(modulo)) for modulo in (gdal, ogr)]
    gerentes = []
    for modulo in (gdal, ogr):
        fabrica = getattr(modulo, "ExceptionMgr", None)
        if fabrica is None:
            modulo.UseExceptions()
            continue
        gerente = fabrica(useExceptions=True)
        gerente.__enter__()
        gerentes.append(gerente)
    try:
        yield
    finally:
        try:
            gdal.ErrorReset()
        except Exception as exc:
            _LOG.debug("ErrorReset do GDAL falhou: %s", exc)
        for gerente in reversed(gerentes):
            try:
                gerente.__exit__(None, None, None)
            except Exception as exc:
                _LOG.debug("ExceptionMgr nao restaurou o estado: %s", exc)
        # Ordem inversa da que ligou: no GDAL < 3.7 os manipuladores de erro
        # formam uma pilha (gdal, ogr), e gdal.DontUseExceptions() com o do ogr
        # no topo levanta -- o GDAL do QGIS inteiro ficava com excecoes ligadas.
        for modulo, ligado in reversed(anteriores):
            if ligado is None:
                continue
            try:
                if _estado_excecoes(modulo) != ligado:
                    if ligado:
                        modulo.UseExceptions()
                    else:
                        modulo.DontUseExceptions()
            except Exception as exc:
                _LOG.debug("estado de excecoes do GDAL nao restaurado: %s", exc)


def _erro(mensagem):
    """Erro do algoritmo, no tipo que o Processing sabe mostrar.

    O invólucro Python do Processing re-embrulha Exception e ValueError
    incluindo o traceback inteiro como mensagem: a frase escrita para o usuario
    virava a ultima linha de uma pilha com os caminhos absolutos da maquina de
    quem empacotou. Medido na auditoria (ALT_MIN=5000): o texto entregue
    comecava em "Traceback (most recent call last)". QgsProcessingException e
    mostrada como a frase e nada mais. Mesmo padrao de _cancelado: se o
    qgis.core nao for importavel -- e o caso da suite hermetica de tests/ --
    cai em Exception, que e o que havia antes.
    """
    try:
        from qgis.core import QgsProcessingException
        return QgsProcessingException(mensagem)
    except Exception:
        return Exception(mensagem)


def _erro_do_algoritmo(excecao):
    """True se a excecao e um erro escrito para o usuario (o tipo de _erro)."""
    return isinstance(excecao, type(_erro("")))


def project_crs_from_context(context):
    """CRS do projeto que o context carrega, ou None quando nao houver.

    Substitui a leitura de QgsProject.instance() que estava em initAlgorithm:
    o projeto certo para um algoritmo de Processing e o do contexto de
    execucao. Sem contexto, sem projeto ou com projeto sem CRS valido devolve
    None, e o algoritmo mantem o CRS de trabalho -- que e o comportamento de
    quem nao pediu reprojecao nenhuma.
    """
    if context is None:
        return None
    try:
        project = context.project()
    except Exception:
        return None
    if project is None:
        return None
    try:
        crs = project.crs()
    except Exception:
        return None
    if crs is None or not crs.isValid():
        return None
    return crs


def cost_model_name(cost_model):
    """Nome do modelo de custo para o registro de diagnostico.

    Existe porque ate a 1.1.2 o log montava esse texto com um condicional de
    duas vias sobre um enum de tres valores: toda execucao no modo Tobler --
    que e o padrao -- gravava "cost = 1 / (adequabilidade + 0.05)", isto e, o
    modelo inverso. Quem recebesse o log reproduziria a execucao errada.
    """
    if cost_model == ROUTE_COST_TOBLER:
        return "tobler"
    if cost_model == ROUTE_COST_EXPONENTIAL:
        return "exponencial"
    return "inverso"


def build_route_cost(score_array, cost_model, contrast, penalty_mask=None, feedback=None):
    """Converte adequabilidade em custo de deslocamento.

    O modelo inverso, `1/(S + eps)`, e o das versoes 0.5.x. O contraste que ele
    aparenta oferecer supoe S percorrendo todo o intervalo [0, 1]; em cena real
    S fica concentrado no miolo. Medido na cena da Serra da Mantiqueira usada
    na dissertacao: P05 = 0,49 e P95 = 0,77, de modo que o custo entre esses
    percentis varia por um fator de 1,5 -- plano demais para valer o desvio.

    O modelo de Tobler e diferente em natureza: o custo passa a ser tempo, em
    horas, e depende da direcao do passo -- subir 100 m custa muito mais que
    descer os mesmos 100 m. Nesse modo este array nao e um custo, e um fator de
    retardo que multiplica o tempo calculado passo a passo dentro do A*.

    O modelo exponencial, `exp(k(1 - S))`, mantem o contraste independentemente
    de quao comprimida esteja a distribuicao de S, e `k` passa a ser o controle
    explicito de quanto vale a pena desviar para achar terreno melhor. Na mesma
    cena, k=6 elevou a sinuosidade para 1,19 e a adequabilidade media ao longo
    da rota de 0,810 para 0,848, ao custo de 14% de comprimento.
    """
    finite = np.isfinite(score_array)
    # penalty_mask pode ser booleano (fator fixo de 8x) ou um array de fatores
    # reais -- 1 onde nao ha restricao (inclusive nos cursos vadeaveis, que so
    # informam a rota), 8 na camada penalizada, inf onde a travessia nao e
    # presumida.
    factor = None
    if penalty_mask is not None:
        if penalty_mask.dtype == bool:
            factor = np.where(penalty_mask, CONSTRAINT_PENALTY_FACTOR, 1.0)
        else:
            factor = np.asarray(penalty_mask, dtype=np.float64)
    if cost_model == ROUTE_COST_TOBLER:
        # Aqui o array nao e custo: e um fator de retardo adimensional, aplicado
        # sobre o tempo que a funcao de Tobler calcula para cada passo.
        cost = np.where(finite, 1.0 + TERRAIN_SLOWDOWN_MAX * (1.0 - score_array), np.inf)
        if factor is not None:
            cost = np.where(finite, cost * factor, cost)
        if feedback:
            usable = cost[np.isfinite(cost)]
            if usable.size:
                feedback.pushInfo(t("msg_retardo", min=float(usable.min()), median=float(np.median(usable)),
                                    max=float(usable.max())))
        return cost
    if cost_model == ROUTE_COST_EXPONENTIAL:
        cost = np.where(finite, np.exp(float(contrast) * (1.0 - score_array)), np.inf)
    else:
        cost = np.where(finite, 1.0 / (score_array + ROUTE_COST_EPSILON), np.inf)

    if factor is not None:
        cost = np.where(finite, cost * factor, cost)

    if feedback:
        usable = cost[np.isfinite(cost)]
        if usable.size:
            feedback.pushInfo(t(
                "msg_superficie_custo",
                model=(t("msg_modelo_exponencial", k=contrast) if cost_model == ROUTE_COST_EXPONENTIAL
                       else t("msg_modelo_inverso")),
                min=float(usable.min()), max=float(usable.max()),
                contrast=float(usable.max() / max(usable.min(), 1e-9))))
    return cost


def stream_crossing_factors(stream_mask, basin_km2, ford_max_km2, transform, channel_axis=None):
    """Fator de custo por celula para atravessar a drenagem, pelo tamanho do curso.

    Cada celula da faixa de drenagem recebe a area de contribuicao do canal mais
    proximo (a faixa vem de um buffer; so o eixo tem area). Classes em
    FORD_CLASSES; acima de `ford_max_km2` o fator e infinito (barreira).
    Devolve (fatores float64 com 1.0 fora da faixa, area_km2_na_faixa, classe_idx
    int8 com -1 fora, len(FORD_CLASSES) para barreira).
    """
    factors = np.ones(stream_mask.shape, dtype=np.float64)
    classes = np.full(stream_mask.shape, -1, dtype=np.int8)
    area = np.full(stream_mask.shape, np.nan, dtype=np.float32)
    if not stream_mask.any() or basin_km2 is None:
        return factors, area, classes
    # A area vem do EIXO do canal (antes do buffer): as celulas da faixa
    # herdam a area do eixo mais proximo. Sem isso, uma celula de margem com
    # 0,02 km2 de bacia propria era classificada como "corrego" ao lado de um rio.
    axis = channel_axis if channel_axis is not None else stream_mask
    channel = np.isfinite(basin_km2) & (basin_km2 > 0) & axis
    if not channel.any():
        channel = stream_mask
        source_area = np.where(stream_mask, np.nan_to_num(basin_km2, nan=0.0), 0.0)
    else:
        source_area = np.where(channel, basin_km2, 0.0)
    px = abs(float(transform[1]))
    py = abs(float(transform[5]))
    _, (rr, cc) = morphology.distance_transform_edt(~channel, sampling=(py, px), return_indices=True)
    nearest_area = source_area[rr, cc]
    area = np.where(stream_mask, nearest_area, np.nan).astype(np.float32)
    inside = stream_mask
    for index, (limit, factor, _key) in enumerate(FORD_CLASSES):
        band = inside & (classes == -1) & (nearest_area < min(limit, float(ford_max_km2)))
        factors[band] = factor
        classes[band] = index
    barrier = inside & (classes == -1)
    factors[barrier] = np.inf
    classes[barrier] = len(FORD_CLASSES)
    return factors, area, classes


def _com_travessias_diagonais(path_cells, stream_mask, crossing_area=None, marcar=False):
    """Insere a celula de canto quando a rota atravessa a drenagem na diagonal.

    Um passo diagonal cruza o canto compartilhado por quatro celulas. Quando a
    faixa de drenagem passa justamente pelas duas celulas que o passo contorna,
    a rota corta o curso d'agua sem pousar em nenhuma celula de curso, e a
    travessia nao entra na lista que o usuario confere em campo. Medido na cena
    da Mantiqueira do capitulo, dois dos oito cruzamentos reais escapavam assim
    -- um quarto do total -- e o log chegava a afirmar que a rota nao cruzava
    curso nenhum. A celula de canto que entra e a que esta na faixa; havendo as
    duas, entra a de maior area de contribuicao, que e a que manda na classe.
    """
    rows, cols = stream_mask.shape

    def na_faixa(row, col):
        return 0 <= row < rows and 0 <= col < cols and bool(stream_mask[row, col])

    saida = []
    celulas = list(path_cells)
    for posicao, atual in enumerate(celulas):
        saida.append((atual, False) if marcar else atual)
        if posicao + 1 >= len(celulas):
            continue
        (row0, col0), (row1, col1) = atual, celulas[posicao + 1]
        if abs(row0 - row1) != 1 or abs(col0 - col1) != 1:
            continue
        if na_faixa(row0, col0) or na_faixa(row1, col1):
            continue
        cantos = [(r, c) for r, c in ((row0, col1), (row1, col0)) if na_faixa(r, c)]
        if not cantos:
            continue
        if len(cantos) > 1 and crossing_area is not None:
            cantos.sort(key=lambda rc: float(np.nan_to_num(crossing_area[rc])), reverse=True)
        # com `marcar`, o canto sai sinalizado: ele nao e um passo da rota, e a
        # distancia percorrida nao pode somar 1 + 1 onde a rota andou raiz de 2
        saida.append((cantos[0], True) if marcar else cantos[0])
    return saida


def _saida_gpkg_utilizavel(path, layer_name, feedback=None):
    """Confere se da para gravar a camada neste GeoPackage sem perder nada.

    O arquivo nunca e apagado: se abrir para atualizacao, a camada homonima e
    substituida dentro dele e as outras ficam intactas. So quando o arquivo
    existe e nao abre -- porque o QGIS esta com ele aberto, ou o sistema o
    bloqueou -- e que a saida muda de nome, com aviso.
    """
    if not os.path.exists(path):
        return path
    aberto = None
    try:
        aberto = ogr.Open(path, 1)
    except Exception:
        aberto = None
    if aberto is not None:
        outras = [aberto.GetLayerByIndex(i).GetName()
                  for i in range(aberto.GetLayerCount())
                  if aberto.GetLayerByIndex(i).GetName() != layer_name]
        aberto = None
        if outras and feedback:
            feedback.pushInfo(t(
                "msg_gpkg_camadas", n=len(outras),
                layers=t("msg_sep_lista").join(outras[:4]) + ("..." if len(outras) > 4 else ""), layer=layer_name))
        return path
    alternativo = available_output_path(path)
    if feedback:
        feedback.pushWarning(t("msg_gpkg_bloqueado", name=os.path.basename(path),
                               alternative=os.path.basename(alternativo)))
    return alternativo


def detect_stream_crossings(path_cells, stream_mask, crossing_area, crossing_class):
    """Travessias ao longo da rota: uma por sequencia continua de celulas na faixa.

    Devolve lista de dicts com a celula (linha, coluna) de entrada, a area de
    contribuicao maxima e a pior classe encontradas na sequencia, e o
    comprimento percorrido dentro da faixa, em celulas -- somando o passo real
    de cada transicao, que vale raiz de dois nas diagonais. Contar celulas e
    multiplicar pelo lado subestimaria a extensao em ate 41%.
    """
    crossings = []
    run = None
    percorrido = 0.0          # distancia ao longo da rota, em celulas, so pelos passos reais
    ultimo_real = None
    pos_anterior = None
    pos = 0.0
    celulas = _com_travessias_diagonais(path_cells, stream_mask, crossing_area, marcar=True)
    for cell, inserida in celulas + [(None, False)]:
        on = False
        if cell is not None:
            row, col = cell
            if inserida:
                # o canto fica no meio do passo diagonal que a rota deu
                pos = percorrido + np.sqrt(2.0) / 2.0
            else:
                if ultimo_real is not None:
                    percorrido += float(np.hypot(row - ultimo_real[0], col - ultimo_real[1]))
                ultimo_real = cell
                pos = percorrido
            if 0 <= row < stream_mask.shape[0] and 0 <= col < stream_mask.shape[1]:
                on = bool(stream_mask[row, col])
        if on:
            a = float(crossing_area[row, col]) if np.isfinite(crossing_area[row, col]) else 0.0
            k = int(crossing_class[row, col])
            if run is None:
                run = {"entrada": (row, col), "area_km2": a, "classe": k,
                       "celulas": 1, "passos": 0.0, "inicio": pos, "fim": pos}
            else:
                run["area_km2"] = max(run["area_km2"], a)
                run["classe"] = max(run["classe"], k)
                run["celulas"] += 1
                run["fim"] = pos
                if pos_anterior is not None:
                    run["passos"] += float(pos - pos_anterior)
        elif run is not None:
            # uma travessia de uma celula so percorre uma celula de faixa
            run["passos"] = max(run["passos"], 1.0)
            crossings.append(run)
            run = None
        pos_anterior = pos if cell is not None else pos_anterior
    return crossings


# Contatos com a drenagem separados por menos que isto, ao longo da rota, sao um
# evento so. Desde que a drenagem so informa, a rota pode acompanhar um rio, e a
# linha do canal (uma celula de largura) toca a da rota a cada poucas celulas: no
# Batedor eram 14 "travessias" num trecho em que a rota segue o corrego. Um evento
# que se estende por mais que isto e um trecho junto ao curso, nao uma travessia.
STREAM_CONTACT_MERGE_M = 150.0
# Em celula grossa a rota toca o eixo a cada 2 ou 3 celulas (180-270 m a 90 m):
# a distancia de fusao nunca fica abaixo de 3,5 celulas da drenagem.
STREAM_CONTACT_MERGE_CELLS = 3.5
# Contatos com bacias que diferem mais que isto sao cursos diferentes (um
# corrego e o riacho ao lado), e cada um continua sendo uma travessia.
STREAM_CONTACT_SAME_STREAM_RATIO = 2.0


def merge_stream_contacts(contacts, pixel_size_m, merge_m=None, stream_cell_m=None):
    """Funde contatos proximos e classifica cada evento: travessia ou trecho junto ao curso.

    Cada contato vem de detect_stream_crossings, com `inicio` e `fim` em celulas
    ao longo da rota. Devolve dicts com a entrada do primeiro contato, a maior
    area, a pior classe, `contatos`, `extensao_m` (do primeiro toque ao ultimo) e
    `tipo` ("travessia" ou "junto ao curso").
    """
    passo = float(pixel_size_m)
    if merge_m is None:
        merge_m = max(STREAM_CONTACT_MERGE_M,
                      STREAM_CONTACT_MERGE_CELLS * max(passo, float(stream_cell_m or 0.0)))
    eventos = []
    for c in contacts:
        if eventos:
            e = eventos[-1]
            perto = (c["inicio"] - e["fim"]) * passo <= merge_m
            a, b = e["area_ultimo"], c["area_km2"]
            mesmo_curso = max(a, b) <= STREAM_CONTACT_SAME_STREAM_RATIO * max(min(a, b), 1e-9)
            if perto and mesmo_curso:
                e["fim"] = c["fim"]
                e["area_km2"] = max(e["area_km2"], c["area_km2"])
                e["area_ultimo"] = c["area_km2"]
                e["classe"] = max(e["classe"], c["classe"])
                e["contatos"] += 1
                continue
        eventos.append(dict(c, contatos=1, area_ultimo=c["area_km2"]))
    for e in eventos:
        e["extensao_m"] = max(e["fim"] - e["inicio"], e.get("passos") or 1.0) * passo
        e["tipo"] = "junto ao curso" if e["extensao_m"] > merge_m else "travessia"
    return eventos


def _rotulo(chave):
    """Nome de uma opcao da janela, no idioma da execucao, para as mensagens citarem."""
    return mensagens.texto(chave)


def _coord(valor):
    """Coordenada no CRS de trabalho (sempre metrico), com ponto decimal em qualquer idioma."""
    return "{:.1f}".format(float(valor))


def _sim_nao(valor):
    return t("msg_sim" if valor else "msg_nao")


_NOMES_DOS_LIMITES = {"curvatura_horizontal": "msg_nome_curvh", "curvatura_vertical": "msg_nome_curvv",
                      "umidade_twi": "msg_nome_umidade", "rugosidade_vrm": "msg_nome_rugosidade"}


def _nome_do_limite(chave):
    return t(_NOMES_DOS_LIMITES[chave]) if chave in _NOMES_DOS_LIMITES else chave


def _origem_do_limite(origem):
    """A origem do limite como o registro tecnico grava ("parametro", "cena P99"), traduzida."""
    if origem == "parametro":
        return t("msg_origem_parametro")
    try:
        return t("msg_origem_cena", p=float(str(origem).rsplit("P", 1)[1]))
    except (IndexError, ValueError):
        return str(origem)


def _ford_labels():
    """Rotulos das classes de travessia no idioma do algoritmo."""
    keys = [key for _limit, _factor, key in FORD_CLASSES] + ["ford_river"]
    fallback = {"ford_headwater": "corrego de cabeceira (< 2 km2)", "ford_stream": "riacho (2-10 km2)",
                "ford_river_small": "rio pequeno (vau depende da estacao)", "ford_river": "rio (travessia nao presumida)"}
    try:
        from ..ui import i18n
        language = _algorithm_language()
        return [i18n.text(language, key) for key in keys]
    except Exception:
        return [fallback[key] for key in keys]


def report_model_discrimination(slope_data, zone_score, valid_mask, slope_score_max,
                                max_slope, feedback=None, log_path=None):
    """Verifica se o modelo esta realmente distinguindo terreno, e avisa se nao.

    Duas maneiras de o resultado sair vazio de informacao sem sair com erro:

    * **Saturacao.** `normalize_cost` corta a nota da declividade em zero acima
      de `slope_score_max`. Onde a maior parte da cena passa desse limite, o
      criterio de declividade deixa de discriminar e sobram apenas as
      curvaturas. Com o padrao de 50%, que equivale a 26,6 graus, isso atinge
      88% de uma cena do Everest e 92% de uma do K2.

    * **Amplitude nula.** Se a adequabilidade sai praticamente constante entre o
      P05 e o P95, o corte por percentil ainda produz zonas e o mapa parece
      normal, mas nao ha diferenca real entre o que foi selecionado e o que foi
      descartado. Medido no Everest: P05 = P95 = 1,000.

    Os limites continuam absolutos de proposito -- calibra-los pela propria cena
    tornaria os resultados incomparaveis entre areas de estudo, e testado em
    terreno suave o efeito e pior: nos Paises Baixos o P90 da declividade e zero
    e em Lofoten a area viavel cairia de 99% para 52%. Entao aqui o plugin nao
    corrige nada: ele mede, avisa e sugere o valor.
    """
    valid_slope = slope_data[valid_mask & np.isfinite(slope_data)]
    if valid_slope.size == 0:
        return None

    saturated = float(np.mean(valid_slope >= slope_score_max))
    scores = zone_score[np.isfinite(zone_score)]
    amplitude = (float(np.percentile(scores, 95) - np.percentile(scores, 5))
                 if scores.size else 0.0)
    suggested_score_max = float(np.percentile(valid_slope, 90))
    suggested_max = float(np.percentile(valid_slope, 99))

    append_diagnostic_log(
        log_path, "discriminacao_do_modelo",
        fracao_declividade_saturada=saturated,
        amplitude_score_p05_p95=amplitude,
        declividade_p50=float(np.percentile(valid_slope, 50)),
        declividade_p90=suggested_score_max,
        declividade_p99=suggested_max,
        limite_custo_configurado=float(slope_score_max),
        limite_absoluto_configurado=float(max_slope),
    )

    if not feedback:
        return saturated, amplitude

    if saturated >= SATURATION_WARNING_FRACTION:
        feedback.pushWarning(t(
            "msg_declividade_saturada", pct=100.0 * saturated, score_max=slope_score_max,
            median=float(np.percentile(valid_slope, 50)), p90=suggested_score_max,
            suggested_score=suggested_score_max, suggested_max=suggested_max))
    if amplitude < MIN_SCORE_AMPLITUDE:
        feedback.pushWarning(t("msg_modelo_nao_distingue", amplitude=amplitude))
    return saturated, amplitude


def normalize_linear(array, min_val, max_val, feedback=None, name=None):
    name = name or t("msg_nome_criterio")
    if max_val <= min_val:
        raise _erro(t("msg_limites_invalidos", name=name, min=min_val, max=max_val))

    valid_mask = ~np.isnan(array)
    normalized = np.zeros_like(array, dtype=np.float32)
    normalized[valid_mask] = (array[valid_mask] - min_val) / (max_val - min_val)
    normalized = np.clip(normalized, 0, 1)

    if feedback:
        feedback.pushInfo(t("msg_normalizado", name=name, min=float(np.nanmin(normalized)),
                            max=float(np.nanmax(normalized)), mean=float(np.nanmean(normalized))))

    return normalized


def normalize_cost(array, min_val, max_val, feedback=None, name=None):
    name = name or t("msg_nome_criterio")
    normalized = normalize_linear(array, min_val, max_val, feedback, name)
    valid_mask = ~np.isnan(array)
    result = np.zeros_like(normalized, dtype=np.float32)
    result[valid_mask] = 1.0 - normalized[valid_mask]

    if feedback:
        feedback.pushInfo(t("msg_invertido", name=name, min=float(np.nanmin(result)),
                            max=float(np.nanmax(result)), mean=float(np.nanmean(result))))

    return result


def report_absurd_criterion_values(array, name, feedback=None, log_path=None,
                                   limit=CRITERION_PLAUSIBLE_ABS):
    """Avisa quando um raster de criterio traz valores fora de escala fisica.

    Medido na auditoria (15_criterio_degenerado.py): um raster de curvatura
    horizontal com 2% das linhas em -3,4e38 e sem NoData declarado levou o
    limite do percentil de 0,0004 para 3,4e37, a nota media da curvatura de
    0,656 para 0,984, mudou a rota e o tempo, e nao emitiu um unico aviso --
    report_model_discrimination so reclama quando a adequabilidade TOTAL fica
    plana, e a declividade segura a amplitude. nanpercentile descarta NaN, mas
    nao descarta infinito nem sentinela.

    Devolve o numero de celulas suspeitas encontradas.
    """
    dados = np.asarray(array)
    if dados.size == 0:
        return 0
    finitos = np.isfinite(dados)
    infinitos = int(np.sum(~finitos & ~np.isnan(dados)))
    fora_de_escala = finitos & (np.abs(dados) > float(limit))
    absurdos = int(np.sum(fora_de_escala))
    total = infinitos + absurdos
    if total == 0:
        return 0
    extremo = None
    if absurdos:
        candidatos = np.abs(dados[fora_de_escala])
        extremo = float(dados[fora_de_escala][int(np.argmax(candidatos))])
    append_diagnostic_log(
        log_path, "valores_absurdos_no_criterio", raster=name,
        celulas_fora_de_escala=absurdos, celulas_infinitas=infinitos,
        proporcao=float(total / dados.size), limite_plausivel=float(limit),
        extremo=extremo,
    )
    if feedback:
        feedback.pushWarning(t(
            "msg_valores_absurdos", name=name, cells=total, pct=100.0 * total / dados.size,
            extreme="" if extremo is None else t("msg_valores_extremo", value=extremo)))
    return total


def curvature_limit(array, target=0.0):
    """Limite de normalizacao da curvatura: o P99 do desvio ao alvo NA CENA.

    E relativo de proposito (a curvatura depende da resolucao do MDE), e por
    isso muda com o recorte. Quem compara recortes deve fixar o limite pelo
    parametro, com o valor registrado no log de uma execucao de referencia.
    """
    valid = np.asarray(array)[np.isfinite(array)]
    if valid.size == 0:
        return 1.0
    deviations = np.abs(valid - target)
    limit = float(np.percentile(deviations, CURVATURE_DEVIATION_PERCENTILE))
    if limit <= 0:
        limit = float(np.max(deviations))
    return limit if limit > 0 else 1.0


def normalize_curvature_preference(
    array,
    feedback=None,
    name=None,
    target=0.0,
    limit=None,
    floor=CURVATURE_SCORE_FLOOR,
):
    """Score curvature by proximity to a target, avoiding extreme concave/convex forms."""
    name = name or t("msg_nome_curvatura")
    valid_mask = ~np.isnan(array)
    valid_data = array[valid_mask]
    if valid_data.size == 0:
        raise _erro(t("msg_sem_valores_validos", name=name))

    if limit is None or limit <= 0:
        limit = curvature_limit(valid_data, target)

    if feedback and limit > CRITERION_PLAUSIBLE_ABS:
        # Segunda rede, para o caso de a sentinela ter entrado por outro
        # caminho: o limite e o sintoma direto -- medido 3,4e37 contra os
        # 0,0004 da mesma cena limpa.
        feedback.pushWarning(t("msg_limite_percentil_absurdo", name=name, limit=limit))

    score = np.zeros_like(array, dtype=np.float32)
    score[valid_mask] = floor + (1.0 - floor) * (
        1.0 - np.clip(np.abs(array[valid_mask] - target) / limit, 0, 1)
    )

    if feedback:
        feedback.pushInfo(t("msg_alvo_limite", name=name, target=target, limit=limit))
        feedback.pushInfo(t("msg_nota_resumo", name=name, min=float(np.nanmin(score)),
                            max=float(np.nanmax(score)), mean=float(np.nanmean(score))))

    return score


def calculate_slope_degrees(dem_array, transform, feedback=None):
    """Calculate slope in degrees using physical pixel size from GeoTransform.

    Expects DEM values in a metric working CRS and uses transform pixel width
    and height as spacing for np.gradient. NaN cells remain NaN in the output.
    Raises a QgsProcessingException for invalid non-positive pixel sizes.
    """
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise _erro(t("msg_resolucao_declividade"))
    dem = dem_array.astype(np.float32)
    valid_mask = np.isfinite(dem)
    filled = np.where(valid_mask, dem, np.nanmean(dem[valid_mask]) if np.any(valid_mask) else 0.0)
    dy, dx = np.gradient(filled, pixel_size_y, pixel_size_x)
    slope = np.degrees(np.arctan(np.sqrt(dx ** 2 + dy ** 2))).astype(np.float32)
    slope[~valid_mask] = np.nan
    slope[~np.isfinite(slope)] = np.nan
    if feedback:
        feedback.pushInfo(t("msg_declividade_calculada", px=pixel_size_x, py=pixel_size_y,
                            stats=array_diagnostics(slope)))
    return slope


def calculate_curvature_arrays(dem_array, transform, feedback=None):
    """Calculate simple second-derivative horizontal/vertical curvature proxies.

    Expects DEM values in a metric working CRS. The derivatives use physical
    pixel spacing from GeoTransform. These arrays are lightweight internal
    diagnostics/fallback terrain derivatives; user supplied curvature rasters
    remain the primary production input. NaN cells remain NaN.
    """
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise _erro(t("msg_resolucao_curvatura"))
    dem = dem_array.astype(np.float32)
    valid_mask = np.isfinite(dem)
    filled = np.where(valid_mask, dem, np.nanmean(dem[valid_mask]) if np.any(valid_mask) else 0.0)
    dy, dx = np.gradient(filled, pixel_size_y, pixel_size_x)
    _, dxx = np.gradient(dx, pixel_size_y, pixel_size_x)
    dyy, _ = np.gradient(dy, pixel_size_y, pixel_size_x)
    curv_h = dxx.astype(np.float32)
    curv_v = dyy.astype(np.float32)
    curv_h[~valid_mask] = np.nan
    curv_v[~valid_mask] = np.nan
    curv_h[~np.isfinite(curv_h)] = np.nan
    curv_v[~np.isfinite(curv_v)] = np.nan
    if feedback:
        feedback.pushInfo(t("msg_curvaturas_calculadas", px=pixel_size_x, py=pixel_size_y,
                            h=array_diagnostics(curv_h), v=array_diagnostics(curv_v)))
    return curv_h, curv_v


def binarize_result(array, threshold, feedback=None):
    binary = np.where(array >= threshold, 1, 0).astype(np.uint8)
    binary = np.where(np.isnan(array), 0, binary).astype(np.uint8)

    if feedback:
        valid_pixels = int(np.sum(binary == 1))
        feedback.pushInfo(t("msg_binarizacao", valid=int(valid_pixels), total=int(binary.size),
                            pct=valid_pixels / binary.size * 100))

    return binary


def combine_constraints(route_mask, zone_mask, layer_mask,
                        stream_factor, constraint_mode):
    """Aplica as restricoes as mascaras da rota e das zonas.

    Regra, isolada aqui para poder ser testada sem QGIS (ate a 1.1.2 ela vivia
    dentro de `_run_algorithm`, e o teste de regressao a reimplementava --
    isto e, verificava a propria copia, nao o codigo que roda):

    * a camada de restricao do usuario segue o modo escolhido: no modo
      "evitar" vira barreira para a rota, no modo "encarecer" multiplica o
      custo por CONSTRAINT_PENALTY_FACTOR;
    * a drenagem NUNCA e barreira por si: entra com o fator de FORD_CLASSES
      (hoje 1, isto e, so informa) e so e intransponivel onde o fator ja veio
      infinito, acima do teto vadeavel declarado pelo usuario. Um rio e uma
      linha, e toda rota de um vale ao vizinho precisa cruzar uma;
    * as zonas excluem o rio acima do teto vadeavel (que a rota nao cruza e o
      mapa de transitabilidade chama de intransitavel) e, no modo "evitar", a
      camada do usuario -- mas NAO a drenagem vadeavel. Desde que a drenagem passou a vir ligada por padrao, tirar as
      margens das zonas tiraria da amostragem justamente o habitat ripario --
      alvo de levantamento de anfibios, de flora de mata ciliar. Quem quiser
      excluir margens fornece a hidrografia como camada de restricao.

    Devolve (route_mask, zone_mask, penalty_mask, route_barrier, tratamento).
    """
    restricted = np.zeros(route_mask.shape, dtype=bool)
    if layer_mask is not None:
        restricted |= layer_mask
    if stream_factor is not None:
        restricted |= stream_factor != 1.0
    route_barrier = np.zeros(route_mask.shape, dtype=bool)
    if not restricted.any():
        return route_mask, zone_mask, None, route_barrier, None

    factor = np.ones(route_mask.shape, dtype=np.float64)
    if stream_factor is not None:
        factor = np.maximum(factor, stream_factor)
        route_barrier |= ~np.isfinite(stream_factor)
    if layer_mask is not None:
        if constraint_mode == CONSTRAINT_AVOID:
            route_barrier |= layer_mask
        else:
            factor = np.where(layer_mask, np.maximum(factor, CONSTRAINT_PENALTY_FACTOR), factor)
    route_mask = route_mask & ~route_barrier
    factor = np.where(route_barrier, np.inf, factor)
    penalty_mask = factor if np.any(factor != 1.0) else None
    if stream_factor is not None:
        zone_mask = zone_mask & np.isfinite(stream_factor)
    if constraint_mode == CONSTRAINT_AVOID:
        if layer_mask is not None:
            zone_mask = zone_mask & ~layer_mask
        tratamento = t("msg_tratamento_evitar")
    else:
        tratamento = t("msg_tratamento_encarecer", factor=CONSTRAINT_PENALTY_FACTOR)
    return route_mask, zone_mask, penalty_mask, route_barrier, tratamento


def build_walkability_mask(zone_constraint_mask, feedback=None):
    binary = zone_constraint_mask.astype(np.uint8)
    if feedback:
        valid_pixels = int(np.sum(binary == 1))
        feedback.pushInfo(t("msg_mascara_caminhavel", valid=int(valid_pixels), total=int(binary.size),
                            pct=valid_pixels / binary.size * 100))
    return binary


def binarize_by_altitude_bands(score_array, dem_array, percentile, band_size_m, feedback=None):
    valid_mask = np.isfinite(score_array) & np.isfinite(dem_array)
    binary = np.zeros_like(score_array, dtype=np.uint8)
    if not np.any(valid_mask):
        return binary

    min_altitude = float(np.nanmin(dem_array[valid_mask]))
    max_altitude = float(np.nanmax(dem_array[valid_mask]))
    band_size_m = max(MIN_ALTITUDE_BAND_SIZE_M, float(band_size_m))
    start = np.floor(min_altitude / band_size_m) * band_size_m
    thresholds = []

    current = start
    while current <= max_altitude:
        next_altitude = current + band_size_m
        band_mask = valid_mask & (dem_array >= current) & (dem_array < next_altitude)
        band_scores = score_array[band_mask]
        if band_scores.size >= 50:
            band_threshold = float(np.percentile(band_scores, percentile))
            binary[band_mask & (score_array >= band_threshold)] = 1
            thresholds.append((current, next_altitude, band_threshold, int(band_scores.size)))
        current = next_altitude

    if feedback:
        feedback.pushInfo(t("msg_limiar_faixas", n=len(thresholds), size=band_size_m, percentile=percentile))
        for low, high, band_threshold, pixels in thresholds[:12]:
            feedback.pushInfo(t("msg_limiar_faixa_item", low=low, high=high, threshold=band_threshold,
                                pixels=int(pixels)))
        if len(thresholds) > 12:
            feedback.pushInfo(t("msg_faixas_adicionais", n=len(thresholds) - 12))

    return binary


# Representatividade das zonas: em quantas das 10 faixas da area analisada as
# zonas estao presentes, para cada variavel do relevo. A altitude usa faixas de
# mesma largura em metros -- e o gradiente que o pesquisador quer cobrir, e em
# decis de area a ultima faixa das Carnaubas ia de 333 a 920 m. As demais usam
# decis. Uma faixa conta como coberta se tiver ao menos 20% da parcela das
# zonas que teria numa amostra proporcional a area; faixas com menos de 0,5% da
# area (um pico isolado) nao entram na conta.
REPRESENTATIVENESS_BINS = 10
REPRESENTATIVENESS_MIN_RATIO = 0.2
REPRESENTATIVENESS_MIN_AREA_SHARE = 0.005
REPRESENTATIVENESS_WARN_BINS = 8
REPRESENTATIVENESS_EQUAL_WIDTH = ("altitude",)
_KS_MAX_SAMPLE = 200000


def _ks_distance(a, b, rng=None):
    """Estatistica D de Kolmogorov-Smirnov entre duas amostras (subamostradas)."""
    rng = rng or np.random.default_rng(0)
    if a.size > _KS_MAX_SAMPLE:
        a = rng.choice(a, _KS_MAX_SAMPLE, replace=False)
    if b.size > _KS_MAX_SAMPLE:
        b = rng.choice(b, _KS_MAX_SAMPLE, replace=False)
    a = np.sort(a)
    b = np.sort(b)
    pontos = np.concatenate([a, b])
    fa = np.searchsorted(a, pontos, side="right") / a.size
    fb = np.searchsorted(b, pontos, side="right") / b.size
    return float(np.max(np.abs(fa - fb)))


def northness(dem_array, transform):
    """Cosseno do aspecto: +1 encosta voltada para o norte, -1 para o sul, 0 plano.

    Sem dado (NaN na vizinhanca) sai NaN, e nao 0: senao a borda de um MDE
    recortado por poligono vira um pico de "terreno plano" na distribuicao.
    """
    dy = abs(float(transform[5])) or 1.0
    dx = abs(float(transform[1])) or 1.0
    d_linha, d_coluna = np.gradient(dem_array.astype(np.float64), dy, dx)
    # linha cresce para o sul quando o pixel tem altura negativa (norte para cima):
    # z subindo para o sul quer dizer encosta descendo para o norte.
    d_norte = d_linha * (-np.sign(float(transform[5])) or 1.0)
    modulo = np.hypot(d_linha, d_coluna)
    with np.errstate(invalid="ignore", divide="ignore"):
        valido = np.isfinite(modulo) & np.isfinite(dem_array)
        return np.where(valido, np.where(modulo > 0, d_norte / modulo, 0.0), np.nan)


def zone_representativeness(zone_mask, area_mask, variables):
    """Quanto as zonas cobrem o relevo da area analisada.

    O que se mede sao as variaveis do relevo que o plugin conhece. Na bateria de
    06/10 (PE das Carnaubas, Mantiqueira) as zonas de acesso puxavam para o
    fundo de vale e para cotas mais baixas, e nas Carnaubas tinham o dobro de
    area agropecuaria do resto do parque -- esta ultima o MDE nao ve, e a
    mensagem diz isso. Devolve {variavel: {...}} so para as variaveis com dados.
    """
    relatorio = {}
    zona = np.asarray(zone_mask, bool) & np.asarray(area_mask, bool)
    if zona.sum() < 10:
        return relatorio
    for nome, valores in variables.items():
        if valores is None:
            continue
        valores = np.asarray(valores, dtype=np.float64)
        ok = np.asarray(area_mask, bool) & np.isfinite(valores)
        v_area = valores[ok]
        v_zona = valores[zona & np.isfinite(valores)]
        if v_area.size < 100 or v_zona.size < 10:
            continue
        if nome in REPRESENTATIVENESS_EQUAL_WIDTH:
            limites = np.linspace(float(v_area.min()), float(v_area.max()), REPRESENTATIVENESS_BINS + 1)
        else:
            limites = np.unique(np.percentile(v_area, np.linspace(0, 100, REPRESENTATIVENESS_BINS + 1)))
        faixas = len(limites) - 1
        if faixas < 2 or limites[-1] <= limites[0]:
            continue

        def _parcela(v):
            indice = np.clip(np.searchsorted(limites[1:-1], v, side="right"), 0, faixas - 1)
            return np.bincount(indice, minlength=faixas) / float(v.size)

        parcela = _parcela(v_zona)
        parcela_area = _parcela(v_area)
        consideradas = parcela_area >= REPRESENTATIVENESS_MIN_AREA_SHARE
        cobertas = consideradas & (parcela >= REPRESENTATIVENESS_MIN_RATIO * parcela_area)
        faltam = []
        for i in range(faixas):
            if consideradas[i] and not cobertas[i]:
                if faltam and faltam[-1][1] == float(limites[i]):
                    faltam[-1][1] = float(limites[i + 1])
                else:
                    faltam.append([float(limites[i]), float(limites[i + 1])])
        resto = valores[ok & ~zona]
        relatorio[nome] = {
            "faixas": int(consideradas.sum()),
            "faixas_cobertas": int(cobertas.sum()),
            "largura_faixa": (round(float(limites[1] - limites[0]), 3)
                              if nome in REPRESENTATIVENESS_EQUAL_WIDTH else None),
            "parcela_area_por_faixa": [round(float(x), 3) for x in parcela_area],
            "parcela_por_faixa": [round(float(x), 3) for x in parcela],
            "limites": [round(float(x), 3) for x in limites],
            "faltam": faltam,
            "ks_d": round(_ks_distance(v_zona, resto), 3) if resto.size >= 10 else None,
            "mediana_zonas": round(float(np.median(v_zona)), 3),
            "mediana_area": round(float(np.median(v_area)), 3),
        }
    return relatorio


def describe_representativeness(relatorio, altitude_bands_on=False, walkability=False,
                                bands_need_auto_threshold=False):
    """(texto, aviso): a frase para o usuario e se ela deve sair como aviso."""
    if not relatorio:
        return None, False
    nomes = {"altitude": "msg_repr_altitude", "face_norte": "msg_repr_face", "umidade": "msg_repr_umidade"}
    partes = []
    for nome in ("altitude", "face_norte", "umidade"):
        r = relatorio.get(nome)
        if not r:
            continue
        texto = t("msg_repr_item", name=t(nomes[nome]), covered=r["faixas_cobertas"], bands=r["faixas"])
        if r.get("largura_faixa"):
            texto += t("msg_repr_largura", width=r["largura_faixa"])
        if nome == "altitude" and r["faltam"]:
            texto += t("msg_repr_faltam", ranges=t("msg_sep_itens").join(
                t("msg_repr_intervalo", low=a, high=b) for a, b in r["faltam"]))
        partes.append(texto)
    frase = t("msg_repr_frase", parts=t("msg_sep_lista").join(partes))
    altitude = relatorio.get("altitude")
    aviso = bool(altitude and altitude["faixas_cobertas"] < min(
        REPRESENTATIVENESS_WARN_BINS, altitude["faixas"]))
    if aviso:
        if walkability:
            frase += t("msg_repr_caminhaveis", option=_rotulo("band"))
        elif bands_need_auto_threshold:
            frase += t("msg_repr_limiar")
        elif altitude_bands_on:
            frase += t("msg_repr_mesmo_com_faixas")
        else:
            frase += t("msg_repr_ligue", option=_rotulo("band"))
    frase += t("msg_repr_relevo")
    return frase, aviso


def estimate_pixel_area_m2(transform, shape, proj):
    x_size = abs(float(transform[1]))
    y_size = abs(float(transform[5]))

    srs = osr.SpatialReference()
    if proj:
        srs.ImportFromWkt(proj)

    if srs.IsGeographic():
        center_lat = float(transform[3]) + (shape[0] * float(transform[5]) / 2.0)
        meters_per_degree_lon = 111320.0 * np.cos(np.deg2rad(center_lat))
        meters_per_degree_lat = 110574.0
        return abs(x_size * meters_per_degree_lon * y_size * meters_per_degree_lat)

    return abs(x_size * y_size)


def metric_crs_for_raster(transform, shape, proj):
    srs = osr.SpatialReference()
    if proj:
        srs.ImportFromWkt(proj)
    else:
        srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    if not srs.IsGeographic():
        authority = srs.GetAuthorityName(None)
        code = srs.GetAuthorityCode(None)
        if authority and code:
            return f"{authority}:{code}"
        return srs.ExportToWkt()

    center_lon = float(transform[0]) + (shape[1] * float(transform[1]) / 2.0)
    center_lat = float(transform[3]) + (shape[0] * float(transform[5]) / 2.0)
    zone = int(np.floor((center_lon + 180.0) / 6.0)) + 1
    zone = min(60, max(1, zone))
    epsg = (32600 if center_lat >= 0 else 32700) + zone
    return f"EPSG:{epsg}"


def automatic_min_patch_area_ha(analysed_area_ha):
    """Area minima automatica do fragmento: 0,05% da area analisada, entre 1 e 50 ha."""
    lo, hi = MIN_PATCH_AREA_BOUNDS_HA
    return float(min(hi, max(lo, MIN_PATCH_AREA_FRACTION * float(analysed_area_ha))))


def filter_small_regions(binary_array, transform, proj, min_area_ha, feedback=None, log_path=None):
    """Remove connected raster fragments smaller than a minimum area.

    Area is computed from metric pixel area when the CRS is projected; for
    geographic CRS the helper estimates meters from latitude, but production
    flow now prepares a projected working CRS before this function is reached.
    Returns a uint8 mask with small fragments removed and logs pixel/fragment
    counts when log_path is provided.
    """
    if min_area_ha <= 0:
        return binary_array

    pixel_area_m2 = estimate_pixel_area_m2(transform, binary_array.shape, proj)
    min_pixels = max(1, int(np.ceil((min_area_ha * 10000.0) / pixel_area_m2)))
    labels, region_count = morphology.label(binary_array == 1, connectivity=8)

    if region_count == 0:
        return binary_array

    region_sizes = np.bincount(labels.ravel())
    keep_labels = np.where(region_sizes >= min_pixels)[0]
    keep_labels = keep_labels[keep_labels != 0]
    filtered = np.isin(labels, keep_labels).astype(np.uint8)

    if feedback:
        before_pixels = int(np.sum(binary_array == 1))
        after_pixels = int(np.sum(filtered == 1))
        removed_regions = int(region_count - len(keep_labels))
        feedback.pushInfo(t("msg_area_minima_filtro", area=min_area_ha, pixels=int(min_pixels),
                            removed=int(removed_regions)))
        feedback.pushInfo(t("msg_pixels_apos_filtro", after=int(after_pixels), before=int(before_pixels)))
    append_diagnostic_log(
        log_path,
        "filtro_area_minima",
        area_pixel_m2=float(pixel_area_m2),
        area_min_fragmento_ha=float(min_area_ha),
        min_pixels=int(min_pixels),
        fragmentos_antes=int(region_count),
        fragmentos_depois=int(len(keep_labels)),
        pixels_antes=int(np.sum(binary_array == 1)),
        pixels_depois=int(np.sum(filtered == 1)),
    )

    return filtered


def save_score_raster(score_array, transform, proj, output_path, feedback=None):
    base_path, _ = os.path.splitext(output_path)
    score_path = f"{base_path}_adequabilidade.tif"
    rows, cols = score_array.shape
    output_dir = os.path.dirname(score_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output = np.where(np.isnan(score_array), -9999.0, score_array).astype(np.float32)
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(score_path):
        try:
            driver.Delete(score_path)
        except RuntimeError:
            score_path = available_output_path(score_path)
            if feedback:
                feedback.pushWarning(t("msg_adequabilidade_bloqueado", path=score_path))
    dataset = driver.Create(score_path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise _erro(t("msg_adequabilidade_falhou"))

    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(output)
    band.FlushCache()
    dataset = None

    if feedback:
        feedback.pushInfo(t("msg_adequabilidade_salvo", path=score_path))
    return score_path


def save_transitability_raster(classes, transform, proj, output_path, feedback=None,
                               labels=None):
    """Grava o mapa de classes com paleta e rotulos embutidos.

    Um raster categorico sem tabela de cores abre no QGIS como uma rampa
    cinzenta de 0 a 5, que nao comunica nada. Gravar a paleta e a lista de
    categorias no proprio GeoTIFF faz o mapa abrir ja legivel, com legenda,
    sem o usuario ter de estiliza-lo.
    """
    base_path, _ = os.path.splitext(output_path)
    path = f"{base_path}_transitabilidade.tif"
    rows, cols = classes.shape
    output_dir = os.path.dirname(path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(path):
        try:
            driver.Delete(path)
        except RuntimeError:
            path = available_output_path(path)

    dataset = driver.Create(
        path, cols, rows, 1, gdal.GDT_Byte,
        options=["COMPRESS=LZW", "PHOTOMETRIC=PALETTE"],
    )
    if dataset is None:
        raise _erro(t("msg_transitabilidade_falhou"))
    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)

    band = dataset.GetRasterBand(1)
    # A paleta precisa ser gravada antes dos dados: o driver GTiff fixa a tag
    # PhotometricInterpretation na primeira escrita e recusa altera-la depois.
    table = gdal.ColorTable()
    for code, colour in CLASS_COLORS.items():
        table.SetColorEntry(int(code), tuple(int(c) for c in colour))
    band.SetRasterColorTable(table)
    band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    # Onde a legenda fica: o GeoTIFF nao tem lugar padrao para nomes de
    # categoria, entao o GDAL os grava num arquivo irmao .aux.xml, que e o que o
    # QGIS le para montar a legenda. Por isso os mesmos rotulos vao tambem como
    # metadado GDAL, logo abaixo -- esse sim dentro do .tif.
    # Os rotulos vem de quem classificou, ja preenchidos com os limites que a
    # execucao usou. Antes esta linha chamava _class_labels() de novo e gravava
    # sempre os limites de fabrica: medido com TRANSITABILITY_BREAKS = 2,4,6,8,
    # a classe 1 do arquivo valia "< 2%" e a legenda gravada dentro dele dizia
    # "1 - Suave (< 20%)".
    rotulos = labels or format_class_labels(_class_labels())
    band.SetCategoryNames([""] + [rotulos[code] for code in sorted(rotulos)])
    # SetCategoryNames nao entra no TIFF: o driver GTiff grava os nomes de
    # categoria num arquivo .aux.xml ao lado, e quem enviasse so o .tif perdia a
    # legenda -- ficava com as cores certas e sem saber o que cada uma significa.
    # Os mesmos rotulos vao tambem como metadado GDAL, que o GTiff guarda DENTRO
    # do arquivo, na etiqueta GDAL_METADATA. Assim o .tif viaja sozinho e ainda
    # diz o que significa, em qualquer leitor que mostre metadados.
    band.SetMetadata({
        "TOPOTRAIL_CLASSE_{}".format(code): rotulos[code] for code in sorted(rotulos)
    })
    band.SetNoDataValue(0)
    band.WriteArray(classes.astype(np.uint8))
    band.FlushCache()
    dataset = None

    if feedback:
        feedback.pushInfo(t("msg_transitabilidade_salvo", path=path))
    return path


def save_risk_raster(risk_array, transform, proj, output_path, feedback=None):
    base_path, _ = os.path.splitext(output_path)
    risk_path = f"{base_path}_risco_topografico.tif"
    rows, cols = risk_array.shape
    output_dir = os.path.dirname(risk_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output = np.where(np.isnan(risk_array), -9999.0, risk_array).astype(np.float32)
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(risk_path):
        try:
            driver.Delete(risk_path)
        except RuntimeError:
            risk_path = available_output_path(risk_path)
            if feedback:
                feedback.pushWarning(t("msg_risco_bloqueado", path=risk_path))
    dataset = driver.Create(risk_path, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise _erro(t("msg_risco_falhou"))

    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(output)
    band.FlushCache()
    dataset = None

    if feedback:
        feedback.pushInfo(t("msg_risco_salvo", path=risk_path))
    return risk_path


def robust_limit(array, valid_mask, percentile=CURVATURE_RISK_PERCENTILE):
    """Limite de normalizacao robusta: o percentil do modulo NA CENA."""
    values = np.abs(array[valid_mask & np.isfinite(array)])
    if values.size == 0:
        return 1.0
    limit = float(np.nanpercentile(values, percentile))
    if not np.isfinite(limit) or limit <= 0:
        limit = float(np.nanmax(values))
    if not np.isfinite(limit) or limit <= 0:
        limit = 1.0
    return limit


def robust_abs_norm(array, valid_mask, percentile=CURVATURE_RISK_PERCENTILE, limit=None):
    if not np.any(valid_mask & np.isfinite(array)):
        return np.full(array.shape, np.nan, dtype=np.float32)
    if limit is None or not np.isfinite(limit) or limit <= 0:
        limit = robust_limit(array, valid_mask, percentile)
    return np.clip(np.abs(array) / limit, 0, 1).astype(np.float32)


def flat_water_masks(dem, pixel_area_m2, min_area_m2=WATER_MIN_AREA_M2):
    """(mar, lagos): superficies de altitude exatamente constante, >= min_area_m2.

    Uma celula e plana quando a vizinhanca 3x3 inteira tem a mesma altitude;
    celulas planas contiguas formam uma superficie, e todas tem a mesma
    altitude. Mar = superficie ate SEA_LEVEL_MAX_M (inclui NoData gravado como
    zero); lagos = as demais.
    """
    finito = np.isfinite(dem)
    vazio = np.zeros(dem.shape, dtype=bool)
    if not finito.any():
        return vazio, vazio
    linhas, colunas = dem.shape
    borda = np.pad(np.where(finito, dem, np.nan), 1, mode="edge")
    maximo = np.full(dem.shape, -np.inf)
    minimo = np.full(dem.shape, np.inf)
    for d_lin in (0, 1, 2):
        for d_col in (0, 1, 2):
            janela = borda[d_lin:d_lin + linhas, d_col:d_col + colunas]
            maximo = np.fmax(maximo, janela)
            minimo = np.fmin(minimo, janela)
    plano = finito & (maximo == minimo)
    rotulos, quantos = morphology.label(plano, connectivity=8)
    if quantos == 0:
        return vazio, vazio
    tamanho = np.bincount(rotulos.ravel(), minlength=quantos + 1)
    grande = tamanho * float(pixel_area_m2) >= float(min_area_m2)
    grande[0] = False
    nivel = np.zeros(quantos + 1)
    nivel[rotulos[plano]] = dem[plano]
    agua = grande[rotulos]
    mar = agua & (nivel[rotulos] <= SEA_LEVEL_MAX_M)
    return mar, agua & ~mar


def explain_empty_mask(dem, slope, valid_mask, min_altitude, max_altitude, max_slope):
    """Por que nenhuma celula atende as restricoes, em numeros da propria cena."""
    partes = []
    altitudes = dem[valid_mask & np.isfinite(dem)]
    if altitudes.size:
        dentro = float(np.mean((altitudes >= min_altitude) & (altitudes <= max_altitude)))
        if dentro < 0.01:
            partes.append(t("msg_causa_altitude", min=min_altitude, max=max_altitude,
                            dem_min=float(altitudes.min()), dem_max=float(altitudes.max())))
    declividades = slope[valid_mask & np.isfinite(slope)]
    if declividades.size:
        abaixo = float(np.mean(declividades <= max_slope))
        if abaixo < 0.05:
            partes.append(t("msg_causa_declividade", pct=100.0 * abaixo, limit=max_slope,
                            median=float(np.median(declividades))))
    if not altitudes.size:
        partes.append(t("msg_causa_sem_celulas"))
    return " ".join(partes) or t("msg_causa_geral")


def compute_topographic_risk(slope_data, curvh_data, curvv_data, valid_mask, max_slope, feedback=None):
    """Relative topographic risk: 0 is easier terrain, 1 is steep/rough/abrupt terrain."""
    slope_limit = max(float(max_slope), 1.0)
    slope_risk = np.clip(slope_data / slope_limit, 0, 1)
    slope_risk = np.power(slope_risk, SLOPE_RISK_EXPONENT)

    curvh_risk = robust_abs_norm(curvh_data, valid_mask)
    curvv_risk = robust_abs_norm(curvv_data, valid_mask)
    curvature_risk = np.full(slope_data.shape, np.nan, dtype=np.float32)
    curvature_valid = valid_mask & np.isfinite(curvh_risk) & np.isfinite(curvv_risk)
    curvature_risk[curvature_valid] = (curvh_risk[curvature_valid] + curvv_risk[curvature_valid]) / 2.0

    risk = (RISK_SLOPE_WEIGHT * slope_risk + RISK_CURVATURE_WEIGHT * curvature_risk).astype(np.float32)
    risk = np.where(valid_mask, np.clip(risk, 0, 1), np.nan).astype(np.float32)

    if feedback:
        values = risk[np.isfinite(risk)]
        if values.size:
            feedback.pushInfo(t(
                "msg_risco_resumo", min=float(np.nanmin(values)), p50=float(np.nanpercentile(values, 50)),
                p75=float(np.nanpercentile(values, 75)), p95=float(np.nanpercentile(values, 95)),
                max=float(np.nanmax(values))))
    return risk


def _is_valid_quietly(geometry):
    """IsValid sem o aviso do GEOS: anel que se toca no vertice e esperado no Polygonize."""
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        return geometry.IsValid()
    finally:
        gdal.PopErrorHandler()


def vectorize_binary_raster(binary_array, transform, proj, feedback=None):
    """Polygonize a binary raster and return only polygons with value 1."""
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj) if proj else srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    crs = srs.ExportToWkt()
    if np.sum(binary_array == 1) == 0:
        return FeatureSet([], [], crs)

    temp_dir = tempfile.mkdtemp()
    try:
        temp_raster = os.path.join(temp_dir, "mask.tif")
        rows, cols = binary_array.shape
        driver = gdal.GetDriverByName("GTiff")
        dataset = driver.Create(temp_raster, cols, rows, 1, gdal.GDT_Byte)
        if dataset is None:
            raise _erro(t("msg_raster_temporario"))

        dataset.SetGeoTransform(transform)
        if proj:
            dataset.SetProjection(proj)
        band = dataset.GetRasterBand(1)
        band.SetNoDataValue(0)
        band.WriteArray(binary_array)
        band.FlushCache()
        dataset = None

        # Poligoniza para uma camada em memoria: nada toca o disco alem do raster.
        vector_ds = ogr_memory_driver().CreateDataSource("mask")
        if vector_ds is None:
            raise _erro(t("msg_vetor_temporario"))
        layer = vector_ds.CreateLayer("polygons", srs=srs, geom_type=ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))

        raster_ds = gdal.Open(temp_raster)
        raster_band = raster_ds.GetRasterBand(1)
        gdal.Polygonize(raster_band, raster_band, layer, 0, options=["8CONNECTED=8"])
        raster_ds = None

        geometries, attributes = [], []
        layer.ResetReading()
        for feature in layer:
            if feature.GetField("value") != 1:
                continue
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geometry = geometry.Clone()
            # buffer(0): o mesmo reparo de anel que o shapely fazia, agora pelo GEOS do OGR.
            if not _is_valid_quietly(geometry):
                geometry = geometry.Buffer(0)
            if geometry is None or geometry.IsEmpty() or not _is_valid_quietly(geometry):
                continue
            geometries.append(geometry)
            attributes.append({"value": 1})
        vector_ds = None

        result = FeatureSet(geometries, attributes, crs)
        if feedback:
            feedback.pushInfo(t("msg_vetorizacao", n=len(result)))
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def save_vector(features, output_path, output_format, output_crs, feedback=None):
    driver_map = {
        "Shapefile": "ESRI Shapefile",
        "GeoPackage": "GPKG",
        "KML": "KML",
    }

    if len(features) == 0:
        raise _erro(t("msg_sem_area_limiar"))

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    target_crs, target_label = output_crs_target(output_crs)
    if target_crs and output_format == "KML":
        # KML e sempre WGS84 por especificacao; o LIBKML reprojeta ao gravar.
        target_crs = None
        if feedback:
            feedback.pushInfo(t("msg_kml_4326"))
    if target_crs:
        features = features.to_crs(target_crs)
        if feedback:
            feedback.pushInfo(t("msg_reprojetado", crs=target_label))

    export = FeatureSet(features.geometries, features.attributes, features.crs)
    if output_format == "Shapefile" and "area_m2" in export.columns:
        export.drop_column("area_m2")
        if feedback:
            feedback.pushInfo(t("msg_shapefile_area"))

    driver = driver_map.get(output_format, "ESRI Shapefile")
    stringify = False
    if output_format == "KML":
        # O driver classico "KML" do OGR descarta atributos: joga os dois
        # primeiros campos em Name/Description e perde o resto. O LIBKML grava
        # todos, com tipo; e o que o QGIS usa para ler KML quando existe.
        if ogr.GetDriverByName("LIBKML") is not None:
            driver = "LIBKML"
        else:
            stringify = True
    driver_obj = ogr.GetDriverByName(driver)
    # O GeoPackage nao entra aqui: ele e substituido camada a camada dentro de
    # to_file, para nao levar junto as outras camadas do usuario.
    if driver_obj and driver != "GPKG" and os.path.exists(output_path):
        try:
            driver_obj.DeleteDataSource(output_path)
        except RuntimeError:
            output_path = available_output_path(output_path)
            if feedback:
                feedback.pushWarning(t("msg_vetor_bloqueado", path=output_path))
    export.to_file(output_path, driver=driver, stringify=stringify)

    if feedback:
        feedback.pushInfo(t("msg_vetor_salvo", format=output_format, n=len(features)))
    return output_path


def output_crs_target(output_crs):
    """(alvo para to_crs, rotulo) a partir de um QgsCoordinateReferenceSystem.

    Usa o WKT, nunca o authid: um CRS personalizado salvo no QGIS tem authid
    "USER:100000", que o OSR nao conhece (quebrava com "Corrupt data"), e um
    CRS sem autoridade tem authid vazio -- a saida ficava no CRS de trabalho
    sem aviso, embora o parametro tivesse sido preenchido.
    """
    if not output_crs or not output_crs.isValid():
        return None, None
    label = output_crs.authid() or output_crs.description() or t("msg_crs_personalizado")
    try:
        wkt = output_crs.toWkt()
    except Exception:
        wkt = ""
    if not wkt:
        return None, None
    return wkt, label


def ensure_output_extension(output_path, output_format):
    extension_map = {
        "Shapefile": ".shp",
        "GeoPackage": ".gpkg",
        "KML": ".kml",
    }
    expected_extension = extension_map.get(output_format)
    if not expected_extension:
        return output_path

    base_path, current_extension = os.path.splitext(output_path)
    if current_extension.lower() != expected_extension:
        return f"{base_path}{expected_extension}"
    return output_path


def available_output_path(path):
    base, extension = os.path.splitext(path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base}_{timestamp}{extension}"
    counter = 1
    while os.path.exists(candidate):
        candidate = f"{base}_{timestamp}_{counter}{extension}"
        counter += 1
    return candidate


_POINTS_WITHOUT_CRS_WARNED = set()


def _warn_points_without_crs(point_path):
    """Aviso unico por arquivo: camada de pontos sem CRS e lida no CRS do MDE."""
    if point_path in _POINTS_WITHOUT_CRS_WARNED:
        return
    _POINTS_WITHOUT_CRS_WARNED.add(point_path)
    try:
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(
            f"Camada de pontos sem CRS definido ({point_path}); as coordenadas foram "
            "assumidas no CRS de trabalho do MDE.", "TopoTrail",
            _qgs_enum(Qgis, "MessageLevel", "Warning"))
    except Exception as exc:  # fora do QGIS (testes): registra no logging do Python
        _LOG.debug("aviso de CRS nao pode ir ao QgsMessageLog: %s", exc)


def transform_point_to_raster(point_path, raster_proj):
    try:
        datasource = ogr.Open(point_path)
    except RuntimeError as exc:
        raise _erro(t("msg_ponto_abrir", path=point_path)) from exc
    if datasource is None:
        raise _erro(t("msg_ponto_abrir", path=point_path))

    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(raster_proj) if raster_proj else raster_srs.ImportFromEPSG(4326)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    for layer_index in range(datasource.GetLayerCount()):
        layer = datasource.GetLayerByIndex(layer_index)
        source_srs = layer.GetSpatialRef()
        transform = None
        if source_srs is None or (source_srs.GetName() or "").lower().startswith("undefined"):
            # Sem CRS declarado: assume-se o CRS do raster, e diz-se isso.
            _warn_points_without_crs(point_path)
            source_srs = None
        if source_srs is not None and not source_srs.IsSame(raster_srs):
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            transform = osr.CoordinateTransformation(source_srs, raster_srs)

        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geom = geometry.Clone()
            if transform is not None:
                geom.Transform(transform)
            flat_type = ogr.GT_Flatten(geom.GetGeometryType())
            if flat_type == ogr.wkbPoint:
                return float(geom.GetX()), float(geom.GetY())
            if geom.GetGeometryCount() > 0:
                sub_geom = geom.GetGeometryRef(0)
                if sub_geom and ogr.GT_Flatten(sub_geom.GetGeometryType()) == ogr.wkbPoint:
                    return float(sub_geom.GetX()), float(sub_geom.GetY())

    raise _erro(t("msg_ponto_sem_geometria", path=point_path))


def transform_points_to_raster(point_path, raster_proj):
    """Todos os pontos do arquivo, na ordem das feicoes, reprojetados.

    A ordem importa: e ela que define a sequencia da travessia. O QGIS preserva
    a ordem de insercao numa camada de pontos desenhada a mao, entao desenhar
    Marins, Marinzinho e Itaguare nessa ordem produz exatamente essa rota. Quem
    quiser outra ordem pode reordenar a camada ou pedir a otimizacao.
    """
    try:
        datasource = ogr.Open(point_path)
    except RuntimeError as exc:
        raise _erro(t("msg_camada_pontos_abrir", path=point_path)) from exc
    if datasource is None:
        raise _erro(t("msg_camada_pontos_abrir", path=point_path))

    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(raster_proj) if raster_proj else raster_srs.ImportFromEPSG(4326)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    points = []
    for layer_index in range(datasource.GetLayerCount()):
        layer = datasource.GetLayerByIndex(layer_index)
        source_srs = layer.GetSpatialRef()
        transform = None
        if source_srs is None or (source_srs.GetName() or "").lower().startswith("undefined"):
            # Sem CRS declarado: assume-se o CRS do raster, e diz-se isso.
            _warn_points_without_crs(point_path)
            source_srs = None
        if source_srs is not None and not source_srs.IsSame(raster_srs):
            source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            transform = osr.CoordinateTransformation(source_srs, raster_srs)
        for feature in layer:
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            geom = geometry.Clone()
            if transform is not None:
                geom.Transform(transform)
            if ogr.GT_Flatten(geom.GetGeometryType()) == ogr.wkbPoint:
                points.append((float(geom.GetX()), float(geom.GetY())))
            else:
                for index in range(geom.GetGeometryCount()):
                    sub = geom.GetGeometryRef(index)
                    if sub and ogr.GT_Flatten(sub.GetGeometryType()) == ogr.wkbPoint:
                        points.append((float(sub.GetX()), float(sub.GetY())))
    if not points:
        raise _erro(t("msg_nenhum_ponto", path=point_path))
    return points


def world_to_pixel(transform, x, y):
    # floor, e nao round: a celula (r, c) cobre [r, r+1) x [c, c+1) em coordenadas
    # continuas de pixel. round() empurrava um ponto a 0,6 da celula para a
    # vizinha, e o mesmo ponto dado em dois CRS caia em celulas diferentes.
    inv_transform = gdal.InvGeoTransform(transform)
    col = int(np.floor(inv_transform[0] + inv_transform[1] * x + inv_transform[2] * y))
    row = int(np.floor(inv_transform[3] + inv_transform[4] * x + inv_transform[5] * y))
    return row, col


def pixel_to_world(transform, row, col):
    x = transform[0] + (col + 0.5) * transform[1] + (row + 0.5) * transform[2]
    y = transform[3] + (col + 0.5) * transform[4] + (row + 0.5) * transform[5]
    return float(x), float(y)


def meters_to_pixels(transform, shape, proj, distance_m):
    pixel_area = estimate_pixel_area_m2(transform, shape, proj)
    pixel_size = np.sqrt(pixel_area) if pixel_area > 0 else 30.0
    return max(1, int(np.ceil(distance_m / pixel_size)))


def nearest_valid_cell(valid_mask, row, col, radius=NEAREST_VALID_CELL_RADIUS):
    rows, cols = valid_mask.shape
    if 0 <= row < rows and 0 <= col < cols and valid_mask[row, col]:
        return row, col

    best = None
    best_dist = None
    row_min = max(0, row - radius)
    row_max = min(rows, row + radius + 1)
    col_min = max(0, col - radius)
    col_max = min(cols, col + radius + 1)
    candidates = np.argwhere(valid_mask[row_min:row_max, col_min:col_max])
    for candidate_row, candidate_col in candidates:
        rr = int(candidate_row + row_min)
        cc = int(candidate_col + col_min)
        dist = (rr - row) ** 2 + (cc - col) ** 2
        if best_dist is None or dist < best_dist:
            best = (rr, cc)
            best_dist = dist
    if best is None:
        raise _erro(t("msg_ponto_sem_celula"))
    return best


def tobler_hours(delta_z, horizontal_m):
    """Tempo de caminhada de um passo, em horas, pela funcao de Tobler.

    Tobler, W. (1993) Three presentations on geographical analysis and modeling.
    NCGIA Technical Report 93-1.

    `delta_z` e a variacao de altitude do passo, com sinal, e `horizontal_m` o
    seu comprimento horizontal. A velocidade maxima nao esta no plano e sim numa
    descida suave; subidas e descidas fortes sao ambas lentas, mas nao pelo
    mesmo tanto. Nenhum modelo isotropico consegue representar isso.
    """
    if horizontal_m <= 0:
        return 0.0
    slope = delta_z / horizontal_m
    speed_kmh = TOBLER_MAX_SPEED_KMH * np.exp(
        -TOBLER_DECAY * abs(slope + TOBLER_OPTIMUM_SLOPE))
    if speed_kmh <= 1e-6:
        return np.inf
    return (horizontal_m / 1000.0) / speed_kmh


def tobler_hours_along(path_cells, elevation, pixel_size_m):
    """Tempo de Tobler puro ao longo de uma sequencia de celulas, em horas.

    E o tempo que a rota leva a pe pela funcao de Tobler, sem o retardo por
    terreno e sem os fatores de vau. Esses dois entram no custo que o A*
    minimiza, porque exprimem preferencia: terreno suave e travessia rasa sao
    preferiveis por risco, esforco e erosao. Mas nao sao tempo. O ajuste de
    VALIDACAO.md (6c) deu o coeficiente do retardo indistinguivel de zero (e de
    sinal trocado) contra o ritmo medido em campo. Na bateria de 51 trilhas
    consagradas, relatar o custo acumulado como tempo inflava a duracao de 1,10
    a 1,91 vez (mediana 1,39) conforme o terreno, e o fator de campo, ajustado
    sobre o Tobler puro, multiplicava essa inflacao.
    """
    total = 0.0
    for (r0, c0), (r1, c1) in zip(path_cells[:-1], path_cells[1:]):
        horizontal_m = float(np.hypot(r1 - r0, c1 - c0)) * float(pixel_size_m)
        delta_z = float(elevation[r1, c1] - elevation[r0, c0])
        if horizontal_m <= 0 or not np.isfinite(delta_z):
            continue
        total += tobler_hours(delta_z, horizontal_m)
    return total


def format_hours(hours):
    """Duracao em horas decimais como '5h07'.

    Arredonda o total de minutos, e nao so a fracao: 4,996 h e 5h00, nao 4h60.
    """
    total = int(round(float(hours) * 60.0))
    return "{:d}h{:02d}".format(*divmod(total, 60))


def _liga_apenas_pelo_canto(cost_array, start_rc, end_rc):
    """Os dois pontos se ligariam se o passo diagonal pudesse cortar o canto?

    Rotula componentes conexas duas vezes sobre a mesma grade: uma com a
    vizinhanca de 8 crua, que e a regra ate a 1.2.0 e deixa passar pelo vertice,
    e outra so com os quatro vizinhos ortogonais, que nunca corta canto. Ligados
    na primeira e separados na segunda significa que toda ligacao entre eles
    depende de um contato de largura zero.

    A vizinhanca de 4 e mais restritiva do que a regra em vigor -- que aceita a
    diagonal quando ha passagem por fora -- entao um "sim" aqui e conservador.
    Por isso o resultado so serve para ESCOLHER A MENSAGEM, nunca para permitir
    ou proibir um passo.
    """
    passavel = np.isfinite(cost_array)
    if not (passavel[start_rc] and passavel[end_rc]):
        return False
    rotulos_oito, _ = morphology.label(passavel, connectivity=8)
    rotulos_quatro, _ = morphology.label(passavel, connectivity=4)
    return bool(rotulos_oito[start_rc] == rotulos_oito[end_rc]
                and rotulos_quatro[start_rc] != rotulos_quatro[end_rc])


def _todos_ligados(rotulos, pontos):
    componentes = {int(rotulos[p]) for p in pontos}
    return len(componentes) == 1 and 0 not in componentes


def minimum_connecting_slope(slope, barrier, points, max_slope):
    """Menor declividade maxima (%, inteira) que liga todos os pontos, ou None.

    A ligacao do A* e a de quatro vizinhos: a diagonal so existe com os dois
    cantos transponiveis. `barrier` marca o que bloqueia por outro motivo
    (restricao no modo evitar, curso d'agua acima do teto vadeavel).
    """
    base = np.isfinite(slope) & ~barrier
    if not base.any():
        return None
    teto = float(np.nanmax(slope[base]))

    def liga(limite):
        rotulos, _ = morphology.label(base & (slope <= limite), connectivity=4)
        return _todos_ligados(rotulos, points)

    if teto <= max_slope or not liga(teto):
        return None
    baixo, alto = float(max_slope), teto
    for _ in range(20):
        meio = (baixo + alto) / 2.0
        if liga(meio):
            alto = meio
        else:
            baixo = meio
    return int(np.ceil(alto))


def check_route_connectivity(cost_array, points, slope=None, penalty=None,
                             max_slope=None, cell_size_m=None, log_path=None):
    """Antes do A*: os pontos se ligam? Se nao, diz por que e o que fazer.

    Sem isto o A* percorria todo o componente da origem antes de desistir, e a
    mensagem pedia "aumente a declividade maxima" sem dizer para quanto. No
    Khumbu, com o padrao de 55%, o usuario ficava tentando as cegas.
    """
    passavel = np.isfinite(cost_array)
    rotulos, _ = morphology.label(passavel, connectivity=4)
    if _todos_ligados(rotulos, points):
        return
    oito, _ = morphology.label(passavel, connectivity=8)
    so_vertice = _todos_ligados(oito, points)
    sugestao = ""
    necessario = None
    if slope is not None and max_slope:
        barreira = (np.isinf(penalty) if penalty is not None
                    else np.zeros(cost_array.shape, dtype=bool))
        necessario = minimum_connecting_slope(slope, barreira, points, max_slope)
        if necessario is not None:
            sugestao = t("msg_ligacao_declividade", needed=necessario, current=max_slope,
                         cell=cell_size_m or 0)
        elif so_vertice:
            sugestao = ""
        else:
            sugestao = t("msg_ligacao_nem_sem_limite")
    append_diagnostic_log(log_path, "rota_sem_ligacao", declividade_que_liga_pct=necessario,
                          so_contato_de_vertice=bool(so_vertice))
    if so_vertice and necessario is None:
        raise _erro(t("msg_contato_vertice"))
    raise _erro(t("msg_sem_ligacao", hint=sugestao))


def path_length_m(path_cells, pixel_size_m):
    """Comprimento de uma rota em celulas (passos ortogonais e diagonais), em metros."""
    if len(path_cells) < 2:
        return 0.0
    passos = np.diff(np.asarray(path_cells, dtype=float), axis=0)
    return float(np.hypot(passos[:, 0], passos[:, 1]).sum() * float(pixel_size_m))


def slope_detour(route_cells, free_cells, slope, max_slope, pixel_size_m):
    """A rota contorna terreno acima da declividade maxima? Compara com a rota sem o limite.

    `free_cells` e a rota de menor custo sem o limite de declividade (os rios e
    as restricoes continuam valendo). Devolve os comprimentos, a razao, a maior
    declividade que a rota sem limite usa e quantos metros dela ficam acima do
    limite. `avisar` e verdadeiro quando a rota e ao menos DETOUR_WARN_RATIO vezes
    e DETOUR_WARN_MIN_M metros mais longa e a rota sem limite de fato passa por
    terreno acima dele.
    """
    comprimento = path_length_m(route_cells, pixel_size_m)
    livre = path_length_m(free_cells, pixel_size_m)
    decl = np.array([slope[r, c] for r, c in free_cells], dtype=float)
    acima = np.isfinite(decl) & (decl > float(max_slope))
    metros_acima = 0.0
    if len(free_cells) >= 2:
        passos = np.diff(np.asarray(free_cells, dtype=float), axis=0)
        trecho = np.hypot(passos[:, 0], passos[:, 1]) * float(pixel_size_m)
        metros_acima = float(trecho[acima[1:] | acima[:-1]].sum())
    maior = float(np.nanmax(decl)) if np.isfinite(decl).any() else float("nan")
    razao = comprimento / livre if livre > 0 else float("nan")
    return {
        "comprimento_m": comprimento,
        "comprimento_sem_limite_m": livre,
        "razao": razao,
        "declividade_max_sem_limite_pct": maior,
        "declividade_que_encurta_pct": int(np.ceil(maior)) if np.isfinite(maior) else None,
        "metros_acima_do_limite": metros_acima,
        "avisar": bool(np.isfinite(razao) and razao >= DETOUR_WARN_RATIO
                       and comprimento - livre >= DETOUR_WARN_MIN_M and metros_acima > 0),
    }


def check_slope_detour(score_crop, free_crop, sequence, path_cells, slope_crop, max_slope,
                       cost_model, contrast, penalty_crop, elevation_crop, pixel_size_m,
                       anisotropic, feedback=None, log_path=None):
    """Depois da rota: ela contorna terreno acima da declividade maxima? Se sim, avisa.

    So roda quando ha, no recorte, celulas barradas apenas pela declividade. A
    rota sem limite usa o mesmo custo, os mesmos pontos na mesma ordem e as
    mesmas barreiras (rios acima do teto vadeavel, restricao no modo evitar). A
    comparacao nunca derruba a rota que ja existe: se falhar, fica so no log.
    """
    if not (np.isfinite(free_crop) & ~np.isfinite(score_crop)).any():
        return None
    # Atalho exato: o A* anda em 8 direcoes, entao nenhuma rota entre os pontos
    # e mais curta que a distancia octil. Se a rota ja esta perto dela, o desvio
    # nao tem como chegar a 25% e 500 m, e a segunda rota nao precisa ser feita.
    comprimento = path_length_m(path_cells, pixel_size_m)
    passos = np.abs(np.diff(np.asarray(sequence, dtype=float), axis=0))
    octil = float((passos.max(axis=1) + (np.sqrt(2.0) - 1.0) * passos.min(axis=1)).sum() * pixel_size_m)
    if comprimento < DETOUR_WARN_RATIO * octil or comprimento - octil < DETOUR_WARN_MIN_M:
        return None
    try:
        custo_livre = build_route_cost(free_crop, cost_model, contrast, penalty_crop).astype(np.float32)
        livre, _, _ = multi_leg_route(custo_livre, sequence, elevation=elevation_crop,
                                      pixel_size_m=pixel_size_m, anisotropic=anisotropic,
                                      crossing_factor=penalty_crop)
    except Exception as erro:  # noqa: BLE001
        append_diagnostic_log(log_path, "desvio_pela_declividade", erro=str(erro)[:300])
        return None
    desvio = slope_detour(path_cells, livre, slope_crop, max_slope, pixel_size_m)
    append_diagnostic_log(log_path, "desvio_pela_declividade", limite_pct=float(max_slope), **desvio)
    if desvio["avisar"] and feedback:
        feedback.pushWarning(t(
            "msg_desvio", limit=max_slope, free_km=desvio["comprimento_sem_limite_m"] / 1000.0,
            route_km=desvio["comprimento_m"] / 1000.0, metres=desvio["metros_acima_do_limite"],
            needed=desvio["declividade_que_encurta_pct"], cell=pixel_size_m))
    return desvio


def least_cost_path(cost_array, start_rc, end_rc, elevation=None,
                    pixel_size_m=None, anisotropic=False, feedback=None,
                    progress_range=None, crossing_factor=None):
    rows, cols = cost_array.shape
    start_index = start_rc[0] * cols + start_rc[1]
    end_index = end_rc[0] * cols + end_rc[1]

    if crossing_factor is not None:
        crossing_factor = np.asarray(crossing_factor)
        if crossing_factor.dtype == bool:
            crossing_factor = np.where(crossing_factor, CONSTRAINT_PENALTY_FACTOR, 1.0)
        crossing_factor = crossing_factor.astype(np.float64, copy=False)

    dist = np.full(rows * cols, np.inf, dtype=np.float64)
    previous = np.full(rows * cols, -1, dtype=np.int64)
    visited = np.zeros(rows * cols, dtype=bool)
    dist[start_index] = 0.0
    finite_costs = cost_array[np.isfinite(cost_array)]
    if finite_costs.size == 0:
        raise _erro(t("msg_area_busca_vazia"))
    min_step_cost = float(np.nanmin(finite_costs))

    if anisotropic:
        if elevation is None or pixel_size_m is None:
            raise ValueError("The anisotropic model needs the elevation and the pixel size.")
        # A heuristica precisa continuar admissivel: o tempo por metro nunca fica
        # abaixo do de Tobler na sua velocidade maxima, e o retardo por terreno
        # nunca fica abaixo do seu minimo na cena.
        min_hours_per_m = 1.0 / (TOBLER_MAX_SPEED_KMH * 1000.0)
        heuristic_unit = min_hours_per_m * min_step_cost * float(pixel_size_m)
    else:
        heuristic_unit = min_step_cost

    def heuristic(row, col):
        return np.hypot(row - end_rc[0], col - end_rc[1]) * heuristic_unit

    heap = [(heuristic(start_rc[0], start_rc[1]), 0.0, start_index)]

    # Cada passo diagonal atravessa o canto compartilhado por quatro celulas, e
    # duas delas nao sao nem a origem nem o destino do passo: sao as celulas que
    # ele contorna. Olhar so o destino deixa a rota escapar por um vao que nao
    # existe no terreno -- passar entre duas celulas intransponiveis -- e cruzar
    # a drenagem sem pousar em nenhuma celula de curso d'agua, de modo que o
    # fator de vau nao e cobrado e a travessia nao entra na lista conferida em
    # campo. Por isso cada diagonal carrega, alem do passo, as duas celulas
    # ortogonais que ela contorna.
    neighbors = [
        (-1, 0, 1.0, ()),
        (1, 0, 1.0, ()),
        (0, -1, 1.0, ()),
        (0, 1, 1.0, ()),
        (-1, -1, np.sqrt(2.0), ((-1, 0), (0, -1))),
        (-1, 1, np.sqrt(2.0), ((-1, 0), (0, 1))),
        (1, -1, np.sqrt(2.0), ((1, 0), (0, -1))),
        (1, 1, np.sqrt(2.0), ((1, 0), (0, 1))),
    ]

    expandidas = 0
    total_celulas = max(1, int(np.isfinite(cost_array).sum()))
    while heap:
        _, current_dist, index = heapq.heappop(heap)
        if visited[index]:
            continue
        visited[index] = True
        expandidas += 1
        # Uma cena grande pode levar minutos por trecho. Sem isto o usuario
        # fica com o QGIS preso e o botao de cancelar sem efeito.
        if feedback is not None and expandidas % 20000 == 0:
            if feedback.isCanceled():
                raise _cancelado(t("msg_cancelado_rota"))
            if progress_range is not None:
                inicio, fim = progress_range
                fracao = min(1.0, expandidas / float(total_celulas))
                feedback.setProgress(inicio + (fim - inicio) * fracao)
        if index == end_index:
            break
        row = index // cols
        col = index % cols
        current_cost = cost_array[row, col]
        for d_row, d_col, step_length, corners in neighbors:
            next_row = row + d_row
            next_col = col + d_col
            if next_row < 0 or next_row >= rows or next_col < 0 or next_col >= cols:
                continue
            next_cost = cost_array[next_row, next_col]
            if not np.isfinite(next_cost):
                continue
            next_index = next_row * cols + next_col
            if visited[next_index]:
                continue
            # Uma celula de canto fora do recorte nao e barreira: e terreno que
            # a janela de busca nao cobre, e bloquear por causa dela impediria
            # a rota de acompanhar a borda do recorte.
            corner_block = False
            corner_factor = 1.0
            for c_row, c_col in corners:
                corner_r = row + c_row
                corner_c = col + c_col
                if not (0 <= corner_r < rows and 0 <= corner_c < cols):
                    continue
                if not np.isfinite(cost_array[corner_r, corner_c]):
                    corner_block = True
                    break
                if crossing_factor is not None:
                    corner_factor = max(corner_factor,
                                        float(crossing_factor[corner_r, corner_c]))
            if corner_block:
                continue
            if anisotropic:
                delta_z = float(elevation[next_row, next_col] - elevation[row, col])
                if not np.isfinite(delta_z):
                    continue
                horizontal_m = step_length * float(pixel_size_m)
                move_cost = tobler_hours(delta_z, horizontal_m) * (
                    (current_cost + next_cost) / 2.0)
                if not np.isfinite(move_cost):
                    continue
            else:
                move_cost = ((current_cost + next_cost) / 2.0) * step_length
            # O canto contornado tambem se paga. Sem isto, atravessar a drenagem
            # na diagonal sai de graca e o otimizador aprende exatamente isso:
            # o fator de vau so incide em quem pousa na celula do curso d'agua.
            if crossing_factor is not None and corner_factor > 1.0:
                passo = max(float(crossing_factor[row, col]),
                            float(crossing_factor[next_row, next_col]))
                if corner_factor > passo:
                    move_cost = move_cost * (corner_factor / max(passo, 1e-12))
            candidate_dist = current_dist + move_cost
            if candidate_dist < dist[next_index]:
                dist[next_index] = candidate_dist
                previous[next_index] = index
                priority = candidate_dist + heuristic(next_row, next_col)
                heapq.heappush(heap, (priority, candidate_dist, next_index))

    if not np.isfinite(dist[end_index]):
        # Antes de devolver o beco sem saida, vale saber se ele e um beco de
        # verdade. Se os dois lados so se ligam pelo VERTICE de duas celulas
        # intransponiveis, o diagnostico e outro e a saida tambem: nao adianta
        # elevar a declividade maxima, o que falta e largura. Medido no caso do
        # Parque das Carnaubas, da bateria: a rota que a 1.2.0 devolvia dependia
        # de um unico contato pelo canto -- descrevia uma travessia que nao
        # existe no terreno.
        if _liga_apenas_pelo_canto(cost_array, start_rc, end_rc):
            raise _erro(t("msg_contato_vertice_trecho"))
        raise _erro(t("msg_sem_caminho", avoid=_rotulo("alg_consavoid"), penalise=_rotulo("alg_conspen")))

    path = []
    index = end_index
    while index != -1:
        path.append((index // cols, index % cols))
        if index == start_index:
            break
        index = previous[index]
    path.reverse()
    return path, float(dist[end_index])


def multi_leg_route(cost_array, waypoints_rc, elevation=None, pixel_size_m=None,
                    anisotropic=False, optimise_order=False, feedback=None,
                    crossing_factor=None, return_order=False):
    """Rota otima passando por uma sequencia de pontos, na ordem dada.

    Uma travessia raramente e um par origem-destino. "Subir o Marins, depois o
    Marinzinho, depois o Itaguare e descer" sao quatro objetivos encadeados, e
    pedir isso a um algoritmo de menor custo entre dois pontos da a resposta
    errada: ele contorna os cumes, porque o cume e exatamente o lugar caro.

    Cada trecho e resolvido pelo mesmo A* de sempre, e o resultado e a
    concatenacao. Isso e otimo *dada a ordem*: o caminho de menor custo que
    visita os pontos naquela sequencia. Nao e o mesmo que o melhor circuito
    possivel -- para isso existe `optimise_order`.

    Devolve (celulas, custo_total, custos_por_trecho), e a sequencia de pontos
    efetivamente usada quando return_order=True.
    """
    if len(waypoints_rc) < 2:
        raise ValueError(t("msg_rota_poucos_pontos"))

    if optimise_order and len(waypoints_rc) > 3:
        waypoints_rc = optimise_waypoint_order(
            cost_array, waypoints_rc, elevation, pixel_size_m, anisotropic, feedback,
            crossing_factor=crossing_factor)

    cells, leg_costs = [], []
    for index in range(len(waypoints_rc) - 1):
        start, end = waypoints_rc[index], waypoints_rc[index + 1]
        if tuple(start) == tuple(end):
            raise _erro(t("msg_mesma_celula_trecho", a=index + 1, b=index + 2))
        passo = 100.0 / max(1, len(waypoints_rc) - 1)
        leg, cost = least_cost_path(cost_array, tuple(start), tuple(end),
                                    elevation=elevation, pixel_size_m=pixel_size_m,
                                    crossing_factor=crossing_factor,
                                    anisotropic=anisotropic, feedback=feedback,
                                    progress_range=(index * passo, (index + 1) * passo))
        leg_costs.append(float(cost))
        # o primeiro ponto de cada trecho repete o ultimo do anterior
        cells.extend(leg if index == 0 else leg[1:])
        if feedback:
            feedback.pushInfo(t("msg_trecho", i=index + 1, n=len(waypoints_rc) - 1, cells=len(leg), cost=cost))
    if return_order:
        return cells, float(sum(leg_costs)), leg_costs, list(waypoints_rc)
    return cells, float(sum(leg_costs)), leg_costs


def optimise_waypoint_order(cost_array, waypoints_rc, elevation=None,
                            pixel_size_m=None, anisotropic=False, feedback=None,
                            crossing_factor=None):
    """Melhor ordem de visita, mantendo fixos o primeiro e o ultimo ponto.

    Held-Karp sobre a matriz de custos entre pares. O custo e assimetrico no
    modelo de Tobler -- subir e descer nao custam o mesmo -- entao a matriz nao
    e simetrica e o problema e um caminho hamiltoniano dirigido, resolvido
    exatamente. O que limita o numero de pontos intermediarios nao e o custo
    do DP -- com oito pontos sao ~16 mil operacoes, microssegundos -- e sim a
    montagem da matriz, que exige da ordem de n^2 execucoes completas do A*.
    """
    middle = list(range(1, len(waypoints_rc) - 1))
    if len(middle) > MAX_OPTIMISED_WAYPOINTS:
        raise ValueError(t("msg_otimizacao_max", max=MAX_OPTIMISED_WAYPOINTS, n=len(middle)))

    n = len(waypoints_rc)
    if feedback:
        feedback.pushInfo(t("msg_otimizando", n=len(middle), legs=n * (n - 1)))

    # O DP so le os pares que saem da origem, os que ligam pontos
    # intermediarios e os que chegam ao destino: calcular (i, 0) ou (last, j)
    # seria jogar fora cerca de um quinto das buscas.
    necessarios = [(i, j) for i in range(n) for j in range(n)
                   if i != j and j != 0 and i != n - 1]
    pair = {}
    for contagem, (i, j) in enumerate(necessarios, start=1):
        if feedback is not None:
            if feedback.isCanceled():
                raise _cancelado(t("msg_cancelado_ordem"))
            feedback.setProgress(100.0 * contagem / len(necessarios))
        _, cost = least_cost_path(cost_array, tuple(waypoints_rc[i]),
                                  tuple(waypoints_rc[j]), elevation=elevation,
                                  pixel_size_m=pixel_size_m, anisotropic=anisotropic,
                                  feedback=feedback, crossing_factor=crossing_factor)
        pair[(i, j)] = float(cost)

    last = n - 1
    size = len(middle)
    best = {}
    for position, node in enumerate(middle):
        best[(1 << position, position)] = (pair[(0, node)], None)
    for mask in range(1 << size):
        for position in range(size):
            if not mask & (1 << position):
                continue
            state = best.get((mask, position))
            if state is None:
                continue
            for nxt in range(size):
                if mask & (1 << nxt):
                    continue
                total = state[0] + pair[(middle[position], middle[nxt])]
                key = (mask | (1 << nxt), nxt)
                if key not in best or total < best[key][0]:
                    best[key] = (total, (mask, position))

    full = (1 << size) - 1
    end_state = min(((best[(full, p)][0] + pair[(middle[p], last)], p)
                     for p in range(size) if (full, p) in best), default=None)
    if end_state is None:
        return waypoints_rc
    order, mask, position = [], full, end_state[1]
    while position is not None:
        order.append(middle[position])
        previous = best[(mask, position)][1]
        if previous is None:
            break
        mask, position = previous
    order.reverse()

    ordered = [waypoints_rc[0]] + [waypoints_rc[i] for i in order] + [waypoints_rc[last]]
    if feedback:
        original = sum(pair[(i, i + 1)] for i in range(n - 1))
        feedback.pushInfo(t("msg_ordem_custos", given=original, best=end_state[0],
                            change=100.0 * (end_state[0] / original - 1.0)))
    return ordered


# Os oito passos da grade, com as duas celulas de canto de cada diagonal --
# o mesmo modelo de least_cost_path, vetorizado.
_PASSOS_DA_GRADE = (
    (-1, 0, 1.0, False), (1, 0, 1.0, False), (0, -1, 1.0, False), (0, 1, 1.0, False),
    (-1, -1, np.sqrt(2.0), True), (-1, 1, np.sqrt(2.0), True),
    (1, -1, np.sqrt(2.0), True), (1, 1, np.sqrt(2.0), True),
)


def route_graph_edges(cost_array, elevation=None, pixel_size_m=None,
                      anisotropic=False, crossing_factor=None):
    """Arestas (origem, destino, custo) da grade, com o modelo de passo do A*.

    Mesmas regras de least_cost_path: celula de custo infinito e intransponivel;
    a diagonal exige as duas celulas de canto transponiveis e paga o fator de
    vau do canto; no modelo de Tobler o custo e o tempo do passo, que depende do
    sentido. Os indices sao os da grade achatada (linha * colunas + coluna).
    """
    rows, cols = cost_array.shape
    custo = np.asarray(cost_array, dtype=np.float64)
    finito = np.isfinite(custo)
    fator = None
    if crossing_factor is not None:
        fator = np.asarray(crossing_factor)
        if fator.dtype == bool:
            fator = np.where(fator, CONSTRAINT_PENALTY_FACTOR, 1.0)
        fator = fator.astype(np.float64)
    if anisotropic:
        if elevation is None or pixel_size_m is None:
            raise ValueError("The anisotropic model needs the elevation and the pixel size.")
        altitude = np.asarray(elevation)
    indice = np.arange(rows * cols, dtype=np.int64).reshape(rows, cols)
    origens, destinos, pesos = [], [], []
    for d_row, d_col, passo, diagonal in _PASSOS_DA_GRADE:
        r0, r1 = max(0, -d_row), rows - max(0, d_row)
        c0, c1 = max(0, -d_col), cols - max(0, d_col)
        if r1 <= r0 or c1 <= c0:
            continue
        a = (slice(r0, r1), slice(c0, c1))
        b = (slice(r0 + d_row, r1 + d_row), slice(c0 + d_col, c1 + d_col))
        ok = finito[a] & finito[b]
        if diagonal:
            # Com o destino dentro da grade, os dois cantos tambem estao.
            k1 = (slice(r0 + d_row, r1 + d_row), slice(c0, c1))
            k2 = (slice(r0, r1), slice(c0 + d_col, c1 + d_col))
            ok &= finito[k1] & finito[k2]
        media = (custo[a][ok] + custo[b][ok]) / 2.0
        if anisotropic:
            dz = (altitude[b] - altitude[a])[ok].astype(np.float64)
            horizontal = passo * float(pixel_size_m)
            velocidade = TOBLER_MAX_SPEED_KMH * np.exp(
                -TOBLER_DECAY * np.abs(dz / horizontal + TOBLER_OPTIMUM_SLOPE))
            with np.errstate(divide="ignore", invalid="ignore"):
                horas = np.where(velocidade > 1e-6, (horizontal / 1000.0) / velocidade, np.inf)
            peso = horas * media
        else:
            peso = media * passo
        if fator is not None and diagonal:
            canto = np.maximum(np.maximum(fator[k1][ok], fator[k2][ok]), 1.0)
            no_passo = np.maximum(fator[a][ok], fator[b][ok])
            peso = np.where(canto > no_passo, peso * (canto / np.maximum(no_passo, 1e-12)), peso)
        fica = np.isfinite(peso)
        origens.append(indice[a][ok][fica])
        destinos.append(indice[b][ok][fica])
        pesos.append(peso[fica])
    return np.concatenate(origens), np.concatenate(destinos), np.concatenate(pesos)


def cost_distances(edges, n_cells, source, reverse=False):
    """Custo minimo de `source` a todas as celulas (ou de todas ate ela, com reverse).

    Dijkstra completo -- nao para no destino. Com SciPy usa csgraph (C); sem
    ele, um Dijkstra em Python sobre a mesma lista de arestas.
    """
    origens, destinos, pesos = edges
    if reverse:
        origens, destinos = destinos, origens
    if morphology.has_scipy():
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import dijkstra

        grafo = csr_matrix((pesos, (origens, destinos)), shape=(n_cells, n_cells))
        return dijkstra(grafo, directed=True, indices=int(source))
    ordem = np.argsort(origens, kind="stable")
    inicio = np.searchsorted(origens[ordem], np.arange(n_cells + 1)).tolist()
    vizinho = destinos[ordem].tolist()
    custo = pesos[ordem].tolist()
    dist = [float("inf")] * n_cells
    dist[int(source)] = 0.0
    feito = [False] * n_cells
    fila = [(0.0, int(source))]
    while fila:
        d, no = heapq.heappop(fila)
        if feito[no]:
            continue
        feito[no] = True
        for k in range(inicio[no], inicio[no + 1]):
            outro = vizinho[k]
            candidato = d + custo[k]
            if candidato < dist[outro]:
                dist[outro] = candidato
                heapq.heappush(fila, (candidato, outro))
    return np.asarray(dist)


def near_optimal_corridor(edges, shape, legs, slack):
    """Celulas por onde passa algum caminho ate `slack` (fracao) mais caro.

    Para cada trecho (s, e): custo(s->x) + custo(x->e) <= (1 + slack) * otimo.
    Devolve (mascara, folga relativa por celula), com a folga minima entre os
    trechos. O conjunto e conexo -- e uniao de caminhos de s a e --, e a rota
    otima esta sempre dentro dele.
    """
    n_cells = int(shape[0] * shape[1])
    folga = np.full(n_cells, np.inf)
    for inicio, fim in legs:
        de_inicio = cost_distances(edges, n_cells, inicio)
        ate_fim = cost_distances(edges, n_cells, fim, reverse=True)
        otimo = de_inicio[fim]
        if not np.isfinite(otimo) or otimo <= 0:
            continue
        with np.errstate(invalid="ignore"):
            folga = np.minimum(folga, (de_inicio + ate_fim) / otimo - 1.0)
    folga = folga.reshape(shape)
    return folga <= slack + 1e-9, folga


def save_slack_raster(slack_pct, transform, proj, output_path, feedback=None):
    """Grava a folga (%) de cada celula sobre a rota otima. -9999 = sem caminho."""
    base_path, _ = os.path.splitext(output_path)
    caminho = f"{base_path}_folga.tif"
    driver = gdal.GetDriverByName("GTiff")
    if os.path.exists(caminho):
        try:
            driver.Delete(caminho)
        except RuntimeError:
            caminho = available_output_path(caminho)
    rows, cols = slack_pct.shape
    dataset = driver.Create(caminho, cols, rows, 1, gdal.GDT_Float32, options=["COMPRESS=LZW"])
    if dataset is None:
        raise _erro(t("msg_folga_falhou"))
    dataset.SetGeoTransform(transform)
    if proj:
        dataset.SetProjection(proj)
    banda = dataset.GetRasterBand(1)
    banda.SetNoDataValue(-9999.0)
    banda.WriteArray(np.where(np.isfinite(slack_pct), slack_pct, -9999.0).astype(np.float32))
    banda.FlushCache()
    dataset = None
    return caminho


def save_access_route(
    score_array,
    transform,
    proj,
    start_path,
    end_path,
    output_path,
    buffer_m,
    margin_m,
    feedback=None,
    elevation_array=None,
    output_crs=None,
    log_path=None,
    cost_model=ROUTE_COST_INVERSE,
    contrast=DEFAULT_ROUTE_CONTRAST,
    penalty_mask=None,
    via_path=None,
    optimise_order=False,
    stream_mask=None,
    stream_area=None,
    stream_class=None,
    stream_cell_m=None,
    field_speed_kmh=FIELD_SURVEY_SPEED_KMH,
    alternatives_pct=0.0,
    slope_array=None,
    max_slope=None,
    lake_mask=None,
    free_score=None,
):
    """Generate least-cost route and metric corridor files.

    Inputs are an adequability raster array in the prepared working grid,
    GeoTransform/projection, point files, output base path, buffer width and
    search margin in meters. NaN cells are blocked. The per-cell cost depends on
    the chosen model (see build_route_cost). Route and corridor are written as GeoPackage
    files; corridor buffering is done in a metric CRS. Raises clear errors for
    invalid buffer/margin, unreachable endpoints or impossible paths.
    """
    if buffer_m <= 0:
        raise _erro(t("msg_corredor_zero"))
    if margin_m <= 0:
        raise _erro(t("msg_margem_zero"))

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    start_xy = transform_point_to_raster(start_path, proj)
    end_xy = transform_point_to_raster(end_path, proj)
    via_xy = transform_points_to_raster(via_path, proj) if via_path else []

    valid_mask = np.isfinite(score_array)
    sequence = []
    rows_total, cols_total = score_array.shape
    labels = ([t("msg_rotulo_inicial")] + [t("msg_rotulo_intermediario", n=i + 1) for i in range(len(via_xy))]
              + [t("msg_rotulo_final")])
    deslocamentos = []
    for label, (x, y) in zip(labels, [start_xy] + via_xy + [end_xy]):
        row, col = world_to_pixel(transform, x, y)
        if not (0 <= row < rows_total and 0 <= col < cols_total):
            # Dizer que o ponto esta FORA do raster, e nao "sem celula valida
            # proxima": era a mensagem que quem digitava X, Y no CRS errado via.
            x0, y0 = pixel_to_world(transform, 0, 0)
            x1, y1 = pixel_to_world(transform, rows_total - 1, cols_total - 1)
            raise _erro(t(
                "msg_ponto_fora_mde", label=label, x=_coord(x), y=_coord(y), x0=_coord(min(x0, x1)),
                x1=_coord(max(x0, x1)), y0=_coord(min(y0, y1)), y1=_coord(max(y0, y1))))
        celula = nearest_valid_cell(valid_mask, row, col)
        sequence.append(celula)
        if celula != (row, col):
            # nearest_valid_cell troca o ponto pedido pela celula viavel mais
            # proxima dentro de NEAREST_VALID_CELL_RADIUS celulas e ate aqui
            # nao dizia nada -- nem ao feedback, nem ao log. Em metros o
            # deslocamento nao tem teto: e 30 x o tamanho do pixel.
            x_efetivo, y_efetivo = pixel_to_world(transform, celula[0], celula[1])
            distancia = float(np.hypot(x_efetivo - x, y_efetivo - y))
            deslocamentos.append(dict(
                ponto=label, pedido=[float(x), float(y)],
                usado=[x_efetivo, y_efetivo], deslocamento_m=distancia))
            texto = t("msg_ponto_deslocado", label=label, distance=distancia, x=_coord(x_efetivo),
                      y=_coord(y_efetivo))
            if feedback:
                if distancia > NEAREST_VALID_CELL_WARN_M:
                    feedback.pushWarning(texto)
                else:
                    feedback.pushInfo(texto)
    if deslocamentos:
        append_diagnostic_log(log_path, "pontos_deslocados", pontos=deslocamentos,
                              limite_de_aviso_m=NEAREST_VALID_CELL_WARN_M)
    start_row, start_col = sequence[0]
    end_row, end_col = sequence[-1]

    if via_xy and feedback:
        feedback.pushInfo(t("msg_rota_destinos", n=len(via_xy), legs=len(sequence) - 1))

    margin_pixels = meters_to_pixels(transform, score_array.shape, proj, margin_m)
    rows_used = [r for r, _ in sequence]
    cols_used = [c for _, c in sequence]
    row_min = max(0, min(rows_used) - margin_pixels)
    row_max = min(score_array.shape[0], max(rows_used) + margin_pixels + 1)
    col_min = max(0, min(cols_used) - margin_pixels)
    col_max = min(score_array.shape[1], max(cols_used) + margin_pixels + 1)

    score_crop = score_array[row_min:row_max, col_min:col_max]
    if score_crop.size > MAX_ROUTE_CROP_CELLS:
        raise _erro(t("msg_area_busca_grande"))
    penalty_crop = None
    if penalty_mask is not None:
        penalty_crop = penalty_mask[row_min:row_max, col_min:col_max]
    cost_crop = build_route_cost(
        score_crop, cost_model, contrast, penalty_crop, feedback).astype(np.float32)
    finite_costs = cost_crop[np.isfinite(cost_crop)]
    append_diagnostic_log(
        log_path,
        "superficie_custo_rota",
        metodo=(
            f"tempo de Tobler x retardo = 1 + {TERRAIN_SLOWDOWN_MAX:.1f} * (1 - adequabilidade)"
            if cost_model == ROUTE_COST_TOBLER
            else f"cost = exp({contrast:.1f} * (1 - adequabilidade))"
            if cost_model == ROUTE_COST_EXPONENTIAL
            else f"cost = 1 / (adequabilidade + {ROUTE_COST_EPSILON})"),
        modelo_de_custo=cost_model_name(cost_model),
        grandeza_do_array=("fator de retardo adimensional (o tempo sai do passo a passo)"
                           if cost_model == ROUTE_COST_TOBLER else "custo por celula"),
        contraste_k=(float(contrast) if cost_model == ROUTE_COST_EXPONENTIAL else None),
        contraste_dinamico=(float(np.nanmax(finite_costs) / max(float(np.nanmin(finite_costs)), 1e-9))
                            if finite_costs.size else None),
        restricoes_encarecidas=bool(penalty_crop is not None and penalty_crop.any()),
        recorte_shape=list(cost_crop.shape),
        custo_min=float(np.nanmin(finite_costs)) if finite_costs.size else None,
        custo_max=float(np.nanmax(finite_costs)) if finite_costs.size else None,
        custo_medio=float(np.nanmean(finite_costs)) if finite_costs.size else None,
        celulas_bloqueadas=int(np.sum(~np.isfinite(cost_crop))),
        celulas_navegaveis=int(finite_costs.size),
    )

    if feedback:
        feedback.pushInfo(t("msg_recorte", cols=cost_crop.shape[1], rows=cost_crop.shape[0], margin=margin_m))

    anisotropic = cost_model == ROUTE_COST_TOBLER
    elevation_crop = None
    pixel_size_m = None
    if anisotropic:
        if elevation_array is None:
            raise _erro(t("msg_tobler_sem_mde"))
        elevation_crop = elevation_array[row_min:row_max, col_min:col_max]
        pixel_size_m = float(np.sqrt(max(estimate_pixel_area_m2(
            transform, score_array.shape, proj), 1e-9)))

    local_sequence = [(r - row_min, c - col_min) for r, c in sequence]
    slope_crop = (slope_array[row_min:row_max, col_min:col_max]
                  if slope_array is not None else None)
    check_route_connectivity(cost_crop, local_sequence, slope_crop, penalty_crop,
                             max_slope, pixel_size_m or abs(float(transform[1])), log_path)
    path_cells, accumulated_cost, leg_costs, ordem = multi_leg_route(
        cost_crop, local_sequence, elevation=elevation_crop,
        pixel_size_m=pixel_size_m, anisotropic=anisotropic,
        optimise_order=optimise_order, feedback=feedback,
        crossing_factor=penalty_crop, return_order=True)
    if len(path_cells) < 2:
        raise _erro(t("msg_mesma_celula"))
    if free_score is not None and slope_crop is not None and max_slope:
        check_slope_detour(
            cost_crop, free_score[row_min:row_max, col_min:col_max], ordem, path_cells, slope_crop,
            max_slope, cost_model, contrast, penalty_crop, elevation_crop,
            pixel_size_m or float(np.sqrt(max(estimate_pixel_area_m2(transform, score_array.shape, proj), 1e-9))),
            anisotropic, feedback, log_path)
    coordinates = [pixel_to_world(transform, row + row_min, col + col_min) for row, col in path_cells]
    if lake_mask is not None:
        no_lago = sum(1 for row, col in path_cells if lake_mask[row + row_min, col + col_min])
        if no_lago and feedback:
            feedback.pushWarning(t("msg_rota_lago", n=no_lago, option=_rotulo("alg_streams")))
    line = ogr.Geometry(ogr.wkbLineString)
    for x, y in coordinates:
        line.AddPoint_2D(float(x), float(y))
    route_attributes = {
        "tipo": "rota_principal",
        "custo": float(accumulated_cost),
        "vertices": len(coordinates),
        "trechos": len(leg_costs),
    }
    tempo_tobler = None
    if anisotropic:
        # O custo acumulado tem unidade de horas, mas inclui o retardo por terreno
        # e os vaus, que sao preferencia e nao tempo: a duracao e o Tobler puro
        # ao longo da rota escolhida (ver tobler_hours_along). O custo continua
        # no atributo "custo".
        tempo_tobler = tobler_hours_along(path_cells, elevation_crop, pixel_size_m)
        route_attributes["tempo_h"] = float(tempo_tobler)
        route_attributes["tempo_hms"] = format_hours(tempo_tobler)
        # A duracao de Tobler e otimista para trabalho de campo por um fator de
        # 1,7 a 3,1, medido contra 65 km de trajetos de levantamento com marcacao
        # de tempo. Como multiplicar a velocidade maxima por uma constante divide
        # todos os custos pela mesma constante, a ROTA nao muda -- so a duracao.
        # Por isso a estimativa de campo e uma simples reescala, e sai ao lado da
        # de Tobler em vez de substitui-la: o usuario ve as duas e escolhe.
        fator_campo = TOBLER_MAX_SPEED_KMH / float(field_speed_kmh)
        tempo_campo = float(tempo_tobler) * fator_campo
        route_attributes["tempo_campo_h"] = tempo_campo
        route_attributes["tempo_campo_hms"] = format_hours(tempo_campo)
        route_attributes["velocidade_campo_kmh"] = float(field_speed_kmh)
        if feedback:
            feedback.pushInfo(t("msg_duracao", tobler=float(tempo_tobler), max_speed=TOBLER_MAX_SPEED_KMH,
                                field=tempo_campo, field_speed=float(field_speed_kmh)))
    if elevation_array is not None:
        route_altitudes = [
            float(elevation_array[row + row_min, col + col_min])
            for row, col in path_cells
            if np.isfinite(elevation_array[row + row_min, col + col_min])
        ]
        if route_altitudes:
            route_attributes.update(
                {
                    "alt_ini_m": route_altitudes[0],
                    "alt_fim_m": route_altitudes[-1],
                    "alt_min_m": min(route_altitudes),
                    "alt_max_m": max(route_altitudes),
                    # Ganho acumulado: soma das subidas ao longo do tracado. Ate a
                    # 1.1.2 este campo trazia max - inicio, que e a amplitude ate o
                    # ponto mais alto, nao o que se sobe caminhando: numa travessia
                    # em sobe-e-desce os dois diferem por quase o dobro. O valor
                    # antigo continua disponivel em desnivel_max_m.
                    "ganho_m": float(sum(max(b - a, 0.0) for a, b
                                         in zip(route_altitudes, route_altitudes[1:]))),
                    "perda_m": float(sum(max(a - b, 0.0) for a, b
                                         in zip(route_altitudes, route_altitudes[1:]))),
                    "desnivel_max_m": max(route_altitudes) - route_altitudes[0],
                }
            )

    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(proj) if proj else raster_srs.ImportFromEPSG(4326)
    raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    crs_wkt = raster_srs.ExportToWkt()
    route = FeatureSet([line], [route_attributes], crs_wkt)

    base_path, _ = os.path.splitext(output_path)
    route_path = f"{base_path}_rota.gpkg"
    corridor_path = f"{base_path}_corredor.gpkg"

    corridor_attributes = {"tipo": "corredor_acesso", "buffer_m": float(buffer_m)}
    try:
        metric_crs = metric_crs_for_raster(transform, score_array.shape, proj)
        metric_route = route.to_crs(metric_crs) if raster_srs.IsGeographic() else route
        route_length_m = metric_route.lengths()[0]
        route.set_column("compr_m", [route_length_m])
        corridor = FeatureSet(metric_route.buffer(buffer_m).geometries, [corridor_attributes], metric_route.crs)
        corridor_area_m2 = corridor.areas()[0] if len(corridor) else None
        if raster_srs.IsGeographic():
            corridor = corridor.to_crs(crs_wkt)
    except Exception:
        route_length_m = float("nan")
        route.set_column("compr_m", [route_length_m])
        corridor = FeatureSet(route.buffer(0).geometries, [corridor_attributes], crs_wkt)
        corridor_area_m2 = None

    target_crs, target_label = output_crs_target(output_crs)
    if target_crs:
        route = route.to_crs(target_crs)
        corridor = corridor.to_crs(target_crs)
        if feedback:
            feedback.pushInfo(t("msg_rota_reprojetada", crs=target_label))

    for nome, path in (("rota", route_path), ("corredor", corridor_path)):
        alternativo = _saida_gpkg_utilizavel(path, nome, feedback)
        if alternativo != path:
            if nome == "rota":
                route_path = alternativo
            else:
                corridor_path = alternativo

    route.to_file(route_path, driver="GPKG", layer_name="rota")
    corridor.to_file(corridor_path, driver="GPKG", layer_name="corredor")

    # Travessias de cursos d'agua: um ponto por cruzamento, com o tamanho do
    # curso e a classe. E a parte que protege o usuario: a rota pode cruzar a
    # drenagem, mas cada cruzamento fica listado para ser conferido em campo.
    crossings_path = None
    crossings = []
    if stream_mask is not None and stream_area is not None and stream_class is not None:
        global_cells = [(row + row_min, col + col_min) for row, col in path_cells]
        crossings = merge_stream_contacts(
            detect_stream_crossings(global_cells, stream_mask, stream_area, stream_class),
            float(pixel_size_m or abs(transform[1])), stream_cell_m=stream_cell_m)
        if crossings:
            labels = _ford_labels()
            geometries, attributes = [], []
            for number, item in enumerate(crossings, start=1):
                x, y = pixel_to_world(transform, *item["entrada"])
                point = ogr.Geometry(ogr.wkbPoint)
                point.AddPoint_2D(float(x), float(y))
                geometries.append(point)
                k = min(item["classe"], len(labels) - 1)
                attributes.append({
                    "n": number,
                    "tipo": t("msg_tipo_travessia" if item["tipo"] == "travessia" else "msg_tipo_junto"),
                    "bacia_km2": round(float(item["area_km2"]), 3),
                    "classe": labels[k],
                    "extensao_m": round(float(item["extensao_m"]), 1),
                    "aviso": t("msg_travessia_aviso_campo"),
                })
            crossings_set = FeatureSet(geometries, attributes, crs_wkt)
            if target_crs:
                crossings_set = crossings_set.to_crs(target_crs)
            crossings_path = _saida_gpkg_utilizavel(
                f"{base_path}_travessias.gpkg", "travessias", feedback)
            crossings_set.to_file(crossings_path, driver="GPKG", layer_name="travessias")
            if feedback:
                travessia = [item["tipo"] == "travessia" for item in crossings]
                junto = [a for a, e_travessia in zip(attributes, travessia) if not e_travessia]
                feedback.pushInfo(t(
                    "msg_travessias_resumo", crossings=sum(travessia), along=len(junto),
                    km=sum(a["extensao_m"] for a in junto) / 1000.0,
                    items=t("msg_sep_itens").join(
                        t("msg_travessia_item" if e_travessia else "msg_junto_item", n=a["n"], kind=a["tipo"],
                          cls=a["classe"], area=a["bacia_km2"], length=a["extensao_m"])
                        for a, e_travessia in zip(attributes, travessia)),
                    path=crossings_path))
        elif feedback:
            feedback.pushInfo(t("msg_sem_travessias"))

    alternatives = None
    if alternatives_pct and alternatives_pct > 0:
        alternatives = _save_alternatives(
            cost_crop, elevation_crop, pixel_size_m, anisotropic, penalty_crop,
            ordem, path_cells, alternatives_pct, transform, proj, row_min, col_min,
            base_path, target_crs, crs_wkt, buffer_m, float(accumulated_cost),
            feedback, log_path)

    if feedback:
        length = route_length_m
        feedback.pushInfo(t("msg_rota_salva", path=route_path))
        feedback.pushInfo(t("msg_corredor_salvo", path=corridor_path))
        if np.isfinite(length):
            feedback.pushInfo(t("msg_comprimento", length=length))
            if anisotropic:
                feedback.pushInfo(t("msg_tempo_tobler", hours=tempo_tobler, hms=format_hours(tempo_tobler),
                                    speed=(length / 1000.0) / max(tempo_tobler, 1e-9)))
    append_diagnostic_log(
        log_path,
        "rota_calculada",
        custo_acumulado=float(accumulated_cost),
        tempo_tobler_h=float(tempo_tobler) if tempo_tobler is not None else None,
        celulas_percorridas=int(len(path_cells)),
        vertices=int(len(coordinates)),
        comprimento_m=float(route_length_m) if np.isfinite(route_length_m) else None,
        buffer_m=float(buffer_m),
        crs_buffer=srs_label(corridor.srs()),
        area_corredor_m2=corridor_area_m2,
        extensao_corredor=corridor.total_bounds(),
        geometrias_corredor=int(len(corridor)),
        travessias=len(crossings),
    )

    return route_path, corridor_path, crossings_path, alternatives


def _save_alternatives(cost_crop, elevation_crop, pixel_size_m, anisotropic, penalty_crop,
                       ordem, path_cells, alternatives_pct, transform, proj, row_min,
                       col_min, base_path, target_crs, crs_wkt, buffer_m, custo_otimo,
                       feedback=None, log_path=None):
    """Corredor de rotas quase otimas: vetor + raster de folga. None se pulado.

    Mostra o que a linha unica esconde: quando ha dois corredores de custo
    quase igual, uma perturbacao minima (outro recorte do MDE, outro pixel)
    troca um pelo outro. Medido na trilha da Reserva Chico Nunes: 3,9 km e
    6,1 km com 5h10 e 5h13 -- 1% de diferenca de custo.
    """
    if cost_crop.size > MAX_ALTERNATIVES_CELLS:
        if feedback:
            feedback.pushWarning(t("msg_alternativas_grande", cells=int(cost_crop.size), limit=MAX_ALTERNATIVES_CELLS))
        return None
    slack = float(alternatives_pct) / 100.0
    cols = cost_crop.shape[1]
    arestas = route_graph_edges(cost_crop, elevation_crop, pixel_size_m, anisotropic,
                                crossing_factor=penalty_crop)
    trechos = [(int(a[0]) * cols + int(a[1]), int(b[0]) * cols + int(b[1]))
               for a, b in zip(ordem[:-1], ordem[1:])]
    mascara, folga = near_optimal_corridor(arestas, cost_crop.shape, trechos, slack)

    px = abs(float(transform[1]))
    py = abs(float(transform[5]))
    na_rota = np.zeros(cost_crop.shape, dtype=bool)
    linhas, colunas = zip(*path_cells)
    na_rota[list(linhas), list(colunas)] = True
    afastamento = morphology.distance_transform_edt(~na_rota, sampling=(py, px))
    afastamento_max = float(afastamento[mascara].max()) if mascara.any() else 0.0
    area_ha = float(mascara.sum()) * px * py / 10000.0

    recorte = (float(transform[0]) + col_min * float(transform[1]), float(transform[1]), 0.0,
               float(transform[3]) + row_min * float(transform[5]), 0.0, float(transform[5]))
    poligonos = vectorize_binary_raster(mascara.astype(np.uint8), recorte, proj)
    geometria = None
    for g in poligonos.geometries:
        geometria = g.Clone() if geometria is None else geometria.Union(g)
    if geometria is None:
        return None
    atributos = {"tipo": "corredor_alternativas", "folga_pct": float(alternatives_pct),
                 "area_ha": round(area_ha, 2), "afastamento_max_m": round(afastamento_max, 1),
                 "custo_otimo": float(custo_otimo)}
    conjunto = FeatureSet([geometria], [atributos], crs_wkt)
    if target_crs:
        conjunto = conjunto.to_crs(target_crs)
    caminho_vetor = _saida_gpkg_utilizavel(f"{base_path}_alternativas.gpkg", "alternativas", feedback)
    conjunto.to_file(caminho_vetor, driver="GPKG", layer_name="alternativas")
    # Folga em %, ate o triplo da pedida: mostra tambem os vales que quase entraram.
    folga_pct = np.where(folga <= 3.0 * slack, 100.0 * np.maximum(folga, 0.0), np.nan)
    caminho_raster = save_slack_raster(folga_pct, recorte, proj, base_path + ".tif")

    append_diagnostic_log(log_path, "corredor_alternativas", folga_pct=float(alternatives_pct),
                          celulas=int(mascara.sum()), area_ha=area_ha,
                          afastamento_max_m=afastamento_max,
                          vetor=caminho_vetor, raster=caminho_raster)
    if feedback:
        feedback.pushInfo(t("msg_alternativas_resumo", pct=alternatives_pct, area=area_ha, distance=afastamento_max))
        if afastamento_max > max(4.0 * float(buffer_m), 10.0 * px):
            feedback.pushWarning(t("msg_alternativas_aviso", pct=alternatives_pct, distance=afastamento_max))
    return caminho_vetor, caminho_raster


def _qgs_enum(cls, group, value):
    """Enum de classe do QGIS que funciona no Qt5 e no Qt6.

    No QGIS 4 (Qt6) o acesso solto sai: _qgs_enum(QgsProcessingParameterNumber, "Type", "Double") vira
    QgsProcessingParameterNumber.Type.Double, e o mesmo vale para o Behavior do
    parametro de arquivo. Buscar o grupo com recurso a propria classe atende as
    duas versoes -- e o metadata.txt ja declarava qgisMaximumVersion=4.99, ou
    seja, o plugin prometia QGIS 4 com codigo que estouraria la.
    """
    return getattr(getattr(cls, group, cls), value)


def _flag_avancado():
    """Flag de parametro avancado no QGIS 3.22-3.34 e no 3.36+/4."""
    try:
        from qgis.core import Qgis
        return _qgs_enum(Qgis, "ProcessingParameterFlag", "Advanced")
    except (ImportError, AttributeError):
        try:
            from qgis.core import QgsProcessingParameterDefinition as definicao
        except ImportError:
            return None
        # Por nome: o verificador Qt6 do repositorio de plugins acusa o acesso
        # sem escopo, mesmo neste ramo que so roda no QGIS < 3.36.
        grupo = getattr(definicao, "Flag", None)
        return getattr(grupo, "FlagAdvanced", None) or getattr(definicao, "FlagAdvanced", None)


def _class_labels():
    """Rotulos das classes de transitabilidade no idioma em vigor.

    Eles nao ficam so na tela: vao gravados no proprio GeoTIFF, como nomes de
    categoria (que o QGIS le, pelo arquivo .aux.xml que o driver escreve ao lado)
    e como metadado GDAL, que fica dentro do .tif. Sem isto, um usuario japones
    abria o raster no QGIS e via a legenda em portugues -- e o arquivo
    continuaria assim depois de enviado a outra pessoa.
    """
    try:
        from ..ui import i18n
        idioma = _algorithm_language()
        return {code: i18n.text(idioma, f"class_{code}") for code in range(1, 6)}
    except Exception:
        return dict(CLASS_LABELS)


def _algorithm_language():
    """Idioma dos rotulos do Processing.

    Respeita primeiro a escolha feita na janela do plugin -- alguem que trocou
    para espanhol ali nao espera ver o Processing em ingles -- e so entao o
    idioma do proprio QGIS.
    """
    try:
        from ..ui import i18n
        from qgis.core import QgsSettings
        escolhido = QgsSettings().value("TopoTrail/language", "")
        if escolhido in i18n.LANGUAGE_CODES:
            return escolhido
        return i18n.detect()
    except Exception:
        return "en"


class TopotrailAlgorithm(QgsProcessingAlgorithm):
    INPUT_DEM = "INPUT_DEM"
    INPUT_SLOPE = "INPUT_SLOPE"
    INPUT_CURVH = "INPUT_CURVH"
    INPUT_CURVV = "INPUT_CURVV"
    OUTPUT_CRS = "OUTPUT_CRS"
    ALT_MIN = "ALT_MIN"
    ALT_MAX = "ALT_MAX"
    DERIVE_FROM_DEM = "DERIVE_FROM_DEM"
    VERTICAL_UNIT = "VERTICAL_UNIT"
    SLOPE_UNIT = "SLOPE_UNIT"
    STREAMS_FROM_DEM = "STREAMS_FROM_DEM"
    STREAM_MIN_BASIN_KM2 = "STREAM_MIN_BASIN_KM2"
    STREAM_FORD_MAX_KM2 = "STREAM_FORD_MAX_KM2"
    CONSTRAINT_LAYER = "CONSTRAINT_LAYER"
    CONSTRAINT_BUFFER_M = "CONSTRAINT_BUFFER_M"
    CONSTRAINT_MODE = "CONSTRAINT_MODE"
    ROUTE_COST_MODEL = "ROUTE_COST_MODEL"
    ROUTE_CONTRAST = "ROUTE_CONTRAST"
    TRANSITABILITY_BREAKS = "TRANSITABILITY_BREAKS"
    EXTRA_CRITERION_LAYER = "EXTRA_CRITERION_LAYER"
    EXTRA_CRITERION_WEIGHT = "EXTRA_CRITERION_WEIGHT"
    EXTRA_CRITERION_DIRECTION = "EXTRA_CRITERION_DIRECTION"
    SLOPE_MAX = "SLOPE_MAX"
    SLOPE_SCORE_MAX = "SLOPE_SCORE_MAX"
    WEIGHT_ALT = "WEIGHT_ALT"
    WEIGHT_SLOPE = "WEIGHT_SLOPE"
    WEIGHT_CURVH = "WEIGHT_CURVH"
    WEIGHT_CURVV = "WEIGHT_CURVV"
    WEIGHT_WETNESS = "WEIGHT_WETNESS"
    WEIGHT_ROUGHNESS = "WEIGHT_ROUGHNESS"
    MIN_PATCH_AREA_HA = "MIN_PATCH_AREA_HA"
    THRESHOLD = "THRESHOLD"
    AUTO_PERCENTILE = "AUTO_PERCENTILE"
    ALTITUDE_BAND_THRESHOLD = "ALTITUDE_BAND_THRESHOLD"
    ALTITUDE_BAND_SIZE_M = "ALTITUDE_BAND_SIZE_M"
    WALKABILITY_ZONES = "WALKABILITY_ZONES"
    START_POINT_FILE = "START_POINT_FILE"
    END_POINT_FILE = "END_POINT_FILE"
    VIA_POINTS_FILE = "VIA_POINTS_FILE"
    OPTIMISE_ORDER = "OPTIMISE_ORDER"
    ROUTE_BUFFER_M = "ROUTE_BUFFER_M"
    ROUTE_MARGIN_M = "ROUTE_MARGIN_M"
    GENERATE_ZONES = "GENERATE_ZONES"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    OUTPUT_FILE = "OUTPUT_FILE"
    OUTPUT_VECTOR = "OUTPUT_VECTOR"
    OUTPUT_SCORE_RASTER = "OUTPUT_SCORE_RASTER"
    OUTPUT_RISK_RASTER = "OUTPUT_RISK_RASTER"
    OUTPUT_TRANSITABILITY = "OUTPUT_TRANSITABILITY"
    OUTPUT_ROUTE = "OUTPUT_ROUTE"
    OUTPUT_CORRIDOR = "OUTPUT_CORRIDOR"
    OUTPUT_CROSSINGS = "OUTPUT_CROSSINGS"
    OUTPUT_DEBUG_LOG = "OUTPUT_DEBUG_LOG"
    CURVH_LIMIT = "CURVH_LIMIT"
    CURVV_LIMIT = "CURVV_LIMIT"
    WETNESS_LIMIT = "WETNESS_LIMIT"
    ROUGHNESS_LIMIT = "ROUGHNESS_LIMIT"
    FIELD_SPEED_KMH = "FIELD_SPEED_KMH"
    ROUTE_ALTERNATIVES_PCT = "ROUTE_ALTERNATIVES_PCT"
    WORKING_CELL_M = "WORKING_CELL_M"
    OUTPUT_ALTERNATIVES = "OUTPUT_ALTERNATIVES"
    OUTPUT_SLACK = "OUTPUT_SLACK"

    # Recolhidos em "Parametros avancados" no dialogo do Processing: sao ajustes
    # de especialista, com padrao que serve a maioria dos estudos.
    ADVANCED = (
        "INPUT_SLOPE", "INPUT_CURVH", "INPUT_CURVV", "SLOPE_UNIT", "THRESHOLD",
        "AUTO_PERCENTILE", "ALTITUDE_BAND_THRESHOLD", "ALTITUDE_BAND_SIZE_M",
        "WALKABILITY_ZONES", "ROUTE_CONTRAST", "ROUTE_MARGIN_M",
        "STREAM_MIN_BASIN_KM2", "STREAM_FORD_MAX_KM2", "CONSTRAINT_BUFFER_M",
        "EXTRA_CRITERION_WEIGHT", "EXTRA_CRITERION_DIRECTION",
        "TRANSITABILITY_BREAKS", "CURVH_LIMIT", "CURVV_LIMIT", "WETNESS_LIMIT",
        "ROUGHNESS_LIMIT", "FIELD_SPEED_KMH", "WORKING_CELL_M",
    )

    def tr(self, key):
        """Traduz um rotulo do Processing pelo mesmo mecanismo da janela.

        Antes usava QCoreApplication.translate, que depende de arquivos .qm
        compilados com lrelease. Isso obrigava a um passo de build antes de
        empacotar o plugin e punha um binario nao revisavel no repositorio --
        e na pratica nenhum .qm chegou a ser gerado, entao a Caixa de
        Ferramentas ficava em portugues em qualquer idioma. Com o mesmo
        carregador JSON da janela, as duas superficies falam a mesma lingua e
        nao ha nada para compilar.
        """
        try:
            from ..ui import i18n
            return i18n.text(_algorithm_language(), key)
        except Exception:
            return key

    def createInstance(self):
        return TopotrailAlgorithm()

    def name(self):
        return "topotrail"

    def displayName(self):
        return self.tr("alg_name")

    def group(self):
        return self.tr("alg_group")

    def groupId(self):
        return "topotrail"

    def shortHelpString(self):
        return self.tr("alg_help")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.INPUT_DEM, self.tr("alg_dem")))
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.DERIVE_FROM_DEM,
                self.tr("alg_derive"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VERTICAL_UNIT,
                self.tr("alg_vunit"),
                options=[self.tr("alg_metres"), self.tr("alg_feet")],
                defaultValue=VERTICAL_UNIT_METRES,
            )
        )
        # Opcionais desde a 0.6.0: so sao exigidos quando DERIVE_FROM_DEM e
        # desmarcado. Fornece-los da ao usuario controle total sobre o metodo de
        # derivacao, ao custo de ter de garantir unidade, convencao e grade.
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_SLOPE, self.tr("alg_slope"), optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_CURVH, self.tr("alg_curvh"), optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_CURVV, self.tr("alg_curvv"), optional=True))

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALT_MIN,
                self.tr("alg_altmin"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALT_MAX,
                self.tr("alg_altmax"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=2600.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SLOPE_UNIT,
                self.tr("alg_sunit"),
                options=[self.tr("alg_percent"), self.tr("alg_degrees")],
                defaultValue=SLOPE_UNIT_PERCENT,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLOPE_MAX,
                self.tr("alg_slopemax"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                # 85%, e nao os 55% ate a 1.4.1. Em 35 trilhas reais (17 de caminhada,
                # 6 exigentes, 8 alpinas, Copernicus 30 m): 55% ligava 18 -- e so 13 das
                # 17 de caminhada --, 85% liga 33 e todas as de caminhada, com a melhor
                # concordancia; o que fica de fora sao rotas de cabo e via ferrata (Half
                # Dome pede 118%, Triglav 94%), que o padrao nao deve sugerir a um leigo.
                # A 100% ligava uma a mais e havia mais rotas por terreno mais ingreme
                # que o da propria trilha (6 contra 4); a 150%, rota por celula de 140%.
                defaultValue=85.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLOPE_SCORE_MAX,
                self.tr("alg_slopescore"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=50.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.THRESHOLD,
                self.tr("alg_threshold"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=0.0,
                minValue=0.0,
                maxValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.AUTO_PERCENTILE,
                self.tr("alg_percentile"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=75.0,
                minValue=1.0,
                maxValue=99.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_PATCH_AREA_HA,
                self.tr("alg_minarea"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=MIN_PATCH_AREA_AUTO,
                minValue=MIN_PATCH_AREA_AUTO,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALTITUDE_BAND_THRESHOLD,
                self.tr("alg_band"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ALTITUDE_BAND_SIZE_M,
                self.tr("alg_bandsize"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=200.0,
                minValue=50.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.WALKABILITY_ZONES,
                self.tr("alg_walkzones"),
                defaultValue=False,
            )
        )

        for key, label, default in [
            (self.WEIGHT_ALT, "alg_w_alt", 0.0),
            (self.WEIGHT_SLOPE, "alg_w_slope", 1.0),
            (self.WEIGHT_CURVH, "alg_w_curvh", 1.0),
            (self.WEIGHT_CURVV, "alg_w_curvv", 1.0),
            # Criterios novos na 0.6.1. Peso zero por padrao: quem ja usa o
            # plugin nao tem os resultados alterados sem pedir.
            (self.WEIGHT_WETNESS, "alg_w_wet", 0.0),
            (self.WEIGHT_ROUGHNESS, "alg_w_rough", 0.0),
        ]:
            self.addParameter(
                QgsProcessingParameterNumber(
                    key,
                    self.tr(label),
                    _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                    defaultValue=default,
                    minValue=0.0,
                    maxValue=10.0,
                )
            )

        self.addParameter(
            QgsProcessingParameterFile(
                self.START_POINT_FILE,
                self.tr("alg_start"),
                behavior=_qgs_enum(QgsProcessingParameterFile, "Behavior", "File"),
                fileFilter=self.tr("filter_vectors"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.END_POINT_FILE,
                self.tr("alg_end"),
                behavior=_qgs_enum(QgsProcessingParameterFile, "Behavior", "File"),
                fileFilter=self.tr("filter_vectors"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.VIA_POINTS_FILE,
                self.tr("alg_via"),
                behavior=_qgs_enum(QgsProcessingParameterFile, "Behavior", "File"),
                fileFilter=self.tr("filter_vectors"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OPTIMISE_ORDER,
                self.tr("alg_optimise"),
                defaultValue=False,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_BUFFER_M,
                self.tr("alg_corridor"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=100.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_MARGIN_M,
                self.tr("alg_margin"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=5000.0,
                minValue=100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.STREAMS_FROM_DEM,
                self.tr("alg_streams"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STREAM_MIN_BASIN_KM2,
                self.tr("alg_basin"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=1.0,
                minValue=0.01,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STREAM_FORD_MAX_KM2,
                self.tr("alg_ford_max"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=DEFAULT_STREAM_FORD_MAX_KM2,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.CONSTRAINT_LAYER,
                self.tr("alg_conslayer"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CONSTRAINT_BUFFER_M,
                self.tr("alg_consbuffer"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=30.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CONSTRAINT_MODE,
                self.tr("alg_consmode"),
                options=[self.tr("alg_consavoid"), self.tr("alg_conspen")],
                defaultValue=CONSTRAINT_AVOID,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.ROUTE_COST_MODEL,
                self.tr("alg_costmodel"),
                options=[self.tr("alg_costinv"),
                         self.tr("alg_costexp"),
                         self.tr("alg_costtobler")],
                # O padrao acompanha a janela em quatro etapas: tempo de
                # caminhada. Ate a 1.1.2 a caixa de ferramentas do Processing
                # abria no modelo inverso, que a propria documentacao descreve
                # como de contraste insuficiente.
                defaultValue=ROUTE_COST_TOBLER,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_CONTRAST,
                self.tr("alg_contrast"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=DEFAULT_ROUTE_CONTRAST,
                minValue=0.5,
                maxValue=20.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.EXTRA_CRITERION_LAYER,
                self.tr("alg_extralayer"),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EXTRA_CRITERION_WEIGHT,
                self.tr("alg_extraweight"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=0.0, minValue=0.0, maxValue=10.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.EXTRA_CRITERION_DIRECTION,
                self.tr("alg_extradir"),
                options=[self.tr("alg_extralow"),
                         self.tr("alg_extrahigh")],
                defaultValue=CRITERION_LOWER_IS_BETTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TRANSITABILITY_BREAKS,
                self.tr("alg_breaks"),
                defaultValue=", ".join(f"{b:.0f}" for b in DEFAULT_SLOPE_BREAKS),
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_ZONES,
                self.tr("alg_genzones"),
                defaultValue=True,
            )
        )

        # Limites de normalizacao. Zero = automatico, pelo percentil da cena,
        # que e o comportamento de sempre; o valor usado sai no log
        # (limites_normalizacao) e pode ser fixado aqui para que recortes
        # diferentes da mesma area normalizem igual.
        for key, label in [
            (self.CURVH_LIMIT, "alg_lim_curvh"),
            (self.CURVV_LIMIT, "alg_lim_curvv"),
            (self.WETNESS_LIMIT, "alg_lim_wet"),
            (self.ROUGHNESS_LIMIT, "alg_lim_rough"),
        ]:
            self.addParameter(
                QgsProcessingParameterNumber(
                    key, self.tr(label),
                    _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                    defaultValue=0.0, minValue=0.0,
                )
            )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.WORKING_CELL_M,
                self.tr("alg_cell"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=0.0, minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.FIELD_SPEED_KMH,
                self.tr("alg_field_speed"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=FIELD_SURVEY_SPEED_KMH, minValue=0.1, maxValue=TOBLER_MAX_SPEED_KMH,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROUTE_ALTERNATIVES_PCT,
                self.tr("alg_alternatives"),
                _qgs_enum(QgsProcessingParameterNumber, "Type", "Double"),
                defaultValue=0.0, minValue=0.0, maxValue=MAX_ALTERNATIVES_PCT,
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_FILE,
                self.tr("alg_outfile"),
                "Vetores (*.shp *.gpkg *.kml)",
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                self.tr("alg_outfmt"),
                options=["Shapefile", "GeoPackage", "KML"],
                defaultValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterCrs(
                self.OUTPUT_CRS,
                self.tr("alg_outcrs"),
                # initAlgorithm nao pode ler QgsProject.instance(): o singleton
                # so existe na thread principal e, em execucao em background
                # (modelo, lote, script, QGIS Server), ele nao e o projeto do
                # usuario. Medido na auditoria: com um contexto cujo projeto
                # estava em EPSG:4674, o default lido saia 'EPSG:31983' --
                # veio do singleton, nao do contexto. Alem disso o default
                # congelava na instancia registrada no provider, de modo que
                # trocar o CRS do projeto nao atualizava a Caixa de
                # Ferramentas. O CRS do projeto passa a ser lido do context em
                # tempo de execucao, em project_crs_from_context().
                defaultValue=None,
                # Sem projeto aberto nao ha CRS nenhum para o padrao. Sem
                # optional=True o algoritmo recusa o proprio valor padrao
                # quando chamado por script, modelo ou linha de comando.
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_VECTOR, self.tr("alg_o_zones")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_SCORE_RASTER, self.tr("alg_o_score")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_RISK_RASTER, self.tr("alg_o_risk")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_TRANSITABILITY, self.tr("alg_o_transit")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_ROUTE, self.tr("alg_o_route")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_CORRIDOR, self.tr("alg_o_corridor")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_CROSSINGS, self.tr("alg_o_crossings")))
        self.addOutput(QgsProcessingOutputFile(self.OUTPUT_DEBUG_LOG, self.tr("alg_o_log")))
        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT_ALTERNATIVES, self.tr("alg_o_alternatives")))
        self.addOutput(QgsProcessingOutputRasterLayer(self.OUTPUT_SLACK, self.tr("alg_o_slack")))
        avancado = _flag_avancado()
        definicao_de = getattr(self, "parameterDefinition", None)
        for key in (self.ADVANCED if avancado is not None and definicao_de else ()):
            definicao = definicao_de(key)
            if definicao is not None:
                definicao.setFlags(definicao.flags() | avancado)

    def processAlgorithm(self, parameters, context, feedback):
        """Executa a analise e garante a limpeza dos diretorios temporarios.

        O trabalho real fica em _run_algorithm; este invólucro existe para que
        os diretórios criados durante o processamento sejam removidos mesmo
        quando a execucao falha. Sem ele, cada execucao deixava no diretorio
        temporario do sistema uma copia completa do MDE reprojetado e dos
        rasters alinhados.

        As excecoes de GDAL/OGR sao ligadas aqui, e so aqui: ligadas no import
        elas valiam para o processo QGIS inteiro.
        """
        self._temp_dirs = []
        mensagens.definir_idioma(_algorithm_language())
        try:
            with gdal_exceptions_scoped():
                return self._run_algorithm(parameters, context, feedback)
        finally:
            for directory in self._temp_dirs:
                shutil.rmtree(directory, ignore_errors=True)
            self._temp_dirs = []

    def _run_algorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
        slope_layer = self.parameterAsRasterLayer(parameters, self.INPUT_SLOPE, context)
        curvh_layer = self.parameterAsRasterLayer(parameters, self.INPUT_CURVH, context)
        curvv_layer = self.parameterAsRasterLayer(parameters, self.INPUT_CURVV, context)

        # Desde a 0.6.0 apenas o MDE e obrigatorio: declividade e curvaturas sao
        # derivadas dele quando nao forem fornecidas. A checagem de ausencia
        # ficou em _run_algorithm, junto da decisao de derivar ou nao, porque
        # depende do parametro DERIVE_FROM_DEM.
        for label, layer in [
            (t("msg_nome_mde"), dem_layer),
            (t("msg_nome_declividade"), slope_layer),
            (t("msg_nome_curvh"), curvh_layer),
            (t("msg_nome_curvv"), curvv_layer),
        ]:
            if layer is None:
                if layer is dem_layer:
                    raise _erro(t("msg_camada_ausente", name=label))
                continue
            if not layer.crs().isValid():
                raise _erro(t("msg_raster_sem_crs", name=label))
            # gdal.Open, e nao os.path.exists: um MDE dentro de um GeoPackage
            # ("GPKG:/caminho.gpkg:mde") e valido no QGIS e nao e um caminho.
            try:
                probe = gdal.Open(str(layer.source()))
            except RuntimeError as exc:
                raise _erro(t("msg_gdal_camada", name=label, source=layer.source())) from exc
            if probe is None:
                raise _erro(t("msg_gdal_camada", name=label, source=layer.source()))
            probe = None

        min_altitude = self.parameterAsDouble(parameters, self.ALT_MIN, context)
        max_altitude = self.parameterAsDouble(parameters, self.ALT_MAX, context)
        derive_from_dem = self.parameterAsBool(parameters, self.DERIVE_FROM_DEM, context)
        vertical_unit = self.parameterAsEnum(parameters, self.VERTICAL_UNIT, context)
        streams_from_dem = self.parameterAsBool(parameters, self.STREAMS_FROM_DEM, context)
        stream_min_basin_km2 = self.parameterAsDouble(parameters, self.STREAM_MIN_BASIN_KM2, context)
        stream_ford_max_km2 = self.parameterAsDouble(parameters, self.STREAM_FORD_MAX_KM2, context)
        if stream_ford_max_km2 is None or stream_ford_max_km2 <= 0:
            stream_ford_max_km2 = DEFAULT_STREAM_FORD_MAX_KM2
        constraint_layer = self.parameterAsVectorLayer(parameters, self.CONSTRAINT_LAYER, context)
        constraint_buffer_m = self.parameterAsDouble(parameters, self.CONSTRAINT_BUFFER_M, context)
        constraint_mode = self.parameterAsEnum(parameters, self.CONSTRAINT_MODE, context)
        route_cost_model = self.parameterAsEnum(parameters, self.ROUTE_COST_MODEL, context)
        route_contrast = self.parameterAsDouble(parameters, self.ROUTE_CONTRAST, context)
        extra_layer = self.parameterAsRasterLayer(parameters, self.EXTRA_CRITERION_LAYER, context)
        extra_weight = self.parameterAsDouble(parameters, self.EXTRA_CRITERION_WEIGHT, context)
        extra_direction = self.parameterAsEnum(parameters, self.EXTRA_CRITERION_DIRECTION, context)
        breaks_text = self.parameterAsString(parameters, self.TRANSITABILITY_BREAKS, context)
        try:
            transitability_breaks = tuple(
                float(part) for part in breaks_text.replace(";", ",").split(",") if part.strip()
            )
        except ValueError:
            raise _erro(t("msg_transit_limites_texto", text=repr(breaks_text)))
        if len(transitability_breaks) != 4:
            raise _erro(t("msg_transit_limites_quatro", n=len(transitability_breaks)))
        slope_unit = self.parameterAsEnum(parameters, self.SLOPE_UNIT, context)
        max_slope = self.parameterAsDouble(parameters, self.SLOPE_MAX, context)
        slope_score_max = self.parameterAsDouble(parameters, self.SLOPE_SCORE_MAX, context)
        threshold = self.parameterAsDouble(parameters, self.THRESHOLD, context)
        auto_percentile = self.parameterAsDouble(parameters, self.AUTO_PERCENTILE, context)
        min_patch_area_ha = self.parameterAsDouble(parameters, self.MIN_PATCH_AREA_HA, context)
        altitude_band_threshold = self.parameterAsBool(parameters, self.ALTITUDE_BAND_THRESHOLD, context)
        altitude_band_size_m = self.parameterAsDouble(parameters, self.ALTITUDE_BAND_SIZE_M, context)
        walkability_zones = self.parameterAsBool(parameters, self.WALKABILITY_ZONES, context)
        start_point_file = self.parameterAsFile(parameters, self.START_POINT_FILE, context)
        end_point_file = self.parameterAsFile(parameters, self.END_POINT_FILE, context)
        via_points_file = self.parameterAsFile(parameters, self.VIA_POINTS_FILE, context)
        optimise_order = self.parameterAsBool(parameters, self.OPTIMISE_ORDER, context)
        route_buffer_m = self.parameterAsDouble(parameters, self.ROUTE_BUFFER_M, context)
        route_margin_m = self.parameterAsDouble(parameters, self.ROUTE_MARGIN_M, context)
        generate_zones = self.parameterAsBool(parameters, self.GENERATE_ZONES, context)
        altitude_weight = self.parameterAsDouble(parameters, self.WEIGHT_ALT, context)
        slope_weight = self.parameterAsDouble(parameters, self.WEIGHT_SLOPE, context)
        curvh_weight = self.parameterAsDouble(parameters, self.WEIGHT_CURVH, context)
        curvv_weight = self.parameterAsDouble(parameters, self.WEIGHT_CURVV, context)
        wetness_weight = self.parameterAsDouble(parameters, self.WEIGHT_WETNESS, context)
        roughness_weight = self.parameterAsDouble(parameters, self.WEIGHT_ROUGHNESS, context)
        curvh_limit = self.parameterAsDouble(parameters, self.CURVH_LIMIT, context)
        curvv_limit = self.parameterAsDouble(parameters, self.CURVV_LIMIT, context)
        wetness_limit = self.parameterAsDouble(parameters, self.WETNESS_LIMIT, context)
        roughness_limit = self.parameterAsDouble(parameters, self.ROUGHNESS_LIMIT, context)
        field_speed_kmh = self.parameterAsDouble(parameters, self.FIELD_SPEED_KMH, context)
        if not field_speed_kmh or field_speed_kmh <= 0:
            field_speed_kmh = FIELD_SURVEY_SPEED_KMH
        alternatives_pct = self.parameterAsDouble(parameters, self.ROUTE_ALTERNATIVES_PCT, context) or 0.0
        working_cell_m = self.parameterAsDouble(parameters, self.WORKING_CELL_M, context) or 0.0
        total_weight = (altitude_weight + slope_weight + curvh_weight + curvv_weight
                        + wetness_weight + roughness_weight + extra_weight)

        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT_FILE, context)
        output_format_idx = self.parameterAsEnum(parameters, self.OUTPUT_FORMAT, context)
        output_formats = ["Shapefile", "GeoPackage", "KML"]
        output_format = output_formats[output_format_idx] if 0 <= output_format_idx < len(output_formats) else "Shapefile"
        output_crs = self.parameterAsCrs(parameters, self.OUTPUT_CRS, context)
        if output_crs is None or not output_crs.isValid():
            # O padrao de OUTPUT_CRS deixou de ser lido em initAlgorithm (onde
            # so havia o singleton QgsProject.instance()) e passou a sair do
            # projeto do proprio contexto de execucao.
            output_crs = project_crs_from_context(context) or output_crs
        output_path = ensure_output_extension(output_path, output_format)
        debug_log_path = diagnostic_log_path(output_path)
        append_diagnostic_log(
            debug_log_path,
            "processamento_iniciado",
            plugin="TopoTrail",
            ambiente=dependency_diagnostics(),
            output_path=output_path,
            output_format=output_format,
            output_crs=output_crs.authid() if output_crs and output_crs.isValid() else None,
            inputs={
                "dem": file_diagnostics(dem_layer.source() if dem_layer else ""),
                "slope": file_diagnostics(slope_layer.source() if slope_layer else ""),
                "curvatura_horizontal": file_diagnostics(curvh_layer.source() if curvh_layer else ""),
                "curvatura_vertical": file_diagnostics(curvv_layer.source() if curvv_layer else ""),
                "ponto_inicial": file_diagnostics(start_point_file),
                "ponto_final": file_diagnostics(end_point_file),
            },
            parametros={
                "altitude_min_m": min_altitude,
                "altitude_max_m": max_altitude,
                "declividade_unidade_entrada": "graus" if slope_unit == SLOPE_UNIT_DEGREES else "porcentagem",
                "declividade_max_abs_pct": max_slope,
                "declividade_custo_max_pct": slope_score_max,
                "threshold": threshold,
                "percentil_automatico": auto_percentile,
                "area_min_fragmento_ha": min_patch_area_ha,
                "zonas_como_area_caminhavel": walkability_zones,
                "threshold_por_faixa_altimetrica": altitude_band_threshold,
                "faixa_altimetrica_m": altitude_band_size_m,
                "pesos": {
                    "altitude": altitude_weight,
                    "declividade": slope_weight,
                    "curvatura_horizontal": curvh_weight,
                    "curvatura_vertical": curvv_weight,
                    "umidade": wetness_weight,
                    "rugosidade": roughness_weight,
                    "raster_extra": extra_weight,
                },
                "gerar_zonas_vetoriais": generate_zones,
                "corredor_raio_m": route_buffer_m,
                "margem_busca_m": route_margin_m,
                "modelo_de_custo": cost_model_name(route_cost_model),
                "contraste_k": route_contrast,
                "destinos_intermediarios": file_diagnostics(via_points_file),
                "otimizar_ordem": optimise_order,
                "drenagem_do_mde": streams_from_dem,
                "bacia_min_km2": stream_min_basin_km2,
                "teto_vadeavel_km2": stream_ford_max_km2,
                "restricao_modo": ("evitar" if constraint_mode == CONSTRAINT_AVOID else "encarecer"),
                "restricao_buffer_m": constraint_buffer_m,
                "derivar_do_mde_solicitado": derive_from_dem,
                "unidade_vertical": ("pes" if vertical_unit == VERTICAL_UNIT_FEET else "metros"),
                "velocidade_campo_kmh": field_speed_kmh,
                "folga_alternativas_pct": alternatives_pct,
                "celula_trabalho_m": working_cell_m or "automatica",
            },
        )
        if bool(start_point_file) != bool(end_point_file):
            message = t("msg_pontos_obrigatorios")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        for point_file, label in [(start_point_file, t("msg_rotulo_inicial")), (end_point_file, t("msg_rotulo_final"))]:
            if point_file and not os.path.exists(point_file):
                message = t("msg_arquivo_ponto", label=label, path=point_file)
                append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
                raise _erro(message)

        if total_weight <= 0:
            message = t("msg_pesos_soma")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if any(weight < 0 for weight in [altitude_weight, slope_weight, curvh_weight,
                                         curvv_weight, wetness_weight, roughness_weight,
                                         extra_weight]):
            message = t("msg_pesos_negativos")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if min_altitude >= max_altitude:
            message = t("msg_altitude_ordem")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if max_slope <= 0 or slope_score_max <= 0:
            message = t("msg_declividade_positiva")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if min_patch_area_ha < 0 and min_patch_area_ha != MIN_PATCH_AREA_AUTO:
            message = t("msg_area_minima_negativa")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if not (0 <= threshold <= 1):
            message = t("msg_limiar_faixa_valida")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if not (0 < auto_percentile < 100):
            message = t("msg_percentil_faixa")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if not (0 <= alternatives_pct <= MAX_ALTERNATIVES_PCT):
            message = t("msg_folga_faixa", max=MAX_ALTERNATIVES_PCT)
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)
        if route_buffer_m <= 0 or route_margin_m <= 0:
            message = t("msg_corredor_margem")
            append_diagnostic_log(debug_log_path, "validacao_falhou", erro=message)
            raise _erro(message)

        if feedback:
            feedback.pushInfo(t("msg_param_titulo"))
            feedback.pushInfo(t("msg_param_log", path=debug_log_path))
            feedback.pushInfo(t("msg_param_alt_min", value=min_altitude))
            feedback.pushInfo(t("msg_param_alt_max", value=max_altitude))
            feedback.pushInfo(t("msg_param_decl_graus" if slope_unit == SLOPE_UNIT_DEGREES else "msg_param_decl_pct"))
            feedback.pushInfo(t("msg_param_decl_max", value=max_slope))
            feedback.pushInfo(t("msg_param_decl_custo", value=slope_score_max))
            feedback.pushInfo(t("msg_param_limiar", value=threshold) if threshold else t("msg_param_limiar_auto"))
            feedback.pushInfo(t("msg_param_percentil", value=auto_percentile))
            feedback.pushInfo(
                t("msg_param_area_auto") if min_patch_area_ha == MIN_PATCH_AREA_AUTO
                else t("msg_param_area", value=min_patch_area_ha))
            feedback.pushInfo(t(
                "msg_param_zonas", zones=_sim_nao(generate_zones), walkable=_sim_nao(walkability_zones),
                bands=_sim_nao(altitude_band_threshold), size=altitude_band_size_m))
            feedback.pushInfo(t("msg_param_pesos", alt=altitude_weight, slope=slope_weight, curvh=curvh_weight,
                                curvv=curvv_weight))
            feedback.pushInfo(t("msg_param_formato", format=output_format))
            feedback.pushInfo("================================")

        temp_work_dir = tempfile.mkdtemp(prefix="topotrail_work_")
        getattr(self, "_temp_dirs", []).append(temp_work_dir)
        dem_crs_info = ensure_projected_working_crs(
            dem_layer.source(),
            feedback=feedback,
            temp_dir=temp_work_dir,
            log_path=debug_log_path,
            cell_size_m=working_cell_m,
        )
        dem_path = dem_crs_info["dem_path"]
        prepared_rasters = {"dem": dem_path}
        derivative_layers = [
            (t("msg_nome_declividade"), slope_layer, "slope"),
            (t("msg_nome_curvh"), curvh_layer, "curvh"),
            (t("msg_nome_curvv"), curvv_layer, "curvv"),
        ]
        missing = [label for label, layer, _ in derivative_layers if layer is None]
        if not derive_from_dem and missing:
            raise _erro(t("msg_camadas_obrigatorias", layers=t("msg_sep_lista").join(missing),
                          option=_rotulo("alg_derive")))
        if derive_from_dem and not missing and feedback:
            feedback.pushInfo(t("msg_rasters_fornecidos"))
        derive_from_dem = derive_from_dem and bool(missing)
        # O bloco de parametros grava o que o usuario pediu; aqui fica o que de
        # fato aconteceu, que pode divergir quando ele fornece os rasters.
        append_diagnostic_log(
            debug_log_path, "origem_das_derivadas",
            derivadas_do_mde=bool(derive_from_dem),
            rasters_ausentes=list(missing))

        for label, source_path, key in [
            (label, layer.source(), key)
            for label, layer, key in derivative_layers
            if layer is not None
        ]:
            compatibility = validate_raster_grid_compatibility(dem_path, source_path)
            append_diagnostic_log(
                debug_log_path,
                "compatibilidade_raster",
                raster=label,
                entrada=source_path,
                compatibilidade=compatibility,
            )
            if compatibility["compatible"]:
                prepared_rasters[key] = source_path
            else:
                aligned_path = os.path.join(temp_work_dir, f"{key}_alinhado.tif")
                prepared_rasters[key] = align_raster_to_reference(
                    source_path,
                    dem_path,
                    aligned_path,
                    resampling="bilinear",
                    feedback=feedback,
                    log_path=debug_log_path,
                )

        dem_data, transform, proj = read_raster(prepared_rasters["dem"], feedback)
        # O teto e o aviso de memoria viviam so dentro de derive_terrain e
        # vector_ruggedness. Com DERIVE_FROM_DEM=False e rugosidade com peso
        # zero, nenhuma das duas rodava: nem o aviso, nem o teto. Medido na
        # auditoria com a mesma grade de 9.000.000 de celulas, o caminho que
        # deriva avisou e gastou 96 B/celula e o que recebe os rasters prontos
        # nao avisou e gastou 103 B/celula -- o caminho sem aviso gasta mais.
        # Quem gasta a memoria e a leitura das quatro grades e a combinacao
        # ponderada, nao a derivacao, entao a guarda pertence aqui. O feedback
        # so vai quando a derivacao nao roda, para nao duplicar a mesma linha.
        try:
            check_terrain_size(dem_data, None if derive_from_dem else feedback)
        except ValueError as exc:
            raise _erro(str(exc)) from exc

        if vertical_unit == VERTICAL_UNIT_FEET:
            dem_data = (dem_data * FEET_TO_METRES).astype(np.float32)
            if feedback:
                finite = dem_data[np.isfinite(dem_data)]
                feedback.pushInfo(
                    t("msg_pes_metros", min=float(finite.min()), max=float(finite.max())) if finite.size
                    else t("msg_pes_metros_curto"))
            append_diagnostic_log(debug_log_path, "unidade_vertical",
                                  unidade_declarada="pes", convertido_para_metros=True)

        if derive_from_dem:
            slope_data, curvh_data, curvv_data = derive_terrain(dem_data, transform, feedback)
            slope_unit = SLOPE_UNIT_PERCENT      # a derivacao ja devolve porcentagem
            slope_transform = curvh_transform = curvv_transform = transform
            slope_proj = curvh_proj = curvv_proj = proj
            append_diagnostic_log(debug_log_path, "derivadas_calculadas_do_mde",
                                  metodo="gradiente central; curvaturas geometricas de contorno e perfil (Moore et al. 1991)",
                                  pixel_x=abs(float(transform[1])), pixel_y=abs(float(transform[5])))
        else:
            slope_data, slope_transform, slope_proj = read_raster(prepared_rasters["slope"], feedback)
            curvh_data, curvh_transform, curvh_proj = read_raster(prepared_rasters["curvh"], feedback)
            curvv_data, curvv_transform, curvv_proj = read_raster(prepared_rasters["curvv"], feedback)
            # Sentinela nao declarada num raster fornecido pelo usuario apagava
            # o criterio inteiro em silencio. Vale para os tres que ele traz;
            # os derivados do MDE saem da propria grade e ja passaram pelo
            # aviso de faixa de altitude.
            for nome_raster, dados_raster in (
                    (t("msg_nome_declividade"), slope_data),
                    (t("msg_nome_curvh"), curvh_data),
                    (t("msg_nome_curvv"), curvv_data)):
                report_absurd_criterion_values(
                    dados_raster, nome_raster, feedback, debug_log_path)
        append_diagnostic_log(
            debug_log_path,
            "rasters_lidos",
            crs_trabalho=dem_crs_info,
            caminhos_preparados=prepared_rasters,
            transform=list(transform) if transform else None,
            projection_wkt_start=proj[:300] if proj else None,
            dem=array_diagnostics(dem_data),
            declividade=array_diagnostics(slope_data),
            curvatura_horizontal=array_diagnostics(curvh_data),
            curvatura_vertical=array_diagnostics(curvv_data),
        )

        if not derive_from_dem:
            validate_raster_alignment(
                dem_data.shape,
                transform,
                [
                    ("Declividade", slope_data, slope_transform),
                    ("Curvatura horizontal", curvh_data, curvh_transform),
                    ("Curvatura vertical", curvv_data, curvv_transform),
                ],
                feedback,
            )

            for label, raster_proj in [
                (t("msg_nome_declividade"), slope_proj),
                (t("msg_nome_curvh"), curvh_proj),
                (t("msg_nome_curvv"), curvv_proj),
            ]:
                if proj and raster_proj and proj != raster_proj:
                    raise _erro(t("msg_projecao_diferente", name=label))

        slope_data = slope_to_percent(slope_data, slope_unit, feedback, debug_log_path)

        altitude_norm = normalize_linear(dem_data, min_altitude, max_altitude, feedback, t("msg_nome_altitude"))
        slope_norm = normalize_cost(slope_data, 0, slope_score_max, feedback, t("msg_nome_declividade"))
        limites = {
            "curvatura_horizontal": (curvh_limit if curvh_limit > 0 else curvature_limit(curvh_data)),
            "curvatura_vertical": (curvv_limit if curvv_limit > 0 else curvature_limit(curvv_data)),
        }
        origem_limites = {
            "curvatura_horizontal": "parametro" if curvh_limit > 0 else "cena P{:g}".format(
                CURVATURE_DEVIATION_PERCENTILE),
            "curvatura_vertical": "parametro" if curvv_limit > 0 else "cena P{:g}".format(
                CURVATURE_DEVIATION_PERCENTILE),
        }
        curvh_norm = normalize_curvature_preference(
            curvh_data, feedback, t("msg_nome_curvh"), limit=limites["curvatura_horizontal"])
        curvv_norm = normalize_curvature_preference(
            curvv_data, feedback, t("msg_nome_curvv"), limit=limites["curvatura_vertical"])

        valid_mask = ~np.isnan(dem_data) & ~np.isnan(slope_data) & ~np.isnan(curvh_data) & ~np.isnan(curvv_data)
        area_pixel_m2 = estimate_pixel_area_m2(transform, dem_data.shape, proj)
        mar_mask, lagos_mask = flat_water_masks(dem_data, area_pixel_m2)
        agua_fora = mar_mask | (lagos_mask if streams_from_dem else False)
        if agua_fora.any():
            valid_mask = valid_mask & ~agua_fora
            if feedback:
                feedback.pushInfo(t(
                    "msg_agua_retirada", sea=float(mar_mask.sum()) * area_pixel_m2 / 1e6,
                    lakes="" if not (streams_from_dem and lagos_mask.any()) else
                    t("msg_agua_lagos", area=float(lagos_mask.sum()) * area_pixel_m2 / 1e6)))
        append_diagnostic_log(
            debug_log_path, "superficies_dagua",
            mar_km2=float(mar_mask.sum()) * area_pixel_m2 / 1e6,
            lagos_km2=float(lagos_mask.sum()) * area_pixel_m2 / 1e6,
            lagos_como_barreira=bool(streams_from_dem),
            area_minima_km2=WATER_MIN_AREA_M2 / 1e6)
        altitude_range_mask = (dem_data >= min_altitude) & (dem_data <= max_altitude)
        zone_constraint_mask = valid_mask & altitude_range_mask & (slope_data <= max_slope)
        route_constraint_mask = valid_mask & (slope_data <= max_slope)

        # ---- restricoes: cursos d'agua e camada vetorial do usuario ----
        restricted_mask = np.zeros(dem_data.shape, dtype=bool)
        twi_data = None
        if streams_from_dem or wetness_weight > 0:
            channels, twi_data, basin_km2, stream_metrics = analyse_hydrology(
                dem_data, transform, stream_min_basin_km2, feedback,
                warn_about_width=streams_from_dem, return_basin_area=True)
            append_diagnostic_log(debug_log_path, "drenagem_extraida_do_mde", **stream_metrics)
        stream_mask = np.zeros(dem_data.shape, dtype=bool)
        stream_factor = None
        stream_area = None
        stream_class = None
        channel_axis = None
        if streams_from_dem:
            channel_axis = channels.astype(bool).copy()
            if constraint_buffer_m > 0 and channels.any():
                # Buffer circular (distancia euclidiana em metros), e nao uma
                # dilatacao 3x3 repetida, que da um quadrado: 50 m viravam 71 m
                # na diagonal.
                px = abs(float(transform[1]))
                py = abs(float(transform[5]))
                distance = morphology.distance_transform_edt(~channels, sampling=(py, px))
                channels = distance <= float(constraint_buffer_m)
            stream_mask = channels.astype(bool)
            stream_factor, stream_area, stream_class = stream_crossing_factors(
                stream_mask, basin_km2, stream_ford_max_km2, transform, channel_axis=channel_axis)
            # So o rio acima do teto vadeavel restringe; o resto da drenagem so
            # informa a rota (FORD_CLASSES) e as zonas mantem as margens.
            restricted_mask |= stream_mask & ~np.isfinite(stream_factor)
            if feedback:
                labels = _ford_labels()
                counts = [int(((stream_class == k) & valid_mask).sum()) for k in range(len(FORD_CLASSES) + 1)]
                feedback.pushInfo(t(
                    "msg_cursos_classe", ford=stream_ford_max_km2, items=t("msg_sep_itens").join(
                        t("msg_classe_contagem", label=labels[k], n=counts[k]) for k in range(len(labels)))))

        layer_mask = None
        if constraint_layer is not None:
            layer_mask = rasterize_constraint_layer(
                constraint_layer, constraint_buffer_m, transform,
                dem_data.shape, proj, feedback, debug_log_path)
            if layer_mask is not None:
                restricted_mask |= layer_mask

        # A rota trata a drenagem SEMPRE como custo (8x), nunca como parede,
        # mesmo no modo "evitar". Um curso d'agua e uma linha: toda rota que
        # vai de um vale ao vizinho tem de cruzar um, e uma rede linear
        # transformada em barreira absoluta retalha a paisagem em ilhas -- a
        # travessia Marins-Marinzinho-Itaguare falhava com os padroes da janela
        # exatamente por isso. As ZONAS mantem a drenagem (ver combine_constraints:
        # a margem e habitat de amostragem); no modo "evitar" elas excluem so a
        # camada do usuario. Ate a 1.4.1 as zonas tambem excluiam a drenagem no
        # modo "evitar". A camada de restricao
        # do usuario segue o modo escolhido nos dois casos: cerca e cerca.
        # Fatores de custo para a rota: a drenagem entra com o fator de
        # FORD_CLASSES (1: so informa; barreira acima do teto vadeavel), a camada do
        # usuario entra com 8x no modo "encarecer" ou como barreira no modo
        # "evitar". Onde os dois coincidem vale o pior.
        penalty_mask = None
        route_barrier = np.zeros(dem_data.shape, dtype=bool)
        if restricted_mask.any():
            affected = int((restricted_mask & valid_mask).sum())
            (route_constraint_mask, zone_constraint_mask, penalty_mask,
             route_barrier, tratamento) = combine_constraints(
                route_constraint_mask, zone_constraint_mask,
                layer_mask, stream_factor, constraint_mode)
            if feedback:
                feedback.pushInfo(t("msg_restricoes", cells=affected, pct=100.0 * affected / max(1, int(valid_mask.sum())),
                                    treatment=tratamento))
            append_diagnostic_log(
                debug_log_path, "restricoes_aplicadas",
                celulas=affected, modo=("evitar" if constraint_mode == CONSTRAINT_AVOID else "encarecer"),
                buffer_m=float(constraint_buffer_m),
                fonte_drenagem=bool(streams_from_dem),
                drenagem_na_rota=("so informa; barreira acima do teto vadeavel"
                                  if stream_mask.any() else None),
                teto_vadeavel_km2=float(stream_ford_max_km2),
                celulas_barreira_rota=int(route_barrier.sum()),
                fonte_camada=bool(constraint_layer is not None),
            )

        if feedback:
            valid_count = int(np.sum(valid_mask))
            above = int(np.sum(valid_mask & (dem_data > max_altitude)))
            below = int(np.sum(valid_mask & (dem_data < min_altitude)))
            if valid_count and (above + below) > 0.01 * valid_count:
                dem_valid = dem_data[valid_mask]
                feedback.pushWarning(t(
                    "msg_faixa_altitude", min=min_altitude, max=max_altitude,
                    pct=100.0 * (above + below) / valid_count, above=100.0 * above / valid_count,
                    below=100.0 * below / valid_count, dem_min=float(np.nanmin(dem_valid)),
                    dem_max=float(np.nanmax(dem_valid))))
            viable = int(np.sum(zone_constraint_mask))
            route_viable = int(np.sum(route_constraint_mask))
            feedback.pushInfo(t("msg_mascara_zonas", viable=viable, total=int(dem_data.size),
                                pct=viable / dem_data.size * 100))
            feedback.pushInfo(t("msg_mascara_rota", viable=route_viable, total=int(dem_data.size),
                                pct=route_viable / dem_data.size * 100))
        append_diagnostic_log(
            debug_log_path,
            "mascara_booleana",
            pixels_total=int(dem_data.size),
            pixels_validos_entrada=int(np.sum(valid_mask)),
            pixels_viaveis_zonas=int(np.sum(zone_constraint_mask)),
            proporcao_viavel_zonas=float(np.sum(zone_constraint_mask) / dem_data.size),
            pixels_navegaveis_rota=int(np.sum(route_constraint_mask)),
            proporcao_navegavel_rota=float(np.sum(route_constraint_mask) / dem_data.size),
            pixels_altitude_baixa=int(np.sum(valid_mask & (dem_data < min_altitude))),
            pixels_altitude_alta=int(np.sum(valid_mask & (dem_data > max_altitude))),
            pixels_declividade_acima_limite=int(np.sum(valid_mask & (slope_data > max_slope))),
        )

        extra_norm = None
        if extra_weight > 0:
            if extra_layer is None:
                raise _erro(t("msg_extra_sem_raster"))
            extra_aligned = align_raster_to_reference(
                extra_layer.source(), prepared_rasters["dem"],
                os.path.join(temp_work_dir, "criterio_adicional_alinhado.tif"),
                resampling="bilinear", feedback=feedback, log_path=debug_log_path)
            extra_data, _, _ = read_raster(extra_aligned, feedback)
            report_absurd_criterion_values(
                extra_data, t("msg_nome_extra"), feedback, debug_log_path)
            extra_valid = valid_mask & np.isfinite(extra_data)
            if not np.any(extra_valid):
                raise _erro(t("msg_extra_sem_validos"))
            # Normalizacao robusta pelos percentis 5 e 95 da propria cena: a
            # unidade do raster e desconhecida -- pode ser %, indice, contagem --
            # e os percentis absorvem tanto a escala quanto valores extremos.
            low = float(np.percentile(extra_data[extra_valid], 5))
            high = float(np.percentile(extra_data[extra_valid], 95))
            if high - low < 1e-12:
                raise _erro(t("msg_extra_constante", low=low, high=high))
            scaled = np.clip((extra_data - low) / (high - low), 0.0, 1.0)
            extra_norm = (scaled if extra_direction == CRITERION_HIGHER_IS_BETTER
                          else 1.0 - scaled).astype(np.float32)
            extra_norm = np.where(extra_valid, extra_norm, np.nan).astype(np.float32)
            append_diagnostic_log(
                debug_log_path, "criterio_adicional",
                origem=str(extra_layer.source()), peso=float(extra_weight),
                sentido=("maiores sao melhores" if extra_direction == CRITERION_HIGHER_IS_BETTER
                         else "maiores sao piores"),
                p05_entrada=low, p95_entrada=high,
                celulas_validas=int(extra_valid.sum()),
                cobertura=float(extra_valid.sum() / max(1, int(valid_mask.sum()))),
            )
            if feedback:
                cobertura = 100.0 * extra_valid.sum() / max(1, int(valid_mask.sum()))
                feedback.pushInfo(t(
                    "msg_extra_resumo", low=low, high=high, coverage=cobertura, weight=extra_weight,
                    direction=t("msg_maiores_melhores" if extra_direction == CRITERION_HIGHER_IS_BETTER
                                else "msg_maiores_piores")))
                if cobertura < 95.0:
                    feedback.pushWarning(t("msg_extra_cobertura", coverage=cobertura))

        roughness_data = None
        if roughness_weight > 0:
            roughness_data = vector_ruggedness(dem_data, transform, feedback)
            append_diagnostic_log(
                debug_log_path, "rugosidade_calculada",
                metodo="VRM (Sappington et al. 2007), desacoplado da declividade",
                **{k: v for k, v in array_diagnostics(roughness_data).items()
                   if k in ("min", "p50", "p95", "max")})

        # Criterios opcionais. Ambos sao "menos e melhor": terreno mais seco e
        # mais liso caminha melhor, entao a nota inverte a normalizacao robusta.
        wetness_norm = None
        if wetness_weight > 0:
            if twi_data is None:
                raise _erro(t("msg_twi_sem_drenagem", option=_rotulo("alg_streams")))
            limites["umidade_twi"] = (wetness_limit if wetness_limit > 0
                                      else robust_limit(twi_data, valid_mask))
            origem_limites["umidade_twi"] = ("parametro" if wetness_limit > 0
                                             else "cena P{:g}".format(CURVATURE_RISK_PERCENTILE))
            wetness_norm = (1.0 - robust_abs_norm(
                twi_data, valid_mask, limit=limites["umidade_twi"])).astype(np.float32)
        roughness_norm = None
        if roughness_weight > 0:
            limites["rugosidade_vrm"] = (roughness_limit if roughness_limit > 0
                                         else robust_limit(roughness_data, valid_mask))
            origem_limites["rugosidade_vrm"] = ("parametro" if roughness_limit > 0
                                                else "cena P{:g}".format(CURVATURE_RISK_PERCENTILE))
            roughness_norm = (1.0 - robust_abs_norm(
                roughness_data, valid_mask, limit=limites["rugosidade_vrm"])).astype(np.float32)
        # Os limites que fazem a nota -- e o custo da rota -- depender do recorte.
        # Gravados para que um estudo os fixe entre recortes da mesma area.
        append_diagnostic_log(debug_log_path, "limites_normalizacao",
                              limites=limites, origem=origem_limites)
        if feedback:
            feedback.pushInfo(t("msg_limites_normalizacao", items=t("msg_sep_itens").join(
                t("msg_limite_item", name=_nome_do_limite(k), value=v, origin=_origem_do_limite(origem_limites[k]))
                for k, v in limites.items())))

        altitude_component = altitude_weight * altitude_norm
        slope_component = slope_weight * slope_norm
        curvh_component = curvh_weight * curvh_norm
        curvv_component = curvv_weight * curvv_norm
        raw_score = altitude_component + slope_component + curvh_component + curvv_component
        # Criterios que podem nao cobrir toda a grade (raster extra menor, TWI ou
        # VRM sem valor na borda): a celula descoberta e pontuada so pelos
        # criterios que TEM, com a soma dos pesos ajustada por celula. Antes,
        # nan_to_num contava a lacuna como nota zero -- a pior possivel -- e o
        # aviso ao usuario dizia o contrario ("favorece artificialmente").
        weight_sum = np.full(raw_score.shape, float(
            altitude_weight + slope_weight + curvh_weight + curvv_weight), dtype=np.float64)
        for component, weight in ((wetness_norm, wetness_weight),
                                  (roughness_norm, roughness_weight),
                                  (extra_norm, extra_weight)):
            if component is None:
                continue
            covered = np.isfinite(component)
            raw_score = raw_score + weight * np.where(covered, component, 0.0)
            weight_sum = weight_sum + np.where(covered, weight, 0.0)
        raw_score = raw_score / np.maximum(weight_sum, 1e-12)
        zone_score = np.where(zone_constraint_mask, raw_score, np.nan).astype(np.float32)
        route_score = np.where(route_constraint_mask, raw_score, np.nan).astype(np.float32)
        risk_score = compute_topographic_risk(slope_data, curvh_data, curvv_data, valid_mask, max_slope, feedback)

        zone_valid_scores = zone_score[~np.isnan(zone_score)]
        route_valid_scores = route_score[~np.isnan(route_score)]
        causa = explain_empty_mask(dem_data, slope_data, valid_mask,
                                   min_altitude, max_altitude, max_slope)
        if start_point_file and end_point_file and route_valid_scores.size == 0:
            raise _erro(t("msg_sem_celulas_rota", cause=causa))
        if route_valid_scores.size == 0:
            raise _erro(t("msg_sem_celulas", cause=causa))
        if generate_zones and zone_valid_scores.size == 0:
            # Antes a execucao inteira parava aqui, e a rota e os rasters -- que
            # nao dependem da faixa de altitude -- se perdiam junto. Medido no
            # Khumbu com os padroes (0-2600 m): nenhum produto.
            mensagem = t("msg_zonas_sem_celulas", cause=causa)
            if feedback:
                feedback.pushWarning(mensagem)
            append_diagnostic_log(debug_log_path, "zonas_sem_celulas", motivo=causa)
            generate_zones = False
        output_score = zone_score if generate_zones else route_score

        report_model_discrimination(
            slope_data, output_score, valid_mask, slope_score_max, max_slope,
            feedback, debug_log_path)

        threshold_is_auto = threshold is None or threshold == 0
        if generate_zones and not walkability_zones and threshold_is_auto:
            threshold = float(np.percentile(zone_valid_scores, auto_percentile))
            if feedback:
                feedback.pushInfo(t("msg_limiar_auto", percentile=auto_percentile, threshold=threshold))
                if altitude_band_threshold:
                    feedback.pushInfo(t("msg_zonas_faixa_auto"))
        append_diagnostic_log(
            debug_log_path,
            "score_e_threshold",
            threshold_final=threshold,
            threshold_automatico=threshold_is_auto,
            score_zonas=array_diagnostics(zone_score),
            score_rota=array_diagnostics(route_score),
            risco_topografico=array_diagnostics(risk_score),
        )

        if feedback:
            if zone_valid_scores.size:
                feedback.pushInfo(t("msg_nota_zonas", min=float(np.nanmin(zone_valid_scores)),
                                    max=float(np.nanmax(zone_valid_scores)), mean=float(np.nanmean(zone_valid_scores))))
            if route_valid_scores.size:
                feedback.pushInfo(t("msg_nota_rota", min=float(np.nanmin(route_valid_scores)),
                                    max=float(np.nanmax(route_valid_scores)), mean=float(np.nanmean(route_valid_scores))))

        score_path = save_score_raster(output_score, transform, proj, output_path, feedback)
        risk_path = save_risk_raster(risk_score, transform, proj, output_path, feedback)

        transitability_classes, transitability_metrics = classify_transitability(
            slope_data, valid_mask,
            roughness=roughness_data, wetness=twi_data,
            # So marca como intransitavel o que o usuario mandou evitar. Se ele
            # escolheu apenas encarecer, dizer "intransitavel" no mapa
            # contradiria a propria escolha dele.
            blocked_mask=(route_barrier if route_barrier.any() else None),
            slope_breaks=transitability_breaks, feedback=feedback,
            cell_size_m=abs(float(transform[1])),
            labels=_class_labels(),
        )
        transitability_path = save_transitability_raster(
            transitability_classes, transform, proj, output_path, feedback,
            labels=transitability_metrics.get("rotulos"))
        walkable = walkable_fraction(transitability_classes)
        append_diagnostic_log(
            debug_log_path, "transitabilidade",
            arquivo=file_diagnostics(transitability_path),
            fracao_transitavel_classes_1_2=walkable,
            rotulos_en={str(k): v for k, v in format_class_labels(
                CLASS_LABELS_EN, transitability_breaks).items()},
            **transitability_metrics,
        )
        if feedback and walkable is not None:
            feedback.pushInfo(t("msg_transitavel", pct=100.0 * walkable))
        append_diagnostic_log(debug_log_path, "raster_adequabilidade_salvo", arquivo=file_diagnostics(score_path))
        append_diagnostic_log(debug_log_path, "raster_risco_topografico_salvo", arquivo=file_diagnostics(risk_path))
        route_path = None
        corridor_path = None
        crossings_path = None
        alternatives = None
        rota_falhou = None
        if start_point_file and end_point_file:
            try:
                route_path, corridor_path, crossings_path, alternatives = save_access_route(
                    route_score,
                    transform,
                    proj,
                    start_point_file,
                    end_point_file,
                    output_path,
                    route_buffer_m,
                    route_margin_m,
                    feedback,
                    dem_data,
                    output_crs,
                    debug_log_path,
                    cost_model=route_cost_model,
                    contrast=route_contrast,
                    penalty_mask=penalty_mask,
                    via_path=via_points_file or None,
                    optimise_order=optimise_order,
                    # A travessia e contada no EIXO do canal, nao na faixa: desde
                    # que a drenagem so informa, a rota pode acompanhar o rio, e
                    # cada entrada e saida da faixa virava uma "travessia" -- no
                    # exemplo, o mesmo riacho saia duas vezes.
                    stream_mask=(channel_axis if channel_axis is not None and channel_axis.any()
                                 else None),
                    stream_area=stream_area, stream_class=stream_class,
                    stream_cell_m=(stream_metrics.get("pixel_trabalho_m")
                                   if channel_axis is not None else None),
                    field_speed_kmh=field_speed_kmh,
                    alternatives_pct=alternatives_pct,
                    slope_array=slope_data,
                    max_slope=max_slope,
                    lake_mask=(lagos_mask if not streams_from_dem and lagos_mask.any() else None),
                    # sem o limite de declividade, para o aviso de desvio (rios e
                    # restricao no modo evitar continuam barrando)
                    free_score=np.where(valid_mask & ~route_barrier, raw_score, np.nan).astype(np.float32),
                )
            except Exception as erro:
                # A rota e o ultimo produto antes das zonas: se ela falhava, o
                # algoritmo inteiro abortava e levava junto as zonas e os tres
                # mapas ja calculados. Medido na bateria de 51 trilhas
                # consagradas: com a declividade maxima de 55%, 30 delas nao
                # ligam -- e quem pediu zonas de amostragem ficava sem nada.
                # Quando as zonas foram pedidas, a falha da rota vira aviso e o
                # resto e entregue. Rota sozinha, ou cancelamento, continua
                # interrompendo, como antes.
                if (not generate_zones or not _erro_do_algoritmo(erro)
                        or (feedback is not None and feedback.isCanceled())):
                    raise
                rota_falhou = str(erro)
                # Arquivos de rota com este nome sao de uma execucao anterior, ou
                # parciais desta: nenhum descreve a rota que acabou de falhar.
                base_saida = os.path.splitext(output_path)[0]
                apagados = []
                for sufixo in ("_rota.gpkg", "_corredor.gpkg", "_travessias.gpkg",
                               "_alternativas.gpkg", "_folga.tif"):
                    velho = base_saida + sufixo
                    if os.path.exists(velho):
                        try:
                            os.remove(velho)
                            apagados.append(os.path.basename(velho))
                        except OSError as exc:
                            _LOG.debug("arquivo de rota velho nao removido: %s", exc)
                append_diagnostic_log(debug_log_path, "rota_nao_gerada", erro=rota_falhou,
                                      arquivos_de_rota_removidos=apagados)
                if feedback:
                    feedback.reportError(t("msg_rota_nao_gerada", error=rota_falhou), False)
            else:
                append_diagnostic_log(
                    debug_log_path,
                    "rota_e_corredor_salvos",
                    rota=file_diagnostics(route_path),
                    corredor=file_diagnostics(corridor_path),
                    travessias=file_diagnostics(crossings_path) if crossings_path else None,
                )
        gdf = None
        if generate_zones:
            if walkability_zones:
                binary_result = build_walkability_mask(zone_constraint_mask, feedback)
            elif altitude_band_threshold and threshold_is_auto:
                binary_result = binarize_by_altitude_bands(
                    zone_score,
                    dem_data,
                    auto_percentile,
                    altitude_band_size_m,
                    feedback,
                )
            else:
                binary_result = binarize_result(zone_score, threshold, feedback)
            append_diagnostic_log(
                debug_log_path,
                "zonas_binarizadas",
                pixels_aptos_antes_filtro=int(np.sum(binary_result == 1)),
                modo_caminhavel=bool(walkability_zones),
                threshold_por_faixa_altimetrica=bool(altitude_band_threshold and threshold_is_auto and not walkability_zones),
            )
            area_minima_ha = min_patch_area_ha
            area_analisada_ha = float(np.sum(valid_mask & altitude_range_mask)) * area_pixel_m2 / 1e4
            if min_patch_area_ha == MIN_PATCH_AREA_AUTO:
                area_minima_ha = automatic_min_patch_area_ha(area_analisada_ha)
                if feedback:
                    feedback.pushInfo(t("msg_area_minima_auto", area=area_minima_ha, analysed=area_analisada_ha))
            binary_result = filter_small_regions(binary_result, transform, proj, area_minima_ha, feedback, debug_log_path)
            append_diagnostic_log(
                debug_log_path,
                "zonas_filtradas",
                pixels_aptos_apos_filtro=int(np.sum(binary_result == 1)),
                area_min_fragmento_ha=area_minima_ha,
                area_min_automatica=bool(min_patch_area_ha == MIN_PATCH_AREA_AUTO),
                area_analisada_ha=area_analisada_ha,
            )
            representatividade = zone_representativeness(
                binary_result == 1, valid_mask & altitude_range_mask,
                {"altitude": dem_data, "face_norte": northness(dem_data, transform),
                 "umidade": twi_data})
            append_diagnostic_log(debug_log_path, "representatividade_das_zonas", **representatividade)
            frase, aviso = describe_representativeness(
                representatividade,
                altitude_bands_on=bool(altitude_band_threshold and threshold_is_auto
                                       and not walkability_zones),
                walkability=bool(walkability_zones),
                bands_need_auto_threshold=bool(altitude_band_threshold and not threshold_is_auto
                                               and not walkability_zones))
            if frase and feedback:
                (feedback.pushWarning if aviso else feedback.pushInfo)(frase)
            gdf = vectorize_binary_raster(binary_result, transform, proj, feedback)
            append_diagnostic_log(
                debug_log_path,
                "zonas_vetorizadas",
                feicoes=int(len(gdf)),
                colunas=list(gdf.columns),
                crs=srs_label(gdf.srs()),
            )

            if len(gdf) > 0:
                area_crs = metric_crs_for_raster(transform, dem_data.shape, proj)
                try:
                    areas_m2 = gdf.to_crs(area_crs).areas()
                    gdf.set_column("area_m2", areas_m2)
                    gdf.set_column("area_ha", [a / 10000.0 for a in areas_m2])
                except Exception as e:
                    if feedback:
                        feedback.pushWarning(t("msg_areas_metricas", error=e))
        elif feedback:
            feedback.pushInfo(t("msg_zonas_desativadas"))
        result = {self.OUTPUT_SCORE_RASTER: score_path, self.OUTPUT_RISK_RASTER: risk_path,
                  self.OUTPUT_TRANSITABILITY: transitability_path}
        if gdf is not None and len(gdf) > 0:
            vector_path = save_vector(gdf, output_path, output_format, output_crs, feedback)
            result[self.OUTPUT_VECTOR] = vector_path
            append_diagnostic_log(debug_log_path, "vetor_zonas_salvo", arquivo=file_diagnostics(vector_path))
        elif generate_zones and feedback:
            feedback.pushWarning(t("msg_nenhuma_zona"))
        if route_path:
            result[self.OUTPUT_ROUTE] = route_path
        if corridor_path:
            result[self.OUTPUT_CORRIDOR] = corridor_path
        if crossings_path:
            result[self.OUTPUT_CROSSINGS] = crossings_path
        if alternatives:
            result[self.OUTPUT_ALTERNATIVES] = alternatives[0]
            result[self.OUTPUT_SLACK] = alternatives[1]
        if rota_falhou and feedback:
            feedback.pushWarning(t("msg_concluido_sem_rota", error=rota_falhou))
        result[self.OUTPUT_DEBUG_LOG] = debug_log_path
        # QgsProcessingParameterFileDestination declara automaticamente uma
        # saida com o mesmo nome do parametro, e ate aqui ela nunca era
        # preenchida: o dicionario voltava so com as cinco chaves de produto.
        # Sem esta chave o Modelador nao encadeia OUTPUT_FILE, o modo lote e o
        # processing.run() nao recebem de volta o caminho pedido e o "carregar
        # resultados ao concluir" nao acha a saida declarada. O valor e o
        # caminho ja normalizado por ensure_output_extension, que e o nome-base
        # de todos os sete produtos.
        result[self.OUTPUT_FILE] = output_path
        append_diagnostic_log(debug_log_path, "processamento_concluido", outputs=result)
        return result
