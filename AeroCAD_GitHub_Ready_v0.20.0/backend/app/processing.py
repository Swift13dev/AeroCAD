from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from rasterio.warp import transform_geom
from shapely.geometry import shape as shapely_shape
from shapely.ops import unary_union

from .specialized_models import AeroCADSpecialists
from .parcel import infer_parcels
from .evidence import fuse_boundary_evidence
from .workflow import build_field_queue


class ProcessingError(RuntimeError):
    pass


def _write_geojson(path: Path, geometries: list[dict], crs: str | None, source: str) -> None:
    geojson_geometries = [transform_geom(crs, "EPSG:4326", geom, precision=7) if crs else geom for geom in geometries]
    payload = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {"source": source}} for geom in geojson_geometries]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.with_suffix(".crs.json").write_text(json.dumps({"source_crs": crs}, indent=2), encoding="utf-8")


def _baseline_mask(tile: np.ndarray, dsm_tile: np.ndarray | None, dtm_tile: np.ndarray | None = None) -> np.ndarray:
    rgb = tile.astype(np.float32) / 255.0
    mx = rgb.max(axis=2); mn = rgb.min(axis=2)
    chroma = mx - mn; brightness = rgb.mean(axis=2)
    white_roof = (brightness > 0.58) & (chroma < 0.20)
    red_tile = (rgb[...,0] > 0.40) & (rgb[...,0] > rgb[...,1]*1.08) & (rgb[...,0] > rgb[...,2]*1.04) & (brightness > 0.30)
    dark_roof = (brightness > 0.18) & (brightness < 0.52) & (chroma < 0.10)
    mask = white_roof | red_tile | dark_roof
    try:
        from PIL import Image, ImageFilter
        im=Image.fromarray(mask.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
        mask=np.asarray(im)>0
    except Exception:
        pass
    return mask.astype(np.uint8)


def _baseline_road_mask(tile: np.ndarray) -> np.ndarray:
    rgb=tile.astype(np.float32)/255.0
    mx=rgb.max(axis=2); mn=rgb.min(axis=2); chroma=mx-mn; brightness=rgb.mean(axis=2)
    neutral=(chroma<0.14)&(brightness>0.24)&(brightness<0.76)
    tan=(rgb[...,0]>0.34)&(rgb[...,1]>0.25)&(rgb[...,2]<0.40)&(np.abs(rgb[...,0]-rgb[...,1])<0.22)
    mask=neutral|tan
    try:
        from PIL import Image, ImageFilter
        im=Image.fromarray(mask.astype(np.uint8)*255).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(9))
        mask=np.asarray(im)>0
    except Exception:
        pass
    return mask.astype(np.uint8)


def _polygonize(mask: np.ndarray, transform, min_pixels: int, max_fraction: float = 0.12) -> list[dict]:
    geometries = []
    pixel_area = abs(float(transform.a * transform.e - transform.b * transform.d)) or 1.0
    total_pixels = int(mask.shape[0] * mask.shape[1])
    for geom, value in shapes(mask.astype(np.uint8), mask=mask.astype(bool), transform=transform):
        if int(value) != 1:
            continue
        poly = shapely_shape(geom)
        if poly.is_empty:
            continue
        equivalent_pixels = float(poly.area) / pixel_area
        if equivalent_pixels < min_pixels:
            continue
        if equivalent_pixels > total_pixels * max_fraction:
            continue
        geometries.append(geom)
    return geometries


def _find_input(project_dir: Path, key: str, filename: str) -> Path:
    target = project_dir / f"{key}__{filename}"
    if not target.exists():
        raise ProcessingError(f"Uploaded {key.upper()} input was not found on disk.")
    return target


def _merge_features(geometries: list[dict]) -> list[dict]:
    if not geometries:
        return []
    union = unary_union([shapely_shape(g) for g in geometries])
    if union.geom_type == "Polygon":
        return [union.__geo_interface__]
    return [g.__geo_interface__ for g in getattr(union, "geoms", [])]


def _save_mask_preview(mask: np.ndarray, path: Path) -> None:
    try:
        from PIL import Image
        Image.fromarray((mask.astype(np.uint8) * 255)).save(path)
    except Exception:
        pass


