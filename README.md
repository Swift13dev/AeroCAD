# AeroCAD — AI-Assisted Urban Cadastral Mapping & Verification

<div align="center">

### Turning Drone & Geospatial Data into Preliminary, Reviewable Urban Parcel Maps

**Smart India Hackathon (SIH) 2026 · Problem Statement 26012 · AICTE**

</div>

---

## Smart India Hackathon 2026

### Problem Statement Details

| Detail | Information |
|---|---|
| **Problem Statement ID** | **26012** |
| **Problem Statement Title** | **AI-Based Automated Urban Parcel Mapping and Cadastral Feature Extraction System using Drone Imagery** |
| **Organization** | **AICTE — All India Council for Technical Education** |
| **Focus Areas** | Drone Imagery · Geospatial AI · Computer Vision · GIS · Urban Cadastral Mapping |

### The Problem

Accurate and up-to-date urban land records are important for land governance, urban planning, taxation, infrastructure development, and citizen services.

However, preparing cadastral maps can involve a large amount of manual work. Survey teams may have to inspect drone imagery, identify buildings and roads, delineate parcel boundaries, compare new information with existing GIS records, and perform ground verification.

This becomes especially challenging in dense urban environments because:

- parcel boundaries may not always be directly visible in aerial imagery,
- buildings can be close to or cross recorded boundaries,
- roads and access corridors may be narrow,
- parcels can have irregular shapes,
- settlements can contain overlapping or inconsistent structures,
- and manual digitization and validation can take significant time.

The SIH problem statement therefore calls for an AI-enabled platform that can use **high-resolution drone imagery, orthorectified imagery (ORI), DSM/DTM datasets, existing GIS parcel layers, ground-truth datasets, and GNSS/CORS-enabled survey data** to automate cadastral feature extraction and support the preparation of preliminary urban parcel maps.

---

# Our Solution — AeroCAD

**AeroCAD** is an **AI-assisted urban cadastral mapping and verification platform** designed to take aerial and geospatial data and turn it into **preliminary, reviewable cadastral information**.

