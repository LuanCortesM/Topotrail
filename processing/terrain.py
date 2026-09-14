"""Terrain derivatives computed from the working DEM.

TopoTrail historically required the user to supply slope and both curvatures as
separate rasters. That requirement was the single largest barrier to using the
plugin: it forced three Processing runs before the tool could be opened, and it
made the result depend on choices the plugin could not see -- the unit of the
slope raster (degrees or percent), the sign convention and magnitude scale of
the curvature provider, and whether the derived rasters shared the DEM's grid.

Deriving them here removes all four problems at once. The derivatives are
computed on the projected metric working DEM, so pixel spacing is in metres and
the same everywhere, and they are aligned to the DEM by construction.

Only NumPy is required; nothing here touches QGIS or GDAL.
"""

import numpy as np


# Acima disto a derivacao de relevo passa a ser um risco para o processo do
# QGIS, nao so uma espera. O MDE e promovido a float64 e cada gradiente cria
# varios temporarios de grade cheia.
#
# A constante valia 134, medida com tracemalloc so dentro de derive_terrain e
# vector_ruggedness em grades de 1000x1000. Isso media a derivacao, nao a
# execucao: a auditoria mediu 205,2 bytes por celula no caminho completo e a
# promessa de "13,4 GB" em 100 milhoes de celulas era 53% menor que o consumo
# real. Remedido aqui com resource.getrusage(RUSAGE_SELF).ru_maxrss, pico de
# processo menos a linha de base, numa grade de 3.000 x 3.000 = 9.000.000 de
# celulas (medir_memoria.py, um subprocesso limpo por caso):
#
#   derivando do MDE, sem hidrologia .................... 130,7 B/celula
#   rasters proprios, sem hidrologia .................... 103,5 B/celula
#   derivando do MDE + drenagem + umidade + rugosidade .. 206,4 B/celula
#   rasters proprios + drenagem + umidade + rugosidade .. 206,7 B/celula
#
# Vale o pior caminho, 206,7, arredondado para 230 -- 11% de folga declarada,
# porque o pico depende do alocador e da fragmentacao e subestimar aqui e o
# erro que derruba a sessao do usuario. Com isso 8 milhoes de celulas ficam em
# torno de 1,8 GB (aviso) e 100 milhoes passam de 23 GB (erro, com instrucao de
# recortar).
WARN_TERRAIN_CELLS = 8_000_000
MAX_TERRAIN_CELLS = 100_000_000
BYTES_POR_CELULA = 230


def check_terrain_size(dem_array, feedback=None):
    """Avisa ou barra grades cuja derivacao estouraria a memoria do QGIS."""
    celulas = int(np.asarray(dem_array).size)
    gb = "{:.1f}".format(celulas * BYTES_POR_CELULA / 1e9).replace(".", ",")
    quantas = "{:,}".format(celulas).replace(",", ".")
    if celulas > MAX_TERRAIN_CELLS:
        raise ValueError(
            "O MDE tem {} celulas; derivar declividade, curvaturas e rugosidade "
            "exigiria cerca de {} GB de memoria transitoria e muito provavelmente "
            "encerraria o QGIS. Recorte o MDE para a area de interesse "
            "(Raster > Extrair > Cortar pelo retangulo) ou reamostre para uma "
            "celula maior antes de rodar.".format(quantas, gb))
    if celulas > WARN_TERRAIN_CELLS and feedback:
        feedback.pushWarning(
            "MDE grande: {} celulas. A derivacao pode usar cerca de {} GB de "
            "memoria e levar varios minutos. Recortar a area de interesse deixa "
            "o resultado igual e a espera menor.".format(quantas, gb))


def _metric_spacing(transform):
    pixel_size_x = abs(float(transform[1]))
    pixel_size_y = abs(float(transform[5]))
    if pixel_size_x <= 0 or pixel_size_y <= 0:
        raise ValueError(
            "Resolucao espacial invalida no GeoTransform para derivar o relevo."
        )
    return pixel_size_x, pixel_size_y


