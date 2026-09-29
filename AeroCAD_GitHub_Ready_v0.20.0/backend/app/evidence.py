from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform, unary_union
try:
    from shapely.validation import make_valid
except ImportError:
    make_valid = None

from .metrics import metric_crs_for_geometry, transform_geom



def _repair_for_analysis(geom):
    """Repair invalid geometry only for analytical overlay operations."""
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

def _read_geojson(path: Path, source_crs: str | None = None, target_crs: str | None = None) -> list:
    payload = json.loads(path.read_text(encoding="utf-8"))
    crs_text = source_crs or "EPSG:4326"
    crs_obj = payload.get("crs") if isinstance(payload, dict) else None
    if isinstance(crs_obj, dict):
        crs_text = (crs_obj.get("properties") or {}).get("name") or crs_text
    geoms = [shape(f["geometry"]) for f in payload.get("features", []) if f.get("geometry")]
    if crs_text and target_crs and CRS.from_user_input(crs_text) != CRS.from_user_input(target_crs):
        transformer = Transformer.from_crs(crs_text, target_crs, always_xy=True)
        fn = lambda x, y, z=None: transformer.transform(x, y)
        geoms = [transform(fn, g) for g in geoms]
    return [_repair_for_analysis(g) for g in geoms if not g.is_empty]


def _load_output(output_dir: Path, filename: str, target_crs: str | None) -> list:
    path = output_dir / filename
    if not path.exists():
        return []
    return _read_geojson(path, "EPSG:4326", target_crs)


def _load_existing(path: Path | None, target_crs: str | None) -> list:
    if not path or not path.exists():
        return []
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        return _read_geojson(path, target_crs, target_crs)
    if suffix in {".gpkg", ".shp"}:
        import fiona
        geoms: list = []
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
                        geoms.append(shape(feat["geometry"]))
                if src_crs_text and target_crs and CRS.from_user_input(src_crs_text) != CRS.from_user_input(target_crs):
                    transformer = Transformer.from_crs(src_crs_text, target_crs, always_xy=True)
                    fn = lambda x, y, z=None: transformer.transform(x, y)
                    geoms = [transform(fn, g) for g in geoms]
        return [_repair_for_analysis(g) for g in geoms if not g.is_empty]
    return []


def _sample_points(line, count: int = 12) -> list[Point]:
    if line.is_empty or line.length <= 0:
        return []
    return [line.interpolate((i + 0.5) / count, normalized=True) for i in range(count)]


def _boundary_proximity_score(parcel, geoms: list, distance: float) -> float:
    if not geoms or parcel.boundary.length <= 0:
        return 0.0
    target = parcel.boundary.buffer(max(distance, 1e-6))
    safe_geoms = [_repair_for_analysis(g) for g in geoms if g is not None and not g.is_empty]
    if not safe_geoms:
        return 0.0
    inter = unary_union(safe_geoms).intersection(target)
    if inter.is_empty:
        return 0.0
    # Convert area/length contact into a bounded evidence score.
    contact = min(1.0, inter.area / max(target.area, 1e-9))
    return float(100.0 * contact)


def _existing_match(parcel, existing: list) -> float:
    if not existing:
        return 0.0
    best = 0.0
    safe_parcel = _repair_for_analysis(parcel)
    for other in existing:
        other = _repair_for_analysis(other)
        if other is None or other.is_empty:
            continue
        union_area = safe_parcel.union(other).area
        if union_area <= 0:
            continue
        best = max(best, safe_parcel.intersection(other).area / union_area)
    return float(best * 100.0)


