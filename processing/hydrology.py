"""Drainage network extracted from the DEM itself.

Watercourses are the constraint that topography alone cannot express. A route
that is excellent on slope and curvature may still be unusable because it fords
a stream every kilometre, and until now nothing in TopoTrail knew that streams
existed.

The obvious fix -- ask the user for a hydrography layer -- fails exactly where
the plugin most needs to work: outside the country whose official datasets the
author happens to have. Official hydrography is distributed differently in every
jurisdiction, under different licences, at different scales, and often not at
all for the area someone is planning in.

So the network is derived from the DEM, which the user already supplied. The
method is standard and has no free parameters other than the channel-initiation
threshold:

1. **Priority-Flood with epsilon** fills depressions while imposing a strictly
   descending gradient across filled flats, so every cell drains
   (Barnes, R., Lehman, C. & Mulla, D. 2014, Computers & Geosciences 62: 117-127).
   A vectorised Planchon-Darboux was tried first and rejected: without
   directional sweeps it propagates one cell per pass, and on a real DEM it had
   not converged after 400 whole-array passes, leaving a fifth of the cells with
   nowhere to drain and halving the drainage density. Priority-Flood is exact;
   the cost is that it is inherently sequential, which is why the working grid
   is capped (see MAX_HYDROLOGY_CELLS).
2. **D8** assigns each cell to its steepest downslope neighbour, weighting
   diagonal steps by sqrt(2) (O'Callaghan, J.F. & Mark, D.M. 1984, Computer
   Vision, Graphics and Image Processing 28: 323-344).
3. **Flow accumulation** is propagated in descending elevation order.
4. Cells whose upslope contributing area exceeds the threshold are channels.
5. The same accumulation gives the Topographic Wetness Index for free.

The threshold is a real methodological choice and should be reported. A useful
check is drainage density: humid mountainous terrain typically falls between
1 and 3 km of channel per km2, and a threshold that lands far outside that band
is probably wrong for the landscape. Note that measured density also falls as
the working cell grows, so the working pixel size is reported alongside it and
both belong in any methods section that cites these numbers.

Only NumPy and the standard library are required.
"""

import heapq

import numpy as np

# Vizinhanca de 8 celulas, na ordem usada por todo o modulo.
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

# Incremento aplicado sobre areas aplainadas pelo preenchimento. Precisa ser
# pequeno perto da precisao vertical do MDE e grande o bastante para sobreviver
# ao float64; sem ele o fluxo estagna nos flats e a acumulacao nao se propaga.
FLAT_EPSILON_M = 1e-3

# Teto de celulas para o calculo hidrologico. A geometria da rede a um limiar de
# ordem de 1 km2 nao precisa da resolucao do MDE -- produtos globais de drenagem
# trabalham entre 90 e 500 m -- e a acumulacao de fluxo e inerentemente
# sequencial, entao uma grade grande demais trava a interface. Acima deste teto
# o modulo trabalha numa grade reamostrada por um fator inteiro e devolve a
# mascara na resolucao original.
MAX_HYDROLOGY_CELLS = 1_200_000

# Limite de iteracoes do preenchimento. Cada iteracao e uma passagem NumPy sobre
# a grade inteira; na pratica a convergencia vem em dezenas de passagens.
MAX_FILL_ITERATIONS = 400

# Piso da declividade no denominador do TWI. tan(beta) tende a zero em terreno
# plano e o indice iria ao infinito; 0.001 corresponde a 0,057 graus, abaixo da
# precisao de qualquer MDE.
MIN_TAN_BETA = 0.001


