from __future__ import annotations

import json
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd


def _json_safe_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _prepare_gdf(gdf: gpd.GeoDataFrame, *, shapefile: bool = False) -> gpd.GeoDataFrame:
    """Make GeoDataFrames safe for Fiona/GDAL vector writers.

    GeoJSON properties can contain nested evidence dictionaries/lists, but common
    GIS drivers expect scalar attribute fields. Shapefiles also impose a 10
    character field-name limit, so names are shortened deterministically without
    collisions.
    """
    gdf = gdf.copy()
    for column in list(gdf.columns):
        if column == "geometry":
            continue
        series = gdf[column]
        if any(isinstance(value, (dict, list, tuple)) for value in series.dropna()):
            gdf[column] = series.map(_json_safe_value)

    if shapefile:
        used = set()
        renamed = []
        counters = defaultdict(int)
        for column in gdf.columns:
            if column == "geometry":
                renamed.append(column)
                continue
            base = str(column)[:10] or "FIELD"
            key = base.upper()
            candidate = base
            if key in used:
                counters[key] += 1
                counter = counters[key]
                suffix = f"_{counter}"
                candidate = f"{base[:max(1, 10-len(suffix))]}{suffix}"
                while candidate.upper() in used:
                    counters[key] += 1
                    counter = counters[key]
                    suffix = f"_{counter}"
                    candidate = f"{base[:max(1, 10-len(suffix))]}{suffix}"
            used.add(candidate.upper())
            renamed.append(candidate)
        gdf.columns = renamed
    return gdf


OUTPUT_LAYERS = [
    ("parcels.geojson", "parcels", "Parcel candidates"),
    ("parcel_boundaries.geojson", "parcel_boundaries", "Parcel boundaries"),
    ("buildings.geojson", "buildings", "Building footprints"),
    ("roads.geojson", "roads", "Road / access candidates"),
    ("boundary_evidence.geojson", "boundary_evidence", "Boundary evidence"),
]


def _read_geojson(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(path)


def _safe_layer_name(value: str) -> str:
    return value.replace("-", "_").replace(" ", "_")[:48]


def _write_gpkg(output_dir: Path, gpkg_path: Path) -> list[str]:
    written: list[str] = []
    first = True
    for filename, layer, _label in OUTPUT_LAYERS:
        source = output_dir / filename
        if not source.exists():
            continue
        try:
            gdf = _read_geojson(source)
            if gdf.empty:
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            gdf = _prepare_gdf(gdf)
            mode = "w" if first else "a"
            gdf.to_file(gpkg_path, layer=_safe_layer_name(layer), driver="GPKG", mode=mode)
            written.append(layer)
            first = False
        except Exception as exc:  # noqa: BLE001
            # One optional export failure must not block the main GIS package.
            written.append(f"{layer} (GeoPackage skipped: {exc})")
    return written


def _write_shapefiles(output_dir: Path, shp_root: Path) -> list[str]:
    written: list[str] = []
    shp_root.mkdir(parents=True, exist_ok=True)
    for filename, layer, _label in OUTPUT_LAYERS:
        source = output_dir / filename
        if not source.exists():
            continue
        try:
            gdf = _read_geojson(source)
            if gdf.empty:
                continue
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            layer_dir = shp_root / _safe_layer_name(layer)
            layer_dir.mkdir(parents=True, exist_ok=True)
            target = layer_dir / f"{_safe_layer_name(layer)}.shp"
            # Shapefile field names are limited; keep the useful attributes.
            gdf = _prepare_gdf(gdf, shapefile=True)
            gdf.to_file(target, driver="ESRI Shapefile", encoding="UTF-8")
            written.append(layer)
        except Exception as exc:  # noqa: BLE001
            written.append(f"{layer} (Shapefile skipped: {exc})")
    return written


def build_export_package(project_dir: Path) -> Path:
    processing_dir = project_dir / "processing"
    output_dir = processing_dir / "outputs"
    if not output_dir.exists():
        raise FileNotFoundError("No processing outputs exist for this project.")

    result_path = processing_dir / "result.json"
    validation_path = project_dir / "validation.json"
    processing_path = project_dir / "processing.json"
    edit_log = processing_dir / "edit_log.json"

    staging = processing_dir / "export_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    # Preserve the easy-to-consume GeoJSON outputs exactly as generated.
    geojson_dir = staging / "geojson"
    geojson_dir.mkdir()
    copied = []
    for filename, _layer, _label in OUTPUT_LAYERS:
        source = output_dir / filename
        if source.exists():
            shutil.copy2(source, geojson_dir / filename)
            copied.append(filename)

    gpkg_path = staging / "aerocad_cadastral.gpkg"
    gpkg_layers = _write_gpkg(output_dir, gpkg_path)

    shp_root = staging / "shapefile"
    shp_layers = _write_shapefiles(output_dir, shp_root)

    def read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    result = read_json(result_path)
    validation = read_json(validation_path)
    processing = read_json(processing_path)
    history = read_json(edit_log)

    manifest = {
        "product": "AeroCAD",
        "package": "Preliminary urban cadastral GIS export",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_dir.name,
        "source_crs": result.get("source_crs") or validation.get("raster_summary", {}).get("crs"),
        "processing": {
            "status": result.get("status", processing.get("status")),
            "mode": result.get("mode"),
            "model_id": result.get("model_id"),
            "tiles_processed": result.get("tiles_processed"),
            "parcel_count": result.get("parcel_count"),
            "building_candidates": result.get("building_candidates"),
            "road_candidates": result.get("road_candidates"),
            "topology_health": result.get("topology_health"),
            "topology_issue_count": result.get("topology_issue_count"),
            "field_queue_count": result.get("field_queue_count"),
        },
        "files": {
            "geojson": copied,
            "geopackage_layers": gpkg_layers,
            "shapefile_layers": shp_layers,
        },
        "audit": {
            "edit_count": len(history.get("history", [])) if isinstance(history, dict) else 0,
            "validation_present": bool(validation),
            "processing_result_present": bool(result),
        },
        "status_note": "AeroCAD outputs are preliminary cadastral candidates and quality-control evidence. Human survey verification remains required before authoritative cadastral use.",
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Include the evidence/QC/audit JSON records for traceability.
    for source, target in [
        (validation_path, "validation.json"),
        (result_path, "processing_result.json"),
        (output_dir / "topology.json", "topology.json"),
        (output_dir / "field_queue.json", "field_queue.json"),
        (output_dir / "boundary_evidence.json", "boundary_evidence.json"),
        (edit_log, "edit_history.json"),
    ]:
        if source.exists():
            shutil.copy2(source, staging / target)

    zip_path = processing_dir / f"AeroCAD_{project_dir.name}_GIS_Package.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(staging.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(staging))
    shutil.rmtree(staging, ignore_errors=True)
    return zip_path
