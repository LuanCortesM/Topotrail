"""Defeitos achados na revisao de codigo antes da 1.5.0 (25/10/2026).

Cada teste reproduz o cenario do revisor e falha contra o codigo anterior a
correcao.
"""

import math

import numpy as np


def _contatos(algorithm, eixo, area, classes, caminho):
    return algorithm.detect_stream_crossings(caminho, eixo, area, classes)


def test_dois_cursos_diferentes_a_90_m_sao_duas_travessias(algorithm):
    """Um corrego de 1 km2 e um riacho de 8 km2 a 90 m: eram fundidos num evento
    so, e a travessia maior sumia da lista conferida em campo."""
    eixo = np.zeros((5, 30), bool); eixo[:, 10] = True; eixo[:, 13] = True
    area = np.full(eixo.shape, np.nan, np.float32); area[:, 10] = 1.0; area[:, 13] = 8.0
    classes = np.full(eixo.shape, -1, np.int8); classes[:, 10] = 0; classes[:, 13] = 1
    eventos = algorithm.merge_stream_contacts(
        _contatos(algorithm, eixo, area, classes, [(2, c) for c in range(30)]), 30.0)
    assert len(eventos) == 2
    assert [e["classe"] for e in eventos] == [0, 1]
    assert all(e["tipo"] == "travessia" for e in eventos)


def test_no_mde_de_90_m_a_rota_ao_longo_do_rio_continua_sendo_um_trecho(algorithm):
    """Com 150 m fixos, a 90 m o toque a cada 3 celulas (270 m) virava 10
    "travessias" -- o problema do Batedor de volta no GLO-90 das Carnaubas."""
    eixo = np.zeros((5, 40), bool); eixo[2, 2:32:3] = True
    area = np.where(eixo, 1.5, np.nan).astype(np.float32)
    classes = np.where(eixo, 0, -1).astype(np.int8)
    eventos = algorithm.merge_stream_contacts(
        _contatos(algorithm, eixo, area, classes, [(2, c) for c in range(40)]), 90.0)
    assert len(eventos) == 1 and eventos[0]["tipo"] == "junto ao curso"
    assert eventos[0]["contatos"] == 10


def test_a_extensao_junto_ao_curso_nao_infla_nas_diagonais(algorithm):
    """Rota diagonal ao lado de um canal diagonal: cada passo inseria um canto e
    a distancia somava 1 + 1 onde a rota andou raiz de 2 (+41%)."""
    n = 30
    eixo = np.zeros((n + 2, n + 2), bool)
    for k in range(n):
        eixo[k, k + 1] = True                      # canal na diagonal colada a rota
    area = np.where(eixo, 1.0, np.nan).astype(np.float32)
    classes = np.where(eixo, 0, -1).astype(np.int8)
    caminho = [(k, k) for k in range(n)]           # cada passo corta o canto do canal
    eventos = algorithm.merge_stream_contacts(
        _contatos(algorithm, eixo, area, classes, caminho), 30.0)
    assert len(eventos) == 1
    real = (n - 2) * math.sqrt(2.0) * 30.0         # do primeiro ao ultimo canto
    assert abs(eventos[0]["extensao_m"] - real) <= 30.0, (eventos[0]["extensao_m"], real)


def test_rio_acima_do_teto_sai_das_zonas_e_o_vadeavel_fica(algorithm):
    """O rio que a rota nao cruza (e o mapa chama de intransitavel) entrava nas
    zonas; a margem vadeavel continua dentro, nos dois modos."""
    shape = (5, 9)
    fator = np.ones(shape); fator[:, 2] = 1.0; fator[:, 6] = np.inf
    for modo in (algorithm.CONSTRAINT_AVOID, algorithm.CONSTRAINT_PENALISE):
        _rota, zonas, _pen, barreira, tratamento = algorithm.combine_constraints(
            np.ones(shape, bool), np.ones(shape, bool), None, fator, modo)
        assert zonas[:, 2].all() and not zonas[:, 6].any()
        assert barreira[:, 6].all() and tratamento


def test_face_norte_sem_dado_e_nan_e_nao_plano(algorithm):
    dem = np.tile(np.arange(10, dtype=float)[:, None], (1, 10))
    dem[4, 4] = np.nan
    norte = algorithm.northness(dem, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0))
    assert np.isnan(norte[4, 4]) and np.isnan(norte[3, 4])
    assert np.allclose(norte[8, 8], 1.0)


def test_pixel_retangular_nao_entorta_a_face(algorithm):
    """Encosta a 45 graus no plano, com pixel de 30 x 60 m: sem o espacamento,
    o gradiente em celulas pendia para um lado."""
    linhas, colunas = np.mgrid[0:20, 0:20].astype(float)
    dem = linhas * 60.0 + colunas * 30.0               # sobe 1 m por metro nos dois sentidos
    norte = algorithm.northness(dem, (0.0, 30.0, 0.0, 0.0, 0.0, -60.0))
    assert abs(float(norte[10, 10]) - math.sqrt(0.5)) < 1e-6


def test_o_conselho_da_representatividade_segue_o_modo(algorithm):
    dem = np.tile(np.arange(100, dtype=float), (100, 1)) + 1000.0
    rep = algorithm.zone_representativeness(dem < 1030.0, np.ones(dem.shape, bool), {"altitude": dem})
    caminhavel, aviso = algorithm.describe_representativeness(rep, walkability=True)
    assert aviso and "zonas caminhaveis" in caminhavel and "ligue 'Equilibrar zonas por faixa altimetrica'" not in caminhavel
    manual, _ = algorithm.describe_representativeness(rep, bands_need_auto_threshold=True)
    assert "limiar em 0" in manual and "ligue 'Equilibrar zonas por faixa altimetrica'" not in manual


def test_aviso_de_celula_grossa_quando_quem_engrossa_e_a_reamostragem(hydrology, monkeypatch):
    """MDE de 30 m reamostrado por falta de memoria: o aviso mandava "use um MDE
    de 30 m" a quem ja usava um."""
    class _Avisos:
        def __init__(self):
            self.avisos = []

        def pushInfo(self, mensagem):
            pass

        def pushWarning(self, mensagem):
            self.avisos.append(mensagem)

    monkeypatch.setattr(hydrology, "MAX_HYDROLOGY_CELLS", 400)
    y, x = np.mgrid[0:40, 0:40].astype(np.float64)
    dem = 500.0 - y * 2.0 + np.abs(x - 20.0) * 3.0
    fb = _Avisos()
    hydrology.analyse_hydrology(dem, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0), min_basin_km2=0.05,
                                feedback=fb, warn_about_width=True)
    grossa = [a for a in fb.avisos if "hidrografia oficial" in a]
    assert grossa and "recorte a area de estudo" in grossa[0] and "use um MDE de 30 m" not in grossa[0]
