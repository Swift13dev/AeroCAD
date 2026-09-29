from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from pyproj import CRS
from shapely.geometry import GeometryCollection, MultiPoint, Point, box, mapping, shape
from shapely.ops import polygonize, transform, unary_union, voronoi_diagram
try:
    from shapely.validation import make_valid
except ImportError:
    make_valid = None
from pyproj import Transformer
from shapely.strtree import STRtree

from .metrics import metric_crs_for_geometry, transform_geom


def _explode_polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return [g for g in geom.geoms if not g.is_empty]
    if hasattr(geom, "geoms"):
        out = []
        for g in geom.geoms:
            out.extend(_explode_polygons(g))
        return out
    return []


def _transform_geometries(geoms: list, source_crs: str | None, target_crs: str | None) -> list:
    if not source_crs or not target_crs or source_crs == target_crs:
        return geoms
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    fn = lambda x, y, z=None: transformer.transform(x, y)
    return [transform(fn, g) for g in geoms]


def _read_geojson(path: Path, target_crs: str | None = None) -> list:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_crs = "EPSG:4326"
    crs_obj = payload.get("crs") if isinstance(payload, dict) else None
    if isinstance(crs_obj, dict):
        source_crs = (crs_obj.get("properties") or {}).get("name") or source_crs
    geoms = [shape(f["geometry"]) for f in payload.get("features", []) if f.get("geometry")]
    return _transform_geometries(geoms, source_crs, target_crs)


