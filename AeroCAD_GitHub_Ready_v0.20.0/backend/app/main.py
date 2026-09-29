from __future__ import annotations

import json
import shutil
import uuid
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .geospatial import inspect_raster, inspect_vector_or_table
from .processing import run_processing
from .workflow import build_field_queue, get_topology_issues, resolve_topology_issue, verify_parcel
from .parcel import metric_crs_for_geometry, transform_geom, validate_topology
from shapely.geometry import shape, box
from .editing import revalidate_parcel, split_parcel, merge_parcels, get_edit_history
from .exporter import build_export_package

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = BASE_DIR / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
APP_VERSION = "0.20.0"
VALID_INPUT_KEYS = {"ori", "dsm", "dtm", "parcels", "gt", "gnss"}

app = FastAPI(
    title="AeroCAD GeoAI Backend",
    version=APP_VERSION,
    description="Geospatial ingestion, GeoAI processing, cadastral editing and GIS export service for AeroCAD.",
)



class TopologyResolution(BaseModel):
    note: str = ""


class ProjectMetadata(BaseModel):
    name: str
    zone: str = ""


class ParcelVerification(BaseModel):
    method: str = "Human field verification"
    outcome: str = "verified"
    notes: str = ""
    gnss_lat: float | None = None
    gnss_lon: float | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "aerocad-geoai", "version": APP_VERSION}


def _safe_name(name: str | None) -> str:
    raw = Path(name or "upload.bin").name
    return raw.replace(" ", "_") or "upload.bin"


def _read_json(path: Path, default: dict | None = None) -> dict:
    try:
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else (default or {})
    except Exception:
        pass
    return default or {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)




def _status_path(project_dir: Path) -> Path | None:
    candidates = [project_dir / "processing.json", project_dir / "processing" / "processing.json"]
    return next((p for p in candidates if p.exists()), None)


def _project_record(project_dir: Path) -> dict:
    validation = _read_json(project_dir / "validation.json")
    manifest = _read_json(project_dir / "project.json")
    status = _read_json(_status_path(project_dir) or Path("__missing__"))
    result = _read_json(project_dir / "processing" / "result.json")

    created_at = manifest.get("created_at") or validation.get("validated_at") or datetime.now(timezone.utc).isoformat()
    updated_at = manifest.get("updated_at") or result.get("completed_at") or validation.get("validated_at") or created_at
    project_name = manifest.get("name") or validation.get("project_name") or f"AeroCAD Project {project_dir.name}"
    zone = manifest.get("zone") or validation.get("project_zone") or ""

    if status.get("status") == "running" or status.get("status") == "queued":
        project_status = "Processing"
    elif status.get("status") == "complete":
        project_status = "Processed"
    elif status.get("status") == "error":
        project_status = "Error"
    elif validation.get("ready"):
        project_status = "Validated"
    else:
        project_status = validation.get("status") or manifest.get("status") or "Draft"

    record = {
        "id": project_dir.name,
        "name": project_name,
        "zone": zone,
        "status": project_status,
        "created_at": created_at,
        "updated_at": updated_at,
        "inputs": validation.get("records", []),
        "input_count": len(validation.get("records", [])),
        "parcel_count": validation.get("parcel_count"),
        "source": manifest.get("source") or validation.get("source"),
        "project_id": project_dir.name,
    }
    if result:
        record["result"] = {
            "parcel_count": result.get("parcel_count"),
            "building_candidates": result.get("building_candidates"),
            "road_candidates": result.get("road_candidates"),
            "review_parcels": result.get("review_parcels"),
            "topology_health": result.get("topology_health"),
            "completed_at": result.get("completed_at"),
        }
    return record


def _persist_project_manifest(project_dir: Path, *, name: str | None = None, zone: str | None = None, status: str | None = None) -> dict:
    existing = _read_json(project_dir / "project.json")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        **existing,
        "project_id": project_dir.name,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    if name is not None:
        payload["name"] = name.strip() or payload.get("name") or f"AeroCAD Project {project_dir.name}"
    if zone is not None:
        payload["zone"] = zone.strip()
    if status is not None:
        payload["status"] = status
    _write_json(project_dir / "project.json", payload)
    return payload


