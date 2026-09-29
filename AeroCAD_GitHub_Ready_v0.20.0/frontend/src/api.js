export async function validateDataset(filesByKey, projectName = "", projectZone = "") {
  const form = new FormData();
  Object.entries(filesByKey).forEach(([key, file]) => {
    if (!file) return;
    form.append('input_key', key);
    form.append('file', file, file.name);
  });
  if (projectName) form.append('project_name', projectName);
  if (projectZone) form.append('project_zone', projectZone);

  const response = await fetch('/api/projects/validate', {
    method: 'POST',
    body: form,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || 'Dataset validation failed.');
  }
  return payload;
}

export async function startProcessing(projectId) {
  const response = await fetch(`/api/projects/${projectId}/process`, { method: 'POST' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not start GeoAI extraction.');
  return payload;
}


export async function reprocessProject(projectId) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/reprocess`, { method: 'POST' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not restart GeoAI extraction.');
  return payload;
}

export async function rebuildProjectQC(projectId) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/rebuild-qc`, { method: 'POST' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not rebuild topology QC.');
  return payload;
}

export async function getProcessingStatus(projectId) {
  const response = await fetch(`/api/projects/${projectId}/process`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not read processing status.');
  return payload;
}


export async function getArtifacts(projectId) {
  const response = await fetch(`/api/projects/${projectId}/artifacts`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load project artifacts.');
  return payload;
}

export async function getOutputGeoJSON(projectId, filename) {
  const response = await fetch(`/api/projects/${projectId}/outputs/${filename}`);
  if (!response.ok) throw new Error('Could not load map output.');
  return response.json();
}

export async function getBoundaryEvidence(projectId) {
  return getOutputGeoJSON(projectId, 'boundary_evidence.geojson');
}

export async function getTopologyIssues(projectId) {
  const response = await fetch(`/api/projects/${projectId}/topology/issues`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load topology issues.');
  return payload;
}

export async function resolveTopologyIssue(projectId, issueId, note = '') {
  const response = await fetch(`/api/projects/${projectId}/topology/issues/${issueId}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not resolve topology issue.');
  return payload;
}

export async function getFieldQueue(projectId) {
  const response = await fetch(`/api/projects/${projectId}/field-queue`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load field verification queue.');
  return payload;
}

export async function verifyParcel(projectId, parcelId, data = {}) {
  const response = await fetch(`/api/projects/${projectId}/field-queue/${encodeURIComponent(parcelId)}/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not verify parcel.');
  return payload;
}

export async function getParcel(projectId, parcelId) {
  const response = await fetch(`/api/projects/${projectId}/parcels/${encodeURIComponent(parcelId)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load parcel.');
  return payload;
}

export async function editParcelBoundary(projectId, parcelId, geometry, note = '') {
  const response = await fetch(`/api/projects/${projectId}/parcels/${encodeURIComponent(parcelId)}/edit-boundary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ geometry, note }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not save boundary edit.');
  return payload;
}

export async function revalidateParcel(projectId, parcelId, note = '') {
  const response = await fetch(`/api/projects/${projectId}/parcels/${encodeURIComponent(parcelId)}/revalidate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not revalidate parcel.');
  return payload;
}

export async function splitParcel(projectId, parcelId, start, end, note = '') {
  const response = await fetch(`/api/projects/${projectId}/parcels/${encodeURIComponent(parcelId)}/split`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start, end, note }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not split parcel.');
  return payload;
}

export async function mergeParcels(projectId, primaryId, secondaryId, note = '') {
  const response = await fetch(`/api/projects/${projectId}/parcels/${encodeURIComponent(primaryId)}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ secondary_parcel_id: secondaryId, note }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not merge parcels.');
  return payload;
}

export async function getEditHistory(projectId) {
  const response = await fetch(`/api/projects/${projectId}/edit-history`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load edit history.');
  return payload;
}


export function exportProject(projectId) {
  return `/api/projects/${encodeURIComponent(projectId)}/export`;
}


export async function listProjects() {
  const response = await fetch('/api/projects');
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load projects.');
  return payload;
}

export async function getProject(projectId) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not load project.');
  return payload;
}

export async function updateProjectMetadata(projectId, data) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/metadata`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not update project metadata.');
  return payload;
}

export async function deleteProject(projectId) {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Could not delete project.');
  return payload;
}
