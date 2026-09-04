"""Transitability classes: a map a person can read without a legend lecture.

The suitability raster is continuous and relative; the potential-zone vector is
binary and depends on a percentile of the scene. Neither answers the question a
researcher actually asks while looking at a map before going to the field:
**can I walk here, or not?**

This module answers that with absolute, physically meaningful classes. Absolute
matters: a class must mean the same thing in the Mantiqueira and in the Andes,
otherwise two maps cannot be compared and a field team cannot build an
intuition that transfers.

Slope sets the class, because slope is what stops a walker first. Two modifiers
can push a cell one class worse:

* **ruggedness**, because a boulder field and a smooth grassy slope at the same
  inclination are not the same walk, and slope alone cannot tell them apart;
* **wetness**, because a saturated valley floor at 5% slope can be less
  passable than a dry 30% hillside, and it is also where a trail erodes.

The thresholds below are empirical modelling decisions, like every other
constant in this plugin. They follow the usual reading of walking and
scrambling literature -- comfortable walking gives out around 20%, hands come
into play around 60%, and past 100% (45 degrees) it stops being walking -- but
they are defaults, not measurements, and they are exposed as parameters so that
a study can justify its own. Report them.

Only NumPy is required.
"""

import numpy as np

# Codigos das classes gravados no raster. A ordem e crescente em dificuldade,
# entao o raster pode ser lido diretamente como uma escala ordinal.
CLASS_NODATA = 0
CLASS_EASY = 1
CLASS_MODERATE = 2
CLASS_STEEP = 3
CLASS_SCRAMBLE = 4
CLASS_IMPASSABLE = 5

# Limites de declividade em porcentagem. 20% ~ 11 graus, 35% ~ 19 graus,
# 60% ~ 31 graus, 100% = 45 graus.
DEFAULT_SLOPE_BREAKS = (20.0, 35.0, 60.0, 100.0)

# Percentis usados para decidir o que conta como "muito rugoso" e "muito umido"
# nesta cena. Sao relativos de proposito: a rugosidade absoluta depende da
# resolucao do MDE, e o TWI depende do tamanho da bacia, entao um limiar
# absoluto para esses dois nao seria transferivel. A classe base, que e o que a
# legenda promete, continua absoluta.
ROUGHNESS_PERCENTILE = 90.0
WETNESS_PERCENTILE = 95.0

CLASS_LABELS = {
    CLASS_EASY: "1 - Transitavel a pe",
    CLASS_MODERATE: "2 - Transitavel com esforco",
    CLASS_STEEP: "3 - Dificil, exige apoio",
    CLASS_SCRAMBLE: "4 - Muito dificil, escalonamento",
    CLASS_IMPASSABLE: "5 - Intransitavel a pe",
}

CLASS_LABELS_EN = {
    CLASS_EASY: "1 - Walkable",
    CLASS_MODERATE: "2 - Walkable with effort",
    CLASS_STEEP: "3 - Hard, hands needed",
    CLASS_SCRAMBLE: "4 - Very hard, scrambling",
    CLASS_IMPASSABLE: "5 - Not walkable",
}

# Cor por classe, do verde ao vermelho escuro. Gravadas no proprio GeoTIFF para
# que o mapa abra legivel no QGIS sem o usuario ter de estiliza-lo.
CLASS_COLORS = {
    CLASS_NODATA: (0, 0, 0, 0),
    CLASS_EASY: (46, 93, 66, 255),
    CLASS_MODERATE: (140, 184, 151, 255),
    CLASS_STEEP: (214, 172, 78, 255),
    CLASS_SCRAMBLE: (196, 106, 62, 255),
    CLASS_IMPASSABLE: (128, 42, 26, 255),
}


