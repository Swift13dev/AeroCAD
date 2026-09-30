# AeroCAD

### AI-assisted urban cadastral mapping from drone and geospatial data

AeroCAD is a Web-GIS prototype that converts aerial and spatial data into **preliminary parcel candidates** for survey and GIS teams to review, edit, verify, and export.

> **AI proposes. GIS validates. Humans verify.**

**Smart India Hackathon 2026 · Problem Statement 26012**

[Demo video](https://drive.google.com/file/d/1YbyHn0VsJcihsGW3uCZWLbe1_ksPdr1A/view?usp=sharing)

---

## What it does

```text
Drone / ORI / DSM-DTM / GIS / Survey data
                    ↓
          Validate & preprocess
                    ↓
       Extract buildings, roads,
          and spatial evidence
                    ↓
         Generate parcel candidates
                    ↓
        Topology & geometry checks
                    ↓
       Human review / field check
                    ↓
          GIS-ready export
```

Parcel boundaries are not always visible in a single image. AeroCAD combines imagery, extracted features, terrain, and available GIS/survey evidence instead of treating one AI prediction as the final answer.

## Key capabilities

- **Geospatial preflight** — CRS, extent, geometry, and input-coverage checks
- **Feature extraction** — buildings, roads/access, and land-use evidence
- **Evidence fusion** — combines multiple spatial sources for parcel candidate generation
- **Topology & QC** — flags overlaps, gaps, slivers, duplicates, and invalid geometries
- **Human review** — inspect, edit, accept, reject, or send parcels for field verification
- **GIS export** — GeoJSON, GeoPackage, and Shapefile
- **Method-aware processing** — specialist models when available, with deterministic fallback processing

## Prototype snapshot

The prototype has been demonstrated on prepared Telangana survey workspaces, including **Yavapur** and **Kistapur**.

One Yavapur processing run produced:

| Output | Candidates |
|---|---:|
| Parcels | **491** |
| Buildings | **161** |
| Roads | **49** |

> These are prototype output counts, not accuracy or ground-truth metrics.

## Tech stack

**Frontend**  
React 19 · Vite 8 · JavaScript / JSX · Custom CSS

**Backend**  
Python · FastAPI · Uvicorn

**Geospatial**  
Rasterio · GeoPandas · Shapely · PyProj · GDAL/Fiona

**AI / ML (optional)**  
PyTorch · Transformers · ONNX Runtime · Ultralytics

## Run locally

### 1. Backend

```bash
cd backend

python -m venv .venv
.venv\Scripts\activate

python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

### 2. Frontend

In a second terminal:

```bash
cd frontend

npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5174
```

The frontend proxies `/api` requests to the backend at port `8000`.

**Node.js 20.19+** is required by the current frontend toolchain.

For offline smoke testing, disable specialist model inference:

```text
AEROCAD_DISABLE_SPECIALIST_MODELS=1
```

## Repository structure

```text
AeroCAD/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── geospatial.py
│   │   ├── processing.py
│   │   ├── specialized_models.py
│   │   ├── model_adapter.py
│   │   ├── parcel.py
│   │   ├── evidence.py
│   │   ├── workflow.py
│   │   ├── editing.py
│   │   └── exporter.py
│   └── requirements.txt
│
└── frontend/
    ├── package.json
    └── src/
        ├── main.jsx
        ├── api.js
        └── styles.css
```

## Prototype status

**AeroCAD v0.20.0 — Working prototype**

The current build demonstrates the end-to-end flow: geospatial ingestion, parcel generation, quality checks, review, field verification, and GIS export.

AeroCAD is **not** a legal land-record or cadastral adjudication system. Its parcel outputs are preliminary candidates and require surveyor review and field verification before official use.

## Why it matters

Instead of requiring survey teams to trace every feature manually, AeroCAD is designed to:

**automate the first pass → flag uncertain cases → focus human review where needed → export usable GIS data**

---

Built for **Smart India Hackathon 2026 · SIH26012**
