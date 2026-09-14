"""Regressoes do lote de correcoes vindo da auditoria de especialistas.

Cada teste reproduz o defeito como foi medido e falha contra o codigo anterior
a correcao; o numero medido na auditoria fica no comentario de cada um.
"""

import numpy as np

import pytest


# ---- 1. QgsProject.instance() dentro de initAlgorithm --------------------

class _Recorder:
    """Guarda os argumentos de construcao de um parametro do Processing."""

    ultimos = {}

    def __init__(self, *args, **kwargs):
        _Recorder.ultimos = dict(kwargs)
        _Recorder.ultimos["posicionais"] = args


def _prepara_enums(algorithm, monkeypatch):
    """Da aos dubles os enums que _qgs_enum busca em initAlgorithm."""
    monkeypatch.setattr(
        algorithm.QgsProcessingParameterNumber, "Type",
        type("Type", (object,), {"Double": 1, "Integer": 0}), raising=False)
    monkeypatch.setattr(
        algorithm.QgsProcessingParameterFile, "Behavior",
        type("Behavior", (object,), {"File": 0, "Folder": 1}), raising=False)


def _instancia_gravadora(algorithm):
    class _Alg(algorithm.TopotrailAlgorithm):
        def __init__(self):
            self.parametros = []
            self.saidas = []

        def addParameter(self, parametro, *args, **kwargs):
            self.parametros.append(parametro)

        def addOutput(self, saida):
            self.saidas.append(saida)

    return _Alg()


def test_init_algorithm_nao_toca_no_singleton_do_projeto(algorithm, monkeypatch):
    """Antes: defaultValue=QgsProject.instance().crs().authid().

    Medido na auditoria: com um contexto cujo projeto estava em EPSG:4674, o
    default lido saia 'EPSG:31983' -- veio do singleton, nao do contexto.
    Aqui o singleton explode se for tocado.
    """
    class _Proibido:
        @staticmethod
        def instance():
            raise RuntimeError("QgsProject.instance() nao pode ser lido em initAlgorithm")

    _prepara_enums(algorithm, monkeypatch)
    monkeypatch.setattr(algorithm, "QgsProject", _Proibido, raising=False)
    monkeypatch.setattr(algorithm, "QgsProcessingParameterCrs", _Recorder)

    alg = _instancia_gravadora(algorithm)
    alg.initAlgorithm()

    assert _Recorder.ultimos.get("defaultValue") is None
    assert any(isinstance(p, _Recorder) for p in alg.parametros)


def test_crs_do_projeto_vem_do_contexto(algorithm):
    """O CRS padrao passa a sair de context.project(), nao do singleton."""
    class _Crs:
        def isValid(self):
            return True

        def authid(self):
            return "EPSG:4674"

    class _Projeto:
        def crs(self):
            return _Crs()

    class _Contexto:
        def project(self):
            return _Projeto()

    assert algorithm.project_crs_from_context(_Contexto()).authid() == "EPSG:4674"


def test_crs_do_projeto_sem_projeto_e_sem_contexto(algorithm):
    """Fallback seguro: sem contexto, sem projeto ou sem CRS valido -> None."""
    class _SemProjeto:
        def project(self):
            return None

    class _CrsInvalido:
        def isValid(self):
            return False

    class _ProjetoSemCrs:
        def crs(self):
            return _CrsInvalido()

    class _ContextoSemCrs:
        def project(self):
            return _ProjetoSemCrs()

    assert algorithm.project_crs_from_context(None) is None
    assert algorithm.project_crs_from_context(_SemProjeto()) is None
    assert algorithm.project_crs_from_context(_ContextoSemCrs()) is None


# ---- 5. a legenda tem de refletir os limites realmente usados -------------

