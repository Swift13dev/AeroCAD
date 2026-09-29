from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import Point, LineString, shape, mapping
from shapely.ops import split as split_geometry, transform, unary_union

from .parcel import _transform_geometries, metric_crs_for_geometry, validate_topology
from .workflow import build_field_queue


def _read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _parcel_store(project_dir: Path) -> Path:
    return project_dir / "processing" / "outputs" / "parcels.geojson"


def _read_parcels(project_dir: Path) -> dict:
    return _read_json(_parcel_store(project_dir), {"type": "FeatureCollection", "features": []})


def _find_parcel(data: dict, parcel_id: str) -> tuple[dict, int]:
    for idx, feature in enumerate(data.get("features", [])):
        if (feature.get("properties") or {}).get("parcel_id") == parcel_id:
            return feature, idx
    raise ValueError("Parcel not found.")


def _source_crs(project_dir: Path) -> str | None:
    validation = _read_json(project_dir / "validation.json", {})
    raster = validation.get("raster_summary") or {}
    return raster.get("crs")


def _metric_transformer(source_crs: str | None):
    if not source_crs:
        return None
    try:
        crs = CRS.from_user_input(source_crs)
        if crs.is_projected:
            return None
        return Transformer.from_crs(crs, CRS.from_epsg(3857), always_xy=True)
    except Exception:
        return None


def _metric_geom(geometry, source_crs: str | None):
    transformer = _metric_transformer(source_crs)
    if transformer is None:
        return geometry
    fn = lambda x, y, z=None: transformer.transform(x, y)
    return transform(fn, geometry)


def _distance_m(a, b, source_crs: str | None) -> float:
    return float(_metric_geom(a, source_crs).distance(_metric_geom(b, source_crs)))


def _area_m2(geometry, source_crs: str | None) -> float:
    return float(_metric_geom(geometry, source_crs).area)


def _perimeter_m(geometry, source_crs: str | None) -> float:
    return float(_metric_geom(geometry, source_crs).length)


def _geometry_from_payload(geometry_payload: dict, original_geometry):
    geometry = shape(geometry_payload)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Edited parcel geometry must be a non-empty Polygon or MultiPolygon.")
    # Preserve existing holes for a single-ring browser edit when the original polygon has interiors.
    if geometry.geom_type == "Polygon" and original_geometry.geom_type == "Polygon" and len(geometry.interiors) == 0 and len(original_geometry.interiors) > 0:
        from shapely.geometry import Polygon
        geometry = Polygon(list(geometry.exterior.coords), [list(r.coords) for r in original_geometry.interiors])
    return geometry


def _snapshot_original(project_dir: Path) -> None:
    current = _parcel_store(project_dir)
    original = current.with_name("parcels_original.geojson")
    if current.exists() and not original.exists():
        original.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")


def _vertex_shift_metrics(original, edited, source_crs: str | None) -> dict[str, float | int]:
    old = list(original.exterior.coords)[:-1] if original.geom_type == "Polygon" else []
    new = list(edited.exterior.coords)[:-1] if edited.geom_type == "Polygon" else []
    paired = min(len(old), len(new))
    shifts = []
    for idx in range(paired):
        shifts.append(_distance_m(Point(old[idx]), Point(new[idx]), source_crs))
    return {
        "original_vertices": len(old),
        "edited_vertices": len(new),
        "paired_vertices": paired,
        "max_vertex_shift_m": round(max(shifts) if shifts else 0.0, 3),
        "mean_vertex_shift_m": round(sum(shifts) / len(shifts), 3) if shifts else 0.0,
    }


def _read_reference_features(path: Path, target_crs: str | None) -> list[tuple[Any, dict]]:
    suffix = path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_crs = "EPSG:4326"
        crs_obj = payload.get("crs") if isinstance(payload, dict) else None
        if isinstance(crs_obj, dict):
            source_crs = (crs_obj.get("properties") or {}).get("name") or source_crs
        out = []
        for feature in payload.get("features", []):
            if not feature.get("geometry"):
                continue
            geom = shape(feature["geometry"])
            props = dict(feature.get("properties") or {})
            if source_crs and target_crs and source_crs != target_crs:
                geom = _transform_geometries([geom], source_crs, target_crs)[0]
            out.append((geom, props))
        return out

    if suffix in {".gpkg", ".shp"}:
        import fiona

        layers = fiona.listlayers(path) if suffix == ".gpkg" else [None]
        out = []
        for layer in layers:
            with fiona.open(path, layer=layer) as src:
                source_crs = src.crs_wkt or src.crs
                source_crs_text = None
                if source_crs:
                    try:
                        source_crs_text = CRS.from_user_input(source_crs).to_string()
                    except Exception:
                        pass
                for feat in src:
                    if not feat.get("geometry"):
                        continue
                    geom = shape(feat["geometry"])
                    if source_crs_text and target_crs and source_crs_text != target_crs:
                        geom = _transform_geometries([geom], source_crs_text, target_crs)[0]
                    out.append((geom, dict(feat.get("properties") or {})))
        return out

    return []