def _list_project_records() -> list[dict]:
    records = []
    for project_dir in sorted(UPLOAD_ROOT.iterdir() if UPLOAD_ROOT.exists() else [], key=lambda p: p.name):
        if not project_dir.is_dir():
            continue
        if not ((project_dir / "validation.json").exists() or (project_dir / "project.json").exists()):
            continue
        record = _project_record(project_dir)
        # Backfill a manifest for projects created before server-side persistence existed.
        if not (project_dir / "project.json").exists():
            _persist_project_manifest(project_dir, name=record["name"], zone=record["zone"], status=record["status"])
        records.append(record)

    # Do not show duplicate placeholder records created by repeated validation of the
    # same inputs when a named project already represents that input set. The underlying
    # folders are retained for safety; this only cleans the registry view.
    def fingerprint(record: dict) -> tuple:
        parts = []
        for item in record.get("inputs") or []:
            metadata = item.get("metadata") or {}
            parts.append((item.get("key"), item.get("filename"), metadata.get("size_bytes")))
        return tuple(sorted(parts))

    grouped: dict[tuple, list[dict]] = {}
    for record in records:
        grouped.setdefault(fingerprint(record), []).append(record)

    visible: list[dict] = []
    for group in grouped.values():
        named = [r for r in group if not str(r.get("name", "")).startswith("AeroCAD Project " )]
        if named:
            best_named = sorted(named, key=lambda r: r.get("updated_at") or "", reverse=True)[0]
            visible.append(best_named)
            # Preserve distinct named projects even when their inputs overlap.
            for r in group:
                if r["id"] == best_named["id"]:
                    continue
                if not str(r.get("name", "")).startswith("AeroCAD Project "):
                    visible.append(r)
        else:
            visible.append(sorted(group, key=lambda r: r.get("updated_at") or "", reverse=True)[0])

    return sorted(visible, key=lambda item: item.get("updated_at") or "", reverse=True)


