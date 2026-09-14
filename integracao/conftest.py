"""Suite de integracao: GDAL e QGIS de verdade, sem nenhum substituto.

A suite de `tests/` e hermetica de proposito -- substitui `osgeo` e `qgis` por
modulos falsos para rodar em qualquer maquina em cinco segundos. O preco e que
ela nao ve nada que dependa do comportamento real do GDAL, e foi exatamente ai
que passou o pior defeito que a auditoria da 1.2.0 encontrou: gravar a saida num
GeoPackage existente apagava as camadas do usuario. Nenhum teste unitario podia
ter pego isso, porque no substituto `GetDriverByName` devolve None.

Esta suite roda o pacote instalado, com as bibliotecas de verdade, e e pulada
inteira onde elas nao existirem.

    /usr/bin/python3.12 -m pytest integracao -q
"""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _real(nome):
    """Importa de verdade, recusando qualquer substituto deixado por outra suite."""
    modulo = sys.modules.get(nome)
    if modulo is not None and getattr(modulo, "__topotrail_stub__", False):
        return None
    try:
        return __import__(nome, fromlist=["*"])
    except Exception:
        return None


@pytest.fixture(scope="session")
def ogr():
    modulo = _real("osgeo.ogr")
    if modulo is None or modulo.GetDriverByName("GPKG") is None:
        pytest.skip("GDAL com driver GPKG nao disponivel")
    modulo.UseExceptions()
    return modulo


@pytest.fixture(scope="session")
def osr():
    modulo = _real("osgeo.osr")
    if modulo is None:
        pytest.skip("GDAL/OSR nao disponivel")
    return modulo


@pytest.fixture(scope="session")
def plugin():
    """O pacote do plugin como ele e importado dentro do QGIS."""
    pai = os.path.dirname(RAIZ)
    if pai not in sys.path:
        sys.path.insert(0, pai)
    try:
        modulo = __import__(
            "{}.processing.algorithm".format(os.path.basename(RAIZ)),
            fromlist=["algorithm"])
    except Exception as erro:      # pragma: no cover - depende do ambiente
        pytest.skip("plugin nao importavel fora do QGIS: {}".format(erro))
    return modulo