def _load_gt(project_dir: Path, target_crs: str | None, parcel_id: str) -> tuple[Any | None, dict]:
    candidates = sorted(project_dir.glob("gt__*"))
    if not candidates:
        return None, {"status": "not_available"}
    refs = _read_reference_features(candidates[0], target_crs)
    if not refs:
        return None, {"status": "empty", "file": candidates[0].name}
    def candidate_id(props: dict) -> str | None:
        for key in ("parcel_id", "parcel_id", "id", "ID", "plot_id", "plot_no", "survey_no"):
            if props.get(key) is not None:
                return str(props.get(key))
        return None
    for geom, props in refs:
        ref_id = candidate_id(props)
        if ref_id and ref_id == parcel_id:
            return geom, {"status": "matched", "file": candidates[0].name, "match": "parcel_id"}
    return refs[0][0], {"status": "matched", "file": candidates[0].name, "match": "nearest_reference_first_feature"}


def _load_gnss(project_dir: Path, target_crs: str | None) -> list[Point]:
    points: list[Point] = []
    for path in sorted(project_dir.glob("gnss__*")):
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = csv.DictReader(handle)
                for row in rows:
                    norm = {str(k).strip().lower(): v for k, v in row.items()}
                    lat = next((norm.get(k) for k in ("lat", "latitude", "y") if norm.get(k) not in (None, "")), None)
                    lon = next((norm.get(k) for k in ("lon", "longitude", "x") if norm.get(k) not in (None, "")), None)
                    if lat is None or lon is None:
                        continue
                    try:
                        p = Point(float(lon), float(lat))
                        if target_crs and target_crs != "EPSG:4326":
                            p = _transform_geometries([p], "EPSG:4326", target_crs)[0]
                        points.append(p)
                    except ValueError:
                        continue
        elif suffix == ".gpx":
            try:
                import fiona
                with fiona.open(path) as src:
                    source_crs = CRS.from_user_input(src.crs_wkt or src.crs or "EPSG:4326").to_string()
                    for feature in src:
                        if feature.get("geometry"):
                            geom = shape(feature["geometry"])
                            if geom.geom_type == "Point":
                                if source_crs and target_crs and source_crs != target_crs:
                                    geom = _transform_geometries([geom], source_crs, target_crs)[0]
                                points.append(geom)
            except Exception:
                pass
    return points


def compare_reference(project_dir: Path, parcel_id: str, geometry, source_crs: str | None) -> dict:
    gt_geom, gt_meta = _load_gt(project_dir, source_crs, parcel_id)
    gt_result: dict[str, Any] = dict(gt_meta)
    if gt_geom is not None:
        union_area = _area_m2(geometry.union(gt_geom), source_crs)
        iou = _area_m2(geometry.intersection(gt_geom), source_crs) / union_area if union_area > 0 else 0.0
        symmetric = _area_m2(geometry.symmetric_difference(gt_geom), source_crs)
        gt_result.update({
            "iou": round(iou, 4),
            "intersection_area_m2": round(_area_m2(geometry.intersection(gt_geom), source_crs), 2),
            "symmetric_difference_m2": round(symmetric, 2),
            "boundary_deviation_m": round(_distance_m(geometry.boundary, gt_geom.boundary, source_crs), 3),
        })

    gnss_points = _load_gnss(project_dir, source_crs)
    gnss_distances = [round(_distance_m(p, geometry.boundary, source_crs), 3) for p in gnss_points]
    gnss_result = {
        "status": "not_available" if not gnss_points else "available",
        "points_checked": len(gnss_points),
        "nearest_boundary_m": min(gnss_distances) if gnss_distances else None,
        "mean_boundary_distance_m": round(sum(gnss_distances) / len(gnss_distances), 3) if gnss_distances else None,
    }

    return {"ground_truth": gt_result, "gnss": gnss_result}