def fill_depressions(dem_array, feedback=None):
    """Priority-Flood + epsilon. Devolve a superficie preenchida (float64).

    As saidas sao a borda da grade e as bordas do nodata. A fila de prioridade
    garante que cada celula seja fixada no menor nivel a partir do qual a agua
    consegue sair, e o epsilon impoe gradiente estritamente descendente sobre as
    areas aplainadas -- sem ele o fluxo estagna nos flats e a acumulacao nao se
    propaga.
    """
    rows, cols = dem_array.shape
    filled = np.where(np.isfinite(dem_array), dem_array, np.inf).astype(np.float64)
    invalid = ~np.isfinite(dem_array)
    closed = invalid.copy()

    heap = []
    push = heapq.heappush
    for row in range(rows):
        for col in (0, cols - 1):
            if not closed[row, col]:
                push(heap, (filled[row, col], row, col))
                closed[row, col] = True
    for col in range(cols):
        for row in (0, rows - 1):
            if not closed[row, col]:
                push(heap, (filled[row, col], row, col))
                closed[row, col] = True
    if invalid.any():
        border = np.zeros((rows, cols), bool)
        for d_row, d_col in NEIGHBOURS:
            border |= _shift_bool(invalid, d_row, d_col, rows, cols)
        border &= ~closed
        for row, col in np.argwhere(border):
            row, col = int(row), int(col)
            closed[row, col] = True
            push(heap, (filled[row, col], row, col))

    pop = heapq.heappop
    while heap:
        level, row, col = pop(heap)
        for d_row, d_col in NEIGHBOURS:
            n_row, n_col = row + d_row, col + d_col
            if not (0 <= n_row < rows and 0 <= n_col < cols) or closed[n_row, n_col]:
                continue
            closed[n_row, n_col] = True
            if filled[n_row, n_col] <= level:
                filled[n_row, n_col] = level + FLAT_EPSILON_M
            push(heap, (filled[n_row, n_col], n_row, n_col))
    return filled


def _shift_bool(array, d_row, d_col, rows, cols):
    out = np.zeros_like(array)
    out[max(0, -d_row):rows + min(0, -d_row), max(0, -d_col):cols + min(0, -d_col)] = \
        array[max(0, d_row):rows + min(0, d_row), max(0, d_col):cols + min(0, d_col)]
    return out


def _shift(array, d_row, d_col, rows, cols):
    """out[r, c] = array[r + d_row, c + d_col], com inf fora da grade."""
    out = np.full_like(array, np.inf)
    out[max(0, -d_row):rows + min(0, -d_row), max(0, -d_col):cols + min(0, -d_col)] = \
        array[max(0, d_row):rows + min(0, d_row), max(0, d_col):cols + min(0, d_col)]
    return out


def flow_direction(filled, pixel_size_x, pixel_size_y):
    """D8: indice do vizinho de maior declive, ou -1 quando nao ha jusante."""
    rows, cols = filled.shape
    diagonal = float(np.hypot(pixel_size_x, pixel_size_y))
    step = np.array([diagonal, pixel_size_y, diagonal, pixel_size_x,
                     pixel_size_x, diagonal, pixel_size_y, diagonal])

    direction = np.full((rows, cols), -1, np.int8)
    steepest = np.zeros((rows, cols), np.float64)
    for index, (d_row, d_col) in enumerate(NEIGHBOURS):
        with np.errstate(invalid="ignore"):
            drop = (filled - _shift(filled, d_row, d_col, rows, cols)) / step[index]
        better = drop > steepest
        steepest[better] = drop[better]
        direction[better] = index
    return direction


def flow_accumulation(direction, valid, filled):
    """Numero de celulas a montante, incluindo a propria celula."""
    rows, cols = direction.shape
    accumulated = valid.astype(np.int64)

    order = np.argsort(-np.where(valid, filled, -np.inf).ravel(), kind="stable")
    flat_direction = direction.ravel()
    flat_accumulated = accumulated.ravel()
    flat_valid = valid.ravel()

    for index in order:
        if not flat_valid[index]:
            break                                   # invalidos ficam no fim
        neighbour = flat_direction[index]
        if neighbour < 0:
            continue
        d_row, d_col = NEIGHBOURS[neighbour]
        row, col = divmod(int(index), cols)
        n_row, n_col = row + d_row, col + d_col
        if 0 <= n_row < rows and 0 <= n_col < cols:
            target = n_row * cols + n_col
            if flat_valid[target]:
                flat_accumulated[target] += flat_accumulated[index]
    return accumulated


