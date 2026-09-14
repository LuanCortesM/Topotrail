"""The terrain derivatives, checked against surfaces with closed-form answers.

Every test here compares the code to a number derived on paper, not to another
run of the same code. A regression test that only pins current behaviour cannot
tell a correct implementation from a consistently wrong one.
"""

import numpy as np
import pytest

from apoio import inclined_plane


# --------------------------------------------------------------------------
# Slope
# --------------------------------------------------------------------------

@pytest.mark.parametrize("slope_ratio", [0.0, 0.1, 0.5, 1.0, 2.0])
def test_slope_on_an_inclined_plane_equals_the_gradient(terrain, transform_10m, slope_ratio):
    """On a plane rising `slope_ratio` metres per metre, slope is exactly
    100 * slope_ratio per cent, everywhere except the edges."""
    dem = inclined_plane(40, 40, 10.0, slope_ratio)
    slope = terrain.slope_percent_from_dem(dem, transform_10m)
    interior = slope[2:-2, 2:-2]
    assert np.allclose(interior, 100.0 * slope_ratio, atol=1e-3)


def test_slope_is_independent_of_aspect(terrain, transform_10m):
    """A plane tilted along x and one tilted along y by the same amount have
    the same slope: slope is the magnitude of the gradient, not a component."""
    along_x = terrain.slope_percent_from_dem(
        inclined_plane(40, 40, 10.0, 0.3, "x"), transform_10m)
    along_y = terrain.slope_percent_from_dem(
        inclined_plane(40, 40, 10.0, 0.3, "y"), transform_10m)
    assert np.allclose(along_x[2:-2, 2:-2], along_y[2:-2, 2:-2], atol=1e-3)


def test_slope_of_45_degrees_is_100_percent(terrain, transform_10m):
    """The defining identity of the unit: tan(45 degrees) = 1 = 100%."""
    dem = inclined_plane(30, 30, 10.0, np.tan(np.deg2rad(45.0)))
    slope = terrain.slope_percent_from_dem(dem, transform_10m)
    assert np.allclose(slope[2:-2, 2:-2], 100.0, atol=1e-3)


def test_slope_scales_with_pixel_size(terrain):
    """The same elevation differences over a coarser grid mean a gentler slope.
    Doubling the cell size halves the slope."""
    dem = inclined_plane(30, 30, 1.0, 1.0)            # 1 m rise per column
    fine = terrain.slope_percent_from_dem(dem, (0.0, 10.0, 0.0, 0.0, 0.0, -10.0))
    coarse = terrain.slope_percent_from_dem(dem, (0.0, 20.0, 0.0, 0.0, 0.0, -20.0))
    assert np.allclose(fine[2:-2, 2:-2], 2.0 * coarse[2:-2, 2:-2], atol=1e-3)


def test_flat_terrain_has_zero_slope(terrain, transform_10m):
    dem = np.full((20, 20), 742.0, np.float32)
    assert np.allclose(terrain.slope_percent_from_dem(dem, transform_10m), 0.0)


# --------------------------------------------------------------------------
# Curvature
# --------------------------------------------------------------------------

def test_plane_has_zero_curvature(terrain, transform_10m):
    """A plane is not curved. Both curvatures must vanish, whatever its tilt."""
    dem = inclined_plane(40, 40, 10.0, 0.4)
    plan, profile = terrain.curvatures_from_dem(dem, transform_10m)
    assert np.allclose(plan[3:-3, 3:-3], 0.0, atol=1e-9)
    assert np.allclose(profile[3:-3, 3:-3], 0.0, atol=1e-9)