def adjusted_confidence(old_confidence: int, geometry, original, source_crs: str | None, comparison: dict, topology_valid: bool) -> tuple[int, str]:
    score = float(old_confidence)
    old_area = max(_area_m2(original, source_crs), 1e-6)
    new_area = _area_m2(geometry, source_crs)
    area_delta_pct = abs(new_area - old_area) / old_area * 100.0
    if area_delta_pct > 25:
        score -= 12
    elif area_delta_pct > 10:
        score -= 6

    shift = _vertex_shift_metrics(original, geometry, source_crs)["max_vertex_shift_m"]
    threshold = max(math.sqrt(new_area) * 0.10, 0.5)
    if shift > threshold * 2:
        score -= 10
    elif shift > threshold:
        score -= 4

    gt = comparison.get("ground_truth", {})
    if gt.get("iou") is not None:
        iou = float(gt.get("iou", 0.0))
        score += (iou - 0.5) * 20.0
    gnss = comparison.get("gnss", {})
    nearest = gnss.get("nearest_boundary_m")
    if nearest is not None:
        if nearest <= 0.25:
            score += 4
        elif nearest <= 1.0:
            score += 1
        elif nearest > 5.0:
            score -= 6
    if not topology_valid:
        score -= 20
    return int(max(5, min(99, round(score)))), "review-adjusted evidence heuristic"


def revalidate_parcel(project_dir: Path, parcel_id: str, geometry_override: dict | None = None, note: str = "") -> dict:
    source_crs = _source_crs(project_dir)
    data = _read_parcels(project_dir)
    target, index = _find_parcel(data, parcel_id)
    original_geometry = shape(target["geometry"])
    geometry = _geometry_from_payload(geometry_override, original_geometry) if geometry_override else original_geometry
    if not geometry.is_valid:
        validity_reason = "Edited geometry is invalid; repair before final approval."
    else:
        validity_reason = "Geometry passes Shapely validity check."

    topo_data = json.loads(json.dumps(data))
    topo_data["features"][index]["geometry"] = mapping(geometry)
    topology = _topology_for_features(project_dir, topo_data, source_crs)
    comparison = compare_reference(project_dir, parcel_id, geometry, source_crs)

    old_conf = int((target.get("properties") or {}).get("boundary_confidence", 50) or 50)
    new_conf, confidence_type = adjusted_confidence(old_conf, geometry, original_geometry, source_crs, comparison, geometry.is_valid)
    props = target.setdefault("properties", {})
    props.update({
        "area": _area_m2(geometry, source_crs) if source_crs else float(geometry.area),
        "perimeter": _perimeter_m(geometry, source_crs) if source_crs else float(geometry.length),
        "boundary_confidence": new_conf,
        "boundary_confidence_type": confidence_type,
        "revalidation_status": "Validated" if geometry.is_valid else "Needs Review",
        "revalidated_at": datetime.now(timezone.utc).isoformat(),
        "revalidation_note": note,
        "review_reason": "Edited geometry needs review" if not geometry.is_valid or new_conf < 70 else "",
    })
    if geometry_override is not None:
        # Any geometry edit invalidates a prior field confirmation because the
        # survey decision was made against a different boundary. Route it back
        # through human verification rather than silently retaining Verified.
        props["verification_status"] = "Pending"
        props["verification_outcome"] = "pending_after_edit"
        props.pop("verified_at", None)
        props.pop("verification_method", None)
        props.pop("verification_notes", None)
        props.pop("gnss_lat", None)
        props.pop("gnss_lon", None)
    target["geometry"] = mapping(geometry)
    data["features"][index] = target
    _snapshot_original(project_dir)
    _parcel_store(project_dir).write_text(json.dumps(data), encoding="utf-8")

    history_path = project_dir / "processing" / "edit_log.json"
    history = _read_json(history_path, [])
    metrics = _vertex_shift_metrics(original_geometry, geometry, source_crs)
    old_area = max(_area_m2(original_geometry, source_crs), 1e-6)
    new_area = _area_m2(geometry, source_crs)
    metrics["area_delta_pct"] = round(abs(new_area - old_area) / old_area * 100.0, 2)
    history.append({
        "parcel_id": parcel_id,
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "action": "boundary-edit" if geometry_override else "revalidate",
        "metrics": metrics,
        "confidence_before": old_conf,
        "confidence_after": new_conf,
        "comparison": comparison,
        "topology_issue_count": topology["issue_count"],
        "note": note,
    })
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    build_field_queue(project_dir)
    return {
        "parcel_id": parcel_id,
        "parcel": target,
        "geometry": mapping(geometry),
        "metrics": metrics,
        "comparison": comparison,
        "confidence_before": old_conf,
        "confidence_after": new_conf,
        "confidence_type": confidence_type,
        "geometry_valid": geometry.is_valid,
        "validity_reason": validity_reason,
        "topology": topology,
        "status": props.get("revalidation_status"),
    }



