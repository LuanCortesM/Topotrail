"""Superficies sinteticas usadas pelos testes.

Vivia em conftest.py, e `from conftest import ...` e ambiguo assim que
existe mais de um conftest no projeto: coletar tests/ e integracao/ na mesma
chamada fazia o conftest da integracao responder pelo nome e a importacao
quebrava. Um modulo proprio nao tem esse problema.
"""
import numpy as np


def inclined_plane(rows, cols, spacing, slope_ratio, axis="x"):
    """A perfect plane of known gradient, for closed-form comparison."""
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    distance = (x if axis == "x" else y) * spacing
    return (distance * slope_ratio).astype(np.float32)