def test_rotulos_de_classe_seguem_os_limites_escolhidos(transitability):
    """Antes: com TRANSITABILITY_BREAKS = 2,4,6,8 a legenda saia
    '1 - Suave (< 20%)' ... '5 - Escarpada (> 100%)', os limites de fabrica --
    a classe 1 do arquivo valia '< 2%' e a legenda dizia '< 20%'.
    """
    rotulos = transitability.format_class_labels(
        transitability.CLASS_LABELS, (2.0, 4.0, 6.0, 8.0))
    assert rotulos[1] == "1 - Suave (< 2%)"
    assert rotulos[2] == "2 - Moderada (2-4%)"
    assert rotulos[3] == "3 - Forte (4-6%)"
    assert rotulos[4] == "4 - Muito forte (6-8%)"
    assert rotulos[5] == "5 - Escarpada (> 8%)"


def test_com_os_limites_de_fabrica_a_legenda_sai_identica_a_de_antes(transitability):
    """Nenhum texto muda no caminho padrao: 20.0 continua saindo como '20'."""
    rotulos = transitability.format_class_labels(transitability.CLASS_LABELS)
    assert rotulos == {
        1: "1 - Suave (< 20%)",
        2: "2 - Moderada (20-35%)",
        3: "3 - Forte (35-60%)",
        4: "4 - Muito forte (60-100%)",
        5: "5 - Escarpada (> 100%)",
    }


def test_classify_devolve_os_rotulos_com_os_limites_em_vigor(transitability):
    slope = np.array([[1.0, 3.0], [5.0, 9.0]], dtype=np.float32)
    valido = np.ones(slope.shape, dtype=bool)
    _, metricas = transitability.classify(
        slope, valido, slope_breaks=(2.0, 4.0, 6.0, 8.0))
    assert metricas["rotulos"][1] == "1 - Suave (< 2%)"
    assert "< 2%" in " ".join(metricas["distribuicao"].keys())


