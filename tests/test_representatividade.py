"""Representatividade das zonas: em quantas faixas do relevo da area elas estao.

Na bateria de 06/10 as zonas de acesso das Carnaubas cobriam so 61% do
gradiente de altitude do parque (99% com as faixas de altitude ligadas), e
nada no plugin dizia isso a quem ia planejar a amostragem.
"""

import numpy as np


def _rampa(linhas=100, colunas=100):
    """Altitude crescendo de oeste para leste, 1 m por coluna."""
    return np.tile(np.arange(colunas, dtype=float), (linhas, 1)) + 1000.0


def test_zonas_so_na_metade_baixa_cobrem_metade_do_gradiente(algorithm):
    dem = _rampa()
    area = np.ones(dem.shape, bool)
    zonas = dem < 1050.0                                   # so a metade oeste
    r = algorithm.zone_representativeness(zonas, area, {"altitude": dem})
    alt = r["altitude"]
    assert alt["faixas"] == 10
    assert alt["faixas_cobertas"] == 5
    assert len(alt["faltam"]) == 1                         # faixas vizinhas viram um intervalo so
    baixo, alto = alt["faltam"][0]
    assert 1049.0 <= baixo <= 1051.0 and alto == 1099.0
    assert alt["ks_d"] == 1.0                              # zonas e resto nao se sobrepoem


def test_zonas_espalhadas_cobrem_todo_o_gradiente(algorithm):
    dem = _rampa()
    area = np.ones(dem.shape, bool)
    zonas = np.zeros(dem.shape, bool)
    zonas[::4, :] = True                                   # uma linha a cada quatro, de ponta a ponta
    r = algorithm.zone_representativeness(zonas, area, {"altitude": dem})
    assert r["altitude"]["faixas_cobertas"] == 10 and r["altitude"]["faltam"] == []
    assert r["altitude"]["ks_d"] < 0.05


def test_a_frase_diz_o_que_falta_e_o_que_fazer(algorithm):
    dem = _rampa()
    area = np.ones(dem.shape, bool)
    r = algorithm.zone_representativeness(dem < 1050.0, area, {"altitude": dem, "umidade": None})
    frase, aviso = algorithm.describe_representativeness(r, altitude_bands_on=False)
    assert aviso
    assert "altitude em 5 de 10 faixas" in frase and "faltam 1050–1099 m" in frase
    assert "ligue \"Equilibrar zonas por faixa altimétrica\"" in frase
    assert "MapBiomas" in frase                            # o MDE nao ve a cobertura do solo
    # com as faixas ja ligadas, a sugestao muda
    frase2, _ = algorithm.describe_representativeness(r, altitude_bands_on=True)
    assert "Mesmo com as faixas de altitude" in frase2


def test_cobertura_completa_nao_vira_aviso(algorithm):
    dem = _rampa()
    zonas = np.zeros(dem.shape, bool)
    zonas[::4, :] = True
    r = algorithm.zone_representativeness(zonas, np.ones(dem.shape, bool), {"altitude": dem})
    frase, aviso = algorithm.describe_representativeness(r)
    assert not aviso and "altitude em 10 de 10 faixas" in frase


def test_face_norte_tem_o_sinal_certo(algorithm):
    # z sobe para o sul (linha cresce para o sul com pixel de altura negativa):
    # a encosta desce para o norte, isto e, esta voltada para o norte
    linhas = np.arange(50, dtype=float)[:, None] * np.ones((1, 50))
    norte = algorithm.northness(linhas * 2.0, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0))
    assert np.allclose(norte, 1.0)
    sul = algorithm.northness(-linhas * 2.0, (0.0, 30.0, 0.0, 0.0, 0.0, -30.0))
    assert np.allclose(sul, -1.0)
    plano = algorithm.northness(np.zeros((10, 10)), (0.0, 30.0, 0.0, 0.0, 0.0, -30.0))
    assert np.all(plano == 0.0)


def test_sem_zonas_ou_sem_dados_nao_ha_relatorio(algorithm):
    dem = _rampa()
    assert algorithm.zone_representativeness(np.zeros(dem.shape, bool), np.ones(dem.shape, bool),
                                             {"altitude": dem}) == {}
    assert algorithm.describe_representativeness({}) == (None, False)
