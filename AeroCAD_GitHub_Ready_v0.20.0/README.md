# AeroCAD — AI Urban Cadastral Intelligence Platform

AeroCAD is an AI-assisted urban cadastral mapping and verification prototype.

**Repository version: 0.20.0** It turns high-resolution drone/orthomosaic inputs plus optional elevation, existing GIS, ground-truth and GNSS evidence into **preliminary** parcel candidates, GIS quality checks and a human-in-the-loop review workflow.

> **Important:** AeroCAD produces preliminary cadastral candidates and review evidence. It is not a legal land-record adjudication system. Human survey verification is required before authoritative cadastral use.

## Core workflow

```text
ORI + DSM/DTM + existing GIS + GT/GNSS
                ↓
        Dataset validation
                ↓
      Tile-based GeoAI extraction
       ├── Buildings
       └── Roads / access
                ↓
       Candidate parcel inference
                ↓
       Multi-source boundary evidence
                ↓
       Topology + confidence QC
                ↓
        Human review / editing
       ├── Revalidate
       ├── Split / merge
       ├── Field verification
       └── QC resolution
                ↓
        GIS-ready export package
```

## What is implemented

- Project register with server-persisted survey workspaces.
- GeoTIFF preflight with CRS, raster size, resolution/GSD and integrity checks.
- ORI + DSM processing with optional DTM support.
- Tile-based aerial feature extraction using dedicated building and roadway specialists when available, with explicit deterministic fallbacks when a specialist cannot load.
- Candidate parcel generation from existing GIS where supplied, otherwise building-driven Voronoi/grid candidates.
- Evidence-weighted boundary confidence and potential encroachment indicators.
- Automated topology validation for overlaps, enclosed internal gaps, slivers and invalid geometry.
- Field verification queue prioritized by confidence, topology and encroachment indicators.
- WebGIS-style parcel inspector with coordinate-based boundary editing.
- Parcel split and merge operations with downstream QC refresh.
- Ground-truth / GNSS comparison during parcel revalidation.
- Reprocessing with archived processing runs.
- GeoJSON, GeoPackage, Shapefile and evidence/report package export.
- Audit-friendly validation, processing, edit and field-verification records.

## Repository structure

```text
AeroCAD/
├── README.md
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   ├── start-backend.bat
│   └── app/
│       ├── main.py
│       ├── geospatial.py
│       ├── processing.py
│       ├── specialized_models.py
│       ├── model_adapter.py
│       ├── parcel.py
│       ├── evidence.py
│       ├── workflow.py
│       ├── editing.py
│       ├── exporter.py
│       └── metrics.py
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── vite.config.js
    ├── index.html
    ├── start-frontend.bat
    └── src/
        ├── main.jsx
        ├── api.js
        └── styles.css
```

## Local setup on Windows

### 1. Start the backend

From `backend/`:

```bat
start-backend.bat
```

Or manually:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Backend health check:

```text
http://127.0.0.1:8000/api/health
```

### 2. Start the frontend

From `frontend/`:

```bat
start-frontend.bat
```

Or manually:

```bat
npm install
npm run dev
```

Frontend:

```text
http://127.0.0.1:5174
```

The Vite development server proxies `/api` requests to the backend on port `8000`.

## Frontend stack

- React 19
- Vite 8
- JavaScript / JSX
- Lucide React
- Custom CSS design system

Node.js `20.19+` is required by the pinned frontend toolchain.

## Backend stack

- Python
- FastAPI / Uvicorn
- Rasterio / GDAL-backed raster handling
- GeoPandas / Fiona
- Shapely
- PyProj
- NumPy
- Optional PyTorch / Transformers / ONNX Runtime / Ultralytics specialists

## Input data

The project creation screen accepts:

| Input | Required | Typical format |
|---|---|---|
| Orthomosaic / ORI | Yes | GeoTIFF |
| DSM | Yes | GeoTIFF |
| DTM | No | GeoTIFF |
| Existing GIS parcels | No | GeoJSON / SHP / GPKG |
| Ground truth | No | GeoJSON / CSV |
| GNSS / CORS survey | No | CSV / GPX |

