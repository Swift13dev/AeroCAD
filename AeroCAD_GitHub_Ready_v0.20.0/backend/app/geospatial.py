from __future__ import annotations

import csv
import json
from pathlib import Path


def inspect_raster(path: Path) -> dict:
    try:
        import rasterio
    except ImportError as exc:
        raise RuntimeError("rasterio is not installed. Install backend/requirements.txt first.") from exc

    with rasterio.open(path) as ds:
        res_x = abs(float(ds.res[0]))
        res_y = abs(float(ds.res[1]))
        raw_resolution = f"{res_x:.10g} × {res_y:.10g} map units/pixel"

        # Geographic CRSs report angular degrees/pixel. For survey users,
        # expose an approximate ground sampling distance at the raster centre.
        gsd_m_x = None
        gsd_m_y = None
        resolution = raw_resolution
        if ds.crs and ds.crs.is_geographic:
            try:
                from pyproj import Geod

                geod = Geod(ellps="WGS84")
                cx = (ds.bounds.left + ds.bounds.right) / 2.0
                cy = (ds.bounds.bottom + ds.bounds.top) / 2.0
                _, _, gsd_m_x = geod.inv(cx, cy, cx + res_x, cy)
                _, _, gsd_m_y = geod.inv(cx, cy, cx, cy + res_y)
                gsd_m_x = abs(float(gsd_m_x))
                gsd_m_y = abs(float(gsd_m_y))
                resolution = f"≈ {gsd_m_x:.2f} m × {gsd_m_y:.2f} m/pixel"
            except Exception:
                pass
        else:
            unit_name = getattr(ds.crs, "linear_units", None) if ds.crs else None
            if unit_name:
                resolution = f"{res_x:.3g} × {res_y:.3g} {unit_name}/pixel"

        return {
            "driver": ds.driver,
            "width": ds.width,
            "height": ds.height,
            "bands": ds.count,
            "dtype": ds.dtypes[0] if ds.dtypes else None,
            "crs": ds.crs.to_string() if ds.crs else None,
            "bounds": [float(v) for v in ds.bounds],
            "resolution": resolution,
            "resolution_map_units": raw_resolution,
            "gsd_m_x": gsd_m_x,
            "gsd_m_y": gsd_m_y,
            "nodata": ds.nodata,
            "transform": [float(v) for v in ds.transform[:6]],
        }


def inspect_vector_or_table(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        data = json.loads(path.read_text(encoding="utf-8"))
        crs = None
        crs_obj = data.get("crs")
        if isinstance(crs_obj, dict):
            props = crs_obj.get("properties") or {}
            crs = props.get("name")
        features = data.get("features", []) if isinstance(data, dict) else []
        return {"kind": "vector", "crs": crs, "feature_count": len(features)}

    if suffix == ".gpkg":
        try:
            import fiona
            layers = fiona.listlayers(path)
            return {"kind": "vector", "layers": layers, "crs": None}
        except Exception:
            return {"kind": "geopackage", "crs": None}

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        return {"kind": "table", "columns": rows[0] if rows else [], "row_count": max(len(rows) - 1, 0), "crs": None}

    if suffix == ".gpx":
        return {"kind": "track/point", "crs": "EPSG:4326"}

    if suffix == ".shp":
        return {"kind": "shapefile", "crs": None, "note": "Upload the complete SHP sidecar set for production use."}

    return {"kind": "file", "crs": None}
