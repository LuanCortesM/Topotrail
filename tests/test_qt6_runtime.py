"""A janela realmente roda sobre Qt6 -- e não apenas passa na inspeção estática.

O QGIS 4 roda sobre Qt6. A checagem estática de `tests/test_qt6_compat.py` pega
o enum solto que ela conhece, e não pegou `QPainter.Antialiasing`, que só
apareceu quando a janela foi construída de fato sob PyQt6. Daí este teste.

Roda num processo separado porque PyQt5 e PyQt6 não convivem no mesmo
interpretador, e o resto da suíte usa o QGIS, que hoje é Qt5.
"""

import pathlib
import subprocess
import sys

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "qt6" / "harness.py"


PROVA = (
    "import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; "
    "from PyQt6.QtWidgets import QApplication; QApplication([]); print('QT6_OK')"
)


def _tem_pyqt6(executavel):
    """Só conta se der para SUBIR um QApplication offscreen nesse interpretador.

    Importar PyQt6 não basta: num runner sem libEGL/libxkbcommon o pacote
    importa e o plugin de plataforma falha ao carregar -- e aí o harness
    aborta e o teste acusaria um problema do plugin que é do ambiente.
    """
    resultado = subprocess.run([executavel, "-c", PROVA], capture_output=True, text=True)
    return resultado.returncode == 0 and "QT6_OK" in resultado.stdout


def _interpretador():
    if _tem_pyqt6(sys.executable):
        return sys.executable
    for alternativa in ("python3", "python3.11", "python3.12", "python3.13"):
        caminho = subprocess.run(["which", alternativa],
                                 capture_output=True, text=True).stdout.strip()
        if caminho and _tem_pyqt6(caminho):
            return caminho
    return None


def test_the_window_runs_under_qt6():
    executavel = _interpretador()
    if executavel is None:
        pytest.skip("PyQt6 não está instalado em nenhum interpretador disponível")

    resultado = subprocess.run([executavel, str(HARNESS)],
                               capture_output=True, text=True, timeout=300)
    saida = resultado.stdout + resultado.stderr
    assert "Traceback" not in saida, f"a janela quebrou sob Qt6:\n{saida[-1800:]}"
    assert "TOTAL=0" in saida, f"problemas sob Qt6:\n{saida[-1800:]}"
    assert resultado.returncode == 0
