from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import shape


def _read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _parcel_features(output_dir: Path) -> list[dict]:
    payload = _read_json(output_dir / "parcels.geojson", {"features": []})
    return [f for f in payload.get("features", []) if f.get("geometry")]


def _issue_priority(issue_type: str, area: float | None = None) -> str:
    if issue_type == "Overlap":
        return "Critical"
    if issue_type == "Invalid ring":
        return "High"
    if issue_type == "Gap":
        return "High"
    return "Medium"


def _suggestion(issue_type: str) -> str:
    return {
        "Overlap": "Inspect shared boundary and trim/snap after human review",
        "Gap": "Review adjacent boundaries and extend to the persistent edge",
        "Sliver": "Review fragment, then merge if survey evidence supports it",
        "Invalid ring": "Repair self-intersection and re-run geometry validation",
    }.get(issue_type, "Inspect geometry before approval")


def _topology_issues(project_dir: Path) -> list[dict]:
    output_dir = project_dir / "processing" / "outputs"
    topo = _read_json(output_dir / "topology.json", {})
    parcels = _parcel_features(output_dir)
    ids = [f.get("properties", {}).get("parcel_id", f"P-{i+1:04d}") for i, f in enumerate(parcels)]
    geometries = [shape(f["geometry"]) for f in parcels]
    issues: list[dict] = []
    counter = 1

    for item in topo.get("overlaps", []):
        a = int(item.get("parcel_a", -1)); b = int(item.get("parcel_b", -1))
        parcel_ids = [ids[a] if 0 <= a < len(ids) else None, ids[b] if 0 <= b < len(ids) else None]
        parcel_ids = [p for p in parcel_ids if p]
        issues.append({
            "issue_id": f"OV-{counter:03d}",
            "type": "Overlap",
            "parcel_ids": parcel_ids,
            "area": float(item.get("area", 0.0)),
            "observation": f"{float(item.get('area', 0.0)):.2f} m² intersecting area",
            "suggestion": _suggestion("Overlap"),
            "priority": _issue_priority("Overlap", float(item.get("area", 0.0))),
            "status": "Open",
        })
        counter += 1

    for idx, item in enumerate(topo.get("gaps", []), start=1):
        gap_geom = shape(item["geometry"]) if item.get("geometry") else None
        parcel_indices = [int(i) for i in item.get("parcel_indices", []) if 0 <= int(i) < len(ids)]
        parcel_ids = [ids[i] for i in parcel_indices]
        if not parcel_ids and gap_geom and geometries:
            nearby: list[tuple[float, str]] = []
            for parcel_id, geom in zip(ids, geometries):
                nearby.append((geom.boundary.distance(gap_geom.boundary), parcel_id))
            nearby.sort(key=lambda x: x[0])
            parcel_ids = [p for _, p in nearby[:2]]
        area = float(item.get("area", gap_geom.area if gap_geom else 0.0))
        issues.append({
            "issue_id": f"GP-{idx:03d}",
            "type": "Gap",
            "parcel_ids": parcel_ids,
            "area": area,
            "observation": f"{area:.2f} m² enclosed internal gap",
            "suggestion": _suggestion("Gap"),
            "priority": _issue_priority("Gap", area),
            "status": "Open",
        })

    for idx, item in enumerate(topo.get("slivers", []), start=1):
        parcel_index = int(item.get("parcel", -1))
        parcel_id = ids[parcel_index] if 0 <= parcel_index < len(ids) else None
        area = float(item.get("area", 0.0))
        issues.append({
            "issue_id": f"SL-{idx:03d}",
            "type": "Sliver",
            "parcel_ids": [parcel_id] if parcel_id else [],
            "area": area,
            "observation": f"{area:.2f} m² fragment below threshold",
            "suggestion": _suggestion("Sliver"),
            "priority": _issue_priority("Sliver", area),
            "status": "Open",
        })

    for idx, item in enumerate(topo.get("invalid_geometries", []), start=1):
        parcel_index = int(item.get("parcel", -1))
        parcel_id = ids[parcel_index] if 0 <= parcel_index < len(ids) else None
        issues.append({
            "issue_id": f"IN-{idx:03d}",
            "type": "Invalid ring",
            "parcel_ids": [parcel_id] if parcel_id else [],
            "area": None,
            "observation": item.get("reason", "Invalid polygon geometry"),
            "suggestion": _suggestion("Invalid ring"),
            "priority": _issue_priority("Invalid ring"),
            "status": "Open",
        })

    actions = _read_json(project_dir / "processing" / "qc_actions.json", [])
    action_map = {a.get("issue_id"): a for a in actions if a.get("issue_id")}
    for issue in issues:
        action = action_map.get(issue["issue_id"])
        if action:
            issue["status"] = action.get("status", "Open")
            issue["resolved_at"] = action.get("resolved_at")
            issue["resolution_note"] = action.get("note", "")
    return issues


