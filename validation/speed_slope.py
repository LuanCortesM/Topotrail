"""Observed walking speed as a function of terrain gradient.

The plugin's route cost rests on Tobler's hiking function, whose three
constants (6 km/h, decay 3.5, optimum -0.05) come from a 1993 technical note
and had never been checked against anyone actually walking the terrain the
plugin is used in. These tracks are that check.

Method
------
Each track is projected to its UTM zone and cut into windows of a fixed path
length L. Using a fixed *length* rather than a fixed time matters: a fixed time
window mixes long flat strides with short steep ones, and the gradient of the
window is then not the gradient anything was walked at.

For each window:
    horizontal distance  = sum of the planimetric segment lengths
    rise                 = DEM elevation at the end minus at the start
    gradient S           = rise / horizontal distance
    speed                = horizontal distance / elapsed time

GPS elevation is deliberately *not* used for the gradient. Consumer GPS
vertical error is two to three times the horizontal error, and differencing two
noisy elevations over 60 m produces a gradient dominated by noise. The DEM is
also what the plugin itself will use, so a calibration against GPS elevation
would not transfer to the model.

Windows containing a pause longer than PAUSE_S are dropped rather than
included: these are herpetological survey tracks, and a stop to handle an
animal is not slow walking, it is not walking.
"""

import numpy as np
import pyproj
from osgeo import gdal

gdal.UseExceptions()

PAUSE_S = 120.0          # a gap longer than this is a stop, not slow progress
MIN_SPEED_KMH = 0.2
MAX_SPEED_KMH = 12.0     # above this it is a vehicle, not a walker


class Dem:
    def __init__(self, path):
        self.ds = gdal.Open(path)
        self.gt = self.ds.GetGeoTransform()
        self.band = self.ds.GetRasterBand(1)
        self.nodata = self.band.GetNoDataValue()
        self.array = self.band.ReadAsArray().astype(np.float64)
        if self.nodata is not None:
            self.array[self.array == self.nodata] = np.nan
        self.epsg = int(self.ds.GetProjection().split('"EPSG","')[-1].split('"')[0])

    def sample(self, x, y):
        col = ((x - self.gt[0]) / self.gt[1]).astype(int)
        row = ((y - self.gt[3]) / self.gt[5]).astype(int)
        ok = ((col >= 0) & (col < self.ds.RasterXSize)
              & (row >= 0) & (row < self.ds.RasterYSize))
        out = np.full(x.shape, np.nan)
        out[ok] = self.array[row[ok], col[ok]]
        return out


def project(lon, lat, epsg):
    tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    return tr.transform(lon, lat)


def windows(lon, lat, t, dem, window_m):
    """Devolve (gradiente, velocidade km/h, distancia, dt) por janela."""
    x, y = project(lon, lat, dem.epsg)
    x, y = np.asarray(x), np.asarray(y)
    step = np.hypot(np.diff(x), np.diff(y))
    dt = np.diff(t)
    z = dem.sample(x, y)

    records = []
    start = 0
    accumulated = 0.0
    for i in range(len(step)):
        accumulated += step[i]
        if accumulated < window_m:
            continue
        end = i + 1
        elapsed = t[end] - t[start]
        gap = np.nanmax(dt[start:end]) if end > start else np.inf
        rise = z[end] - z[start]
        if (elapsed > 0 and np.isfinite(rise) and accumulated > 0
                and gap <= PAUSE_S):
            speed = (accumulated / elapsed) * 3.6
            gradient = rise / accumulated
            if MIN_SPEED_KMH <= speed <= MAX_SPEED_KMH:
                records.append((gradient, speed, accumulated, elapsed))
        start = end
        accumulated = 0.0
    if not records:
        return (np.array([]),) * 4
    a = np.array(records)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def tobler(gradient, vmax, decay, optimum):
    return vmax * np.exp(-decay * np.abs(gradient + optimum))