@app.post("/api/projects/validate")
async def validate_project(
    input_key: Annotated[list[str], Form()] = [],
    file: Annotated[list[UploadFile], File()] = [],
    project_name: Annotated[str | None, Form()] = None,
    project_zone: Annotated[str | None, Form()] = None,
) -> dict:
    if not file:
        raise HTTPException(status_code=400, detail="No survey files were uploaded.")
    if len(input_key) != len(file):
        raise HTTPException(status_code=400, detail="Input labels do not match uploaded files.")
    unknown_keys = sorted(set(input_key) - VALID_INPUT_KEYS)
    if unknown_keys:
        raise HTTPException(status_code=400, detail=f"Unsupported survey input key(s): {', '.join(unknown_keys)}")
    if len(set(input_key)) != len(input_key):
        raise HTTPException(status_code=400, detail="Each survey input type may be uploaded only once.")

    project_id = uuid.uuid4().hex[:12]
    project_dir = UPLOAD_ROOT / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    crs_values: dict[str, str] = {}
    raster_summary: dict | None = None

    for key, upload in zip(input_key, file):
        filename = _safe_name(upload.filename)
        destination = project_dir / f"{key}__{filename}"
        with destination.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)

        suffix = destination.suffix.lower()
        try:
            if suffix in {".tif", ".tiff"}:
                metadata = inspect_raster(destination)
                if key == "ori":
                    raster_summary = metadata
                if metadata.get("crs"):
                    crs_values[key] = metadata["crs"]
                records.append({"key": key, "filename": filename, "kind": "raster", "metadata": metadata})
            else:
                metadata = inspect_vector_or_table(destination)
                if metadata.get("crs"):
                    crs_values[key] = metadata["crs"]
                records.append({"key": key, "filename": filename, "kind": metadata.get("kind", "file"), "metadata": metadata})
        except Exception as exc:  # noqa: BLE001
            records.append({"key": key, "filename": filename, "kind": "unknown", "error": str(exc)})

    checks: list[list[object]] = []
    required_present = {r["key"] for r in records}
    has_ori = "ori" in required_present
    has_dsm = "dsm" in required_present
    crs_ready = bool(crs_values.get("ori") and crs_values.get("dsm") and _crs_aligned(crs_values))
    checks.append(["Coordinate reference system", _crs_detail(crs_values), crs_ready])
    checks.append(["Raster coverage", f"{len(records)} uploaded input(s) inspected", has_ori and has_dsm])
    checks.append(["Resolution", _resolution_detail(raster_summary), bool(raster_summary and raster_summary.get("resolution"))])
    checks.append(["GeoTIFF integrity", _integrity_detail(records), not any("error" in r for r in records)])
    checks.append(["Elevation alignment", _crs_alignment_detail(crs_values), _crs_aligned(crs_values)])

    ready = has_ori and has_dsm and crs_ready and not any("error" in r for r in records)
    warnings: list[str] = []
    if not has_ori:
        warnings.append("ORI is required.")
    if not has_dsm:
        warnings.append("DSM is required.")
    if has_ori and not crs_values.get("ori"):
        warnings.append("ORI is missing CRS metadata; export/processing alignment cannot be trusted yet.")
    if has_dsm and not crs_values.get("dsm"):
        warnings.append("DSM is missing CRS metadata; elevation fusion cannot be trusted yet.")
    if len(set(crs_values.values())) > 1:
        warnings.append("Uploaded geospatial layers use different CRSs; reprojection will be required before fusion.")

    result = {
        "project_id": project_id,
        "project_name": project_name or f"AeroCAD Project {project_id}",
        "project_zone": project_zone or "",
        "status": "Validated" if ready else "Needs Review",
        "ready": ready,
        "summary": "Geospatial metadata inspection completed." if ready else "The backend found inputs that need review.",
        "checks": checks,
        "records": records,
        "raster_summary": raster_summary,
        "warnings": warnings,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    (project_dir / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    _persist_project_manifest(project_dir, name=result["project_name"], zone=result["project_zone"], status=result["status"])
    return result



@app.get("/api/projects")
def list_projects() -> dict:
    return {"projects": _list_project_records()}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    return _project_record(project_dir)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    record = _project_record(project_dir)
    shutil.rmtree(project_dir)
    return {"deleted": True, "project": record}


@app.put("/api/projects/{project_id}/metadata")
def update_project_metadata(project_id: str, payload: ProjectMetadata) -> dict:
    project_dir = _project_dir(project_id)
    _persist_project_manifest(project_dir, name=payload.name, zone=payload.zone)
    return _project_record(project_dir)


def _crs_detail(values: dict[str, str]) -> str:
    return " · ".join(f"{k.upper()} {v}" for k, v in values.items()) if values else "No CRS metadata detected yet"


def _resolution_detail(summary: dict | None) -> str:
    if not summary or not summary.get("resolution"):
        return "Resolution not available"
    return str(summary["resolution"])


def _integrity_detail(records: list[dict]) -> str:
    errors = [r for r in records if r.get("error")]
    return "All uploaded files opened successfully" if not errors else f"{len(errors)} input(s) could not be inspected"


def _crs_alignment_detail(values: dict[str, str]) -> str:
    if not values:
        return "CRS comparison unavailable"
    return "All inspected geospatial layers share the same CRS" if _crs_aligned(values) else "CRS mismatch detected across geospatial layers"


def _crs_aligned(values: dict[str, str]) -> bool:
    unique = {v for v in values.values() if v}
    return len(unique) <= 1



def _project_dir(project_id: str) -> Path:
    path = UPLOAD_ROOT / project_id
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return path


def _process_job(project_dir: Path) -> None:
    status_path = project_dir / "processing.json"

    def update(percent: int, stage: str, detail: str) -> None:
        status_path.write_text(json.dumps({
            "status": "running" if percent < 100 else "complete",
            "progress": percent,
            "stage": stage,
            "detail": detail,
        }, indent=2), encoding="utf-8")

    try:
        _persist_project_manifest(project_dir, status="Processing")
        update(1, "starting", "Starting GeoAI extraction")
        summary = run_processing(project_dir, update)
        status_path.write_text(json.dumps({
            **summary,
            "progress": 100,
            "stage": "complete",
            "detail": "Feature extraction complete",
        }, indent=2), encoding="utf-8")
        _persist_project_manifest(project_dir, status="Processed")
    except Exception as exc:  # noqa: BLE001
        status_path.write_text(json.dumps({
            "status": "error",
            "progress": 0,
            "stage": "error",
            "detail": str(exc),
        }, indent=2), encoding="utf-8")
        _persist_project_manifest(project_dir, status="Error")


@app.post("/api/projects/{project_id}/process")
async def start_processing(project_id: str, background_tasks: BackgroundTasks) -> dict:
    project_dir = _project_dir(project_id)
    status_path = project_dir / "processing.json"
    if status_path.exists():
        current = json.loads(status_path.read_text(encoding="utf-8"))
        if current.get("status") in {"running", "queued", "complete"}:
            return current
    status_path.write_text(json.dumps({
        "status": "queued", "progress": 0, "stage": "queued", "detail": "Extraction job queued"
    }, indent=2), encoding="utf-8")
    _persist_project_manifest(project_dir, status="Processing")
    background_tasks.add_task(_process_job, project_dir)
    return json.loads(status_path.read_text(encoding="utf-8"))


def _archive_processing(project_dir: Path) -> str | None:
    processing_dir = project_dir / "processing"
    root_status = project_dir / "processing.json"
    if not processing_dir.exists() and not root_status.exists():
        return None
    archive_root = project_dir / "processing_runs"
    archive_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    destination = archive_root / stamp
    counter = 2
    while destination.exists():
        destination = archive_root / f"{stamp}_{counter}"
        counter += 1
    destination.mkdir(parents=True, exist_ok=True)
    if processing_dir.exists():
        shutil.move(str(processing_dir), str(destination / "processing"))
    if root_status.exists():
        shutil.move(str(root_status), str(destination / "processing.json"))
    (project_dir / "processing").mkdir(parents=True, exist_ok=True)
    return destination.name


@app.post("/api/projects/{project_id}/reprocess")
async def reprocess_project(project_id: str, background_tasks: BackgroundTasks) -> dict:
    project_dir = _project_dir(project_id)
    validation = json.loads((project_dir / "validation.json").read_text(encoding="utf-8")) if (project_dir / "validation.json").exists() else {}
    if not validation.get("ready"):
        raise HTTPException(status_code=409, detail="Project preflight is not ready for reprocessing.")
    current_path = project_dir / "processing" / "processing.json"
    if current_path.exists():
        current = json.loads(current_path.read_text(encoding="utf-8"))
        if current.get("status") == "running":
            return current
    archived = _archive_processing(project_dir)
    status_path = project_dir / "processing" / "processing.json"
    status_path.write_text(json.dumps({
        "status": "queued", "progress": 0, "stage": "queued",
        "detail": "Fresh extraction run queued", "archived_run": archived
    }, indent=2), encoding="utf-8")
    _persist_project_manifest(project_dir, status="Processing")
    background_tasks.add_task(_process_job, project_dir)
    return json.loads(status_path.read_text(encoding="utf-8"))


def _rebuild_qc_from_current_outputs(project_dir: Path) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    parcel_path = output_dir / "parcels.geojson"
    if not parcel_path.exists():
        raise ValueError("Parcel output is not available. Run extraction first.")
    data = json.loads(parcel_path.read_text(encoding="utf-8"))
    source_crs = ((json.loads((project_dir / "validation.json").read_text(encoding="utf-8")) if (project_dir / "validation.json").exists() else {}).get("raster_summary") or {}).get("crs")
    geoms_src = [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]
    if not geoms_src:
        raise ValueError("No valid parcel geometries are available for QC.")
    envelope_src = box(*geoms_src[0].bounds)
    for geom in geoms_src[1:]:
        envelope_src = envelope_src.union(box(*geom.bounds))
    metric_crs = metric_crs_for_geometry(envelope_src, source_crs) or source_crs
    geoms_metric = [transform_geom(g, source_crs, metric_crs) if metric_crs and source_crs else g for g in geoms_src]
    envelope_metric = box(*geoms_metric[0].bounds)
    for geom in geoms_metric[1:]:
        envelope_metric = envelope_metric.union(box(*geom.bounds))
    topology = validate_topology(geoms_metric, envelope_metric, metric_crs)
    (output_dir / "topology.json").write_text(json.dumps(topology, indent=2), encoding="utf-8")
    queue = build_field_queue(project_dir)
    _persist_project_manifest(project_dir)
    return {"topology": topology, "field_queue": queue, "rebuilt_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/projects/{project_id}/rebuild-qc")
def rebuild_project_qc(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    try:
        return _rebuild_qc_from_current_outputs(project_dir)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/process")
def process_status(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    status_path = project_dir / "processing.json"
    if not status_path.exists():
        return {"status": "idle", "progress": 0, "stage": "idle", "detail": "No extraction has been started."}
    return json.loads(status_path.read_text(encoding="utf-8"))


@app.get("/api/projects/{project_id}/preview/ori")
def ori_preview(project_id: str):
    project_dir = _project_dir(project_id)
    candidates = sorted(project_dir.glob("ori__*.tif")) + sorted(project_dir.glob("ori__*.tiff"))
    if not candidates:
        raise HTTPException(status_code=404, detail="ORI raster not found.")
    import numpy as np
    import rasterio
    from PIL import Image
    with rasterio.open(candidates[0]) as src:
        bands=min(src.count,3)
        scale = min(1.0, 1024.0 / max(src.height, src.width))
        preview_height = max(1, int(round(src.height * scale)))
        preview_width = max(1, int(round(src.width * scale)))
        arr=src.read(list(range(1,bands+1)), out_shape=(bands, preview_height, preview_width))
        arr=np.moveaxis(arr,0,-1)
        if bands==1: arr=np.repeat(arr,3,axis=2)
        elif bands==2: arr=np.concatenate([arr,arr[...,-1:]],axis=2)
        arr=arr.astype(np.float32)
        lo,hi=np.percentile(arr,[1,99])
        arr=np.clip((arr-lo)/max(float(hi-lo),1.0),0,1)
        image=Image.fromarray((arr*255).astype(np.uint8), mode="RGB")
        bio=BytesIO(); image.save(bio,format="PNG",optimize=True); bio.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(bio, media_type="image/png")

@app.get("/api/projects/{project_id}/outputs/{filename}")
def project_output(project_id: str, filename: str):
    project_dir = _project_dir(project_id)
    safe_name = Path(filename).name
    allowed_outputs = {
        "buildings.geojson", "roads.geojson", "building_mask_preview.png",
        "road_mask_preview.png", "specialist_models.json", "parcels.geojson",
        "parcel_boundaries.geojson", "boundary_evidence.geojson", "boundary_evidence.json",
        "topology.json", "field_queue.json", "parcels_original.geojson"
    }
    if safe_name not in allowed_outputs:
        raise HTTPException(status_code=404, detail="Output file not available for direct access.")
    target = project_dir / "processing" / "outputs" / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Output file not found.")
    from fastapi.responses import FileResponse
    return FileResponse(target)


@app.get("/api/projects/{project_id}/artifacts")
def project_artifacts(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    result_path = project_dir / "processing" / "result.json"
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="No processing result is available yet.")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    output_dir = project_dir / "processing" / "outputs"
    topology_path = output_dir / "topology.json"
    topo = json.loads(topology_path.read_text(encoding="utf-8")) if topology_path.exists() else None
    field_queue = build_field_queue(project_dir) if output_dir.exists() else {"queue": [], "summary": {"count": 0}}
    workflow = get_topology_issues(project_dir) if topology_path.exists() else {"issues": [], "summary": {"total": 0, "open": 0, "resolved": 0, "critical": 0}}
    return {"result": result, "topology": topo, "topology_workflow": workflow, "field_queue": field_queue, "available_outputs": [p.name for p in output_dir.iterdir() if p.is_file()] if output_dir.exists() else []}


@app.get("/api/projects/{project_id}/topology/issues")
def topology_issues(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    return get_topology_issues(project_dir)


@app.post("/api/projects/{project_id}/topology/issues/{issue_id}/resolve")
def topology_issue_resolve(project_id: str, issue_id: str, payload: TopologyResolution) -> dict:
    project_dir = _project_dir(project_id)
    try:
        result = resolve_topology_issue(project_dir, issue_id, payload.note)
        _persist_project_manifest(project_dir)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/field-queue")
def field_queue(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    return build_field_queue(project_dir)


@app.post("/api/projects/{project_id}/field-queue/{parcel_id}/verify")
def verify_field_parcel(project_id: str, parcel_id: str, payload: ParcelVerification) -> dict:
    project_dir = _project_dir(project_id)
    try:
        props = verify_parcel(project_dir, parcel_id, payload.model_dump())
        _persist_project_manifest(project_dir)
        return {"status": props.get("verification_status", "Pending"), "parcel_id": parcel_id, "properties": props, "queue": build_field_queue(project_dir)}
    except ValueError as exc:
        status_code = 422 if ("notes" in str(exc).lower() or "gnss" in str(exc).lower() or "outcome" in str(exc).lower()) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


class ParcelBoundaryEdit(BaseModel):
    geometry: dict
    note: str = ""


class ParcelRevalidation(BaseModel):
    note: str = ""


class ParcelSplit(BaseModel):
    start: list[float]
    end: list[float]
    note: str = ""


class ParcelMerge(BaseModel):
    secondary_parcel_id: str
    note: str = ""


@app.get("/api/projects/{project_id}/parcels/{parcel_id}")
def parcel_detail(project_id: str, parcel_id: str) -> dict:
    project_dir = _project_dir(project_id)
    output = project_dir / "processing" / "outputs" / "parcels.geojson"
    if not output.exists():
        raise HTTPException(status_code=404, detail="Parcel output is not available yet.")
    data = json.loads(output.read_text(encoding="utf-8"))
    for feature in data.get("features", []):
        if (feature.get("properties") or {}).get("parcel_id") == parcel_id:
            return {"parcel": feature}
    raise HTTPException(status_code=404, detail="Parcel not found.")


@app.post("/api/projects/{project_id}/parcels/{parcel_id}/edit-boundary")
def edit_parcel_boundary(project_id: str, parcel_id: str, payload: ParcelBoundaryEdit) -> dict:
    project_dir = _project_dir(project_id)
    try:
        result = revalidate_parcel(project_dir, parcel_id, payload.geometry, payload.note)
        _persist_project_manifest(project_dir)
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/parcels/{parcel_id}/revalidate")
def revalidate_existing_parcel(project_id: str, parcel_id: str, payload: ParcelRevalidation | None = None) -> dict:
    project_dir = _project_dir(project_id)
    try:
        note = payload.note if payload else ""
        result = revalidate_parcel(project_dir, parcel_id, None, note)
        _persist_project_manifest(project_dir)
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/projects/{project_id}/parcels/{parcel_id}/split")
def split_existing_parcel(project_id: str, parcel_id: str, payload: ParcelSplit) -> dict:
    project_dir = _project_dir(project_id)
    try:
        result = split_parcel(project_dir, parcel_id, payload.start, payload.end, payload.note)
        _persist_project_manifest(project_dir)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/parcels/{parcel_id}/merge")
def merge_existing_parcel(project_id: str, parcel_id: str, payload: ParcelMerge) -> dict:
    project_dir = _project_dir(project_id)
    try:
        result = merge_parcels(project_dir, parcel_id, payload.secondary_parcel_id, payload.note)
        _persist_project_manifest(project_dir)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/edit-history")
def project_edit_history(project_id: str) -> dict:
    project_dir = _project_dir(project_id)
    return {"history": get_edit_history(project_dir)}


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str):
    project_dir = _project_dir(project_id)
    try:
        package = build_export_package(project_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Export package creation failed: {exc}") from exc
    from fastapi.responses import FileResponse
    return FileResponse(
        package,
        media_type="application/zip",
        filename=package.name,
    )