def read_existing_parcels(path: Path, target_crs: str | None = None) -> list:
    suffix = path.suffix.lower()
    geoms = []
    if suffix in {".geojson", ".json"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_crs = "EPSG:4326"
        crs_obj = payload.get("crs")
        if isinstance(crs_obj, dict):
            source_crs = (crs_obj.get("properties") or {}).get("name") or source_crs
        for feat in payload.get("features", []):
            if feat.get("geometry"):
                g = shape(feat["geometry"])
                if target_crs:
                    g = transform_geom(g, source_crs, target_crs)
                geoms.extend(_explode_polygons(g))
        return geoms
    if suffix in {".gpkg", ".shp"}:
        import fiona
        layers = fiona.listlayers(path) if suffix == ".gpkg" else [None]
        for layer in layers:
            with fiona.open(path, layer=layer) as src:
                src_crs = src.crs_wkt or src.crs
                src_crs_text = None
                if src_crs:
                    try:
                        src_crs_text = CRS.from_user_input(src_crs).to_string()
                    except Exception:
                        pass
                for feat in src:
                    if feat.get("geometry"):
                        g = shape(feat["geometry"])
                        if target_crs and src_crs_text:
                            g = transform_geom(g, src_crs_text, target_crs)
                        geoms.extend(_explode_polygons(g))
        return geoms
    return []

def _load_buildings(output_dir: Path, target_crs: str | None) -> list:
    path = output_dir / "buildings.geojson"
    if not path.exists():
        return []
    return _read_geojson(path, target_crs)


def _load_roads(output_dir: Path, target_crs: str | None) -> list:
    path = output_dir / "roads.geojson"
    if not path.exists():
        return []
    return _read_geojson(path, target_crs)

def _score_land_use(parcel, building_geoms, road_geoms) -> tuple[str, float]:
    area = max(parcel.area, 1e-9)
    buildings = [g for g in building_geoms if g.intersects(parcel)]
    b_area = sum(g.intersection(parcel).area for g in buildings)
    b_ratio = b_area / area
    road_touch = sum(g.intersection(parcel).area for g in road_geoms)
    if b_ratio < 0.02:
        return "Open space", 0.66
    if len(buildings) >= 3 or b_ratio > 0.55:
        return "Mixed use", 0.62
    if road_touch > 0 or any(g.distance(parcel) < math.sqrt(area) * 0.08 for g in road_geoms):
        return "Residential", 0.61
    return "Residential", 0.57


def _evidence_existing() -> dict:
    return {"existing_gis": 45, "imagery_edge": 24, "structure": 16, "road_access": 10, "terrain": 5}


def _evidence_inferred() -> dict:
    return {"existing_gis": 0, "imagery_edge": 28, "structure": 38, "road_access": 24, "terrain": 10}


def _confidence(evidence: dict, validity: float = 1.0) -> int:
    base = sum(evidence.values())
    return int(max(5, min(99, round(base * validity))))



def _generate_voronoi(buildings: list, extent):
    seeds = []
    minx, miny, maxx, maxy = extent.bounds
    width = max(maxx - minx, 1e-9)
    height = max(maxy - miny, 1e-9)
    seen = set()
    for geom in buildings:
        if geom.is_empty:
            continue
        p = geom.representative_point()
        key = (round(p.x, 6), round(p.y, 6))
        if key in seen:
            continue
        seen.add(key)
        seeds.append(Point((p.x - minx) / width, (p.y - miny) / height))
    if len(seeds) < 2:
        return []
    unit_envelope = box(0, 0, 1, 1)
    try:
        diagram = voronoi_diagram(MultiPoint(seeds), envelope=unit_envelope, tolerance=0.0, edges=False)
    except ValueError:
        return []

    def restore(x, y, z=None):
        return minx + x * width, miny + y * height

    cells = []
    for cell in getattr(diagram, "geoms", []):
        restored = transform(restore, cell).intersection(extent)
        cells.extend(_explode_polygons(restored))
    return cells

def _grid_candidates(extent):
    minx, miny, maxx, maxy = extent.bounds
    nx, ny = 4, 4
    dx, dy = (maxx-minx)/nx, (maxy-miny)/ny
    return [box(minx+i*dx, miny+j*dy, minx+(i+1)*dx, miny+(j+1)*dy) for i in range(nx) for j in range(ny)]


def _local_metric_transform(crs_text: str | None):
    if not crs_text:
        return None
    crs = CRS.from_user_input(crs_text)
    if crs.is_projected:
        return lambda g: g
    return None



def _repair_for_analysis(geom):
    """Repair invalid geometry only for analytical overlay operations.

    The original source geometry remains unchanged in the exported parcel layer;
    this normalization prevents GEOS overlay operations from crashing.
    """
    if geom is None or geom.is_empty or geom.is_valid:
        return geom
    try:
        repaired = make_valid(geom) if make_valid is not None else geom.buffer(0)
    except Exception:
        try:
            repaired = geom.buffer(0)
        except Exception:
            repaired = geom
    return repaired

def _pairwise_overlaps(polys: list):
    if not polys:
        return []
    safe_polys = [_repair_for_analysis(p) for p in polys]
    tree = STRtree(safe_polys)
    overlaps = []
    seen = set()
    for i, poly in enumerate(safe_polys):
        if poly is None or poly.is_empty:
            continue
        for j in tree.query(poly):
            j = int(j)
            if j == i:
                continue
            a, b = sorted((i, j))
            if (a, b) in seen:
                continue
            seen.add((a, b))
            try:
                inter = poly.intersection(safe_polys[j])
            except Exception:
                continue
            if not inter.is_empty and inter.area > 1e-8:
                overlaps.append({"a": a, "b": b, "area": float(inter.area)})
    return overlaps

def validate_topology(parcels: list, envelope, crs_text: str | None = None) -> dict:
    """Validate parcel-fabric topology without treating all non-parcel raster area as a gap.

    The previous implementation computed ``envelope.difference(union(parcels))``.
    For a drone orthomosaic this incorrectly labels every road, field, water body,
    and uncovered area outside the parcel fabric as a cadastral gap. The validator
    now reports only *enclosed internal gaps* formed by parcel boundaries.

    Small numerical overlaps/gaps and tiny fragments are filtered using metric-area
    tolerances. Thresholds can be overridden with environment variables:
      AEROCAD_TOPOLOGY_OVERLAP_M2 (default 0.25)
      AEROCAD_TOPOLOGY_GAP_M2     (default 1.0)
      AEROCAD_TOPOLOGY_SLIVER_M2  (default 0.50)
    """
    import os

    overlap_tol = float(os.getenv("AEROCAD_TOPOLOGY_OVERLAP_M2", "0.25"))
    gap_tol = float(os.getenv("AEROCAD_TOPOLOGY_GAP_M2", "1.0"))
    sliver_tol = float(os.getenv("AEROCAD_TOPOLOGY_SLIVER_M2", "0.50"))

    safe_parcels = [_repair_for_analysis(p) for p in parcels] if parcels else []
    overlaps_raw = _pairwise_overlaps(safe_parcels) if safe_parcels else []
    overlaps = [o for o in overlaps_raw if o["area"] > overlap_tol]

    try:
        union = unary_union([p for p in safe_parcels if p is not None and not p.is_empty]) if safe_parcels else GeometryCollection()
    except Exception:
        union = GeometryCollection()
        for geom in safe_parcels:
            if geom is None or geom.is_empty:
                continue
            try:
                union = union.union(geom)
            except Exception:
                continue

    # Build the planar parcel fabric from all parcel boundaries. polygonize()
    # returns finite enclosed faces only, avoiding the giant exterior face created
    # by comparing the parcel union against the full orthomosaic envelope.
    internal_gaps: list[dict] = []
    if parcels and not union.is_empty:
        boundary_network = unary_union([p.boundary for p in safe_parcels if p is not None and not p.is_empty])
        for face in polygonize(boundary_network):
            if face.is_empty or face.area <= gap_tol:
                continue
            # A polygonized face whose representative point is not covered by the
            # parcel union is an enclosed hole/gap inside the parcel fabric.
            if union.covers(face.representative_point()):
                continue
            nearby = []
            probe = face.boundary.buffer(max(0.25, min(1.0, face.length * 0.01)))
            for idx, parcel in enumerate(safe_parcels):
                if parcel is not None and not parcel.is_empty and parcel.boundary.intersects(probe):
                    nearby.append(idx)
            internal_gaps.append({
                "area": float(face.area),
                "geometry": mapping(face),
                "parcel_indices": nearby[:8],
            })

    areas = [p.area for p in parcels]
    slivers = []
    for i, parcel in enumerate(parcels):
        safe_area = abs(float(safe_parcels[i].area)) if i < len(safe_parcels) and safe_parcels[i] is not None else 0.0
        if safe_area < sliver_tol:
            slivers.append(i)

    invalid = [i for i, p in enumerate(parcels) if p is not None and not p.is_valid]
    affected = {i for o in overlaps for i in (o["a"], o["b"])}
    affected.update(sl_i for sl_i in slivers)
    affected.update(i for i in invalid)
    total = len(parcels)
    issue_count = len(overlaps) + len(internal_gaps) + len(slivers) + len(invalid)
    health = 100.0 if total == 0 else max(0.0, 100.0 - (len(affected) / max(total, 1)) * 100.0)

    return {
        "health": round(health, 1),
        "total_parcels": total,
        "overlaps": [{
            "parcel_a": int(o["a"]),
            "parcel_b": int(o["b"]),
            "area": float(o["area"]),
        } for o in overlaps],
        "gaps": internal_gaps,
        "external_uncovered_area_m2": float(max(0.0, (envelope.difference(union).area if union is not None and not union.is_empty and envelope else 0.0))),
        "invalid_geometries": [{"parcel": int(i), "reason": "self-intersection or invalid ring"} for i in invalid],
        "slivers": [{"parcel": int(i), "area": float(parcels[i].area)} for i in slivers],
        "tolerances_m2": {
            "overlap": overlap_tol,
            "gap": gap_tol,
            "sliver": sliver_tol,
        },
        "issue_count": issue_count,
        "method": "Metric parcel-fabric topology validation: tolerance-filtered overlaps, enclosed internal gaps, micro-slivers, and invalid geometries",
    }


def infer_parcels(project_dir: Path, source_crs: str | None, ori_filename: str, existing_path: Path | None = None) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(project_dir / f"ori__{ori_filename}") as src:
        extent_src = box(*src.bounds)
    metric_crs = metric_crs_for_geometry(extent_src, source_crs) or source_crs
    extent = transform_geom(extent_src, source_crs, metric_crs)
    buildings = _load_buildings(output_dir, metric_crs)
    roads = _load_roads(output_dir, metric_crs)
    mode = "existing-gis-assisted" if existing_path else "inferred-candidates"
    source_geoms = read_existing_parcels(existing_path, metric_crs) if existing_path and existing_path.exists() else []
    if source_geoms:
        parcels = source_geoms
    else:
        parcels = _generate_voronoi(buildings, extent)
        if not parcels:
            parcels = _grid_candidates(extent)
            mode = "fallback-grid-candidates"
    clipped=[]
    min_area=max(extent.area*1e-7,0.05)
    for p in parcels:
        q=p.intersection(extent)
        for poly in _explode_polygons(q):
            if poly.area>=min_area:
                clipped.append(poly)
    parcels=clipped
    features=[]
    for idx,p in enumerate(parcels,1):
        out_geom=transform_geom(p, metric_crs, "EPSG:4326") if metric_crs else p
        land_use, land_conf=_score_land_use(p, buildings, roads)
        evidence={"existing_gis":45 if source_geoms else 0,"imagery_edge":24,"structure":16 if buildings else 0,"road_access":10 if roads else 0,"terrain":5}
        total=sum(evidence.values()) or 1
        evidence={k:round(v*100/total,1) for k,v in evidence.items()}
        conf=int(max(5,min(98,round(sum(evidence.values())*0.25))))
        features.append({"type":"Feature","geometry":mapping(out_geom),"properties":{
            "parcel_id":f"P-{idx:04d}","area":float(p.area),"perimeter":float(p.length),"area_unit":"m²",
            "land_use":land_use,"land_use_confidence":round(float(land_conf),2),"building_count":int(sum(1 for b in buildings if b.intersects(p))),
            "boundary_confidence":conf,"status":"Ready" if conf>=70 else "Review","generation_mode":mode,"evidence":evidence,
            "metric_crs":metric_crs,"review_reason":"Low boundary confidence" if conf<70 else ""
        }})
    parcel_path=output_dir/"parcels.geojson"
    parcel_path.write_text(json.dumps({"type":"FeatureCollection","features":features}),encoding="utf-8")
    boundary_features=[{"type":"Feature","geometry":mapping(shape(f["geometry"]).boundary),"properties":{"parcel_id":f["properties"]["parcel_id"],"confidence":f["properties"]["boundary_confidence"]}} for f in features]
    (output_dir/"parcel_boundaries.geojson").write_text(json.dumps({"type":"FeatureCollection","features":boundary_features}),encoding="utf-8")
    topo=validate_topology(parcels,extent,metric_crs)
    (output_dir/"topology.json").write_text(json.dumps(topo,indent=2),encoding="utf-8")
    return {"parcel_count":len(features),"ready_count":sum(f["properties"]["status"]=="Ready" for f in features),"review_count":sum(f["properties"]["status"]=="Review" for f in features),"mode":mode,"metric_crs":metric_crs,"topology":topo,"outputs":["parcels.geojson","parcel_boundaries.geojson","topology.json"]}