def _raster_edge_score(src, point: Point, pixel_x: float, pixel_y: float) -> float:
    try:
        row, col = src.index(point.x, point.y)
        row = int(row); col = int(col)
        if row <= 0 or col <= 0 or row >= src.height - 1 or col >= src.width - 1:
            return 0.0
        r = 1
        window = rasterio.windows.Window(col - r, row - r, 3, 3)
        data = src.read(indexes=list(range(1, min(src.count, 3) + 1)), window=window, boundless=True, fill_value=0)
        gray = data.astype(np.float32).mean(axis=0)
        gx = float(abs(gray[1, 2] - gray[1, 0]))
        gy = float(abs(gray[2, 1] - gray[0, 1]))
        mag = math.sqrt(gx * gx + gy * gy)
        # 0–100 mapping using an intentionally conservative fixed image-space scale.
        return min(100.0, mag / 2.0)
    except Exception:
        return 0.0


def _raster_terrain_score(src, point: Point) -> float:
    try:
        row, col = src.index(point.x, point.y)
        row = int(row); col = int(col)
        window = rasterio.windows.Window(col - 1, row - 1, 3, 3)
        data = src.read(1, window=window, boundless=True, fill_value=np.nan).astype(np.float32)
        finite = data[np.isfinite(data)]
        if finite.size < 4:
            return 0.0
        local_std = float(np.std(finite))
        return min(100.0, local_std * 18.0)
    except Exception:
        return 0.0


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: round(max(0.0, v) * 100.0 / total, 1) for k, v in weights.items()}


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload), encoding="utf-8")