def _filled_for_gradient(dem_array):
    """Devolve (superficie float64 com NaN, mascara_valida). Mantido pelo nome.

    O preenchimento em si deixou de existir: a derivada e calculada por
    `_masked_gradient`, que usa diferenca unilateral onde falta um vizinho
    valido. A versao anterior preenchia o nodata com a MEDIA da cena e
    derivava sobre isso, e toda celula encostada no nodata saia com
    (z - media)/(2*px): numa rampa de 30% a 2000 m, 247%; num MDE reprojetado
    (borda inclinada em toda a volta), centenas de celulas "escarpadas" num
    relevo sem nada acima de 40%.
    """
    dem = dem_array.astype(np.float64)
    valid = np.isfinite(dem)
    return dem, valid


def _masked_gradient(surface, valid, spacing_y, spacing_x):
    """Gradiente (dz/dy, dz/dx) que respeita o nodata.

    Central onde os dois vizinhos do eixo sao validos; unilateral (forward ou
    backward) onde so um e; zero onde nenhum e -- e a mesma regra que o
    np.gradient aplica na borda do array, estendida a borda do dado. Celulas
    invalidas saem NaN.
    """
    z = np.where(valid, surface, 0.0)
    result = []
    for axis, h in ((0, spacing_y), (1, spacing_x)):
        z_next = np.roll(z, -1, axis=axis)
        v_next = np.roll(valid, -1, axis=axis)
        z_prev = np.roll(z, 1, axis=axis)
        v_prev = np.roll(valid, 1, axis=axis)
        # np.roll da a volta: a borda do array nao tem vizinho do outro lado.
        edge_last = np.zeros_like(valid)
        edge_first = np.zeros_like(valid)
        if axis == 0:
            edge_last[-1, :] = True
            edge_first[0, :] = True
        else:
            edge_last[:, -1] = True
            edge_first[:, 0] = True
        v_next &= ~edge_last
        v_prev &= ~edge_first
        both = v_next & v_prev
        central = (z_next - z_prev) / (2.0 * h)
        forward = (z_next - z) / h
        backward = (z - z_prev) / h
        d = np.where(both, central, np.where(v_next, forward, np.where(v_prev, backward, 0.0)))
        d = np.where(valid, d, np.nan)
        result.append(d)
    return result[0], result[1]


def _require_2d(dem_array, what):
    if dem_array.ndim != 2 or min(dem_array.shape) < 2:
        raise ValueError(
            f"O MDE precisa ter pelo menos 2 x 2 celulas para derivar {what}; "
            f"recebido {tuple(dem_array.shape)}."
        )


def slope_percent_from_dem(dem_array, transform, feedback=None):
    """Slope as a percentage: 100 * tan(angle of steepest descent).

    Percentage is TopoTrail's internal unit. A 45 degree slope is 100%.
    """
    _require_2d(dem_array, "a declividade")
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)
    dz_dy, dz_dx = _masked_gradient(filled, valid, py, px)
    slope = (np.hypot(dz_dx, dz_dy) * 100.0).astype(np.float32)
    slope[~valid] = np.nan
    slope[~np.isfinite(slope)] = np.nan
    if feedback:
        finite = slope[np.isfinite(slope)]
        if finite.size:
            feedback.pushInfo(
                "Declividade derivada do MDE ({:.1f} x {:.1f} m): "
                "p50={:.1f}%, p95={:.1f}%, max={:.1f}%".format(
                    px, py, float(np.percentile(finite, 50)),
                    float(np.percentile(finite, 95)), float(finite.max()))
            )
    return slope