Video demonstration link - [AeroCAD](https://drive.google.com/file/d/1YbyHn0VsJcihsGW3uCZWLbe1_ksPdr1A/view?usp=sharing)

AeroCAD does not treat cadastral mapping as a simple:

> **Drone image → AI prediction**

problem.

Instead, it follows a complete workflow:

> **Geospatial data → Feature extraction → Boundary evidence → Candidate parcels → GIS validation → Human verification → GIS-ready output**

### The core idea

## **AI proposes. GIS validates. Humans verify.**

The goal is not to remove surveyors from the process.

The goal is to reduce repetitive digitization work and help direct human attention toward the areas that actually require verification.

---

# Why AeroCAD Uses Multiple Sources of Evidence

One of the most important challenges in cadastral mapping is that a **legal property boundary is not necessarily visible in an aerial image**.

A building can be visible.

A road can be visible.

A wall or fence can sometimes be visible.

But the actual legal parcel boundary may not appear as a physical line in the image.

AeroCAD therefore combines multiple forms of spatial evidence when generating candidate parcel boundaries.

### Boundary evidence can include:

- Drone / orthorectified imagery
- Building footprints
- Roads and access corridors
- Existing cadastral GIS
- DSM / DTM elevation information
- Ground-truth observations
- GNSS / survey observations
- Spatial and topology constraints

This produces a **candidate boundary supported by evidence**, rather than pretending that an AI model can determine legal property boundaries directly from pixels.

---

# AeroCAD End-to-End Workflow

```text
       Drone / ORI / DSM / DTM / GIS / GT / GNSS
                           │
                           ▼
                   Dataset Validation
                           │
                           ▼
                    Geo-Processing
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
        Buildings        Roads        Land-use
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                  Boundary Evidence
                           │
                           ▼
                Candidate Parcel Inference
                           │
                           ▼
              Polygon + Topology Validation
                           │
                           ▼
                 Confidence / QC Analysis
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
           GIS Editing        Field Verification
                 │                   │
                 └─────────┬─────────┘
                           ▼
                  Reviewed / Verified
                       Parcels
                           │
                           ▼
               GIS-Ready Export Package
```

---

# What AeroCAD Actually Does

## 1. Intelligent Data Ingestion

AeroCAD accepts the main types of data described in the SIH problem statement.

| Input | Purpose | Typical Format |
|---|---|---|
| **ORI / Orthomosaic** | High-resolution aerial imagery | GeoTIFF |
| **DSM** | Surface and elevation information | GeoTIFF |
| **DTM** | Terrain information | GeoTIFF |
| **Existing Parcel GIS** | Existing cadastral reference | GeoJSON / SHP / GPKG |
| **Ground Truth** | Reference observations | GeoJSON / CSV |
| **GNSS / CORS Data** | Survey measurements | CSV / GPX |

Before processing, AeroCAD performs dataset preflight checks and reports information such as:

- Coordinate Reference System (CRS)
- Raster dimensions
- Resolution / GSD when available
- Dataset integrity
- Available input layers

This provides an early check that the uploaded geospatial data is suitable for processing.

---

# 2. Aerial Feature Extraction

AeroCAD processes aerial imagery in manageable tiles and extracts useful geographic features.

## Building Extraction

The system can generate building candidates and associated spatial information such as:

- Building ID
- Area
- Perimeter
- Location
- Extraction/evidence information

## Road & Access Extraction

The system can identify roads, pathways, lanes and access corridors that help provide context for parcel interpretation.

## Land-Use Information

Land-use information can also be incorporated so that parcels are interpreted using a wider spatial context rather than isolated shapes.

### AI Transparency

AeroCAD is designed not to falsely claim that a specialist AI model ran successfully.

Specialist models are loaded when available.

If a specialist checkpoint cannot load or inference fails, the system records that condition and can use a deterministic baseline extraction route instead.

This keeps the workflow functional while preserving processing provenance.

---

# 3. Boundary Evidence Fusion

This is one of the central concepts behind AeroCAD.

Instead of asking only:

> **“Where is the parcel boundary?”**

AeroCAD asks:

> **“What spatial evidence supports this candidate boundary?”**

Possible evidence includes:

```text
Imagery edges
      +
Building boundaries
      +
Road / access constraints
      +
Existing cadastral GIS
      +
DSM / DTM information
      +
Ground-truth observations
      +
GNSS observations
      +
Topological consistency
```

The system uses these signals to create an **engineering/QC confidence indicator** for candidate boundaries.

These confidence values are not presented as legal certainty or as trained probability estimates.

---

# 4. Candidate Parcel Generation

After extracting features and combining the available evidence, AeroCAD generates **candidate parcel polygons**.

Each parcel can contain information such as:

- Parcel ID
- Area
- Perimeter
- Land-use
- Building count
- Boundary confidence
- Existing-GIS comparison
- Topology status
- Verification status
- Supporting evidence

When an existing cadastral layer is available, it can be used as a spatial reference during inference and comparison.

When it is not available, the prototype can generate candidates using its fallback spatial inference methods.

---

# 5. Automated Topology & Quality Control

Creating parcel polygons is only one part of cadastral mapping.

Generated GIS geometries can contain errors such as:

- Overlaps
- Gaps
- Sliver polygons
- Self-intersections
- Invalid geometries
- Duplicate or inconsistent features

AeroCAD therefore includes a topology and quality-control stage.

Instead of simply saying:

> **“There are 20 errors.”**

the system is designed to connect the issue to the affected parcel and provide a review or correction workflow.

This gives the user an understanding of **what is wrong, where it is wrong, and what needs attention**.

---

# 6. Human-in-the-Loop GIS Editing

AeroCAD does not assume that AI should make the final cadastral decision.

Users can inspect and edit the generated candidate geometry.

The prototype supports operations including:

- Move boundary vertices
- Add vertices
- Remove vertices
- Split parcels
- Merge parcels
- Revalidate parcels
- Resolve topology issues
- Record verification decisions

The workflow becomes:

```text
AI Candidate
     ↓
GIS Validation
     ↓
Human Review / Edit
     ↓
Revalidation
     ↓
Reviewed Result
```

This is important because some cadastral boundaries require evidence that cannot be reliably determined from aerial imagery alone.

---

# 7. Field Verification & GNSS Support

AeroCAD can direct uncertain or conflicting parcels into a **Field Verification Queue**.

A parcel may require review because of:

- Low boundary confidence
- Existing-GIS mismatch
- Topology conflicts
- Potential structure intrusion
- Survey discrepancy

The workflow can record:

- Verification status
- Survey notes
- GNSS coordinates
- Field evidence
- Review decisions

GNSS/reference observations can also be compared with candidate geometry to identify spatial discrepancies.

---

# 8. Potential Encroachment Detection

AeroCAD can identify situations where a structure appears to extend outside an existing recorded parcel boundary.

These situations are labelled as:

> **Potential Encroachment**

The distinction is important.

AeroCAD does **not** claim that it has legally established an encroachment.

It identifies a **spatial discrepancy that should be investigated through field verification**.

---

# 9. Existing GIS vs AI Comparison

When existing cadastral data is available, AeroCAD can compare it against the newly generated candidate map.

The comparison workflow can highlight:

- Boundary shifts
- Potential parcel splits
- Potential parcel merges
- New structures
- Area discrepancies
- Potential encroachment situations

This makes AeroCAD more than a simple image-analysis application.

It becomes a **cadastral review and change-analysis workflow**.

---

# 10. Confidence & Survey Priority

Not every parcel needs the same level of human attention.

AeroCAD can prioritize review using signals such as:

- Boundary confidence
- Topology errors
- Existing GIS disagreement
- GNSS discrepancy
- Potential encroachment
- Image quality

This creates a practical workflow:

> **Automate routine areas → prioritize uncertain areas → send those areas for human verification.**

The aim is to reduce repetitive digitization and help survey teams focus on the areas where human verification is actually needed.

---

# 11. GIS-Ready Outputs

AeroCAD is designed to produce usable GIS data rather than stopping at a browser visualization.

The prototype supports export workflows for:

- **GeoJSON**
- **GeoPackage**
- **Shapefile**
- CSV attributes
- Processing and validation evidence
- Edit history and related records

The export package also includes supporting metadata so that the result can be inspected outside the web application.

---

#  12. Auditability & Provenance

A cadastral workflow should be able to answer:

> **“Where did this geometry come from?”**

AeroCAD records relevant processing and review information such as:

- Source data
- CRS
- Processing time
- Model identifiers where applicable
- Processing mode
- Confidence/evidence information
- Edit history
- Verification decisions

This creates a more traceable workflow than simply exporting a static map image.

---

#  System Architecture

```text
                    AEROCAD
                       │
              ┌────────┴────────┐
              │   DATA INPUT    │
              └────────┬────────┘
                       │
                       ▼
             GEO-PREPROCESSING
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     Buildings       Roads      Land-use
          │            │            │
          └────────────┼────────────┘
                       ▼
              Boundary Evidence
                       │
                       ▼
              Parcel Inference
                       │
                       ▼
             Polygon Generation
                       │
                       ▼
              Topology / QC
                       │
                       ▼
          Confidence & Priority
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
      GIS Editor             Field Verification
          │                         │
          └────────────┬────────────┘
                       ▼
                Reviewed Parcels
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
          GIS Data   Reports   Audit Data
```

---

# Technology Stack

## Frontend

- React 19
- Vite 8
- JavaScript / JSX
- Lucide React
- Custom CSS design system

## Backend

- Python
- FastAPI
- Uvicorn

## Geospatial Processing

- Rasterio
- GDAL-backed raster handling
- GeoPandas
- Fiona
- Shapely
- PyProj
- NumPy

## Optional AI / ML Components

- PyTorch
- Transformers
- ONNX Runtime
- Ultralytics

The current prototype stores project artifacts on disk. A larger production deployment could introduce dedicated spatial infrastructure such as PostgreSQL/PostGIS and map-serving components.

---

# Repository Structure

```text
AeroCAD/
├── README.md
├── .gitignore
│
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
│
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

---

# Running AeroCAD Locally

## Backend

From the `backend` directory:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Backend health check:

```text
http://127.0.0.1:8000/api/health
```

A Windows startup script is also included:

```text
start-backend.bat
```

## Frontend

From the `frontend` directory:

```bash
npm install
npm run dev
```

Frontend:

```text
http://127.0.0.1:5174
```

The Vite development server proxies `/api` requests to the backend on port `8000`.

**Node.js 20.19+** is required by the current frontend toolchain.

For offline smoke testing, specialist model inference can be disabled with:

```text
AEROCAD_DISABLE_SPECIALIST_MODELS=1
```

---

# Typical AeroCAD Demonstration

AeroCAD can be demonstrated as one continuous story:

```text
1. Create a survey project
          ↓
2. Upload ORI + DSM
          ↓
3. Validate the datasets
          ↓
4. Run cadastral processing
          ↓
5. Extract buildings and roads
          ↓
6. Generate boundary evidence
          ↓
7. Generate candidate parcels
          ↓
8. Run topology / QC checks
          ↓
9. Inspect a flagged parcel
          ↓
10. Edit / resolve / revalidate
          ↓
11. Perform field verification
          ↓
12. Export GIS-ready cadastral data
```

The important part of the demonstration is not one isolated AI prediction.

It is the **complete journey from geospatial input to reviewable cadastral information**.

---

# SIH Requirement → AeroCAD Implementation

| SIH Requirement | AeroCAD Response |
|---|---|
| **High-resolution drone imagery** | ORI / orthomosaic ingestion and tile-based processing |
| **Parcel boundary extraction** | Evidence-driven candidate parcel inference |
| **Building footprints** | Building feature extraction |
| **Roads / pathways / access corridors** | Road and access extraction |
| **Land-use classification** | Land-use workflow support |
| **DSM / DTM datasets** | Elevation-aware geospatial processing |
| **Existing GIS parcel layers** | GIS reference and comparison |
| **Ground Truthing** | Field verification workflow |
| **GNSS / CORS-enabled survey data** | GNSS/reference evidence support |
| **AI image segmentation / feature extraction** | Specialist AI architecture with deterministic fallback |
| **Automated topology generation** | Polygon validation and topology/QC checks |
| **Overlapping / inconsistent geometry detection** | Parcel-level topology issue detection |
| **Web-GIS visualization and editing** | Interactive parcel inspection and editing |
| **GIS-ready cadastral output** | GeoJSON, GeoPackage and Shapefile export |
| **Reduction of manual effort** | Automated extraction + targeted human review |

---

# Prototype Verification

The current repository has been checked through an end-to-end synthetic survey workflow covering:

```text
Dataset Validation
      ↓
ORI Preview
      ↓
Feature Extraction
      ↓
Parcel Inference
      ↓
Evidence Fusion
      ↓
Topology Validation
      ↓
Field Verification
      ↓
Boundary Editing / Revalidation
      ↓
Reprocessing
      ↓
GeoJSON / GeoPackage / Shapefile Export
```

The repository has also been cleaned of generated runtime data, caches and machine-specific artifacts so that the source remains lightweight and suitable for version control.

---

# Prototype Limitations

AeroCAD is a **working prototype for AI-assisted cadastral mapping and review**, not a production legal land-record system.

In particular:

- AI-generated parcel boundaries are **candidate boundaries**.
- Confidence values are **engineering/QC indicators**, not legal certainty.
- Ambiguous areas still require human or field verification.
- Specialist AI checkpoints may require additional compute, model downloads and storage.
- The deterministic fallback extractor is a baseline and not a replacement for a domain-trained cadastral model.
- The prototype can record GNSS/field evidence but does not connect to a live CORS correction service.
- The packaged local version stores project artifacts on disk.
- The local sign-in screen is a prototype session, not a production identity and access-control system.

---

# Project Status

## **AeroCAD v0.20.0 — Prototype**

The current version focuses on an end-to-end urban cadastral workflow combining:

**Geospatial Data Ingestion → AI-Assisted Feature Extraction → Parcel Inference → Topology/QC → Human Review → Field Verification → GIS Export**

Future development can extend the platform with:

- stronger domain-trained cadastral models,
- larger-area benchmarking,
- richer 3D terrain analysis,
- live survey/CORS integrations,
- production spatial infrastructure,
- improved parcel-boundary learning,
- and operational deployment.

---

# The Core Idea Behind AeroCAD

AeroCAD is built around one principle:

> **We are not trying to replace the surveyor. We are trying to replace repetitive digitization and direct the surveyor to the places where verification is actually needed.**

That brings together:

**AI + Computer Vision + Geospatial Processing + GIS + Topology + Human Verification**

into one end-to-end workflow.

---

## Disclaimer

AeroCAD is an engineering prototype developed in the context of **Smart India Hackathon 2026, Problem Statement 26012**.

It is intended to demonstrate an AI-assisted cadastral mapping and verification workflow.

It should **not** be treated as an authoritative legal land-record, ownership, property-rights, or cadastral adjudication system.

---

<div align="center">

### AeroCAD

**AI-Assisted Urban Cadastral Mapping & Verification**

*Drone Imagery → Spatial Intelligence → Human Verification → GIS-Ready Output*

</div>
