# AeroCAD Backend

FastAPI service for AeroCAD geospatial ingestion, GeoAI extraction, parcel inference, topology QC, field verification, editing and export.

Run from this directory:

```bat
start-backend.bat
```

Or:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Health endpoint:

```text
GET /api/health
```

The backend persists each project under `backend/uploads/<project_id>/`. Runtime uploads, model checkpoints and generated outputs are intentionally excluded from Git.