def wetness_index(accumulated, filled, pixel_size_x, pixel_size_y, valid):
    """Indice topografico de umidade: ln(a / tan(beta)).

    Beven, K.J. & Kirkby, M.J. (1979) A physically based, variable contributing
    area model of basin hydrology. Hydrological Sciences Bulletin 24: 43-69.

    `a` e a area de contribuicao especifica -- area a montante dividida pela
    largura da curva de nivel, aqui o tamanho da celula. Valores altos indicam
    terreno que recebe muita agua e escoa mal: fundo de vale, cabeceira umida,
    brejo. Para trilha isso importa duas vezes -- lama e atoleiro no uso, e
    erosao acelerada ao longo do tempo, que e o mecanismo dominante de
    degradacao de trilha na literatura.

    Calculado sobre a superficie preenchida, como e padrao, para que a
    declividade seja consistente com as direcoes de fluxo.
    """
    rows, cols = accumulated.shape
    cell_area = pixel_size_x * pixel_size_y
    contour_width = (pixel_size_x + pixel_size_y) / 2.0
    specific_area = (accumulated.astype(np.float64) * cell_area) / contour_width

    # Derivada sobre a superficie com nodata preenchido pelo vizinho valido mais
    # proximo: derivar uma superficie com NaN propagava NaN um anel para dentro
    # da borda, e nan_to_num no modelo lia esse anel como "o mais umido".
    _masked_gradient = _terrain_masked_gradient()
    surface = np.asarray(filled, dtype=np.float64)
    finite = np.isfinite(surface)
    dz_dy, dz_dx = _masked_gradient(surface, finite, pixel_size_y, pixel_size_x)
    dz_dy = np.where(finite, dz_dy, 0.0)
    dz_dx = np.where(finite, dz_dx, 0.0)
    tan_beta = np.maximum(np.hypot(dz_dx, dz_dy), MIN_TAN_BETA)

    with np.errstate(divide="ignore", invalid="ignore"):
        twi = np.log(np.maximum(specific_area, 1e-6) / tan_beta)
    twi = np.where(valid & np.isfinite(twi), twi, np.nan).astype(np.float32)
    return twi


def stream_network(dem_array, transform, min_basin_km2=1.0, feedback=None):
    """Compatibilidade: devolve apenas a mascara de canais e as metricas."""
    channels, _twi, metrics = analyse_hydrology(
        dem_array, transform, min_basin_km2, feedback)
    return channels, metrics


