from __future__ import annotations
from math import floor
from pyproj import CRS, Transformer
from shapely.ops import transform

def utm_crs_for_lon_lat(lon: float, lat: float) -> str:
    zone = max(1, min(60, int(floor((lon + 180.0) / 6.0) + 1)))
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"

def metric_crs_for_geometry(geom, source_crs: str | None) -> str | None:
    if not source_crs:
        return None
    crs = CRS.from_user_input(source_crs)
    if crs.is_projected:
        return crs.to_string()
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    c = transform(lambda x,y,z=None: to_wgs84.transform(x,y), geom.centroid)
    return utm_crs_for_lon_lat(float(c.x), float(c.y))

def transform_geom(geom, source_crs: str | None, target_crs: str | None):
    if not source_crs or not target_crs:
        return geom
    if CRS.from_user_input(source_crs) == CRS.from_user_input(target_crs):
        return geom
    t = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return transform(lambda x,y,z=None: t.transform(x,y), geom)