def curvatures_from_dem(dem_array, transform, feedback=None):
    """Plan (horizontal) and profile (vertical) curvature of the surface.

    These are the two curvatures the multicriteria model expects, and they are
    defined relative to the direction of steepest descent rather than to the
    grid axes. The forms used are the tangential ("plan") and profile normal
    curvatures of Mitasova & Hofierka (1993), evaluated with the
    central-difference gradient operator applied twice, so that all three
    second derivatives come from the same operator (see the comment in the body
    for why that homogeneity is worth its cost): on a bowl z = a(x^2 + y^2) the
    plan curvature equals 2a/(1+p)^{1/2} and the profile curvature equals
    2a/(1+p)^{3/2}. Up to version 1.2.0 the plan curvature was the geometric
    contour curvature of Moore, Grayson & Ladson (1991), which has p^{3/2} in
    the denominator and therefore diverges as the gradient goes to zero; the
    body comment records what that cost the suitability model. They are not the Zevenbergen-Thorne (1987) forms,
    which come from fitting a partial quartic to the 3x3 window rather than
    from the differential definitions, and which use the opposite profile
    sign. An earlier version of this docstring claimed ZT lacks slope
    normalisation; the claim was dropped, because it is not defensible as
    stated.

    Sign convention, verified against surfaces with known shape in
    `tests/test_terrain_math.py` rather than asserted here:

    * **negative on convex forms** -- domes, ridges, spurs, where the surface
      falls away from the cell;
    * **positive on concave forms** -- bowls, hollows, channels, where the
      surface closes in around it.

    * **plan** curvature is measured across the slope, so it captures whether
      flow spreads out or concentrates. On a cylindrical ridge, whose contours
      are straight, it is exactly zero -- the test asserts that. Being the
      normal curvature in the contour direction rather than the curvature of
      the contour line itself, it stays bounded on gentle ground, where the
      contour line curves sharply but the surface does not.
    * **profile** curvature is measured along the slope: convex breaks where
      the gradient steepens downhill are negative, concave footslopes positive.

    Both are returned in units of 1/m. A uniform change of scale does not
    matter to the suitability model, which normalises each by a percentile of
    its own distribution and scores cells by distance from zero -- so a
    provider using a different scale, or the opposite sign convention, produces
    the same result. What does matter, and what the contour form got wrong, is
    a scale that varies systematically with another criterion in the model. Flat cells, where the curvature is undefined, are returned as zero.

    References: Moore, I.D., Grayson, R.B. & Ladson, A.R. (1991) Digital
    terrain modelling: a review of hydrological, geomorphological, and
    biological applications. Hydrological Processes 5: 3-30. Mitasova, H. &
    Hofierka, J. (1993) Interpolation by regularized spline with tension: II.
    Application to terrain modeling and surface geometry analysis.
    Mathematical Geology 25: 657-669.
    """
    _require_2d(dem_array, "as curvaturas")
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)

    # As tres segundas derivadas saem do MESMO operador aplicado duas vezes, e
    # isso e deliberado. Trocar as derivadas puras por um estencil de tres
    # pontos, mantendo o termo cruzado, resolve melhor formas curtas -- 81% da
    # amplitude verdadeira numa onda de quatro celulas contra 40% -- mas quebra
    # uma propriedade que importa mais aqui: com o operador encadeado o Hessiano
    # discreto tem posto 1 sobre qualquer superficie de curvas de nivel retas,
    # de modo que a curvatura plana de uma encosta lisa fica pequena em qualquer
    # orientacao: exatamente zero nos eixos de simetria da grade e, numa varredura
    # de angulos sobre uma encosta corrugada com ondas de seis celulas, no maximo
    # 0,41% da curvatura de perfil real, a 21 graus. Misturando familias de
    # estencil isso se perde: na MESMA superficie a 45 graus, onde o operador
    # encadeado da zero exato, a curvatura plana espuria do estencil misto sobe
    # para 8,6% do sinal real -- uma feicao concava onde a superficie e lisa. Como o modelo penaliza curvatura
    # afastada de zero, encostas obliquas passariam a ser penalizadas por uma
    # forma que a superficie nao tem.
    #
    # O preco e a atenuacao em formas curtas, que fica declarada como limitacao
    # conhecida em vez de ser trocada por um artefato dependente de orientacao.
    # Os dois comportamentos estao fixados em teste.
    zy, zx = _masked_gradient(filled, valid, py, px)
    zyy, zyx = _masked_gradient(np.where(valid, zy, 0.0), valid, py, px)
    _, zxx = _masked_gradient(np.where(valid, zx, 0.0), valid, py, px)

    p = zx ** 2 + zy ** 2          # squared gradient magnitude
    q = p + 1.0

    with np.errstate(divide="ignore", invalid="ignore"):
        # Curvatura TANGENCIAL (curvatura normal na direcao da curva de nivel),
        # Mitasova & Hofierka (1993), e nao a curvatura de contorno de Moore et
        # al. (1991), que tem p^{3/2} no denominador. A diferenca nao e de
        # escala: a curvatura de contorno diverge quando o gradiente tende a
        # zero, porque e a curvatura da propria curva de nivel, que se fecha
        # cada vez mais perto de um ponto plano. Como o modelo pontua a forma
        # pela distancia a zero, o terreno mais suave -- justamente o que se
        # quer premiar -- recebia a pior nota de forma. Medido na cena da
        # Mantiqueira do capitulo, na grade de trabalho da execucao canonica
        # (543 x 434 celulas de 29,36 m): corr(log da declividade, nota de
        # forma) = +0,58, decil mais suave 0,704 contra 0,958 no mais ingreme,
        # com o criterio de forma trabalhando CONTRA o de declividade sob o
        # mesmo peso. Com a curvatura tangencial a correlacao cai para +0,06 e
        # os decis extremos ficam em 0,779 e 0,805: o criterio de forma deixa
        # de acompanhar a declividade.
        plan = np.where(
            p > 1e-12,
            (zxx * zy ** 2 - 2.0 * zyx * zx * zy + zyy * zx ** 2) / (p * np.sqrt(q)),
            0.0,
        )
        profile = np.where(
            p > 1e-12,
            (zxx * zx ** 2 + 2.0 * zyx * zx * zy + zyy * zy ** 2) / (p * np.power(q, 1.5)),
            0.0,
        )

    curv_h = plan.astype(np.float32)
    curv_v = profile.astype(np.float32)
    for array in (curv_h, curv_v):
        array[~valid] = np.nan
        array[~np.isfinite(array)] = np.nan

    if feedback:
        for name, array in (("horizontal (plan)", curv_h), ("vertical (profile)", curv_v)):
            finite = array[np.isfinite(array)]
            if finite.size:
                feedback.pushInfo(
                    "Curvatura {} derivada do MDE: p05={:.4g}, p50={:.4g}, p95={:.4g}".format(
                        name, float(np.percentile(finite, 5)),
                        float(np.percentile(finite, 50)), float(np.percentile(finite, 95)))
                )
    return curv_h, curv_v


