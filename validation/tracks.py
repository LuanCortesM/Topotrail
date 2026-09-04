"""Reads GPS tracks with per-fix timestamps out of KML gx:Track and GPX.

OGR reads the geometry of a gx:Track but not the <when> stamps that sit beside
the coordinates, and the stamps are the whole point here: without them a track
is a line, and with them it is a measurement of how fast a person actually
walks on a given gradient.
"""

import datetime as _dt
import pathlib
import xml.etree.ElementTree as ET

import numpy as np

KML = "{http://www.opengis.net/kml/2.2}"
GX = "{http://www.google.com/kml/ext/2.2}"
GPX = "{http://www.topografix.com/GPX/1/1}"


def _parse_time(text):
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(text)


def read_kml_gx_track(path):
    """Devolve (lon, lat, ele, epoch_seconds) de cada <gx:Track> do arquivo."""
    root = ET.parse(path).getroot()
    out = []
    for track in root.iter(f"{GX}Track"):
        whens = [_parse_time(e.text) for e in track.findall(f"{KML}when")]
        coords = [c.text.split() for c in track.findall(f"{GX}coord") if c.text]
        n = min(len(whens), len(coords))
        if n < 2:
            continue
        lon = np.array([float(c[0]) for c in coords[:n]])
        lat = np.array([float(c[1]) for c in coords[:n]])
        ele = np.array([float(c[2]) if len(c) > 2 else np.nan for c in coords[:n]])
        t = np.array([w.timestamp() for w in whens[:n]])
        out.append((lon, lat, ele, t))
    return out


def read_gpx(path):
    root = ET.parse(path).getroot()
    out = []
    for seg in root.iter(f"{GPX}trkseg"):
        lon, lat, ele, t = [], [], [], []
        for pt in seg.findall(f"{GPX}trkpt"):
            lon.append(float(pt.get("lon")))
            lat.append(float(pt.get("lat")))
            e = pt.find(f"{GPX}ele")
            ele.append(float(e.text) if e is not None else np.nan)
            w = pt.find(f"{GPX}time")
            t.append(_parse_time(w.text).timestamp() if w is not None else np.nan)
        if len(lon) >= 2:
            out.append((np.array(lon), np.array(lat), np.array(ele), np.array(t)))
    return out


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def read_kml_linestrings(path):
    """Geometria apenas, para trilhas sem estampa de tempo.

    Casa pelo nome local da tag: os arquivos do Wikiloc usam o namespace antigo
    earth.google.com/kml/2.0 e nao o opengis.net/kml/2.2, e um leitor preso a um
    unico namespace simplesmente devolve zero feicoes, sem erro.
    """
    root = ET.parse(path).getroot()
    out = []
    for ls in root.iter():
        if _local(ls.tag) != "LineString":
            continue
        node = next((c for c in ls if _local(c.tag) == "coordinates"), None)
        if node is None or not node.text:
            continue
        pts = [p.split(",") for p in node.text.split()]
        if len(pts) < 2:
            continue
        lon = np.array([float(p[0]) for p in pts])
        lat = np.array([float(p[1]) for p in pts])
        ele = np.array([float(p[2]) if len(p) > 2 else np.nan for p in pts])
        out.append((lon, lat, ele, np.full(lon.shape, np.nan)))
    return out


def read_any(path):
    path = pathlib.Path(path)
    if path.suffix.lower() == ".gpx":
        return read_gpx(path)
    tracks = read_kml_gx_track(path)
    return tracks if tracks else read_kml_linestrings(path)