def fuse_boundary_evidence(
    project_dir: Path,
    source_crs: str | None,
    ori_filename: str,
    existing_path: Path | None,
) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    parcel_path = output_dir / "parcels.geojson"
    if not parcel_path.exists():
        raise RuntimeError("Parcel output is required before boundary evidence fusion.")

    parcels_payload = json.loads(parcel_path.read_text(encoding="utf-8"))
    parcels = [f for f in parcels_payload.get("features", []) if f.get("geometry")]
    ori_path = project_dir / f"ori__{ori_filename}"
    with rasterio.open(ori_path) as meta:
        b = meta.bounds
        raster_extent = shape({"type":"Polygon","coordinates":[[[b.left,b.bottom],[b.right,b.bottom],[b.right,b.top],[b.left,b.top],[b.left,b.bottom]]]})
    metric_crs = metric_crs_for_geometry(raster_extent, source_crs) or source_crs
    buildings = _load_output(output_dir, "buildings.geojson", metric_crs)
    roads = _load_output(output_dir, "roads.geojson", metric_crs)
    existing = _load_existing(existing_path, metric_crs)
    dsm_path = next(iter(project_dir.glob("dsm__*")), None)

    boundary_features: list[dict] = []
    enriched_features: list[dict] = []
    encroachments = 0
    review_count = 0
    confidence_values: list[int] = []
    evidence_method = "Deterministic multi-source evidence fusion"

    with rasterio.open(ori_path) as ori:
        resolution = max(abs(float(ori.transform.a)), abs(float(ori.transform.e)), 0.01)
        dsm = rasterio.open(dsm_path) if dsm_path and dsm_path.exists() else None
        try:
            for feature in parcels:
                parcel_out = shape(feature["geometry"])
                parcel = transform_geom(parcel_out, source_crs, metric_crs)
                parcel_analysis = _repair_for_analysis(parcel)
                props = dict(feature.get("properties") or {})
                pid = props.get("parcel_id", "unknown")

                points = _sample_points(parcel_analysis.boundary, count=16)
                edge_scores = [_raster_edge_score(ori, transform_geom(p, metric_crs, source_crs), resolution, resolution) for p in points]
                terrain_scores = [_raster_terrain_score(dsm, transform_geom(p, metric_crs, source_crs)) for p in points] if dsm else []
                imagery_edge = float(np.mean(edge_scores)) if edge_scores else 0.0
                terrain = float(np.mean(terrain_scores)) if terrain_scores else 0.0
                structure = _boundary_proximity_score(parcel_analysis, buildings, resolution * 2.5)
                road_access = _boundary_proximity_score(parcel_analysis, roads, resolution * 4.0)
                existing_match = _existing_match(parcel_analysis, existing)

                raw = {
                    "existing_gis": existing_match if existing else 0.0,
                    "imagery_edge": imagery_edge,
                    "structure": structure,
                    "road_access": road_access,
                    "terrain": terrain,
                }
                # Weighted confidence, not a trained probability. Missing evidence sources are
                # removed and the remaining weights are renormalised so confidence is not
                # artificially capped merely because an optional layer was not supplied.
                base_weights = {
                    "existing_gis": 0.40,
                    "imagery_edge": 0.25,
                    "structure": 0.15,
                    "road_access": 0.10,
                    "terrain": 0.10,
                }
                availability = {
                    "existing_gis": bool(existing),
                    "imagery_edge": bool(points),
                    "structure": bool(buildings),
                    "road_access": bool(roads),
                    "terrain": dsm is not None,
                }
                weight_total = sum(w for k, w in base_weights.items() if availability[k]) or 1.0
                weighted = {
                    k: raw[k] * (base_weights[k] / weight_total) if availability[k] else 0.0
                    for k in base_weights
                }
                confidence = int(round(max(5.0, min(98.0, sum(weighted.values())))))

                # Encroachment is assessed locally: only structures intersecting the parcel
                # are considered, and only the part extending beyond that parcel is measured.
                outside_buildings = 0.0
                if existing:
                    for building in buildings:
                        building_safe = _repair_for_analysis(building)
                        if building_safe is not None and building_safe.intersects(parcel_analysis):
                            outside_buildings += max(0.0, building_safe.difference(parcel_analysis).area)
                potential_encroachment = outside_buildings > max(parcel.area * 0.01, resolution * resolution * 4)
                if potential_encroachment:
                    encroachments += 1

                topo_review = props.get("status") == "Review"
                status = "Review" if (confidence < 70 or topo_review or potential_encroachment) else "Ready"
                if status == "Review":
                    review_count += 1

                evidence = _normalise(weighted)
                props.update({
                    "boundary_confidence": confidence,
                    "boundary_confidence_type": "evidence-weighted heuristic",
                    "evidence": evidence,
                    "evidence_raw": {k: round(v, 2) for k, v in raw.items()},
                    "potential_encroachment": bool(potential_encroachment),
                    "field_verification_priority": "Critical" if potential_encroachment else ("High" if confidence < 60 else ("Medium" if confidence < 75 else "Low")),
                    "review_reason": (
                        "Potential encroachment" if potential_encroachment
                        else "Low boundary confidence" if confidence < 70
                        else "Topology review" if topo_review
                        else ""
                    ),
                    "evidence_method": evidence_method,
                })
                enriched_features.append({"type": "Feature", "geometry": feature["geometry"], "properties": props})
                confidence_values.append(confidence)

                boundary_features.append({
                    "type": "Feature",
                    "geometry": mapping(transform_geom(parcel_analysis.boundary, metric_crs, source_crs)),
                    "properties": {
                        "parcel_id": pid,
                        "confidence": confidence,
                        "evidence": evidence,
                        "priority": props["field_verification_priority"],
                        "potential_encroachment": bool(potential_encroachment),
                    },
                })
        finally:
            if dsm is not None:
                dsm.close()

    _write_geojson(parcel_path, enriched_features)
    _write_geojson(output_dir / "parcel_boundaries.geojson", boundary_features)
    _write_geojson(output_dir / "boundary_evidence.geojson", boundary_features)

    summary = {
        "method": evidence_method,
        "average_boundary_confidence": round(float(np.mean(confidence_values)), 1) if confidence_values else 0.0,
        "min_boundary_confidence": min(confidence_values) if confidence_values else 0,
        "max_boundary_confidence": max(confidence_values) if confidence_values else 0,
        "review_count": review_count,
        "potential_encroachment_count": encroachments,
        "evidence_sources": ["existing GIS" if existing else "imagery", "imagery edge", "structure", "road/access", "terrain"],
        "notes": "Confidence values are deterministic evidence-weighted indicators for prioritising review; they are not legal cadastral determinations or trained probabilistic outputs.",
    }
    (output_dir / "boundary_evidence.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