For reliable fusion, ORI and DSM must contain usable CRS metadata. Optional layers are interpreted according to their embedded CRS where available; GeoJSON without an explicit CRS is treated as EPSG:4326.

## Specialist AI behaviour

AeroCAD keeps specialist models lazy-loaded so the application can still start without downloading large checkpoints.

By default, the building and roadway specialists are attempted during processing. If a model cannot load or inference fails, AeroCAD records that fact and falls back to deterministic baseline extraction instead of pretending a specialist ran successfully.

For an offline smoke test, set:

```text
AEROCAD_DISABLE_SPECIALIST_MODELS=1
```

The actual model identifiers are recorded in the generated `specialist_models.json` output.

## Main API surface

```text
GET  /api/health
POST /api/projects/validate
GET  /api/projects
GET  /api/projects/{project_id}
PUT  /api/projects/{project_id}/metadata
DELETE /api/projects/{project_id}
POST /api/projects/{project_id}/process
POST /api/projects/{project_id}/reprocess
POST /api/projects/{project_id}/rebuild-qc
GET  /api/projects/{project_id}/process
GET  /api/projects/{project_id}/preview/ori
GET  /api/projects/{project_id}/artifacts
GET  /api/projects/{project_id}/topology/issues
POST /api/projects/{project_id}/topology/issues/{issue_id}/resolve
GET  /api/projects/{project_id}/field-queue
POST /api/projects/{project_id}/field-queue/{parcel_id}/verify
GET  /api/projects/{project_id}/parcels/{parcel_id}
POST /api/projects/{project_id}/parcels/{parcel_id}/edit-boundary
POST /api/projects/{project_id}/parcels/{parcel_id}/revalidate
POST /api/projects/{project_id}/parcels/{parcel_id}/split
POST /api/projects/{project_id}/parcels/{parcel_id}/merge
GET  /api/projects/{project_id}/edit-history
GET  /api/projects/{project_id}/outputs/{filename}
GET  /api/projects/{project_id}/export
```

## Demo sequence

1. Create a survey project and enter a recognizable survey zone.
2. Upload an ORI and DSM; add DTM, existing parcels and reference evidence when available.
3. Run dataset validation and inspect the reported CRS/GSD/integrity checks.
4. Start extraction and watch the live pipeline progress.
5. Open the cadastral map and inspect candidate parcels.
6. Review boundary confidence, evidence sources and field priority.
7. Resolve topology issues or edit a boundary; edits trigger revalidation and field-review reset where appropriate.
8. Verify a parcel with survey notes and optional GNSS coordinates.
9. Export the GIS package for downstream GIS inspection.

## GIS output package

The export endpoint creates a ZIP containing:

- GeoJSON layers
- GeoPackage layers
- Shapefile sets
- `manifest.json`
- validation and processing records
- topology and field-queue evidence
- edit history

Nested evidence attributes are serialized when needed for driver compatibility, and Shapefile field names are made unique within the ten-character field-name limit.

## Data and model provenance

AeroCAD records model IDs, processing mode, source CRS, processing timestamps, review decisions and edit history in project artifacts. Confidence values are explicitly described as deterministic evidence-weighted indicators, not trained probabilities and not legal cadastral determinations.

## Prototype limitations

- There is no production identity provider; the browser sign-in screen is a local prototype session.
- Specialist checkpoints may require internet access and substantial compute/storage.
- The fallback extractor is a deterministic baseline, not a substitute for a domain-trained cadastral model.
- Parcel generation is candidate inference; visible parcel boundaries are not guaranteed to represent legal boundaries.
- Field and GNSS workflows in this prototype record survey evidence but do not connect to a live CORS correction service.
- PostgreSQL/PostGIS/GeoServer are not required for this packaged local prototype; the current build persists project artifacts on disk.

## Verification performed on this repository

The backend source compiles successfully, and an end-to-end synthetic survey smoke test was run through:

```text
validation → ORI preview → extraction → parcel inference → evidence fusion
→ topology → field verification → boundary edit/revalidation
→ reprocess → GeoPackage/Shapefile/GeoJSON export
```

The test also checks output path restrictions and export compatibility for nested evidence attributes.