def _write_parcel_outputs(project_dir: Path, data: dict) -> None:
    output_dir = project_dir / "processing" / "outputs"
    parcel_path = output_dir / "parcels.geojson"
    parcel_path.write_text(json.dumps(data), encoding="utf-8")
    boundary_features = []
    for feature in data.get("features", []):
        geom = shape(feature["geometry"])
        boundary_features.append({
            "type": "Feature",
            "geometry": mapping(geom.boundary),
            "properties": {
                "parcel_id": (feature.get("properties") or {}).get("parcel_id"),
                "confidence": (feature.get("properties") or {}).get("boundary_confidence", 0),
            },
        })
    (output_dir / "parcel_boundaries.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": boundary_features}),
        encoding="utf-8",
    )


def _topology_for_features(project_dir: Path, data: dict, source_crs: str | None) -> dict:
    geoms = [shape(feature["geometry"]) for feature in data.get("features", []) if feature.get("geometry")]
    if not geoms:
        return {"health": 100.0, "total_parcels": 0, "overlaps": [], "gaps": [], "slivers": [], "invalid_geometries": [], "issue_count": 0}
    envelope_src = geoms[0].envelope
    for geom in geoms[1:]:
        envelope_src = envelope_src.union(geom).envelope
    metric_crs = metric_crs_for_geometry(envelope_src, source_crs) or source_crs
    metric_geoms = [
        _transform_geometries([g], source_crs, metric_crs)[0] if metric_crs and source_crs else g
        for g in geoms
    ]
    envelope = metric_geoms[0].envelope
    for geom in metric_geoms[1:]:
        envelope = envelope.union(geom).envelope
    return validate_topology(metric_geoms, envelope, metric_crs)


def _refresh_topology_and_field_queue(project_dir: Path, data: dict, source_crs: str | None) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    topology = _topology_for_features(project_dir, data, source_crs)
    (output_dir / "topology.json").write_text(json.dumps(topology, indent=2), encoding="utf-8")
    build_field_queue(project_dir)
    return topology


def _next_parcel_id(data: dict) -> str:
    used = set()
    for feature in data.get("features", []):
        value = str((feature.get("properties") or {}).get("parcel_id", ""))
        if value.startswith("P-"):
            try:
                used.add(int(value.split("-")[-1]))
            except ValueError:
                pass
    return f"P-{(max(used) + 1 if used else 1):04d}"


def split_parcel(project_dir: Path, parcel_id: str, start: list[float], end: list[float], note: str = "") -> dict:
    source_crs = _source_crs(project_dir)
    data = _read_parcels(project_dir)
    target, index = _find_parcel(data, parcel_id)
    original = shape(target["geometry"])
    if original.geom_type != "Polygon":
        raise ValueError("Split is currently available for Polygon parcels only.")
    if len(start) != 2 or len(end) != 2:
        raise ValueError("Split requires two map coordinates.")
    line = LineString([tuple(start), tuple(end)])
    if line.length <= 0:
        raise ValueError("Split line is too short.")

    minx, miny, maxx, maxy = original.bounds
    diagonal = math.hypot(maxx - minx, maxy - miny) or 1.0
    ux = (end[0] - start[0]) / line.length
    uy = (end[1] - start[1]) / line.length
    extension = diagonal * 4.0
    splitter = LineString([
        (start[0] - ux * extension, start[1] - uy * extension),
        (end[0] + ux * extension, end[1] + uy * extension),
    ])
    try:
        pieces = [g for g in split_geometry(original, splitter).geoms if g.geom_type == "Polygon" and not g.is_empty]
    except Exception as exc:
        raise ValueError(f"Could not split parcel with that line: {exc}") from exc

    pieces = sorted(pieces, key=lambda g: g.area, reverse=True)
    if len(pieces) < 2:
        raise ValueError("The split line does not cross the parcel boundary in two places.")
    total_area = original.area or 1.0
    if pieces[1].area / total_area < 0.05:
        raise ValueError("Split creates a very small fragment. Draw the split farther from the edge.")

    _snapshot_original(project_dir)
    props = dict(target.get("properties") or {})
    base_conf = max(5, int(props.get("boundary_confidence", 50) or 50) - 6)
    first_props = dict(props)
    second_props = dict(props)
    second_id = _next_parcel_id(data)
    first_props.update({
        "area": _area_m2(pieces[0], source_crs),
        "perimeter": _perimeter_m(pieces[0], source_crs),
        "boundary_confidence": base_conf,
        "status": "Review",
        "verification_status": "Pending",
        "review_reason": "Parcel split requires survey review",
        "parent_parcel_id": parcel_id,
        "edit_action": "split",
        "edit_note": note,
    })
    second_props.update({
        "parcel_id": second_id,
        "area": _area_m2(pieces[1], source_crs),
        "perimeter": _perimeter_m(pieces[1], source_crs),
        "boundary_confidence": base_conf,
        "status": "Review",
        "verification_status": "Pending",
        "review_reason": "Parcel split requires survey review",
        "parent_parcel_id": parcel_id,
        "edit_action": "split",
        "edit_note": note,
    })
    # Preserve original ID on the larger piece so references remain as stable as possible.
    data["features"][index] = {"type": "Feature", "geometry": mapping(pieces[0]), "properties": first_props}
    data["features"].insert(index + 1, {"type": "Feature", "geometry": mapping(pieces[1]), "properties": second_props})
    _write_parcel_outputs(project_dir, data)
    topology = _refresh_topology_and_field_queue(project_dir, data, source_crs)

    history_path = project_dir / "processing" / "edit_log.json"
    history = _read_json(history_path, [])
    history.append({
        "parcel_id": parcel_id,
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "action": "split",
        "created_parcel_ids": [parcel_id, second_id],
        "note": note,
        "topology_issue_count": topology.get("issue_count", 0),
    })
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return {"action": "split", "parcel": data["features"][index], "new_parcel": data["features"][index + 1], "topology": topology}