def build_field_queue(project_dir: Path) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    parcels = _parcel_features(output_dir)
    topology_issues = _topology_issues(project_dir)
    issue_map: dict[str, list[dict]] = {}
    for issue in topology_issues:
        if issue.get("status") == "Resolved":
            continue
        for parcel_id in issue.get("parcel_ids", []):
            issue_map.setdefault(parcel_id, []).append(issue)

    priority_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    queue: list[dict] = []
    for feature in parcels:
        props = feature.get("properties") or {}
        parcel_id = props.get("parcel_id", "Unknown")
        verification_status = props.get("verification_status", "Pending")
        if verification_status == "Verified":
            continue
        confidence = int(props.get("boundary_confidence", 0) or 0)
        parcel_issues = issue_map.get(parcel_id, [])
        encroachment = bool(props.get("potential_encroachment"))
        if encroachment:
            priority = "Critical"
            reason = "Potential encroachment indicator"
        elif confidence < 60:
            priority = "High"
            reason = "Low boundary confidence"
        elif parcel_issues:
            priority = min((i.get("priority", "Medium") for i in parcel_issues), key=lambda p: priority_rank.get(p, 9))
            reason = parcel_issues[0].get("type", "Topology review")
        elif confidence < 75:
            priority = "Medium"
            reason = "Boundary confidence below review target"
        else:
            continue
        queue.append({
            "parcel_id": parcel_id,
            "area": round(float(props.get("area", 0.0)), 2),
            "land_use": props.get("land_use", "Unknown"),
            "boundary_confidence": confidence,
            "priority": priority,
            "reason": reason,
            "potential_encroachment": encroachment,
            "topology_issue_count": len(parcel_issues),
            "topology_issue_ids": [i["issue_id"] for i in parcel_issues],
            "verification_status": verification_status,
            "notes": props.get("verification_notes", ""),
        })

    queue.sort(key=lambda item: (priority_rank.get(item["priority"], 9), item["boundary_confidence"], item["parcel_id"]))
    path = project_dir / "processing" / "field_queue.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queue": queue,
        "summary": {
            "count": len(queue),
            "critical": sum(q["priority"] == "Critical" for q in queue),
            "high": sum(q["priority"] == "High" for q in queue),
            "medium": sum(q["priority"] == "Medium" for q in queue),
            "low": sum(q["priority"] == "Low" for q in queue),
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def get_topology_issues(project_dir: Path) -> dict:
    issues = _topology_issues(project_dir)
    summary = {
        "open": sum(i["status"] != "Resolved" for i in issues),
        "resolved": sum(i["status"] == "Resolved" for i in issues),
        "total": len(issues),
        "critical": sum(i["status"] != "Resolved" and i["priority"] == "Critical" for i in issues),
    }
    return {"issues": issues, "summary": summary}


def resolve_topology_issue(project_dir: Path, issue_id: str, note: str = "") -> dict:
    issues = _topology_issues(project_dir)
    target = next((i for i in issues if i["issue_id"] == issue_id), None)
    if not target:
        raise ValueError("Topology issue not found.")
    path = project_dir / "processing" / "qc_actions.json"
    actions = _read_json(path, [])
    actions.append({
        "issue_id": issue_id,
        "status": "Resolved",
        "note": note,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "action": "human-reviewed",
    })
    path.write_text(json.dumps(actions, indent=2), encoding="utf-8")
    build_field_queue(project_dir)
    return next(i for i in _topology_issues(project_dir) if i["issue_id"] == issue_id)


def verify_parcel(project_dir: Path, parcel_id: str, payload: dict[str, Any]) -> dict:
    output_dir = project_dir / "processing" / "outputs"
    parcel_path = output_dir / "parcels.geojson"
    data = _read_json(parcel_path, {"type": "FeatureCollection", "features": []})
    target = None
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        if props.get("parcel_id") == parcel_id:
            target = feature
            break
    if target is None:
        raise ValueError("Parcel not found.")

    outcome = str(payload.get("outcome", "verified")).strip().lower()
    outcome_map = {
        "verified": ("Verified", "verified"),
        "revisit": ("Needs revisit", "needs_revisit"),
        "not_verified": ("Not verified", "not_verified"),
    }
    if outcome not in outcome_map:
        raise ValueError("Unsupported verification outcome.")

    notes = str(payload.get("notes", "")).strip()
    if len(notes) < 5:
        raise ValueError("Verification notes are required (at least 5 characters) so the field decision is auditable.")

    lat = payload.get("gnss_lat")
    lon = payload.get("gnss_lon")
    if (lat is None) != (lon is None):
        raise ValueError("Provide both GNSS latitude and longitude, or leave both blank.")
    if lat is not None and not (-90 <= float(lat) <= 90):
        raise ValueError("GNSS latitude must be between -90 and 90 degrees.")
    if lon is not None and not (-180 <= float(lon) <= 180):
        raise ValueError("GNSS longitude must be between -180 and 180 degrees.")

    status, outcome_key = outcome_map[outcome]
    now = datetime.now(timezone.utc).isoformat()
    props = target.setdefault("properties", {})
    props["verification_status"] = status
    props["verification_outcome"] = outcome_key
    props["verified_at"] = now
    props["verification_method"] = payload.get("method", "Human field verification")
    props["verification_notes"] = notes
    if lat is not None:
        props["gnss_lat"] = float(lat)
        props["gnss_lon"] = float(lon)
    else:
        props.pop("gnss_lat", None)
        props.pop("gnss_lon", None)

    parcel_path.write_text(json.dumps(data), encoding="utf-8")
    log_path = project_dir / "processing" / "verification_log.json"
    log = _read_json(log_path, [])
    log.append({
        "parcel_id": parcel_id,
        "status": status,
        "outcome": outcome_key,
        "verified_at": now,
        "method": props["verification_method"],
        "notes": notes,
        "gnss_lat": props.get("gnss_lat"),
        "gnss_lon": props.get("gnss_lon"),
    })
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    build_field_queue(project_dir)
    return props