def _terrain_masked_gradient():
    """Importa terrain._masked_gradient mesmo quando este modulo e carregado por caminho."""
    try:
        from .terrain import _masked_gradient
        return _masked_gradient
    except ImportError:
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location(
            "_topotrail_terrain", os.path.join(os.path.dirname(os.path.abspath(__file__)), "terrain.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module._masked_gradient


def analyse_hydrology(dem_array, transform, min_basin_km2=1.0, feedback=None,
                      warn_about_width=True, return_basin_area=False):
    """Rede de drenagem e indice de umidade, numa unica passagem.

    Devolve (canais, twi, metricas) -- ou (canais, twi, bacia_km2, metricas)
    com `return_basin_area=True`, onde bacia_km2 e a area de contribuicao de
    cada celula, o que permite graduar a travessia de um curso d'agua pelo
    tamanho dele. `min_basin_km2` e a area de contribuicao a partir da qual uma
    celula e considerada canal. Grades acima de MAX_HYDROLOGY_CELLS sao
    reamostradas por um fator inteiro para o calculo e a mascara e devolvida na
    resolucao original.
    """
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError("Resolucao espacial invalida para extrair a drenagem.")
    if not np.any(np.isfinite(dem_array)):
        raise ValueError("O MDE nao possui celulas validas para extrair a drenagem.")

    full_rows, full_cols = dem_array.shape
    factor = int(np.ceil(np.sqrt(dem_array.size / MAX_HYDROLOGY_CELLS)))
    factor = max(1, factor)
    if factor > 1:
        work = dem_array[::factor, ::factor]
        work_px, work_py = pixel_size_x * factor, pixel_size_y * factor
        if feedback:
            feedback.pushInfo(
                "Hidrologia calculada em grade reamostrada {}x ({} x {} celulas, "
                "pixel {:.0f} m) para manter o tempo de resposta.".format(
                    factor, work.shape[1], work.shape[0], work_px)
            )
    else:
        work, work_px, work_py = dem_array, pixel_size_x, pixel_size_y

    valid = np.isfinite(work)
    filled = fill_depressions(work, feedback=feedback)
    direction = flow_direction(filled, work_px, work_py)
    accumulated = flow_accumulation(direction, valid, filled)
    twi = wetness_index(accumulated, filled, work_px, work_py, valid)

    pixel_area_km2 = (work_px * work_py) / 1e6
    basin_km2 = np.where(valid, accumulated * pixel_area_km2, np.nan).astype(np.float32)
    channels = valid & (basin_km2 >= float(min_basin_km2))

    # Densidade de drenagem: cada celula de canal contribui aproximadamente o
    # comprimento do seu passo a jusante. Serve para aferir o limiar escolhido.
    diagonal = float(np.hypot(work_px, work_py))
    step_length = np.where(
        np.isin(direction, (0, 2, 5, 7)), diagonal,
        np.where(np.isin(direction, (1, 6)), work_py, work_px),
    )
    network_km = float(step_length[channels].sum() / 1000.0) if np.any(channels) else 0.0
    area_km2 = float(valid.sum() * pixel_area_km2)

    metrics = {
        "limiar_bacia_km2": float(min_basin_km2),
        "fator_reamostragem": factor,
        "pixel_trabalho_m": work_px,
        "area_pixel_km2": pixel_area_km2,
        "area_valida_km2": area_km2,
        "celulas_canal": int(channels.sum()),
        "proporcao_canal": float(channels.sum() / max(1, int(valid.sum()))),
        "rede_km": network_km,
        "densidade_drenagem_km_por_km2": (network_km / area_km2) if area_km2 else None,
        "celulas_sem_jusante": int((direction < 0)[valid].sum()),
        # Largura minima que a rede ocupa depois de voltar a resolucao original.
        # A mascara e reamostrada por blocos, entao um canal nunca fica mais
        # estreito que o pixel de trabalho, por menor que seja o buffer pedido.
        "largura_minima_efetiva_m": max(work_px, work_py),
        "twi_p05": float(np.nanpercentile(twi, 5)) if np.any(np.isfinite(twi)) else None,
        "twi_p50": float(np.nanpercentile(twi, 50)) if np.any(np.isfinite(twi)) else None,
        "twi_p95": float(np.nanpercentile(twi, 95)) if np.any(np.isfinite(twi)) else None,
    }

    if factor > 1:
        def expand(array, fill):
            grown = np.repeat(np.repeat(array, factor, axis=0), factor, axis=1)
            grown = grown[:full_rows, :full_cols]
            if grown.shape != dem_array.shape:                   # borda truncada
                padded = np.full(dem_array.shape, fill, dtype=array.dtype)
                padded[:grown.shape[0], :grown.shape[1]] = grown
                grown = padded
            return grown
        channels = expand(channels, False)
        twi = expand(twi, np.nan)
        basin_km2 = expand(basin_km2, np.nan)

    if feedback:
        density = metrics["densidade_drenagem_km_por_km2"]
        feedback.pushInfo(
            "Drenagem extraida do MDE: limiar {:.2f} km2, {:,.0f} km de rede em "
            "{:,.0f} km2, densidade {:.2f} km/km2.".format(
                float(min_basin_km2), network_km, area_km2, density or 0.0)
        )
        if factor > 1 and warn_about_width:
            feedback.pushWarning(
                "A rede foi calculada em pixel de {:.0f} m, entao cada curso d'agua "
                "ocupa pelo menos essa largura ao voltar para a grade do MDE -- um "
                "afastamento pedido menor que isso nao tem efeito pratico. Para uma "
                "faixa mais estreita, recorte a area de estudo ou forneca uma camada "
                "de hidrografia vetorial.".format(max(work_px, work_py))
            )
        if density is not None and not (0.5 <= density <= 5.0):
            feedback.pushWarning(
                "A densidade de drenagem resultante ({:.2f} km/km2) esta fora da faixa "
                "usual de 1 a 3 km/km2 para relevo montanhoso. Se a rede parecer densa "
                "demais aumente o limiar de area de contribuicao; se parecer esparsa "
                "demais, reduza.".format(density)
            )
    if return_basin_area:
        return channels, twi, basin_km2, metrics
    return channels, twi, metrics