def merge_parcels(project_dir: Path, primary_id: str, secondary_id: str, note: str = "") -> dict:
    if primary_id == secondary_id:
        raise ValueError("Choose two different parcels to merge.")
    source_crs = _source_crs(project_dir)
    data = _read_parcels(project_dir)
    primary, primary_index = _find_parcel(data, primary_id)
    secondary, secondary_index = _find_parcel(data, secondary_id)
    a = shape(primary["geometry"])
    b = shape(secondary["geometry"])
    if a.geom_type != "Polygon" or b.geom_type != "Polygon":
        raise ValueError("Merge is currently available for Polygon parcels only.")
    shared_distance = _distance_m(a.boundary, b.boundary, source_crs)
    merged = unary_union([a, b])
    if a.overlaps(b):
        raise ValueError("The selected parcels overlap. Resolve the topology overlap before using merge.")
    if merged.geom_type != "Polygon":
        raise ValueError("These parcels do not form one contiguous polygon. Only adjacent/touching parcels can be merged.")
    if shared_distance > 2.0 and not a.intersects(b):
        raise ValueError("The selected parcels are too far apart to merge safely.")

    _snapshot_original(project_dir)
    pp = dict(primary.get("properties") or {})
    sp = dict(secondary.get("properties") or {})
    confidence_values = [int(pp.get("boundary_confidence", 50) or 50), int(sp.get("boundary_confidence", 50) or 50)]
    pp.update({
        "area": _area_m2(merged, source_crs),
        "perimeter": _perimeter_m(merged, source_crs),
        "boundary_confidence": max(5, min(confidence_values) - 4),
        "status": "Review",
        "verification_status": "Pending",
        "review_reason": "Parcel merge requires survey review",
        "merged_from": sorted(set([primary_id, secondary_id] + list(pp.get("merged_from") or []) + list(sp.get("merged_from") or []))),
        "edit_action": "merge",
        "edit_note": note,
    })
    primary["geometry"] = mapping(merged)
    primary["properties"] = pp
    # Delete the secondary after locating indexes, highest index first.
    for idx in sorted([primary_index, secondary_index], reverse=True):
        if idx == primary_index:
            continue
        data["features"].pop(idx)
    # If primary was after secondary, the list still contains primary at its original index.
    for feature in data["features"]:
        if (feature.get("properties") or {}).get("parcel_id") == primary_id:
            feature.update(primary)
            break

    _write_parcel_outputs(project_dir, data)
    topology = _refresh_topology_and_field_queue(project_dir, data, source_crs)
    history_path = project_dir / "processing" / "edit_log.json"
    history = _read_json(history_path, [])
    history.append({
        "parcel_id": primary_id,
        "edited_at": datetime.now(timezone.utc).isoformat(),
        "action": "merge",
        "merged_parcel_id": secondary_id,
        "note": note,
        "topology_issue_count": topology.get("issue_count", 0),
    })
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return {"action": "merge", "parcel": next(f for f in data["features"] if (f.get("properties") or {}).get("parcel_id") == primary_id), "removed_parcel_id": secondary_id, "topology": topology}


def get_edit_history(project_dir: Path) -> list[dict]:
    return _read_json(project_dir / "processing" / "edit_log.json", [])