def test_traducoes_trazem_os_marcadores_de_limite():
    """Cada idioma precisa dos quatro marcadores, senao a legenda daquele
    idioma volta a mentir os limites."""
    import json
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent
    esperado = {1: ["{b1}"], 2: ["{b1}", "{b2}"], 3: ["{b2}", "{b3}"],
                4: ["{b3}", "{b4}"], 5: ["{b4}"]}
    for arquivo in sorted((raiz / "i18n").glob("*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        for numero, marcadores in esperado.items():
            texto = dados[f"class_{numero}"]
            for marcador in marcadores:
                assert marcador in texto, (arquivo.name, numero, texto)


# ---- 7. BYTES_POR_CELULA calibrado pelo consumo real ---------------------

def test_bytes_por_celula_cobre_o_pior_caminho_medido(terrain):
    """Antes: 134 B/celula, medidos so dentro de derive_terrain/vector_ruggedness.

    O consumo real do caminho completo (drenagem + umidade + rugosidade +
    zonas) foi de 205,2 B/celula na auditoria e de 206,7 B/celula na remedicao
    (3.000 x 3.000 celulas, ru_maxrss de pico menos a linha de base). O teto de
    1e8 celulas prometia 13,4 GB e pediria ~20,7 GB.
    """
    pior_medido = 206.7
    assert terrain.BYTES_POR_CELULA >= pior_medido, terrain.BYTES_POR_CELULA
    folga = terrain.BYTES_POR_CELULA / pior_medido
    assert 1.05 <= folga <= 1.5, folga


def test_a_mensagem_do_teto_nao_promete_menos_memoria_do_que_gasta(terrain):
    """A frase que o usuario le antes de decidir recortar dizia 'cerca de
    13,4 GB' para 100 milhoes de celulas; o gasto real passa de 20 GB."""
    class _Feedback:
        def __init__(self):
            self.avisos = []

        def pushWarning(self, mensagem):
            self.avisos.append(mensagem)

    with pytest.raises(ValueError) as capturado:
        terrain.check_terrain_size(np.empty(terrain.MAX_TERRAIN_CELLS + 1,
                                            dtype=np.uint8))
    prometido = float(str(capturado.value).split("cerca de ")[1]
                      .split(" GB")[0].replace(",", "."))
    assert prometido >= 20.0, prometido


# ---- 10. sentinela nao declarada apaga o criterio -------------------------

class _FeedbackSimples:
    def __init__(self):
        self.infos = []
        self.avisos = []

    def pushInfo(self, mensagem):
        self.infos.append(mensagem)

    def pushWarning(self, mensagem):
        self.avisos.append(mensagem)


def test_sentinela_nao_declarada_e_denunciada_com_o_nome_do_raster(algorithm):
    """Antes: um raster de curvatura com 2% das linhas em -3.4e38 levava a nota
    media de 0,656 para 0,984, mudava a rota e o tempo, e nao emitia
    'avisos: (NENHUM)'.
    """
    curvatura = np.full((50, 50), 0.0001, dtype=np.float32)
    curvatura[::50 // 1, :] = 0.0001
    curvatura[0, :] = -3.4e38

    feedback = _FeedbackSimples()
    achados = algorithm.report_absurd_criterion_values(
        curvatura, "Curvatura horizontal", feedback)

    assert achados == 50
    assert feedback.avisos, "nenhum aviso emitido"
    assert "Curvatura horizontal" in feedback.avisos[0]
    assert "NoData" in feedback.avisos[0]


def test_raster_saudavel_nao_gera_aviso(algorithm):
    curvatura = (np.random.default_rng(0).normal(0, 0.001, (40, 40))
                 .astype(np.float32))
    curvatura[3, 3] = np.nan
    feedback = _FeedbackSimples()
    assert algorithm.report_absurd_criterion_values(
        curvatura, "Curvatura horizontal", feedback) == 0
    assert not feedback.avisos


def test_infinito_no_criterio_tambem_e_denunciado(algorithm):
    curvatura = np.full((20, 20), 0.001, dtype=np.float32)
    curvatura[0, 0] = np.inf
    feedback = _FeedbackSimples()
    assert algorithm.report_absurd_criterion_values(
        curvatura, "Curvatura vertical", feedback) == 1
    assert "Curvatura vertical" in feedback.avisos[0]


def test_limite_do_percentil_fora_de_escala_avisa(algorithm):
    """O sintoma direto: limite=3.4e37 contra os 0,0004 da mesma cena limpa."""
    curvatura = np.full((50, 50), 0.0002, dtype=np.float32)
    curvatura[:2, :] = -3.4e38
    feedback = _FeedbackSimples()
    algorithm.normalize_curvature_preference(
        curvatura, feedback=feedback, name="Curvatura horizontal")
    fora = [a for a in feedback.avisos if "limite do percentil" in a]
    assert fora, feedback.avisos
    assert "Curvatura horizontal" in fora[0]


# ---- 11. VRM e adimensional, nao metros ----------------------------------

def test_vrm_nao_e_impresso_nem_gravado_em_metros(transitability):
    """Antes: 'Rugosidade acima de 0,01 m (P90 da cena)...' e a chave
    'limiar_rugosidade_m' no log. VRM (Sappington et al. 2007) e adimensional
    em [0, 1]; nao ha metro nenhum nele.
    """
    class _Feedback:
        def __init__(self):
            self.infos = []

        def pushInfo(self, mensagem):
            self.infos.append(mensagem)

        def pushWarning(self, mensagem):
            self.infos.append(mensagem)

    gerador = np.random.default_rng(3)
    slope = gerador.uniform(0.0, 80.0, (40, 40)).astype(np.float32)
    rugosidade = gerador.uniform(0.0, 0.05, (40, 40)).astype(np.float32)
    valido = np.ones(slope.shape, dtype=bool)

    feedback = _Feedback()
    _, metricas = transitability.classify(
        slope, valido, roughness=rugosidade, feedback=feedback)

    assert "limiar_rugosidade_m" not in metricas, sorted(metricas)
    assert "limiar_rugosidade_vrm" in metricas, sorted(metricas)
    assert 0.0 <= metricas["limiar_rugosidade_vrm"] <= 1.0

    linha = [i for i in feedback.infos if "Rugosidade" in i]
    assert linha, feedback.infos
    assert " m " not in linha[0] and not linha[0].rstrip().endswith(" m")
    assert "adimensional" in linha[0]