def classify(slope_percent, valid_mask, roughness=None, wetness=None,
             blocked_mask=None, slope_breaks=DEFAULT_SLOPE_BREAKS, feedback=None):
    """Devolve (classes uint8, metricas).

    `blocked_mask` marca celulas intransitaveis por restricao -- curso d'agua,
    camada vetorial do usuario -- que vao direto para a classe 5,
    independentemente da inclinacao.
    """
    breaks = tuple(float(b) for b in slope_breaks)
    if not all(breaks[i] < breaks[i + 1] for i in range(len(breaks) - 1)):
        raise ValueError("Os limites de declividade das classes devem ser crescentes.")

    classes = np.full(slope_percent.shape, CLASS_NODATA, dtype=np.uint8)
    usable = valid_mask & np.isfinite(slope_percent)

    classes[usable] = CLASS_IMPASSABLE
    classes[usable & (slope_percent < breaks[3])] = CLASS_SCRAMBLE
    classes[usable & (slope_percent < breaks[2])] = CLASS_STEEP
    classes[usable & (slope_percent < breaks[1])] = CLASS_MODERATE
    classes[usable & (slope_percent < breaks[0])] = CLASS_EASY

    metrics = {"limites_declividade_pct": list(breaks)}

    # Modificadores: pioram uma classe, nunca melhoram, e nunca criam classe 5 --
    # terreno rugoso ou encharcado e pior de caminhar, mas nao e um paredao.
    def worsen(mask, name):
        target = mask & usable & (classes >= CLASS_EASY) & (classes < CLASS_SCRAMBLE)
        moved = int(target.sum())
        classes[target] = classes[target] + 1
        metrics[f"celulas_rebaixadas_por_{name}"] = moved
        return moved

    if roughness is not None:
        finite = roughness[usable & np.isfinite(roughness)]
        if finite.size:
            limit = float(np.percentile(finite, ROUGHNESS_PERCENTILE))
            metrics["limiar_rugosidade_m"] = limit
            moved = worsen(np.isfinite(roughness) & (roughness > limit), "rugosidade")
            if feedback:
                feedback.pushInfo(
                    "Rugosidade acima de {:.2f} m (P{:.0f} da cena) rebaixou {:,} celulas "
                    "uma classe.".format(limit, ROUGHNESS_PERCENTILE, moved)
                )

    if wetness is not None:
        finite = wetness[usable & np.isfinite(wetness)]
        if finite.size:
            limit = float(np.percentile(finite, WETNESS_PERCENTILE))
            metrics["limiar_umidade_twi"] = limit
            moved = worsen(np.isfinite(wetness) & (wetness > limit), "umidade")
            if feedback:
                feedback.pushInfo(
                    "Umidade acima de TWI {:.2f} (P{:.0f} da cena) rebaixou {:,} celulas "
                    "uma classe.".format(limit, WETNESS_PERCENTILE, moved)
                )

    if blocked_mask is not None:
        blocked = blocked_mask & usable
        classes[blocked] = CLASS_IMPASSABLE
        metrics["celulas_bloqueadas_por_restricao"] = int(blocked.sum())

    total = int(usable.sum())
    distribution = {}
    for code, label in CLASS_LABELS.items():
        count = int((classes == code).sum())
        distribution[label] = {
            "celulas": count,
            "proporcao": (count / total) if total else None,
        }
    metrics["distribuicao"] = distribution
    metrics["celulas_validas"] = total

    if feedback and total:
        feedback.pushInfo("Classes de transitabilidade:")
        for code, label in CLASS_LABELS.items():
            count = int((classes == code).sum())
            feedback.pushInfo(
                "  {:34s} {:>12,} celulas  {:5.1f}%".format(
                    label, count, 100.0 * count / total)
            )
    return classes, metrics


def walkable_fraction(classes, up_to=CLASS_MODERATE):
    """Proporcao da area valida que cai ate a classe indicada, inclusive."""
    valid = classes != CLASS_NODATA
    total = int(valid.sum())
    if not total:
        return None
    return float(((classes >= CLASS_EASY) & (classes <= up_to)).sum() / total)