def roughness_index(dem_array, transform=None, feedback=None):
    """Terrain Ruggedness Index: diferenca absoluta media para os 8 vizinhos.

    Riley, S.J., DeGloria, S.D. & Elliot, R. (1999) A terrain ruggedness index
    that quantifies topographic heterogeneity. Intermountain Journal of Sciences
    5: 23-27.

    Em metros. **Nao e independente da declividade**, e a documentacao anterior
    afirmava que era: numa rampa perfeitamente lisa de 80% o TRI vale 6,00 m,
    contra 3,36 m numa superficie ruidosa de declividade media 27%. Isso nao e
    defeito do indice -- e a definicao dele, a diferenca absoluta media de
    altitude, que cresce com a inclinacao. O teste que mede isso esta em
    tests/test_terrain_math.py.

    Para a rugosidade desacoplada da inclinacao, que e o que o modelo quer,
    use `vector_ruggedness`. Este indice fica disponivel por ser o padrao
    citavel e por ser util como medida de amplitude local em metros.

    Celulas de borda usam apenas os vizinhos existentes.
    """
    dem = dem_array.astype(np.float64)
    valid = np.isfinite(dem)
    rows, cols = dem.shape

    total = np.zeros((rows, cols), np.float64)
    count = np.zeros((rows, cols), np.float64)
    neighbours = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                  (0, 1), (1, -1), (1, 0), (1, 1))
    for d_row, d_col in neighbours:
        shifted = np.full((rows, cols), np.nan)
        shifted_valid = np.zeros((rows, cols), bool)
        dst = (slice(max(0, -d_row), rows + min(0, -d_row)),
               slice(max(0, -d_col), cols + min(0, -d_col)))
        src = (slice(max(0, d_row), rows + min(0, d_row)),
               slice(max(0, d_col), cols + min(0, d_col)))
        shifted[dst] = dem[src]
        shifted_valid[dst] = valid[src]
        usable = valid & shifted_valid
        total[usable] += np.abs(dem[usable] - shifted[usable])
        count[usable] += 1.0

    with np.errstate(divide="ignore", invalid="ignore"):
        tri = np.where(count > 0, total / count, np.nan).astype(np.float32)
    tri[~valid] = np.nan

    if feedback:
        finite = tri[np.isfinite(tri)]
        if finite.size:
            feedback.pushInfo(
                "Rugosidade (TRI) derivada do MDE: p50={:.2f} m, p90={:.2f} m, max={:.2f} m".format(
                    float(np.percentile(finite, 50)), float(np.percentile(finite, 90)),
                    float(finite.max()))
            )
    return tri