def test_curvature_sign_convention(terrain, transform_10m):
    """The sign convention, pinned. Convex forms are negative, concave positive.

    This is the assertion the docstring makes, and it is the one thing about
    curvature a user must know to read the map. The first version of this test
    asserted the opposite and failed, which is how the docstring got corrected
    rather than the code.
    """
    rows = cols = 61
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    radius2 = ((x - cols // 2) * 10.0) ** 2 + ((y - rows // 2) * 10.0) ** 2
    dome = (500.0 - 0.002 * radius2).astype(np.float32)
    bowl = (500.0 + 0.002 * radius2).astype(np.float32)

    dome_plan, dome_profile = terrain.curvatures_from_dem(dome, transform_10m)
    bowl_plan, bowl_profile = terrain.curvatures_from_dem(bowl, transform_10m)

    ring = np.zeros((rows, cols), bool)
    ring[15:-15, 15:-15] = True
    ring[25:-25, 25:-25] = False        # avoid the flat apex, where it is undefined

    assert np.nanmean(dome_profile[ring]) < 0, "a dome is convex: profile must be negative"
    assert np.nanmean(bowl_profile[ring]) > 0, "a bowl is concave: profile must be positive"
    assert np.nanmean(dome_plan[ring]) < 0
    assert np.nanmean(bowl_plan[ring]) > 0
    # Inverting the surface inverts both curvatures. In float64 the identity is
    # exact; the float32 surfaces above carry quantisation of about 3e-5 m at
    # 500 m of elevation, and the three-point second derivative divides by h^2
    # rather than by 4h^2, so it passes four times more of that noise through
    # than the lag-2h estimator used until 1.1.2. That is the price of resolving
    # forms of a few cells, and 2e-4 is what it costs here.
    assert np.allclose(dome_profile[ring], -bowl_profile[ring], rtol=2e-4, atol=1e-9)
    assert np.allclose(dome_plan[ring], -bowl_plan[ring], rtol=2e-4, atol=1e-9)

    exact_dome = (500.0 - 0.002 * radius2).astype(np.float64)
    exact_bowl = (500.0 + 0.002 * radius2).astype(np.float64)
    exact_dome_plan, exact_dome_profile = terrain.curvatures_from_dem(exact_dome, transform_10m)
    exact_bowl_plan, exact_bowl_profile = terrain.curvatures_from_dem(exact_bowl, transform_10m)
    assert np.allclose(exact_dome_profile[ring], -exact_bowl_profile[ring], rtol=0, atol=1e-12)
    assert np.allclose(exact_dome_plan[ring], -exact_bowl_plan[ring], rtol=0, atol=1e-12)


def test_plan_curvature_of_a_cylindrical_ridge_is_zero(terrain, transform_10m):
    """Plan curvature is measured across the slope. A ridge extruded along one
    axis has straight contours, so its plan curvature is exactly zero however
    sharp the crest is -- while profile curvature is not."""
    rows = cols = 61
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    ridge = (500.0 - 0.02 * ((x - cols // 2) * 10.0) ** 2).astype(np.float32)
    plan, profile = terrain.curvatures_from_dem(ridge, transform_10m)
    band = np.zeros((rows, cols), bool)
    band[10:-10, 15:25] = True
    assert np.allclose(plan[band], 0.0, atol=1e-9)
    assert np.nanmean(profile[band]) < 0


def test_curvature_is_scale_and_sign_agnostic_downstream(terrain, algorithm, transform_10m):
    """The claim the README makes about portability between curvature providers,
    as a test: multiplying a curvature raster by 1000, or flipping its sign,
    must not change the score the model derives from it."""
    rows = cols = 41
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    curvature = (np.sin(x / 6.0) * np.cos(y / 5.0)).astype(np.float32)

    base = algorithm.normalize_curvature_preference(curvature)
    scaled = algorithm.normalize_curvature_preference(curvature * 1000.0)
    flipped = algorithm.normalize_curvature_preference(-curvature)

    assert np.allclose(base, scaled, atol=1e-5)
    assert np.allclose(base, flipped, atol=1e-5)


# --------------------------------------------------------------------------
# Ruggedness
# --------------------------------------------------------------------------

def test_ruggedness_of_a_plane_equals_the_mean_neighbour_step(terrain, transform_10m):
    """On a plane rising 1 m per 10 m cell along x, the eight neighbours differ
    by -1, 0 and +1 m, four of them by 1 m in absolute value on each side:
    the mean absolute difference is exactly 6/8 = 0.75 m."""
    dem = inclined_plane(30, 30, 10.0, 0.1)
    tri = terrain.roughness_index(dem, transform_10m)
    assert np.allclose(tri[2:-2, 2:-2], 0.75, atol=1e-4)


def test_ruggedness_of_flat_terrain_is_zero(terrain, transform_10m):
    dem = np.full((20, 20), 300.0, np.float32)
    assert np.allclose(terrain.roughness_index(dem, transform_10m), 0.0)


def test_tri_is_not_independent_of_slope(terrain, transform_10m):
    """TRI grows with slope, and the documentation used to claim it did not.

    On a perfectly smooth 80% ramp the mean absolute neighbour difference is
    6.00 m; on a noisy near-flat surface it is 3.36 m. The smooth ramp scores
    as *rougher*. This is not a defect of Riley's index -- it is its definition
    -- but it is why the model uses the vector measure instead.
    """
    smooth_steep = inclined_plane(40, 40, 10.0, 0.8)
    rng = np.random.default_rng(7)
    rough_gentle = (inclined_plane(40, 40, 10.0, 0.05)
                    + rng.normal(0, 3.0, (40, 40))).astype(np.float32)

    tri_steep = np.nanmean(terrain.roughness_index(smooth_steep, transform_10m)[3:-3, 3:-3])
    tri_rough = np.nanmean(terrain.roughness_index(rough_gentle, transform_10m)[3:-3, 3:-3])
    assert tri_steep > tri_rough


@pytest.mark.parametrize("slope_ratio", [0.05, 0.3, 1.0, 2.0, 5.0])
def test_vector_ruggedness_of_a_plane_is_zero_at_any_slope(terrain, transform_10m, slope_ratio):
    """The defining property of the vector measure, and the reason it replaced
    TRI as the model's roughness criterion: a plane is not rugged, however
    steep. Every surface normal points the same way, so the resultant has full
    length and the index vanishes."""
    dem = inclined_plane(40, 40, 10.0, slope_ratio)
    vrm = terrain.vector_ruggedness(dem, transform_10m)
    assert np.allclose(vrm[3:-3, 3:-3], 0.0, atol=1e-9)


def test_vector_ruggedness_separates_rough_from_steep(terrain, transform_10m):
    """What TRI could not do: rank a noisy gentle surface as rougher than a
    smooth steep one."""
    smooth_steep = inclined_plane(40, 40, 10.0, 0.8)
    rng = np.random.default_rng(7)
    rough_gentle = (inclined_plane(40, 40, 10.0, 0.05)
                    + rng.normal(0, 3.0, (40, 40))).astype(np.float32)

    vrm_steep = np.nanmean(terrain.vector_ruggedness(smooth_steep, transform_10m)[3:-3, 3:-3])
    vrm_rough = np.nanmean(terrain.vector_ruggedness(rough_gentle, transform_10m)[3:-3, 3:-3])
    assert vrm_rough > vrm_steep
    assert vrm_steep == pytest.approx(0.0, abs=1e-9)


def test_vector_ruggedness_stays_in_range(terrain, transform_10m):
    rng = np.random.default_rng(11)
    chaos = rng.normal(0, 60.0, (50, 50)).astype(np.float32)
    vrm = terrain.vector_ruggedness(chaos, transform_10m)
    finite = vrm[np.isfinite(vrm)]
    assert finite.min() >= 0.0 and finite.max() <= 1.0
    assert finite.mean() > 0.1          # genuinely rugged terrain scores well above zero


def test_ruggedness_edges_use_only_existing_neighbours(terrain, transform_10m):
    """Corner cells have three neighbours, not eight. The index must average
    over what exists rather than treating the outside as zero elevation."""
    dem = np.full((10, 10), 500.0, np.float32)
    tri = terrain.roughness_index(dem, transform_10m)
    assert np.isfinite(tri[0, 0]) and tri[0, 0] == pytest.approx(0.0)
    assert np.isfinite(tri[-1, -1]) and tri[-1, -1] == pytest.approx(0.0)


def test_invalid_cells_stay_invalid(terrain, transform_10m):
    dem = inclined_plane(20, 20, 10.0, 0.2).copy()
    dem[5, 5] = np.nan
    for array in (terrain.slope_percent_from_dem(dem, transform_10m),
                  terrain.roughness_index(dem, transform_10m),
                  terrain.vector_ruggedness(dem, transform_10m),
                  *terrain.curvatures_from_dem(dem, transform_10m)):
        assert np.isnan(array[5, 5])


def test_zero_pixel_size_is_refused(terrain):
    dem = np.zeros((10, 10), np.float32)
    with pytest.raises(ValueError):
        terrain.slope_percent_from_dem(dem, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


def test_plan_curvature_is_zero_on_straight_contours_at_any_orientation(terrain, transform_10m):
    """Encosta lisa quase nao tem curvatura plana -- em nenhuma orientacao.

    Este e o teste que faltava, e a sua ausencia custou uma regressao. Uma
    superficie de curvas de nivel retas (desenvolvivel) tem curvatura plana
    identicamente nula, em qualquer angulo em relacao aos eixos da grade.
    Numericamente isso depende de as tres segundas derivadas virem do mesmo
    operador: com o gradiente aplicado duas vezes o Hessiano discreto tem posto
    1, e o residuo fica pequeno em qualquer orientacao -- exatamente zero nos
    eixos de simetria da grade (0, 45 e 90 graus) e no maximo 0,41% da curvatura
    de perfil real nas orientacoes intermediarias, medido a 21 graus numa
    varredura. Misturando um estencil de tres pontos nas derivadas puras com o
    termo cruzado do gradiente, o residuo sobe para 8,6% na mesma superficie a
    45 graus: uma feicao concava aparecendo numa encosta lisa.

    O teste anterior usava uma crista alinhada ao eixo y -- uma das orientacoes
    em que ate o esquema misto continua exato -- e por isso nao podia detectar
    o problema. Aqui a superficie e corrugada e obliqua.
    """
    n = 161
    h = 10.0
    y, x = np.mgrid[0:n, 0:n].astype(np.float64)
    for graus in (0.0, 30.0, 45.0, 63.0):
        angulo = np.deg2rad(graus)
        u = (x - n // 2) * h * np.cos(angulo) + (y - n // 2) * h * np.sin(angulo)
        # Onda de seis celulas sobre uma rampa de 50%: curvas de nivel retas. A
        # rampa e forte de proposito, para que o gradiente nunca se anule -- no
        # cume de uma crista a curvatura plana e indefinida por divisao por
        # zero, e o teste mediria a singularidade em vez do estimador.
        superficie = 2.0 * np.sin(2.0 * np.pi * u / (6.0 * h)) + 0.5 * u
        plan, profile = terrain.curvatures_from_dem(superficie, transform_10m)
        miolo = slice(30, -30)
        espurio = float(np.nanmax(np.abs(plan[miolo, miolo])))
        real = float(np.nanmax(np.abs(profile[miolo, miolo])))
        assert espurio < 0.03 * real, (
            f"a {graus:.0f} graus a curvatura plana deveria ser desprezivel e "
            f"vale {espurio:.3e}, {100 * espurio / real:.1f}% da curvatura de "
            f"perfil real ({real:.3e})")


def test_curvature_attenuates_short_wavelength_forms_by_a_known_amount(terrain, transform_10m):
    """A atenuacao em formas curtas e conhecida, medida e declarada.

    As segundas derivadas saem do operador de gradiente aplicado duas vezes, o
    que as avalia num passo de duas celulas: a amplitude preservada e
    [sin(kh)/(kh)]^2, isto e, 40% numa onda de quatro celulas e 81% numa de
    oito. O estencil de tres pontos preservaria 81% e 95%, mas quebraria a
    identidade fixada no teste acima -- a escolha esta documentada em
    `curvatures_from_dem`.

    Este teste existe para que a atenuacao seja um numero declarado e nao uma
    surpresa: se alguem mudar o estimador, ele avisa exatamente quanto mudou.
    """
    n = 121
    h = 10.0
    declive = 0.05
    y, x = np.mgrid[0:n, 0:n].astype(np.float64)
    coluna = (x - n // 2) * h
    for comprimento, esperado in ((4, 0.405), (8, 0.811), (12, 0.912)):
        k = 2.0 * np.pi / (comprimento * h)
        superficie = declive * coluna + 10.0 * np.sin(k * coluna)
        _plan, profile = terrain.curvatures_from_dem(superficie, transform_10m)
        teorico = (k ** 2) * 10.0 / (1.0 + declive ** 2) ** 1.5
        miolo = slice(30, -30)
        preservado = float(np.nanmax(np.abs(profile[miolo, miolo]))) / teorico
        assert abs(preservado - esperado) < 0.02, (
            f"onda de {comprimento} celulas: preservou {preservado:.3f}, "
            f"esperado {esperado:.3f}")


def test_plan_curvature_stays_bounded_where_the_ground_goes_flat(terrain, transform_10m):
    """O defeito que a 1.3.0 corrigiu, fixado como teste.

    Ate a 1.2.0 a curvatura plana era a curvatura de contorno de Moore et al.
    (1991), com p^{3/2} no denominador. Ela e a curvatura da propria curva de
    nivel, e a curva de nivel se fecha cada vez mais apertada perto de um ponto
    plano: no alto de uma calota lisa ela diverge como 1/r embora a superficie
    ali nao tenha nada de abrupto. Como o modelo pontua a forma pela distancia
    a zero, o terreno mais suave -- que e o que se quer premiar -- recebia a
    pior nota de forma. Medido na cena real da Mantiqueira do capitulo, na grade
    de trabalho da execucao canonica: corr(log da declividade, nota de forma) =
    +0,58, decil mais suave 0,704 contra 0,958 no mais ingreme, com o criterio
    de forma trabalhando CONTRA o de declividade sob o mesmo peso; com a
    tangencial a correlacao cai para +0,06.

    A curvatura tangencial de Mitasova & Hofierka (1993) e a curvatura NORMAL na
    direcao da curva de nivel: numa calota z = 500 - a r^2 ela vale
    2a/(1+p)^{1/2} e nunca passa de 2a, por mais plano que o terreno fique.
    """
    rows = cols = 81
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    dx = (x - cols // 2) * 10.0
    dy = (y - rows // 2) * 10.0
    a = 0.002
    dome = (500.0 - a * (dx ** 2 + dy ** 2)).astype(np.float64)

    plan, _ = terrain.curvatures_from_dem(dome, transform_10m)
    miolo = np.zeros((rows, cols), bool)
    miolo[3:-3, 3:-3] = True

    assert np.nanmax(np.abs(plan[miolo])) <= 2.0 * a * 1.02, (
        "a curvatura plana estourou o limite fechado 2a: o denominador voltou "
        "a ser p^{3/2} e volta a divergir no terreno plano")

    # forma fechada k_t = 2a/(1+p)^{1/2} ao longo de um raio, do quase plano ao
    # ingreme. O apice fica de fora porque ali o gradiente e nulo e a curvatura
    # e indefinida -- o codigo devolve zero, como esta documentado.
    for coluna in range(cols // 2 + 2, cols - 6, 6):
        raio = (coluna - cols // 2) * 10.0
        p = (2.0 * a * raio) ** 2
        esperado = 2.0 * a / np.sqrt(1.0 + p)
        assert abs(plan[rows // 2, coluna]) == pytest.approx(esperado, rel=0.02), (
            "coluna {}: curvatura plana fora da forma fechada tangencial".format(coluna))


def test_plan_curvature_measures_relief_not_the_shape_of_the_contour_line(terrain, transform_10m):
    """A distincao entre as duas formas, isolada num so numero.

    Duas calotas com a MESMA geometria de curvas de nivel -- circulos
    concentricos identicos -- e relevos que diferem por um fator de 2000: uma
    com 2 m de amplitude, outra com 1 mm. A segunda e, para qualquer efeito
    pratico, um plano.

    A curvatura de CONTORNO nao ve diferenca entre as duas: vale 1/r nas duas,
    porque so depende do desenho da curva de nivel. A curvatura TANGENCIAL, que
    e a curvatura da superficie, escala com o relevo. Um criterio de forma que
    nao distingue uma calota de um plano nao esta medindo forma.
    """
    rows = cols = 81
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    radius2 = ((x - cols // 2) * 10.0) ** 2 + ((y - rows // 2) * 10.0) ** 2
    miolo = np.zeros((rows, cols), bool)
    miolo[3:-3, 3:-3] = True

    forte = (500.0 - 2e-3 * radius2).astype(np.float64)
    fraca = (500.0 - 1e-6 * radius2).astype(np.float64)
    plan_forte, _ = terrain.curvatures_from_dem(forte, transform_10m)
    plan_fraca, _ = terrain.curvatures_from_dem(fraca, transform_10m)

    razao = np.nanmax(np.abs(plan_fraca[miolo])) / np.nanmax(np.abs(plan_forte[miolo]))
    assert razao < 0.01, (
        "a curvatura plana quase nao mudou quando o relevo caiu 2000 vezes "
        "(razao {:.3f}): esta medindo a curva de nivel, nao a superficie".format(razao))
