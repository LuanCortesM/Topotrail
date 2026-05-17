import os
import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer, QgsProcessingFeedback
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, MultiLineString, shape, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
import geopandas as gpd
from shapely.errors import ShapelyDeprecationWarning
import warnings

warnings.filterwarnings("ignore", category=ShapelyDeprecationWarning)

def reproject_raster(layer, feedback=None):
    """
    Reprojeta um raster para o CRS de referência (WGS84)
    """
    if feedback:
        feedback.pushInfo(f'Reprojetando {layer.name()}...')
    
    # Criar dataset temporário
    temp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp')
    os.makedirs(temp_path, exist_ok=True)
    output_path = os.path.join(temp_path, f'reproj_{os.path.basename(layer.source())}')
    
    # Configurar opções de reprojeção
    warp_options = gdal.WarpOptions(
        dstSRS='EPSG:4326',
        resampleAlg=gdal.GRA_Bilinear,
        format='GTiff'
    )
    
    # Executar reprojeção
    gdal.Warp(output_path, layer.source(), options=warp_options)
    
    return QgsRasterLayer(output_path, f'reproj_{layer.name()}')

def calculate_centerline(dem_layer, feedback=None):
    """
    Calcula as centerlines a partir do DEM
    """
    if feedback:
        feedback.pushInfo('Calculando centerlines...')
    
    # Ler dados do raster
    dataset = gdal.Open(dem_layer.source())
    band = dataset.GetRasterBand(1)
    dem_array = band.ReadAsArray()
    
    # Calcular distância euclidiana
    distance = distance_transform_edt(dem_array)
    
    # Encontrar pontos de sela
    saddle_points = find_saddle_points(dem_array)
    
    # Gerar linhas de drenagem
    drainage_lines = generate_drainage_lines(dem_array, saddle_points)
    
    # Simplificar e suavizar as linhas
    simplified_lines = simplify_lines(drainage_lines)
    
    return simplified_lines

def find_saddle_points(dem_array):
    """
    Encontra pontos de sela no DEM
    """
    # TODO: Implementar detecção de pontos de sela
    return []

def generate_drainage_lines(dem_array, saddle_points):
    """
    Gera linhas de drenagem a partir dos pontos de sela
    """
    # TODO: Implementar geração de linhas de drenagem
    return []

def simplify_lines(lines):
    """
    Simplifica e suaviza as linhas geradas
    """
    # TODO: Implementar simplificação e suavização de linhas
    return []

def sanitize_geometries(geometries):
    corrected = []
    for i, geom in enumerate(geometries):
        try:
            # Converte se ainda não for Polygon/MultiPolygon
            g = shape(geom) if not isinstance(geom, (Polygon, MultiPolygon)) else geom
            # Corrige geometria inválida
            if not g.is_valid:
                g = g.buffer(0)
            if g.is_valid and not g.is_empty:
                corrected.append(g)
        except Exception as e:
            print(f"[!] Geometria {i} inválida: {e}")
    return corrected

def export_to_format(centerlines, output_path, format_type, output_crs=None, feedback=None):
    """
    Exporta as centerlines para o formato especificado com validação robusta
    """
    if feedback:
        feedback.pushInfo(f'Exportando para {format_type}...')
    
    geoms = sanitize_geometries(centerlines)
    if len(geoms) == 0:
        if feedback:
            feedback.reportError("Nenhuma geometria válida para exportação.")
        return None
    
    if feedback:
        feedback.pushInfo(f"Processando {len(geoms)} geometrias...")
    
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=output_crs if output_crs else "EPSG:4326")
    
    # Reprojetar se necessário
    if output_crs and gdf.crs != output_crs:
        if feedback:
            feedback.pushInfo(f"Reprojetando GeoDataFrame para {output_crs}")
        gdf = gdf.to_crs(output_crs)
    
    # Remover polígonos com área quase zero
    gdf = gdf[~((gdf.geometry.area < 1e-6) & gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon']))]
    
    if len(gdf) == 0:
        if feedback:
            feedback.reportError("GeoDataFrame vazio após filtragem de área.")
        return None
    
    if gdf.total_bounds is None or np.any(np.isnan(gdf.total_bounds)):
        if feedback:
            feedback.reportError("Extensão spatial inválida detectada.")
        return None
    
    try:
        if format_type == 'Shapefile (.shp)':
            gdf.to_file(output_path, driver='ESRI Shapefile')
        elif format_type == 'GeoPackage (.gpkg)':
            gdf.to_file(output_path, driver='GPKG')
        elif format_type == 'KML':
            gdf.to_file(output_path, driver='KML')
        elif format_type == 'GPX':
            gdf.to_file(output_path, driver='GPX')
        if feedback:
            feedback.pushInfo(f"Exportação concluída com sucesso: {len(gdf)} geometrias válidas exportadas")
            feedback.pushInfo(f"Arquivo salvo: {output_path}")
        return output_path
    except Exception as e:
        if feedback:
            feedback.reportError(f"Erro durante exportação: {str(e)}")
        return None

def generate_statistics_report(centerlines, output_path, feedback=None):
    """
    Gera relatório estatístico em CSV
    """
    if feedback:
        feedback.pushInfo('Gerando relatório estatístico...')
    
    # TODO: Implementar geração de relatório estatístico
    return output_path 