def vector_ruggedness(dem_array, transform, feedback=None):
    """Vector Ruggedness Measure: rugosidade desacoplada da inclinacao.

    Sappington, J.M., Longshore, K.M. & Thompson, D.B. (2007) Quantifying
    landscape ruggedness for animal habitat analysis. Journal of Wildlife
    Management 71: 1419-1426.

    Cada celula vira o vetor unitario normal a superficie, decomposto por
    declividade e orientacao. Os vetores da vizinhanca 3x3 sao somados; se o
    terreno for um plano, por mais ingreme que seja, todos os normais apontam
    para o mesmo lado, a resultante tem modulo igual ao numero de celulas e o
    indice da zero. Quanto mais os normais divergem, menor a resultante e maior
    o indice.

    Sai entre 0 (plano, qualquer que seja a inclinacao) e 1 (maximamente
    rugoso). E esta a medida que separa uma encosta lisa de campo de um campo de
    blocos na mesma inclinacao media -- o TRI nao separa, apesar do que a
    documentacao anterior afirmava.
    """
    _require_2d(dem_array, "a rugosidade")
    check_terrain_size(dem_array, feedback)
    px, py = _metric_spacing(transform)
    filled, valid = _filled_for_gradient(dem_array)
    rows, cols = dem_array.shape

    dz_dy, dz_dx = _masked_gradient(filled, valid, py, px)
    dz_dy = np.where(valid, dz_dy, 0.0)
    dz_dx = np.where(valid, dz_dx, 0.0)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dy, dz_dx)

    # Vetor normal unitario de cada celula.
    xy = np.sin(slope)
    vector_x = xy * np.cos(aspect)
    vector_y = xy * np.sin(aspect)
    vector_z = np.cos(slope)

    neighbours = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 0),
                  (0, 1), (1, -1), (1, 0), (1, 1))
    sum_x = np.zeros((rows, cols))
    sum_y = np.zeros((rows, cols))
    sum_z = np.zeros((rows, cols))
    count = np.zeros((rows, cols))
    for d_row, d_col in neighbours:
        dst = (slice(max(0, -d_row), rows + min(0, -d_row)),
               slice(max(0, -d_col), cols + min(0, -d_col)))
        src = (slice(max(0, d_row), rows + min(0, d_row)),
               slice(max(0, d_col), cols + min(0, d_col)))
        usable = np.zeros((rows, cols), bool)
        usable[dst] = valid[src]
        sum_x[dst] += np.where(valid[src], vector_x[src], 0.0)
        sum_y[dst] += np.where(valid[src], vector_y[src], 0.0)
        sum_z[dst] += np.where(valid[src], vector_z[src], 0.0)
        count += usable

    with np.errstate(divide="ignore", invalid="ignore"):
        resultant = np.sqrt(sum_x ** 2 + sum_y ** 2 + sum_z ** 2)
        vrm = np.where(count > 0, 1.0 - resultant / count, np.nan)
    vrm = np.clip(vrm, 0.0, 1.0).astype(np.float32)
    vrm[~valid] = np.nan

    if feedback:
        finite = vrm[np.isfinite(vrm)]
        if finite.size:
            feedback.pushInfo(
                "Rugosidade vetorial (VRM) derivada do MDE: p50={:.5f}, p90={:.5f}, "
                "max={:.5f}".format(
                    float(np.percentile(finite, 50)), float(np.percentile(finite, 90)),
                    float(finite.max()))
            )
    return vrm


def derive_terrain(dem_array, transform, feedback=None):
    """Slope (percent) plus both curvatures, from one DEM in a metric CRS."""
    check_terrain_size(dem_array, feedback)
    slope = slope_percent_from_dem(dem_array, transform, feedback)
    curv_h, curv_v = curvatures_from_dem(dem_array, transform, feedback)
    return slope, curv_h, curv_v