def run_processing(project_dir: Path, progress: Callable[[int, str, str], None]) -> dict:
    validation_path = project_dir / "validation.json"
    if not validation_path.exists():
        raise ProcessingError("Run dataset validation before extraction.")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if not validation.get("ready"):
        raise ProcessingError("Project preflight is not ready for processing.")
    records = validation.get("records", [])
    ori_record = next((r for r in records if r.get("key") == "ori"), None)
    dsm_record = next((r for r in records if r.get("key") == "dsm"), None)
    if not ori_record:
        raise ProcessingError("ORI input not found.")

    ori_path = _find_input(project_dir, "ori", ori_record["filename"])
    dsm_path = _find_input(project_dir, "dsm", dsm_record["filename"]) if dsm_record else None
    dtm_record = next((r for r in records if r.get("key") == "dtm"), None)
    dtm_path = _find_input(project_dir, "dtm", dtm_record["filename"]) if dtm_record else None
    parcel_record = next((r for r in records if r.get("key") == "parcels"), None)
    parcel_path = _find_input(project_dir, "parcels", parcel_record["filename"]) if parcel_record else None

    processing_dir = project_dir / "processing"
    tile_dir = processing_dir / "tiles"
    outputs = processing_dir / "outputs"
    tile_dir.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ori_path) as src:
        width, height = src.width, src.height
        crs = src.crs.to_string() if src.crs else None
        tile_size, overlap = 1024, 64
        stride = tile_size - overlap
        total_tiles_x = max(math.ceil(width / stride), 1)
        total_tiles_y = max(math.ceil(height / stride), 1)
        total_tiles = total_tiles_x * total_tiles_y

        dsm_src = rasterio.open(dsm_path) if dsm_path else None
        dsm = WarpedVRT(dsm_src, crs=src.crs, transform=src.transform, width=src.width, height=src.height, resampling=Resampling.bilinear) if dsm_src is not None else None
        dtm_src = rasterio.open(dtm_path) if dtm_path else None
        dtm = WarpedVRT(dtm_src, crs=src.crs, transform=src.transform, width=src.width, height=src.height, resampling=Resampling.bilinear) if dtm_src is not None else None

        specialists = AeroCADSpecialists(project_dir)
        building_geometries: list[dict] = []
        road_geometries: list[dict] = []
        building_masks = []
        road_masks = []
        building_detail = []
        road_detail = []
        building_available = False
        road_available = False
        mode_parts: set[str] = set()

        try:
            progress(6, "preflight", "Project validated; preparing specialist aerial-feature extraction")
            tile_index = 0
            for row, y in enumerate(range(0, height, stride)):
                for col, x in enumerate(range(0, width, stride)):
                    win = Window(x, y, min(tile_size, width-x), min(tile_size, height-y))
                    transform_win = src.window_transform(win)
                    bands = min(src.count, 3)
                    raw = src.read(list(range(1, bands+1)), window=win)
                    if bands == 1:
                        tile = np.repeat(raw[0][...,None], 3, axis=2)
                    elif bands == 2:
                        tile = np.moveaxis(raw, 0, -1)
                        tile = np.concatenate([tile, tile[...,-1:]], axis=2)
                    else:
                        tile = np.moveaxis(raw, 0, -1)
                    tile = tile.astype(np.float32)
                    lo, hi = np.percentile(tile, [1, 99])
                    tile = np.clip((tile-lo)/max(hi-lo, 1.0), 0, 1)
                    tile = (tile*255).astype(np.uint8)

                    dsm_tile = None
                    if dsm is not None:
                        try:
                            dsm_tile = dsm.read(1, window=win, out_shape=(int(win.height), int(win.width))).astype(np.float32)
                        except Exception:
                            dsm_tile = None
                    dtm_tile = None
                    if dtm is not None:
                        try:
                            dtm_tile = dtm.read(1, window=win, out_shape=(int(win.height), int(win.width))).astype(np.float32)
                        except Exception:
                            dtm_tile = None

                    building_result, road_result = specialists.predict(tile)
                    building_detail.append(building_result.detail)
                    road_detail.append(road_result.detail)

                    if building_result.mask is None:
                        building_mask = _baseline_mask(tile, dsm_tile, dtm_tile)
                        mode_parts.add("building-baseline-fallback")
                    else:
                        building_mask = building_result.mask
                        building_available = True
                        mode_parts.add("building-specialist")
                    if road_result.mask is None:
                        road_mask = _baseline_road_mask(tile)
                        mode_parts.add("road-baseline-fallback")
                    else:
                        road_mask = road_result.mask
                        road_available = True
                        mode_parts.add("road-specialist")

                    b_polys = _polygonize(building_mask, transform_win, min_pixels=80, max_fraction=0.10)
                    r_polys = _polygonize(road_mask, transform_win, min_pixels=120, max_fraction=0.45)
                    building_geometries.extend(b_polys)
                    road_geometries.extend(r_polys)
                    if tile_index < 8:
                        from PIL import Image
                        Image.fromarray(tile).save(tile_dir/f"tile_{row:03d}_{col:03d}.jpg", quality=85)
                    building_masks.append(building_mask)
                    road_masks.append(road_mask)
                    tile_index += 1
                    progress(10 + int(62 * tile_index / total_tiles), "features", f"Specialist feature extraction: tile {tile_index}/{total_tiles}")

            progress(75, "vectorize", "Converting specialist masks to GIS features")
            building_geometries = _merge_features(building_geometries)
            road_geometries = _merge_features(road_geometries)
            _write_geojson(outputs/"buildings.geojson", building_geometries, crs, "AeroCAD specialist building extraction")
            _write_geojson(outputs/"roads.geojson", road_geometries, crs, "AeroCAD specialist road extraction")

            if building_masks:
                _save_mask_preview(building_masks[0], outputs/"building_mask_preview.png")
            if road_masks:
                _save_mask_preview(road_masks[0], outputs/"road_mask_preview.png")

            specialist_meta = {
                "building_model": specialists.buildings.model_id,
                "building_available": building_available,
                "building_threshold": specialists.buildings.threshold,
                "building_detail_sample": building_detail[:4],
                "road_model": specialists.roads.model_id,
                "road_available": road_available,
                "road_confidence": specialists.roads.confidence,
                "road_detail_sample": road_detail[:4],
            }
            (outputs/"specialist_models.json").write_text(json.dumps(specialist_meta, indent=2), encoding="utf-8")

            progress(82, "parcels", "Inferring candidate parcel polygons from multi-source evidence")
            parcel_summary = infer_parcels(project_dir, crs, ori_record["filename"], parcel_path)

            progress(88, "evidence", "Fusing imagery, specialist structures, access, terrain and GIS boundary evidence")
            evidence_summary = fuse_boundary_evidence(project_dir, crs, ori_record["filename"], parcel_path)
            workflow_queue = build_field_queue(project_dir)

            progress(94, "qc", "Running topology validation, field prioritisation and confidence checks")
            topo = parcel_summary["topology"]
            summary = {
                "status": "complete",
                "mode": "+".join(sorted(mode_parts)) or "specialist",
                "model_id": specialists.buildings.model_id,
                "road_model_id": specialists.roads.model_id,
                "model_detail": "Dedicated aerial building and roadway specialists with safe deterministic fallbacks.",
                "source_crs": crs,
                "source_size": {"width": width, "height": height},
                "tile_size": tile_size,
                "overlap": overlap,
                "tiles_processed": total_tiles,
                "dtm_used": bool(dtm_path),
                "building_candidates": len(building_geometries),
                "road_candidates": len(road_geometries),
                "building_specialist_available": building_available,
                "road_specialist_available": road_available,
                "feature_extraction_note": "Building and road outputs come from dedicated aerial specialist models when available; deterministic fallbacks are used only when a specialist cannot produce a mask.",
                "parcel_count": parcel_summary["parcel_count"],
                "ready_parcels": parcel_summary["ready_count"],
                "review_parcels": parcel_summary["review_count"],
                "average_boundary_confidence": evidence_summary["average_boundary_confidence"],
                "potential_encroachment_count": evidence_summary["potential_encroachment_count"],
                "evidence_method": evidence_summary["method"],
                "parcel_mode": parcel_summary["mode"],
                "topology_health": topo["health"],
                "topology_issue_count": topo["issue_count"],
                "outputs": [
                    "buildings.geojson",
                    "roads.geojson",
                    "building_mask_preview.png",
                    "road_mask_preview.png",
                    "specialist_models.json",
                    "parcels.geojson",
                    "parcel_boundaries.geojson",
                    "boundary_evidence.geojson",
                    "boundary_evidence.json",
                    "topology.json",
                    "field_queue.json",
                ],
                "field_queue_count": workflow_queue["summary"]["count"],
                "field_queue_critical": workflow_queue["summary"]["critical"],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            (processing_dir/"result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            progress(100, "complete", "Dedicated building/road extraction, parcel inference and topology QA complete")
            return summary
        finally:
            if dsm is not None: dsm.close()
            if dsm_src is not None: dsm_src.close()
            if dtm is not None: dtm.close()
            if dtm_src is not None: dtm_src.close()
