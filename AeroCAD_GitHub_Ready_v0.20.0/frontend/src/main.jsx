import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft, ArrowRight, ArrowUpRight, Bell, Building2, Check, ChevronDown,
  CircleDashed, ClipboardCheck, Download, FileOutput, FolderOpen, Grid2X2,
  Layers3, Map, MapPinned, MoreHorizontal, Plus, Ruler, ScanLine, Search,
  Settings, ShieldCheck, Sparkles, Target, TriangleAlert, UploadCloud, X,
  ZoomIn, ZoomOut, CheckCheck, RefreshCw, Pencil, Save, Trash2, ChevronRight
} from 'lucide-react';
import './styles.css';
import { validateDataset, startProcessing, reprocessProject, getProcessingStatus, getArtifacts, getOutputGeoJSON, getBoundaryEvidence, getTopologyIssues, resolveTopologyIssue, getFieldQueue, verifyParcel, editParcelBoundary, revalidateParcel, splitParcel, mergeParcels, getEditHistory, exportProject, listProjects, getProject, updateProjectMetadata, deleteProject } from './api';

const initialProject = {
  name: '',
  zone: '',
  files: {},
  status: 'Draft',
  backendId: null,
};

const ProjectContext = createContext(null);

function useProjectContext() {
  const value = useContext(ProjectContext);
  if (!value) throw new Error('Project context is unavailable.');
  return value;
}


const issues = [
  { type: 'Overlap', count: 17, color: 'red', icon: TriangleAlert },
  { type: 'Gap', count: 11, color: 'amber', icon: ScanLine },
  { type: 'Review', count: 23, color: 'blue', icon: ClipboardCheck },
];

const dataTypes = [
  { key: 'ori', label: 'Orthomosaic / ORI', hint: 'GeoTIFF · high-resolution aerial imagery', required: true },
  { key: 'dsm', label: 'DSM', hint: 'GeoTIFF · surface elevation model', required: true },
  { key: 'dtm', label: 'DTM', hint: 'GeoTIFF · terrain elevation model', required: false },
  { key: 'parcels', label: 'Existing GIS parcels', hint: 'GeoJSON · SHP · GPKG', required: false },
  { key: 'gt', label: 'Ground truth dataset', hint: 'GeoJSON · CSV · annotated vectors', required: false },
  { key: 'gnss', label: 'GNSS / CORS survey', hint: 'CSV · GPX · point observations', required: false },
];

const extractionStages = [
  ['preflight', 'Pre-processing & tiling', 'Raster integrity, CRS, project extent'],
  ['buildings', 'Building footprint extraction', 'Segmenting candidate structure footprints'],
  ['roads', 'Road & access detection', 'Extracting road edges and access corridors'],
  ['landuse', 'Urban land-use classification', 'Assigning preliminary land-use evidence'],
  ['boundaries', 'Boundary evidence fusion', 'Combining imagery, terrain and GIS cues'],
  ['parcels', 'Parcel polygon generation', 'Creating candidate cadastral geometries'],
  ['topology', 'Topology & confidence checks', 'Validating geometry and uncertainty'],
];

const mapParcels = [
  { id: 'P-101', x: 7, y: 14, w: 18, h: 22, area: '198.3 m²', confidence: 92, landuse: 'Residential', status: 'Ready' },
  { id: 'P-102', x: 26, y: 14, w: 22, h: 22, area: '214.8 m²', confidence: 88, landuse: 'Residential', status: 'Ready' },
  { id: 'P-103', x: 49, y: 15, w: 20, h: 21, area: '176.2 m²', confidence: 74, landuse: 'Mixed use', status: 'Review' },
  { id: 'P-104', x: 70, y: 14, w: 22, h: 24, area: '184.6 m²', confidence: 53, landuse: 'Residential', status: 'Review' },
  { id: 'P-105', x: 8, y: 38, w: 24, h: 25, area: '232.0 m²', confidence: 95, landuse: 'Residential', status: 'Ready' },
  { id: 'P-106', x: 33, y: 38, w: 25, h: 25, area: '286.1 m²', confidence: 91, landuse: 'Institutional', status: 'Ready' },
  { id: 'P-107', x: 59, y: 39, w: 16, h: 23, area: '152.9 m²', confidence: 82, landuse: 'Residential', status: 'Ready' },
  { id: 'P-108', x: 76, y: 40, w: 15, h: 23, area: '145.7 m²', confidence: 61, landuse: 'Commercial', status: 'Review' },
  { id: 'P-109', x: 7, y: 66, w: 20, h: 17, area: '167.4 m²', confidence: 90, landuse: 'Residential', status: 'Ready' },
  { id: 'P-110', x: 28, y: 66, w: 28, h: 17, area: '318.2 m²', confidence: 97, landuse: 'Open space', status: 'Ready' },
  { id: 'P-111', x: 57, y: 67, w: 20, h: 16, area: '172.0 m²', confidence: 69, landuse: 'Mixed use', status: 'Review' },
  { id: 'P-112', x: 78, y: 67, w: 13, h: 16, area: '121.6 m²', confidence: 86, landuse: 'Residential', status: 'Ready' },
];

function readSavedProject() {
  try {
    const raw = localStorage.getItem('aerocad_project');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return { ...initialProject, ...parsed, files: parsed.files || {} };
  } catch {
    return null;
  }
}

function Logo() {
  return <div className="brand-mark" aria-label="AeroCAD">
    <div className="brand-icon"><span className="brand-square square-a" /><span className="brand-square square-b" /><span className="brand-square square-c" /></div>
    <div><div className="brand-name">AeroCAD</div><div className="brand-subtitle">Urban Cadastral Intelligence</div></div>
  </div>;
}

function Sidebar({ screen, navigate }) {
  const [profileOpen, setProfileOpen] = useState(false);
  const nav = [
    { label: 'Overview', icon: Grid2X2, target: 'dashboard' },
    { label: 'Projects', icon: FolderOpen, target: 'projects' },
    { label: 'Cadastral Map', icon: Map, target: 'map' },
    { label: 'AI Processing', icon: Sparkles, target: 'processing' },
    { label: 'Topology QC', icon: ShieldCheck, target: 'topology' },
    { label: 'Field Verification', icon: MapPinned, target: 'field' },
    { label: 'Reports', icon: FileOutput, target: 'reports' },
  ];
  return <aside className="sidebar">
    <Logo />
    <div className="side-section-label">WORKSPACE</div>
    <nav className="nav-list">
      {nav.map(({ label, icon: Icon, target }) => <button key={label} onClick={() => navigate(target)} className={`nav-item ${screen === target ? 'active' : ''}`}>
        <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
      </button>)}
    </nav>
    <div className="side-divider" />
    <button className={`nav-item ${screen === 'settings' ? 'active' : ''}`} onClick={() => navigate('settings')}>
      <Settings size={18} strokeWidth={1.8} /><span>Settings</span>
    </button>
    <div className="side-spacer" />
    <div className="profile-wrap">
      <button className={`profile-card ${profileOpen ? 'open' : ''}`} onClick={() => setProfileOpen(value => !value)} aria-expanded={profileOpen}>
        <div className="avatar">HM</div>
        <div className="profile-copy"><div className="profile-name">Survey Workspace</div><div className="profile-role">Admin</div></div>
        <ChevronDown size={15} className={profileOpen ? 'profile-chevron-open' : ''} />
      </button>
      {profileOpen && <div className="profile-menu">
        <div className="profile-menu-head"><div className="avatar small">HM</div><div><strong>Survey Workspace</strong><span>Administrator workspace</span></div></div>
        <div className="profile-menu-line"><span>Workspace access</span><strong>Admin</strong></div>
        <button type="button" className="profile-menu-action" onClick={() => { setProfileOpen(false); navigate('settings'); }}><Settings size={14} /> Workspace settings</button>
        <button type="button" className="profile-menu-action muted" onClick={() => setProfileOpen(false)}>Close</button>
      </div>}
    </div>
  </aside>;
}

function Topbar({ navigate, title = 'Good afternoon, Haritha.' }) {
  const { project, remoteProjects, selectProject, startNewProject } = useProjectContext();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const projectName = project?.name || 'No project selected';
  const currentId = project?.backendId || '';
  const dateLabel = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date()).toUpperCase();
  const activeRemote = remoteProjects.find(item => item.id === currentId);
  return <header className="topbar">
    <div><div className="eyebrow">{dateLabel}</div><h1>{title}</h1></div>
    <div className="topbar-actions">
      <div className="notification-wrap">
        <button className={`icon-button ${notificationsOpen ? 'open' : ''}`} onClick={() => setNotificationsOpen(value => !value)} aria-label="Notifications" aria-expanded={notificationsOpen}><Bell size={19} /></button>
        {notificationsOpen && <div className="notification-popover">
          <div className="notification-head"><div><strong>Notifications</strong><span>Current survey workspace</span></div><span className="notification-count">{activeRemote?.status || (projectName !== 'No project selected' ? 'Active' : '—')}</span></div>
          {project?.backendId ? <div className="notification-item"><div className="notification-dot live" /><div><strong>{projectName}</strong><span>{activeRemote?.status || project.status || 'Active'} project context is loaded.</span></div></div> : <div className="notification-item"><div className="notification-dot" /><div><strong>No active project</strong><span>Choose a survey workspace to view its live notifications.</span></div></div>}
          <button className="notification-link" onClick={() => { setNotificationsOpen(false); navigate('projects'); }}>Open project register <ArrowRight size={13} /></button>
        </div>}
      </div>
      <label className="project-context">
        <span className="project-context-label">ACTIVE PROJECT</span>
        <select className="project-switcher" value={currentId} onChange={(event) => event.target.value && selectProject(event.target.value)} aria-label="Select active project">
          {!currentId && <option value="">Select project</option>}
          {remoteProjects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <button className="primary-button" onClick={() => { startNewProject(); navigate('new-project'); }}><Plus size={17} /> New project</button>
    </div>
  </header>;
}

function SummaryCard({ label, value, note, icon: Icon, tone = 'neutral' }) {
  return <article className={`summary-card ${tone}`}><div className="summary-top"><div className="summary-icon"><Icon size={18} strokeWidth={1.9} /></div><span className="summary-note">{note}</span></div><div className="summary-label">{label}</div><div className="summary-value">{value}</div></article>;
}

function MapPreview({ navigate }) {
  const parcels = [['p1', 28, 30, 17, 20], ['p2', 46, 30, 21, 20], ['p3', 68, 31, 16, 19], ['p4', 28, 51, 26, 24], ['p5', 54, 51, 18, 24], ['p6', 72, 51, 12, 24], ['p7', 28, 76, 20, 11], ['p8', 48, 76, 21, 11], ['p9', 69, 76, 15, 11]];
  return <div className="map-card"><div className="map-heading"><div><div className="section-kicker">LIVE PROJECT VIEW</div><h2>Hyderabad North — Ward 14</h2></div><button className="text-button" onClick={() => navigate('map')}>Open map <ArrowUpRight size={15} /></button></div><div className="map-canvas"><div className="map-raster" /><div className="map-road road-a" /><div className="map-road road-b" /><div className="map-road road-c" />{parcels.map(([id, x, y, w, h], i) => <div key={id} className={`parcel parcel-${i}`} style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%` }}><span>{String(101 + i).padStart(3, '0')}</span></div>)}<div className="map-marker marker-one" /><div className="map-marker marker-two" /><div className="map-control-group"><button>+</button><button>−</button></div><div className="map-legend"><span><i className="legend-parcel" /> Candidate parcel</span><span><i className="legend-building" /> Building</span><span><i className="legend-issue" /> Needs review</span></div><div className="map-status"><span className="status-live" /> AI map synced 2 min ago</div></div></div>;
}

function Dashboard({ navigate }) {
  const { project, remoteProjects, selectProject } = useProjectContext();
  const [artifacts, setArtifacts] = useState(null);
  const [loading, setLoading] = useState(Boolean(project?.backendId));
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    if (!project?.backendId) {
      setArtifacts(null);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    getArtifacts(project.backendId)
      .then((data) => { if (!cancelled) { setArtifacts(data); setError(''); } })
      .catch((err) => { if (!cancelled) setError(err.message || 'Could not load the current project summary.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [project?.backendId]);

  const result = artifacts?.result || {};
  const field = artifacts?.field_queue?.summary || {};
  const topo = artifacts?.topology_workflow?.summary || {};
  const current = remoteProjects.find((item) => item.id === project?.backendId) || null;
  const dateLabel = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date()).toUpperCase();
  const processed = String(project?.status || result.status || '').toLowerCase() === 'processed' || Boolean(result.parcel_count);
  const reviewCount = Number(result.review_parcels ?? field.count ?? 0);
  const criticalCount = Number(field.critical ?? result.field_queue_critical ?? 0);
  const openTopology = Number(topo.open ?? result.topology_issue_count ?? 0);
  const buildings = Number(result.building_candidates ?? 0);
  const roads = Number(result.road_candidates ?? 0);
  const parcels = Number(result.parcel_count ?? current?.result?.parcel_count ?? 0);
  const health = result.topology_health != null ? Number(result.topology_health).toFixed(1) : '—';
  const previewUrl = project?.backendId ? `/api/projects/${encodeURIComponent(project.backendId)}/preview/ori` : '';
  const recent = remoteProjects.slice(0, 4);

  return <div className="app-shell"><Sidebar screen="dashboard" navigate={navigate} /><main className="main"><header className="topbar"><div><div className="eyebrow">{dateLabel}</div><h1>Survey control room</h1></div><div className="topbar-actions"><button className="icon-button"><Bell size={19} /></button><label className="project-context"><span className="project-context-label">ACTIVE PROJECT</span><select className="project-switcher" value={project?.backendId || ''} onChange={(event) => { if (event.target.value) selectProject(event.target.value); }} aria-label="Select active project"><option value="">Select project</option>{remoteProjects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="primary-button" onClick={() => navigate('new-project')}><Plus size={17} /> New project</button></div></header><section className="content">
    <div className="overview-hero"><div><div className="section-kicker">FIELD OPERATIONS · CURRENT PROJECT</div><h2>{project?.name || 'No project selected'}</h2><p>{project?.zone || 'Select a survey project to view live processing, QC and verification status.'}</p></div><div className="overview-status"><span className={`overview-status-dot ${processed ? 'done' : ''}`} />{processed ? 'Processed dataset' : (project?.status || 'No active project')}</div></div>
    {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}
    {!project?.backendId ? <section className="overview-empty"><div><div className="section-kicker">NO ACTIVE SURVEY</div><h3>Select a project or start a new one</h3><p>The overview uses live backend metrics. Nothing here is a placeholder when a processed project is selected.</p></div><div className="overview-empty-actions"><button className="secondary-button" onClick={() => navigate('projects')}><FolderOpen size={16} /> Browse projects</button><button className="primary-button" onClick={() => navigate('new-project')}><Plus size={16} /> New project</button></div></section> : loading ? <section className="overview-empty"><div><div className="section-kicker">LIVE BACKEND</div><h3>Loading project control data</h3><p>Reading processing, topology and field-verification outputs.</p></div></section> : <>
      <div className="summary-grid overview-summary"><SummaryCard label="Candidate parcels" value={parcels} note="Current processing run" icon={Layers3} tone="sand" /><SummaryCard label="Building candidates" value={buildings} note="Aerial feature extraction" icon={Building2} tone="olive" /><SummaryCard label="Road candidates" value={roads} note="Access feature extraction" icon={Map} tone="blue" /><SummaryCard label="Topology health" value={`${health}%`} note={`${openTopology} open QC issue${openTopology === 1 ? '' : 's'}`} icon={ShieldCheck} tone="plum" /></div>
      <div className="overview-grid"><section className="overview-imagery-card"><div className="map-heading"><div><div className="section-kicker">CURRENT SURVEY IMAGERY</div><h2>Orthomosaic preview</h2></div><button className="text-button" onClick={() => navigate('map')}>Open cadastral map <ArrowUpRight size={15} /></button></div><div className="overview-imagery"><img src={previewUrl} alt="Current project orthomosaic preview" /><div className="imagery-overlay"><span>{result.source_size?.width || 0} × {result.source_size?.height || 0}px</span><span>{result.source_crs || 'CRS unknown'}</span></div></div><div className="overview-imagery-meta"><span>Parcel fabric <b>{parcels}</b></span><span>Field review <b>{reviewCount}</b></span><span>Critical <b>{criticalCount}</b></span><span>Encoding <b>{result.mode === 'baseline' ? 'Baseline fallback' : result.model_id || 'GeoAI'}</b></span></div></section>
        <section className="overview-actions-card"><div className="map-heading"><div><div className="section-kicker">ACTION QUEUE</div><h2>What needs attention</h2></div><button className="text-button" onClick={() => navigate('field')}>Open queue <ArrowUpRight size={15} /></button></div><div className="overview-action-list"><button className="overview-action-row" onClick={() => navigate('field')}><div className="overview-action-icon sand"><MapPinned size={17} /></div><div><strong>{reviewCount} parcels awaiting field verification</strong><span>{criticalCount} critical · priority sorted by uncertainty</span></div><ArrowRight size={16} /></button><button className="overview-action-row" onClick={() => navigate('topology')}><div className="overview-action-icon plum"><ShieldCheck size={17} /></div><div><strong>{openTopology} topology issue{openTopology === 1 ? '' : 's'} open</strong><span>{topo.critical ?? 0} critical · review before final delivery</span></div><ArrowRight size={16} /></button><button className="overview-action-row" onClick={() => navigate('reports')}><div className="overview-action-icon blue"><FileOutput size={17} /></div><div><strong>GIS delivery package ready</strong><span>{artifacts?.available_outputs?.length || 0} backend outputs available</span></div><ArrowRight size={16} /></button></div><div className="overview-principle"><ShieldCheck size={17} /><div><strong>AI proposes · GIS validates · human approves</strong><span>Use the control room to prioritize review; do not treat candidate geometry as authoritative without survey validation.</span></div></div></section></div>
      <section className="overview-recent-card"><div className="map-heading"><div><div className="section-kicker">PROJECT REGISTER</div><h2>Recent survey projects</h2></div><button className="text-button" onClick={() => navigate('projects')}>All projects <ArrowUpRight size={15} /></button></div><div className="overview-project-list">{recent.map(item => <button className={`overview-project-row ${item.id === project.backendId ? 'active' : ''}`} key={item.id} onClick={() => selectProject(item.id)}><div className="project-icon"><Map size={17} /></div><div className="overview-project-copy"><strong>{item.name}</strong><span>{item.zone || 'Survey zone not specified'} · {item.result?.parcel_count ?? '—'} parcels</span></div><div className="overview-project-metric">{item.result?.topology_health != null ? `${item.result.topology_health}%` : item.status}</div><span className={`status-chip ${String(item.status || '').toLowerCase() === 'processed' ? 'verified' : String(item.status || 'Draft').toLowerCase().replaceAll(' ', '-')}`}>{item.status}</span><ArrowRight size={15} /></button>)}</div></section>
    </>}
  </section></main></div>;
}

function MapPreviewPlaceholder() { return null; }

function FileCard({ item, file, onSelect, onClear }) {
  const inputRef = useRef(null);
  return <div className={`file-card ${file ? 'attached' : ''}`}><div className="file-card-icon">{file ? <Check size={18} /> : <UploadCloud size={18} />}</div><div className="file-card-copy"><strong>{item.label}{item.required && <span className="required-dot">Required</span>}</strong><span>{file ? `${file.name} · ${formatFileSize(file.size)}` : item.hint}</span></div>{file ? <button className="file-remove" onClick={onClear} aria-label={`Remove ${item.label}`}><X size={15} /></button> : <><input ref={inputRef} type="file" hidden onChange={e => onSelect(e.target.files?.[0])} /><button className="file-select" onClick={() => inputRef.current?.click()}>Choose file</button></>}</div>;
}

function formatFileSize(bytes = 0) {
  if (!bytes) return '0 KB';
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function NewProject({ navigate, project, setProject }) {
  const files = project.files;
  const isUpload = value => typeof File !== 'undefined' && value instanceof File;
  const requiredReady = Boolean(
    String(project.name || '').trim() &&
    String(project.zone || '').trim() &&
    isUpload(files.ori) &&
    isUpload(files.dsm)
  );
  const updateFile = (key, file) => file && setProject(prev => ({ ...prev, files: { ...prev.files, [key]: file }, status: 'Draft' }));
  const clearFile = key => setProject(prev => { const copy = { ...prev.files }; delete copy[key]; return { ...prev, files: copy }; });
  return <div className="app-shell"><Sidebar screen="projects" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Create a survey project" /><section className="content"><button className="back-link" onClick={() => navigate('dashboard')}><ArrowLeft size={15} /> Back to overview</button><div className="page-intro"><div><div className="section-kicker">NEW PROJECT</div><h2>Set up your urban parcel survey</h2><p>Bring imagery and survey layers together before running the cadastral extraction pipeline.</p></div><div className="step-indicator"><span className="step current">01</span><span>Project data</span><i /><span className="step">02</span><span>Process</span><i /><span className="step">03</span><span>Review</span></div></div><div className="setup-grid"><section className="form-card"><div className="card-title"><div><h3>Project details</h3><p>Use a human-readable name that survey teams will recognise.</p></div></div><label className="field-label">Project name<input value={project.name} onChange={e => setProject(prev => ({ ...prev, name: e.target.value }))} placeholder="e.g. Yavapur Abadi Survey" /></label><label className="field-label">Survey area / zone<input value={project.zone} onChange={e => setProject(prev => ({ ...prev, zone: e.target.value }))} placeholder="Village · Mandal · District" /></label><div className="note-box"><ShieldCheck size={17} /><div><strong>Preliminary cadastral workflow</strong><span>AI-generated boundaries remain subject to surveyor validation and field verification.</span></div></div></section><section className="form-card"><div className="card-title"><div><h3>Survey inputs</h3><p>Required inputs are enough to start a first-pass extraction. Additional layers improve parcel confidence.</p></div><span className="input-count">{Object.keys(files).length}/6 added</span></div><div className="file-list">{dataTypes.map(item => <FileCard key={item.key} item={item} file={files[item.key]} onSelect={file => updateFile(item.key, file)} onClear={() => clearFile(item.key)} />)}</div></section></div><div className="setup-footer"><div className={`readiness ${requiredReady ? 'ready' : ''}`}><span className="readiness-dot" />{requiredReady ? 'Required inputs ready for validation' : 'Add ORI and DSM to continue'}</div><button className="primary-button large" disabled={!requiredReady} onClick={() => navigate('validation')}><span>Validate dataset</span><ArrowRight size={17} /></button></div></section></main></div>;
}

function Validation({ navigate, project, setProject }) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError('');
        const data = await validateDataset(project.files, project.name, project.zone);
        if (!cancelled) {
          setResult(data);
          setProject(prev => ({ ...prev, status: data.status || 'Validated', backendId: data.project_id || prev.backendId }));
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Backend validation failed.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [project.files, setProject]);

  const checks = result?.checks || [
    ['Coordinate reference system', 'Inspecting raster metadata…', false],
    ['Raster coverage', 'Inspecting uploaded inputs…', false],
    ['Resolution', 'Reading geospatial metadata…', false],
    ['GeoTIFF integrity', 'Opening raster headers…', false],
    ['Elevation alignment', 'Comparing spatial references…', false],
  ];
  const fileRows = dataTypes.filter(item => project.files[item.key]);
  const ready = result?.ready === true;
  return <div className="app-shell"><Sidebar screen="projects" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Dataset validation" /><section className="content"><button className="back-link" onClick={() => navigate('new-project')}><ArrowLeft size={15} /> Back to project setup</button><div className="page-intro"><div><div className="section-kicker">DATA READINESS</div><h2>{loading ? 'Inspecting survey inputs' : ready ? 'Project preflight passed' : 'Dataset needs attention'}</h2><p>{loading ? 'The geospatial backend is reading CRS, raster dimensions, resolution and coverage from the uploaded files.' : result?.summary || 'Review the reported checks before starting extraction.'}</p></div><div className={`validation-badge ${ready ? '' : 'warning'}`}>{loading ? <CircleDashed size={16} /> : ready ? <Check size={16} /> : <TriangleAlert size={16} />} {loading ? 'Validating…' : ready ? 'Ready to process' : 'Review dataset'}</div></div><div className="validation-grid"><section className="validation-card"><div className="card-title"><div><h3>Backend preflight checks</h3><p>These are now coming from the Python geospatial service rather than frontend placeholders.</p></div></div><div className="check-list">{checks.map(([label, detail, pass], idx) => <div className="check-row" key={label}><div className={`check-icon ${pass ? '' : loading ? 'loading' : 'warning'}`}>{pass ? <Check size={16} /> : loading ? <CircleDashed size={16} /> : <TriangleAlert size={16} />}</div><div><strong>{label}</strong><span>{detail}</span></div><span className={`pass-label ${pass ? '' : loading ? 'pending' : 'warn'}`}>{pass ? 'PASS' : loading ? 'CHECKING' : 'REVIEW'}</span></div>)}</div>{error && <div className="backend-error"><TriangleAlert size={16} /><span>{error} Start the backend with <code>uvicorn app.main:app --reload --port 8000</code>.</span></div>}</section><aside className="dataset-summary"><div className="section-kicker">PROJECT</div><h3>{project.name}</h3><div className="summary-line"><span>Survey zone</span><strong>{project.zone}</strong></div><div className="summary-line"><span>Inputs</span><strong>{fileRows.map(item => item.label).join(' · ')}</strong></div><div className="summary-line"><span>Processing mode</span><strong>Multi-source GeoAI</strong></div>{result?.raster_summary && <><div className="summary-rule" /><div className="section-kicker">ORI METADATA</div><div className="metadata-grid">
  <div className="metadata-item"><span>CRS</span><strong>{result.raster_summary.crs || 'Unknown'}</strong></div>
  <div className="metadata-item"><span>Raster size</span><strong>{result.raster_summary.width} × {result.raster_summary.height} px</strong></div>
  <div className="metadata-item metadata-item-wide"><span>Ground sampling distance</span><strong>{result.raster_summary.resolution || 'Unknown'}</strong>{result.raster_summary.resolution_map_units && result.raster_summary.resolution_map_units !== result.raster_summary.resolution && <small>Source resolution: {result.raster_summary.resolution_map_units}</small>}</div>
</div></>}<div className="summary-rule" /><div className="dataset-callout"><Sparkles size={17} /><div><strong>Next: generate the preliminary map</strong><span>After preflight, the next backend step will run feature extraction and parcel inference.</span></div></div></aside></div><div className="setup-footer"><div className={`readiness ${ready ? 'ready' : ''}`}><span className="readiness-dot" />{loading ? 'Backend validation in progress' : ready ? 'Geospatial preflight passed' : 'Fix dataset issues before processing'}</div><button className="primary-button large" disabled={!ready} onClick={() => navigate('processing')}>Start AI extraction <Sparkles size={17} /></button></div></section></main></div>;
}

function Processing({ navigate, project, setProject }) {
  const { project: contextProject } = useProjectContext();
  const activeProject = contextProject?.backendId ? contextProject : project;
  const [status, setStatus] = useState({ status: 'idle', progress: 0, stage: 'idle', detail: 'No extraction has been started.' });
  const [error, setError] = useState('');
  const [artifacts, setArtifacts] = useState(activeProject.artifacts || null);
  const [retrying, setRetrying] = useState(false);
  const startedRef = useRef(false);

  const loadCompletedArtifacts = async (id) => {
    try {
      const data = await getArtifacts(id);
      setArtifacts(data);
      setProject(prev => ({ ...prev, status: 'Processed', artifacts: data, backendId: id }));
    } catch (err) {
      setError(err.message || 'Processing completed but results could not be loaded.');
    }
  };

  useEffect(() => {
    const id = activeProject.backendId;
    if (!id || startedRef.current) return;
    startedRef.current = true;
    let cancelled = false;
    let timer;

    const begin = async () => {
      try {
        setError('');
        const current = await getProcessingStatus(id);
        if (cancelled) return;
        setStatus(current);

        if (current.status === 'complete') {
          await loadCompletedArtifacts(id);
          return;
        }

        // Do not silently restart failed jobs; expose the failure and retry action.
        if (current.status === 'error') {
          setError(current.detail || 'GeoAI extraction failed.');
          return;
        }

        if (current.status !== 'running' && current.status !== 'queued') {
          await startProcessing(id);
        }

        const poll = async () => {
          try {
            const next = await getProcessingStatus(id);
            if (cancelled) return;
            setStatus(next);
            if (next.status === 'complete') {
              await loadCompletedArtifacts(id);
              return;
            }
            if (next.status === 'error') {
              setError(next.detail || 'GeoAI extraction failed.');
              return;
            }
            timer = window.setTimeout(poll, 1200);
          } catch (err) {
            if (!cancelled) setError(err.message || 'Could not read extraction status.');
          }
        };
        poll();
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not start GeoAI extraction.');
      }
    };

    begin();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [activeProject.backendId]);

  const retryExtraction = async () => {
    if (!activeProject.backendId || retrying) return;
    setRetrying(true);
    setError('');
    try {
      const queued = await reprocessProject(activeProject.backendId);
      setStatus(queued);
      while (true) {
        const next = await getProcessingStatus(activeProject.backendId);
        setStatus(next);
        if (next.status === 'complete') {
          await loadCompletedArtifacts(activeProject.backendId);
          break;
        }
        if (next.status === 'error') {
          setError(next.detail || 'GeoAI extraction failed again.');
          break;
        }
        await new Promise(resolve => window.setTimeout(resolve, 1200));
      }
    } catch (err) {
      setError(err.message || 'Could not restart GeoAI extraction.');
    } finally {
      setRetrying(false);
    }
  };

  const done = status.status === 'complete';
  const failed = status.status === 'error';
  const hasProject = Boolean(activeProject.backendId);
  const result = artifacts?.result;

  const stageRank = {
    queued: 1, starting: 1, preflight: 1,
    features: 2, vectorize: 3, parcels: 4,
    evidence: 5, qc: 6, complete: 7,
  };
  const currentRank = stageRank[status.stage] || 0;
  const stageRanks = {
    preflight: 1, buildings: 2, roads: 2, landuse: 3,
    parcels: 4, boundaries: 5, topology: 6,
  };

  const stageState = (key, index) => {
    if (!hasProject) return 'Queued';
    const rank = stageRanks[key] || index + 1;
    if (failed) return currentRank > rank ? 'Done' : 'Queued';
    if (done || currentRank > rank || (currentRank === rank && status.progress >= 95)) return 'Done';
    if (currentRank === rank || (status.status === 'queued' && index === 0)) {
      return status.status === 'queued' ? 'Queued' : 'Running';
    }
    return 'Queued';
  };

  return <div className="app-shell"><Sidebar screen="processing" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="AI extraction workspace" /><section className="content">
    <div className="page-intro">
      <div>
        <div className="section-kicker">GEOAI PIPELINE</div>
        <h2>{!hasProject ? 'Start with a survey project' : done ? 'Preliminary cadastral map ready' : failed ? 'Extraction stopped' : 'Generating the preliminary map'}</h2>
        <p>{!hasProject ? 'Create a project and validate ORI + DSM inputs before starting extraction.' : status.detail}</p>
      </div>
      <div className={`processing-progress-badge ${failed ? 'warning' : ''}`}>
        {failed ? <TriangleAlert size={16} /> : <CircleDashed size={16} />}
        <span>{hasProject ? `${Number(status.progress || 0)}%` : 'Not started'}</span>
      </div>
    </div>

    {!hasProject ? <section className="empty-state processing-empty"><Sparkles size={24} /><strong>No active backend project</strong><span>The live extraction workspace starts after a real survey project is validated.</span><button className="primary-button" onClick={() => navigate('new-project')}>Create survey project <ArrowRight size={16} /></button></section> :

    <div className="processing-layout">
      <section className="processing-card">
        <div className="processing-stage-list">
          {extractionStages.map(([key, label, detail], index) => {
            const state = stageState(key, index);
            return <div className={`processing-stage ${state === 'Running' ? 'active' : ''} ${state === 'Done' ? 'complete' : ''}`} key={key}>
              <div className="stage-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="stage-copy"><strong>{label}</strong><span>{detail}</span></div>
              <span className="stage-state">{state}</span>
            </div>;
          })}
        </div>

        <div className="processing-progress">
          <div className="progress-heading">
            <div><span className="progress-label">PROCESSING PROGRESS</span><strong>{Number(status.progress || 0)}% complete</strong></div>
            <span className="progress-stage">{String(status.stage || 'idle').replaceAll('-', ' ').toUpperCase()}</span>
          </div>
          <div className="progress-track"><div style={{ width: `${Math.max(0, Math.min(100, Number(status.progress || 0)))}%` }} /></div>
        </div>

        {error && <div className={`backend-error processing-error ${failed ? 'error' : ''}`}>
          <TriangleAlert size={16} />
          <div><strong>{failed ? 'Processing failed' : 'Processing notice'}</strong><span>{error}</span></div>
        </div>}

        {done && <div className="processing-complete-strip"><CheckCheck size={17} /><div><strong>Extraction complete</strong><span>Candidate GIS outputs are ready for map review, topology checks and field verification.</span></div></div>}
        <div className="processing-actions">
          <button className="secondary-button" onClick={() => navigate('dashboard')}>Back to overview</button>
          {failed
            ? <button className="primary-button" onClick={retryExtraction} disabled={retrying}>{retrying ? 'Retrying extraction…' : 'Retry extraction'} <RefreshCw size={16} /></button>
            : <button className="primary-button" disabled={!done} onClick={() => navigate('map')}>Open cadastral map <ArrowRight size={16} /></button>}
        </div>
      </section>

      <aside className="processing-summary">
        <div className="section-kicker">EXTRACTION SUMMARY</div>
        <h3>{done ? 'Backend outputs' : failed ? 'Run requires attention' : 'Working set'}</h3>
        {done && result ? <div className="live-metrics">
          <div><span>Building candidates</span><strong>{result.building_candidates}</strong></div>
          <div><span>Road candidates</span><strong>{result.road_candidates}</strong></div>
          <div><span>Candidate parcels</span><strong>{result.parcel_count}</strong></div>
          <div><span>Needs review</span><strong>{result.review_parcels}</strong></div>
          <div><span>Topology health</span><strong>{result.topology_health}%</strong></div>
          <div><span>CRS</span><strong>{result.source_crs || 'Unknown'}</strong></div>
        </div> : failed ? <div className="dataset-callout">
          <TriangleAlert size={17} />
          <div><strong>Run stopped before final QC</strong><span>The source survey data remains intact. Retry after the topology/input error is addressed.</span></div>
        </div> : <div className="dataset-callout">
          <Sparkles size={17} />
          <div><strong>Live backend processing</strong><span>Raster tiles are being processed, vectorized and converted into candidate cadastral outputs.</span></div>
        </div>}
        {done && <><div className="summary-rule" /><div className="dataset-callout"><ShieldCheck size={17} /><div><strong>Human verification remains required</strong><span>Low-confidence and topology-flagged parcels should be reviewed before final cadastral use.</span></div></div></>}
      </aside>
    </div>}
  </section></main></div>;
}

function MapWorkspace({ navigate }) {
  const { project } = useProjectContext();
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [backendFeatures, setBackendFeatures] = useState([]);
  const [backendMeta, setBackendMeta] = useState(null);
  const [boundaryEvidence, setBoundaryEvidence] = useState([]);
  const [buildingFeatures, setBuildingFeatures] = useState([]);
  const [roadFeatures, setRoadFeatures] = useState([]);
  const [showBuildings, setShowBuildings] = useState(false);
  const [showRoads, setShowRoads] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [editHistory, setEditHistory] = useState([]);
  const [splitMode, setSplitMode] = useState(false);
  const [splitPoints, setSplitPoints] = useState([]);
  const [mergeMode, setMergeMode] = useState(false);
  const [mergeTargetId, setMergeTargetId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draftGeometry, setDraftGeometry] = useState(null);
  const [dragVertex, setDragVertex] = useState(null);
  const dragVertexRef = useRef(null);
  const dragPointerIdRef = useRef(null);
  const [activeVertex, setActiveVertex] = useState(null);
  const [vertexXInput, setVertexXInput] = useState('');
  const [vertexYInput, setVertexYInput] = useState('');
  const [vertexPreviewTick, setVertexPreviewTick] = useState(0);
  const [editNote, setEditNote] = useState('');
  const [lastEdit, setLastEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const svgRef = useRef(null);
  const editMapRef = useRef(null);

  const backendProjectId = project?.backendId || null;

  const loadOutputs = async (id) => {
    if (!id) return;
    const data = await getOutputGeoJSON(id, 'parcels.geojson');
    const artifacts = await getArtifacts(id);
    let evidence = { features: [] };
    let buildings = { features: [] };
    let roads = { features: [] };
    let history = { history: [] };
    try { evidence = await getBoundaryEvidence(id); } catch { evidence = { features: [] }; }
    try { buildings = await getOutputGeoJSON(id, 'buildings.geojson'); } catch { buildings = { features: [] }; }
    try { roads = await getOutputGeoJSON(id, 'roads.geojson'); } catch { roads = { features: [] }; }
    try { history = await getEditHistory(id); } catch { history = { history: [] }; }
    setBackendFeatures(data.features || []);
    setBoundaryEvidence(evidence.features || []);
    setBuildingFeatures(buildings.features || []);
    setRoadFeatures(roads.features || []);
    setEditHistory(history.history || []);
    setBackendMeta(artifacts);
  };

  useEffect(() => {
    if (!backendProjectId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        await loadOutputs(backendProjectId);
      } catch {
        if (!cancelled) {
          setBackendFeatures([]);
          setBoundaryEvidence([]);
          setBuildingFeatures([]);
          setRoadFeatures([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [backendProjectId]);

  const actualParcels = backendFeatures.length
    ? backendFeatures.map((feature, index) => ({
        id: feature.properties?.parcel_id || `P-${index + 1}`,
        area: `${Number(feature.properties?.area || 0).toFixed(1)} m²`,
        confidence: Number(feature.properties?.boundary_confidence || 0),
        landuse: feature.properties?.land_use || 'Unknown',
        status: feature.properties?.status || 'Review',
        geometry: feature.geometry,
        evidence: feature.properties?.evidence || {},
        buildingCount: feature.properties?.building_count || 0,
        verificationStatus: feature.properties?.verification_status || 'Pending',
        fieldPriority: feature.properties?.field_verification_priority || 'Low',
        potentialEncroachment: Boolean(feature.properties?.potential_encroachment),
      }))
    : backendProjectId
      ? []
      : mapParcels;

  const filtered = actualParcels.filter((parcel) =>
    `${parcel.id} ${parcel.landuse}`.toLowerCase().includes(query.toLowerCase())
  );

  const currentSelected =
    filtered.find((parcel) => parcel.id === selectedId) || filtered[0] || actualParcels[0] || null;

  const selectedDisplay = currentSelected || {
    id: '—', area: '—', confidence: 0, landuse: '—', status: 'Unavailable',
    geometry: null, evidence: {}, buildingCount: 0, verificationStatus: 'Unavailable',
    fieldPriority: '—', potentialEncroachment: false,
  };

  useEffect(() => {
    if (currentSelected?.id && currentSelected.id !== selectedId) setSelectedId(currentSelected.id);
  }, [currentSelected?.id, selectedId]);

  const allPairs = backendFeatures.flatMap((feature) => {
    const type = feature.geometry?.type;
    const coordinates = feature.geometry?.coordinates;
    if (type === 'Polygon') return coordinates?.flat(2) || [];
    if (type === 'MultiPolygon') return coordinates?.flat(3) || [];
    return [];
  });

  let minX = 0;
  let minY = 0;
  let maxX = 100;
  let maxY = 100;

  if (allPairs.length) {
    const xs = allPairs.map((point) => point[0]);
    const ys = allPairs.map((point) => point[1]);
    minX = Math.min(...xs);
    maxX = Math.max(...xs);
    minY = Math.min(...ys);
    maxY = Math.max(...ys);
  }

  const focusedGeometry = editing ? draftGeometry : (splitMode ? currentSelected?.geometry : null);
  const focusedPairs = focusedGeometry?.type === 'Polygon' ? focusedGeometry.coordinates?.[0] || [] : [];
  const baseXSpan = Math.max(maxX - minX, 1e-9);
  const baseYSpan = Math.max(maxY - minY, 1e-9);

  if (focusedPairs.length) {
    const xs = focusedPairs.map((point) => point[0]);
    const ys = focusedPairs.map((point) => point[1]);
    const focusMinX = Math.min(...xs);
    const focusMaxX = Math.max(...xs);
    const focusMinY = Math.min(...ys);
    const focusMaxY = Math.max(...ys);
    const focusPadX = Math.max((focusMaxX - focusMinX) * 0.55, baseXSpan * 0.018);
    const focusPadY = Math.max((focusMaxY - focusMinY) * 0.55, baseYSpan * 0.018);
    minX = focusMinX - focusPadX;
    maxX = focusMaxX + focusPadX;
    minY = focusMinY - focusPadY;
    maxY = focusMaxY + focusPadY;
  }

  const xSpan = Math.max(maxX - minX, 1e-9);
  const ySpan = Math.max(maxY - minY, 1e-9);

  const toSvgPoint = ([x, y]) => ({
    x: 6 + ((x - minX) / xSpan) * 88,
    y: 91 - ((y - minY) / ySpan) * 78,
  });

  const drawPolygon = (geometry) => {
    if (!geometry) return [];
    const rings =
      geometry.type === 'Polygon'
        ? [geometry.coordinates?.[0] || []]
        : geometry.type === 'MultiPolygon'
          ? (geometry.coordinates || []).map((polygon) => polygon?.[0] || [])
          : [];
    return rings.map((ring, ringIndex) => ({
      key: ringIndex,
      points: ring.map((pair) => {
        const point = toSvgPoint(pair);
        return `${point.x},${point.y}`;
      }).join(' '),
    }));
  };

  const drawVectorGeometry = (geometry, keyPrefix, className) => {
    if (!geometry) return [];
    const pointsFromRing = (ring) => ring.map((pair) => { const point = toSvgPoint(pair); return `${point.x},${point.y}`; }).join(' ');
    if (geometry.type === 'Polygon') return (geometry.coordinates || []).slice(0, 1).map((ring, i) => <polygon key={`${keyPrefix}-p-${i}`} points={pointsFromRing(ring)} className={className} />);
    if (geometry.type === 'MultiPolygon') return (geometry.coordinates || []).flatMap((polygon, i) => (polygon || []).slice(0, 1).map((ring, r) => <polygon key={`${keyPrefix}-mp-${i}-${r}`} points={pointsFromRing(ring)} className={className} />));
    if (geometry.type === 'LineString') return [<polyline key={`${keyPrefix}-l`} points={pointsFromRing(geometry.coordinates || [])} className={className} />];
    if (geometry.type === 'MultiLineString') return (geometry.coordinates || []).map((line, i) => <polyline key={`${keyPrefix}-ml-${i}`} points={pointsFromRing(line)} className={className} />);
    return [];
  };

  const evidenceDefaults = {
    existing_gis: 31,
    imagery_edge: 27,
    structure: 18,
    road_access: 12,
    terrain: 12,
  };

  const draftVertices = useMemo(() => {
    const ring = draftGeometry?.type === 'Polygon' ? draftGeometry.coordinates?.[0] || [] : [];
    return ring.length > 1 ? ring.slice(0, -1) : [];
  }, [draftGeometry]);

  useEffect(() => {
    if (activeVertex == null || !draftVertices[activeVertex]) {
      setVertexXInput(''); setVertexYInput(''); return;
    }
    setVertexXInput(Number(draftVertices[activeVertex][0]).toFixed(8));
    setVertexYInput(Number(draftVertices[activeVertex][1]).toFixed(8));
  }, [activeVertex, draftVertices]);

  const selectVertex = (index) => {
    if (!editing || index == null || !draftVertices[index]) return;
    setActiveVertex(index); setDragVertex(null);
    dragVertexRef.current = null; dragPointerIdRef.current = null;
  };

  const commitVertexCoordinate = (x, y) => {
    if (activeVertex == null || !draftGeometry?.coordinates?.[0]) return false;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
    setDraftGeometry((current) => {
      if (!current?.coordinates?.[0]) return current;
      const ring = [...current.coordinates[0]];
      ring[activeVertex] = [x, y];
      if (ring.length) ring[ring.length - 1] = [...ring[0]];
      return {...current, coordinates:[ring]};
    });
    setVertexXInput(x.toFixed(8));
    setVertexYInput(y.toFixed(8));
    setVertexPreviewTick((v) => v + 1);
    return true;
  };

  const applyVertexCoordinate = () => {
    const x = Number(vertexXInput), y = Number(vertexYInput);
    commitVertexCoordinate(x, y);
  };

  const placeActiveVertexOnMap = (event) => {
    if (!editing || activeVertex == null || !draftGeometry) return false;
    const coordinate = pointerToMapCoordinate(event);
    if (!coordinate) return false;
    event.preventDefault();
    event.stopPropagation();
    return commitVertexCoordinate(coordinate[0], coordinate[1]);
  };

  const pointerToMapCoordinate = (event) => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    let svgX = ((event.clientX - rect.left) / rect.width) * 100;
    let svgY = ((event.clientY - rect.top) / rect.height) * 100;
    if (typeof svg.getScreenCTM === 'function' && svg.getScreenCTM()) {
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const local = point.matrixTransform(svg.getScreenCTM().inverse());
      svgX = local.x;
      svgY = local.y;
    }
    const localX = 50 + (svgX - 50) / zoom;
    const localY = 50 + (svgY - 50) / zoom;
    return [
      minX + ((localX - 6) / 88) * xSpan,
      minY + ((91 - localY) / 78) * ySpan,
    ];
  };

  const beginVertexDrag = (index, event) => {
    if (!editing || !draftGeometry) return;
    event.preventDefault(); event.stopPropagation(); selectVertex(index);
  };
  const endVertexDrag = () => {};
  const handleSvgPointerMove = () => {};

  const stopMapModes = () => {
    setSplitMode(false);
    setSplitPoints([]);
    setMergeMode(false);
    setMergeTargetId(null);
  };

  const handleMapClick = (event) => {
    if (editing && activeVertex != null) {
      placeActiveVertexOnMap(event);
      return;
    }
    if (!splitMode || editing) return;
    const coordinate = pointerToMapCoordinate(event);
    if (!coordinate) return;
    setSplitPoints((current) => current.length >= 2 ? [coordinate] : [...current, coordinate]);
  };

  const handleParcelClick = (event, parcel) => {
    event.preventDefault();
    event.stopPropagation();
    if (editing) return;
    if (splitMode) {
      const coordinate = pointerToMapCoordinate(event);
      if (coordinate) setSplitPoints((current) => current.length >= 2 ? [coordinate] : [...current, coordinate]);
      return;
    }
    if (mergeMode) {
      if (parcel.id !== currentSelected?.id) setMergeTargetId(parcel.id);
      return;
    }
    setSelectedId(parcel.id);
    setQuery('');
  };

  const startSplit = () => {
    if (!canEdit) return;
    setError('');
    setEditNote('');
    setSplitPoints([]);
    setMergeMode(false);
    setMergeTargetId(null);
    setSplitMode(true);
  };

  const cancelSplit = () => {
    setSplitMode(false);
    setSplitPoints([]);
  };

  const applySplit = async () => {
    if (!backendProjectId || !currentSelected?.id || splitPoints.length !== 2) return;
    setBusy(true);
    setError('');
    try {
      const result = await splitParcel(backendProjectId, currentSelected.id, splitPoints[0], splitPoints[1], editNote || 'Split created in WebGIS editor.');
      stopMapModes();
      setLastEdit({ parcel_id: result.parcel?.properties?.parcel_id, action: 'split', topology: result.topology, confidence_after: result.parcel?.properties?.boundary_confidence, confidence_before: currentSelected.confidence, message: `Split created ${result.new_parcel?.properties?.parcel_id}` });
      await loadOutputs(backendProjectId);
      setSelectedId(result.parcel?.properties?.parcel_id || currentSelected.id);
    } catch (err) {
      setError(err.message || 'Could not split parcel.');
    } finally {
      setBusy(false);
    }
  };

  const startMerge = () => {
    if (!canEdit || actualParcels.length < 2) return;
    setError('');
    setEditNote('');
    setSplitMode(false);
    setSplitPoints([]);
    setMergeTargetId(null);
    setMergeMode(true);
  };

  const applyMerge = async () => {
    if (!backendProjectId || !currentSelected?.id || !mergeTargetId) return;
    setBusy(true);
    setError('');
    try {
      const result = await mergeParcels(backendProjectId, currentSelected.id, mergeTargetId, editNote || 'Merge created in WebGIS editor.');
      stopMapModes();
      setLastEdit({ parcel_id: result.parcel?.properties?.parcel_id, action: 'merge', topology: result.topology, confidence_after: result.parcel?.properties?.boundary_confidence, confidence_before: currentSelected.confidence, message: `Merged ${mergeTargetId} into ${currentSelected.id}` });
      await loadOutputs(backendProjectId);
      setSelectedId(result.parcel?.properties?.parcel_id || currentSelected.id);
    } catch (err) {
      setError(err.message || 'Could not merge parcels.');
    } finally {
      setBusy(false);
    }
  };

  const startEditing = () => {
    if (!backendProjectId || !currentSelected?.geometry || currentSelected.geometry.type !== 'Polygon') return;
    setError('');
    stopMapModes();
    setEditNote('');
    setLastEdit(null);
    setDraftGeometry(JSON.parse(JSON.stringify(currentSelected.geometry)));
    setZoom(2.5);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    stopMapModes();
    setDraftGeometry(null);
    setDragVertex(null);
    setActiveVertex(null);
    setEditNote('');
  };

  const saveBoundary = async () => {
    if (!backendProjectId || !currentSelected?.id || !draftGeometry) return;
    setBusy(true);
    setError('');
    try {
      const result = await editParcelBoundary(backendProjectId, currentSelected.id, draftGeometry, editNote);
      setLastEdit(result);
      setEditing(false);
      setDraftGeometry(null);
      setDragVertex(null);
      setActiveVertex(null);
      setBackendFeatures((features) => features.map((feature) =>
        feature.properties?.parcel_id === currentSelected.id ? result.parcel : feature
      ));
      setBackendMeta((prev) => prev ? {
        ...prev,
        result: { ...prev.result, topology_health: result.topology.health, topology_issue_count: result.topology.issue_count },
      } : prev);
      await loadOutputs(backendProjectId);
    } catch (err) {
      setError(err.message || 'Could not save boundary edit.');
    } finally {
      setBusy(false);
    }
  };

  const revalidate = async () => {
    if (!backendProjectId || !currentSelected?.id) return;
    setBusy(true);
    setError('');
    try {
      const result = await revalidateParcel(backendProjectId, currentSelected.id, editNote);
      setLastEdit(result);
      setBackendFeatures((features) => features.map((feature) =>
        feature.properties?.parcel_id === currentSelected.id ? result.parcel : feature
      ));
      setBackendMeta((prev) => prev ? {
        ...prev,
        result: { ...prev.result, topology_health: result.topology.health, topology_issue_count: result.topology.issue_count },
      } : prev);
      await loadOutputs(backendProjectId);
    } catch (err) {
      setError(err.message || 'Could not revalidate parcel.');
    } finally {
      setBusy(false);
    }
  };

  const gt = lastEdit?.comparison?.ground_truth;
  const gnss = lastEdit?.comparison?.gnss;
  const canEdit = Boolean(backendProjectId && currentSelected?.geometry?.type === 'Polygon');
  const exportUrl = backendProjectId ? exportProject(backendProjectId) : null;

  return (
    <div className="app-shell">
      <Sidebar screen="map" navigate={navigate} />
      <main className="main">
        <Topbar navigate={navigate} title="Cadastral map" />
        <section className="content map-workspace-page">
          <div className="map-page-head">
            <div>
              <div className="section-kicker">WEB GIS · PRELIMINARY OUTPUT</div>
              <h2>Candidate urban parcel map</h2>
              <p>Inspect, adjust and revalidate candidate parcel geometries before surveyor verification.</p>
            </div>
            <div className="map-head-actions">
              <a className={`secondary-button ${!exportUrl ? 'disabled-link' : ''}`} href={exportUrl || '#'} onClick={(event) => { if (!exportUrl) event.preventDefault(); }} download><Download size={16} /> Export GIS package</a>
              <button className="primary-button" onClick={() => navigate('field')}><MapPinned size={16} /> Field queue</button>
            </div>
          </div>

          {editing && (
            <div className="edit-banner">
              <div className="edit-banner-main"><Pencil size={16} /><div><strong>Boundary edit mode</strong><span>Select a vertex to locate it on the map, then edit its X/Y coordinates. The original boundary is shown as a dashed line.</span></div></div>
              <span className="edit-banner-count">{draftVertices.length} vertices</span>
            </div>
          )}
          {splitMode && <div className="edit-banner"><div className="edit-banner-main"><Pencil size={16} /><div><strong>Split parcel mode</strong><span>Click two points to draw a cut line. The line should cross the selected parcel boundary on both sides.</span></div></div><span className="edit-banner-count">{splitPoints.length}/2 clicks</span></div>}
          {mergeMode && <div className="edit-banner"><div className="edit-banner-main"><Layers3 size={16} /><div><strong>Merge parcel mode</strong><span>Selected parcel <b>{selectedDisplay.id}</b> is the primary. Click the neighboring parcel you want to merge with it.</span></div></div><span className="edit-banner-count">{mergeTargetId ? '2 selected' : 'choose 1'}</span></div>}
          {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}

          <div className="map-shell">
            <div className="map-toolbar">
              <button className="tool-chip active"><Layers3 size={15} /> Candidate parcels</button>
              <button className={`tool-chip${showBuildings ? ' active' : ''}`} onClick={() => setShowBuildings((value) => !value)}><Building2 size={15} /> Buildings</button>
              <button className={`tool-chip${showRoads ? ' active' : ''}`} onClick={() => setShowRoads((value) => !value)}><Ruler size={15} /> Roads</button>
              <button className={`tool-chip${showEvidence ? ' active' : ''}`} onClick={() => setShowEvidence((value) => !value)}><Target size={15} /> Boundary evidence</button>
              <button className={`tool-chip${splitMode ? ' active' : ''}`} onClick={splitMode ? cancelSplit : startSplit} disabled={!canEdit || editing}><Pencil size={15} /> Split parcel</button>
              <button className={`tool-chip${mergeMode ? ' active' : ''}`} onClick={mergeMode ? stopMapModes : startMerge} disabled={!canEdit || editing}><Layers3 size={15} /> Merge parcels</button>
              <span className="toolbar-separator" />
              <div className="map-search"><Search size={15} /><input placeholder="Find parcel or land use" value={query} onChange={(event) => setQuery(event.target.value)} disabled={editing} /></div>
              <button className="icon-tool"><MoreHorizontal size={17} /></button>
            </div>

            <div ref={editMapRef} className={`gis-canvas${editing ? " editing-canvas" : ""}`}>
              <div className="gis-raster" style={backendProjectId ? { backgroundImage: `url(/api/projects/${backendProjectId}/preview/ori)` } : undefined} />
              {!backendProjectId && <><div className="gis-road gis-road-1" /><div className="gis-road gis-road-2" /><div className="gis-road gis-road-3" /><div className="gis-road gis-road-4" /></>}

              {backendFeatures.length ? (
                <svg ref={svgRef} className={`real-gis-overlay${editing ? " editing-overlay" : ""}`} viewBox="0 0 100 100" preserveAspectRatio="none" onClick={handleMapClick} onPointerMove={editing ? handleSvgPointerMove : undefined} onPointerUp={editing ? endVertexDrag : undefined} onPointerCancel={editing ? endVertexDrag : undefined}>
                  <g transform={`translate(50 50) scale(${zoom}) translate(-50 -50)`}>
                  {showRoads && roadFeatures.flatMap((feature, index) => drawVectorGeometry(feature.geometry, `road-${index}`, 'gis-road-vector'))}
                  {showBuildings && buildingFeatures.flatMap((feature, index) => drawVectorGeometry(feature.geometry, `building-${index}`, 'gis-building-vector'))}
                  {showEvidence && boundaryEvidence.map((feature) => {
                    const parcel = actualParcels.find((item) => item.id === feature.properties?.parcel_id);
                    if (!parcel) return null;
                    return drawPolygon(parcel.geometry).map(({ key, points }) => (
                      <polyline key={`evidence-${parcel.id}-${key}`} points={points} className="evidence-boundary-line" />
                    ));
                  })}
                  {filtered.flatMap((parcel) => {
                    const geometry = editing && parcel.id === currentSelected.id && draftGeometry ? draftGeometry : parcel.geometry;
                    const visualClass = `real-parcel${currentSelected.id === parcel.id ? ' selected' : ''}${mergeTargetId === parcel.id ? ' merge-target' : ''}${parcel.status === 'Review' ? ' review' : ''}`;
                    return drawPolygon(geometry).flatMap(({ key, points }) => ([
                      <polygon key={`${parcel.id}-visual-${key}`} points={points} className={visualClass} pointerEvents="none" />,
                      <polygon key={`${parcel.id}-hit-${key}`} points={points} className="real-parcel-hit" onPointerDown={(event) => handleParcelClick(event, parcel)} onClick={(event) => handleParcelClick(event, parcel)} />
                    ]));
                  })}
                  {editing && <g className="editing-preview-guide" pointerEvents="none">
                    <rect x="1.2" y="2" width="31" height="7.2" rx="1.4" className="editing-map-hint-box" />
                    <text x="3" y="6.6" className="editing-map-hint">Click map to place selected vertex</text>
                  </g>}
                  {editing && draftVertices.map((coordinate, index) => {
                    const point = toSvgPoint(coordinate);
                    const active = activeVertex === index;
                    return <g key={`vertex-${index}`} className={`edit-vertex-group${active ? ' active' : ''}`}>
                      <circle cx={point.x} cy={point.y} r="8" className="edit-vertex-hit" onClick={(event) => { event.preventDefault(); event.stopPropagation(); selectVertex(index); }} onPointerDown={(event) => beginVertexDrag(index, event)} />
                      <circle cx={point.x} cy={point.y} r={active ? 4 : 2.8} className={`edit-vertex${active ? ' dragging' : ''}`} pointerEvents="none" />
                      <text x={point.x + 3.4} y={point.y - 3.2} className="edit-vertex-label" pointerEvents="none">{index + 1}</text>
                      {active && <g className={`vertex-coordinate-callout ${vertexPreviewTick ? 'previewed' : ''}`} pointerEvents="none">
                        <line x1={point.x} y1={point.y - 5} x2={point.x} y2={point.y - 12} className="vertex-callout-line" />
                        <rect x={Math.min(83.5, point.x + 2)} y={Math.max(2, point.y - 25)} width="20" height="13" rx="1.5" className="vertex-callout-box" />
                        <text x={Math.min(84.7, point.x + 2.8)} y={Math.max(7.1, point.y - 18.9)} className="vertex-callout-text">V{index + 1}</text>
                        <text x={Math.min(84.7, point.x + 2.8)} y={Math.max(10.8, point.y - 15.0)} className="vertex-callout-text">X {Number(coordinate[0]).toFixed(7)}</text>
                        <text x={Math.min(84.7, point.x + 2.8)} y={Math.max(14.6, point.y - 11.1)} className="vertex-callout-text">Y {Number(coordinate[1]).toFixed(7)}</text>
                      </g>}
                    </g>;
                  })}
                  {editing && currentSelected?.geometry && drawPolygon(currentSelected.geometry).map(({ key, points }) => (
                    <polyline key={`original-${key}`} points={points} className="original-boundary-line" />
                  ))}
                  {splitMode && splitPoints.length > 0 && <circle cx={toSvgPoint(splitPoints[0]).x} cy={toSvgPoint(splitPoints[0]).y} r="1.3" className="split-point" />}
                  {splitMode && splitPoints.length === 2 && <><circle cx={toSvgPoint(splitPoints[1]).x} cy={toSvgPoint(splitPoints[1]).y} r="1.3" className="split-point" /><line x1={toSvgPoint(splitPoints[0]).x} y1={toSvgPoint(splitPoints[0]).y} x2={toSvgPoint(splitPoints[1]).x} y2={toSvgPoint(splitPoints[1]).y} className="split-line" /></>}
                  </g>
                </svg>
              ) : backendProjectId ? (
                <div className="empty-state gis-empty-state">
                  <CircleDashed size={22} />
                  <strong>No processed geometry is available yet</strong>
                  <span>Open AI Processing to complete the current run, then return here to inspect live parcel geometry.</span>
                  <button className="secondary-button" onClick={() => navigate('processing')}>Open processing <ArrowRight size={15} /></button>
                </div>
              ) : (
                filtered.map((parcel) => <button key={parcel.id} className={`gis-parcel${currentSelected?.id === parcel.id ? ' selected' : ''}${parcel.status === 'Review' ? ' review' : ''}`} style={{ left: `${parcel.x}%`, top: `${parcel.y}%`, width: `${parcel.w}%`, height: `${parcel.h}%` }} onClick={() => setSelectedId(parcel.id)}><span>{parcel.id.replace('P-', '')}</span></button>)
              )}

              {!backendProjectId && !backendFeatures.length && <><div className="building-shape b1" /><div className="building-shape b2" /><div className="building-shape b3" /><div className="building-shape b4" /></>}
              <div className="map-tools-stack"><button onClick={() => setZoom((value) => Math.min(2.5, Number((value + 0.25).toFixed(2))))} title="Zoom in"><ZoomIn size={16} /></button><button onClick={() => setZoom((value) => Math.max(0.75, Number((value - 0.25).toFixed(2))))} title="Zoom out"><ZoomOut size={16} /></button><button onClick={() => setZoom(1)} title="Reset view">1×</button></div>
              <div className="map-scale">200 m</div>
              <div className="gis-legend"><span><i className="gis-legend-parcel" /> Candidate parcel</span><span><i className="gis-legend-review" /> Needs review</span><span><i className="gis-legend-building" /> Building</span>{editing && <span><i className="gis-legend-original" /> Original boundary</span>}</div>
              {backendMeta?.result?.parcel_mode ? <div className="map-status"><span className="status-live" /> Backend: {backendMeta.result.parcel_mode.replaceAll('-', ' ')}</div>
                : !backendProjectId ? <div className="map-status"><span className="status-preview" /> Layout preview · create a project to load live geometry</div> : null}
            </div>

            <aside className="parcel-inspector">
              <div className="inspector-head">
                <div><div className="section-kicker">PARCEL INSPECTOR</div><h3>{selectedDisplay.id}</h3></div>
                <div className="inspector-status-stack"><span className={`inspector-status ${String(selectedDisplay.status).toLowerCase()}`}>{selectedDisplay.status === 'Review' ? 'Needs review' : 'Candidate'}</span><span className={`verification-mini ${String(selectedDisplay.verificationStatus).toLowerCase()}`}>{selectedDisplay.verificationStatus}</span></div>
              </div>

              <div className="parcel-picker">
                <label htmlFor="parcel-select">Selected parcel</label>
                <select id="parcel-select" value={selectedDisplay.id === '—' ? '' : selectedDisplay.id} disabled={editing} onChange={(event) => { setSelectedId(event.target.value); setQuery(''); }}>
                  {actualParcels.map((parcel) => (
                    <option key={parcel.id} value={parcel.id}>{parcel.id} · {parcel.area}</option>
                  ))}
                </select>
                <span>{actualParcels.length} parcels available</span>
              </div>

              <div className="confidence-box">
                <div className="confidence-top"><span>Boundary confidence</span><strong>{selectedDisplay.confidence}%</strong></div>
                <div className="confidence-track"><div style={{ width: `${selectedDisplay.confidence}%` }} /></div>
                <p>{selectedDisplay.confidence < 70 ? 'Below verification threshold · routed to field review' : 'Within current confidence threshold'}</p>
              </div>

              <div className="inspector-stats">
                <div><span>Area</span><strong>{selectedDisplay.area}</strong></div>
                <div><span>Land use</span><strong>{selectedDisplay.landuse}</strong></div>
                <div><span>Buildings</span><strong>{selectedDisplay.buildingCount}</strong></div>
                <div><span>Field priority</span><strong>{selectedDisplay.fieldPriority}</strong></div>
                <div><span>Topology</span><strong className="ok">{backendMeta?.result?.topology_issue_count ? 'Review' : 'Valid'}</strong></div>
              </div>

              <div className="evidence-section">
                <div className="section-kicker">BOUNDARY EVIDENCE</div>
                {Object.entries(selectedDisplay.evidence || evidenceDefaults).map(([key, value]) => <div className="evidence-row" key={key}><span>{key.replaceAll('_', ' ')}</span><div className="evidence-bar"><i style={{ width: `${Math.min(Number(value) * 2, 100)}%` }} /></div><b>{Number(value).toFixed(0)}%</b></div>)}
              </div>

              {splitMode ? (
                <div className="editor-panel">
                  <div className="editor-panel-head"><div><div className="section-kicker">SPLIT TOOL</div><strong>Draw a cut line across {selectedDisplay.id}</strong></div><span>{splitPoints.length}/2 points</span></div>
                  <div className="split-instructions"><span className={splitPoints.length >= 1 ? 'done' : ''}>1. Click the first side</span><span className={splitPoints.length >= 2 ? 'done' : ''}>2. Click the opposite side</span><span>3. Apply split</span></div>
                  <label className="field-label compact">Split note<textarea rows="2" value={editNote} onChange={(event) => setEditNote(event.target.value)} placeholder="Why does this parcel need to be split?" /></label>
                  <div className="inspector-actions"><button className="secondary-button" onClick={cancelSplit} disabled={busy}><X size={15} /> Cancel</button><button className="primary-button" onClick={applySplit} disabled={busy || splitPoints.length !== 2}>{busy ? 'Splitting…' : 'Apply split'} <Save size={15} /></button></div>
                  <div className="field-note"><Target size={15} /><span>The cut is applied as a real polygon operation. New parcels return as review-required candidates and trigger topology + field-queue refresh.</span></div>
                </div>
              ) : mergeMode ? (
                <div className="editor-panel">
                  <div className="editor-panel-head"><div><div className="section-kicker">MERGE TOOL</div><strong>{mergeTargetId ? `Ready to merge ${selectedDisplay.id} + ${mergeTargetId}` : 'Choose a neighboring parcel'}</strong></div><span>{mergeTargetId ? '2 selected' : '1 selected'}</span></div>
                  <div className="merge-target-box">{mergeTargetId ? <><span>Primary</span><strong>{selectedDisplay.id}</strong><span>+</span><strong>{mergeTargetId}</strong></> : <span>Click another parcel on the map. The selected parcel stays as the primary record.</span>}</div>
                  <label className="field-label compact">Merge note<textarea rows="2" value={editNote} onChange={(event) => setEditNote(event.target.value)} placeholder="Why do these parcels form one survey unit?" /></label>
                  <div className="inspector-actions"><button className="secondary-button" onClick={stopMapModes} disabled={busy}><X size={15} /> Cancel</button><button className="primary-button" onClick={applyMerge} disabled={busy || !mergeTargetId}>{busy ? 'Merging…' : 'Merge parcels'} <Save size={15} /></button></div>
                  <div className="field-note"><Target size={15} /><span>Only contiguous polygons that form a single polygon are merged. Verification is reset to Pending so the new boundary is reviewed again.</span></div>
                </div>
              ) : editing ? (
                <div className="editor-panel">
                  <div className="editor-panel-head"><div><div className="section-kicker">VERTEX EDITOR</div><strong>Adjust boundary by coordinates</strong></div><span>{draftVertices.length} pts</span></div>
                  <div className="vertex-list">
                    {draftVertices.map((coordinate, index) => <button type="button" className={`vertex-row${activeVertex === index ? ' active' : ''}`} key={`row-${index}`} onClick={() => selectVertex(index)}><span className="vertex-index">{index + 1}</span><span>X {coordinate[0].toFixed(8)}</span><span>Y {coordinate[1].toFixed(8)}</span></button>)}
                  </div>
                  {activeVertex != null && draftVertices[activeVertex] && <div className="coordinate-editor">
                    <div className="coordinate-editor-head"><strong>Vertex {activeVertex + 1}</strong><span>Highlighted on map</span></div>
                    <div className="coordinate-grid">
                      <label className="field-label compact">X / Longitude<input inputMode="decimal" value={vertexXInput} onChange={(event) => setVertexXInput(event.target.value)} /></label>
                      <label className="field-label compact">Y / Latitude<input inputMode="decimal" value={vertexYInput} onChange={(event) => setVertexYInput(event.target.value)} /></label>
                    </div>
                    <button type="button" className="secondary-button wide-button" onClick={applyVertexCoordinate}>Apply coordinate to map</button>
                    <button type="button" className="text-button vertex-reset-button" onClick={() => {
                      const original = currentSelected?.geometry?.coordinates?.[0]?.[activeVertex];
                      if (original) commitVertexCoordinate(Number(original[0]), Number(original[1]));
                    }}>Restore original vertex</button>
                  </div>}
                  <label className="field-label compact">Edit note<textarea rows="2" value={editNote} onChange={(event) => setEditNote(event.target.value)} placeholder="Why was the boundary adjusted?" /></label>
                  <div className="inspector-actions"><button className="secondary-button" onClick={cancelEditing} disabled={busy}><X size={15} /> Cancel</button><button className="primary-button" onClick={saveBoundary} disabled={busy}>{busy ? 'Validating…' : 'Save & revalidate'} <Save size={15} /></button></div>
                  <div className="field-note"><Target size={15} /><span>Select a vertex from the list or map. Its coordinate callout appears on the image; edit X/Y to move it precisely. Save runs geometry validation, topology checks, confidence adjustment, and GT/GNSS comparison when those inputs are available.</span></div>
                </div>
              ) : (
                <>
                  {lastEdit && lastEdit.parcel_id === currentSelected?.id && <div className="validation-result-card"><div className="section-kicker">LAST REVALIDATION</div><div className="validation-result-title"><strong>{lastEdit.confidence_after}%</strong><span>adjusted confidence</span></div><div className="edit-metric-grid"><div><span>Max shift</span><strong>{lastEdit.metrics?.max_vertex_shift_m ?? 0} m</strong></div><div><span>Area delta</span><strong>{lastEdit.metrics?.area_delta_pct ?? 0}%</strong></div><div><span>GT IoU</span><strong>{gt?.iou != null ? `${Math.round(gt.iou * 100)}%` : '—'}</strong></div><div><span>GNSS</span><strong>{gnss?.nearest_boundary_m != null ? `${gnss.nearest_boundary_m} m` : '—'}</strong></div></div><p>{gt?.status === 'not_available' && gnss?.status === 'not_available' ? 'No GT/GNSS reference was supplied; geometry and topology checks still ran.' : 'Reference comparison updated from the available ground-truth and GNSS evidence.'}</p></div>}
                  <div className="inspector-actions"><button className="secondary-button" onClick={() => navigate('field')}><MapPinned size={15} /> Verify</button><button className="secondary-button" onClick={revalidate} disabled={!backendProjectId || busy}><RefreshCw size={15} /> Revalidate</button><button className="primary-button" onClick={startEditing} disabled={!canEdit}><Pencil size={15} /> Edit boundary</button></div>
                  {!backendProjectId && <div className="field-note"><TriangleAlert size={15} /><span>Editing is enabled after a real backend project has been processed.</span></div>}
                </>
              )}
            </aside>
          </div>

          {lastEdit && lastEdit.parcel_id === currentSelected?.id && <div className="map-insight-strip"><div className="map-insight-main"><RefreshCw size={16} /><div><strong>Parcel revalidated</strong><span>{lastEdit.geometry_valid ? 'Geometry is valid and downstream QC was refreshed.' : 'Geometry is invalid and remains in review.'}</span></div></div><div className="map-insight-stat"><span>Confidence</span><strong>{lastEdit.confidence_before}% → {lastEdit.confidence_after}%</strong></div><div className="map-insight-stat"><span>Topology issues</span><strong>{lastEdit.topology?.issue_count ?? 0}</strong></div><div className="map-insight-note">Reference comparisons inform review; they do not create a legal cadastral determination.</div></div>}

          {backendMeta?.result?.evidence_method && <div className="map-insight-strip"><div className="map-insight-main"><Target size={16} /><div><strong>Boundary evidence fused</strong><span>{backendMeta.result.evidence_method}</span></div></div><div className="map-insight-stat"><span>Avg. confidence</span><strong>{backendMeta.result.average_boundary_confidence ?? '—'}%</strong></div><div className="map-insight-stat"><span>Potential encroachments</span><strong>{backendMeta.result.potential_encroachment_count ?? 0}</strong></div><div className="map-insight-note">Indicators prioritize survey review; they are not legal determinations.</div></div>}
          {editHistory.length > 0 && <div className="map-history-strip"><div><span className="section-kicker">EDIT HISTORY</span><strong>{editHistory.length} recorded parcel edits</strong></div><div className="history-timeline">{editHistory.slice(-4).reverse().map((item, index) => <span key={`${item.edited_at}-${index}`}><b>{item.action}</b> · {item.parcel_id}{item.merged_parcel_id ? ` + ${item.merged_parcel_id}` : ''}{item.created_parcel_ids ? ` → ${item.created_parcel_ids.join(', ')}` : ''}</span>)}</div></div>}
          <div className="map-footer"><div><span>{filtered.length} visible parcels</span><span>·</span><span>{actualParcels.length} total candidate parcels</span><span>·</span><span>{backendMeta?.result?.topology_issue_count ?? 0} topology flags</span></div><span>CRS · {backendMeta?.result?.source_crs || 'EPSG:4326'}</span></div>
        </section>
      </main>
    </div>
  );
}
function Topology({ navigate }) {
  const { project } = useProjectContext();
  const projectId = project?.backendId || null;
  const [data, setData] = useState({ issues: [], summary: { total: 0, open: 0, resolved: 0, critical: 0 } });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = async (id) => {
    setLoading(true);
    try {
      const payload = await getTopologyIssues(id);
      setData(payload);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load topology issues.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (projectId) load(projectId); else setLoading(false); }, [projectId]);

  const resolve = async (issue) => {
    if (!projectId) return;
    setBusy(issue.issue_id);
    try {
      await resolveTopologyIssue(projectId, issue.issue_id, 'Reviewed in AeroCAD QC workspace.');
      await load(projectId);
    } catch (err) {
      setError(err.message || 'Could not resolve issue.');
    } finally {
      setBusy('');
    }
  };

  const openIssues = data.issues.filter(i => i.status !== 'Resolved');
  const resolvedCount = data.summary.resolved || data.issues.filter(i => i.status === 'Resolved').length;
  const healthBase = data.summary.total ? Math.max(0, ((data.summary.total - data.summary.open) / data.summary.total) * 100) : 100;

  return <div className="app-shell"><Sidebar screen="topology" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Topology quality control" /><section className="content">
    <div className="map-page-head"><div><div className="section-kicker">QUALITY CONTROL · LIVE BACKEND</div><h2>Geometry issues before verification</h2><p>These issues are loaded from the project's actual topology output. Resolution records a human review action; it does not silently rewrite legal boundaries.</p></div><button className="secondary-button" onClick={() => projectId && load(projectId)}><RefreshCw size={15} /> Refresh</button></div>
    <div className="qc-summary-grid">
      <SummaryCard label="Open issues" value={data.summary.open ?? 0} note="Needs attention" icon={ShieldCheck} tone="plum" />
      <SummaryCard label="Critical" value={data.summary.critical ?? 0} note="Highest review priority" icon={TriangleAlert} tone="sand" />
      <SummaryCard label="Resolved" value={resolvedCount} note="Human-reviewed" icon={CheckCheck} tone="olive" />
      <SummaryCard label="Resolution rate" value={`${healthBase.toFixed(0)}%`} note={loading ? 'Loading' : 'Current project'} icon={ClipboardCheck} tone="blue" />
    </div>
    {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}
    <section className="topology-table-card"><div className="table-head"><div><div className="section-kicker">ISSUE QUEUE</div><h3>{loading ? 'Loading topology results…' : `${openIssues.length} open issues`}</h3></div><span className="qc-note">Human approval required</span></div>
      <div className="qc-table">
        <div className="qc-row qc-head"><span>ISSUE</span><span>TYPE</span><span>PARCELS</span><span>OBSERVATION</span><span>PRIORITY</span><span>ACTION</span></div>
        {openIssues.length ? openIssues.map(issue => <div className="qc-row" key={issue.issue_id}><strong>{issue.issue_id}</strong><span className="issue-pill">{issue.type}</span><span>{issue.parcel_ids?.join(' · ') || 'Adjacent area'}</span><span>{issue.observation}<br /><small>{issue.suggestion}</small></span><span className={`priority-pill ${issue.priority.toLowerCase()}`}>{issue.priority}</span><button className="row-action" onClick={() => resolve(issue)} disabled={busy === issue.issue_id}>{busy === issue.issue_id ? 'Saving…' : 'Resolve'} <Check size={13} /></button></div>) : <div className="empty-state"><CheckCheck size={20} /><strong>{loading ? 'Connecting to backend' : 'No open topology issues'}</strong><span>{loading ? 'Reading topology.json and workflow state.' : 'All currently indexed issues have been reviewed.'}</span></div>}
      </div>
    </section>
    {resolvedCount > 0 && <div className="resolved-strip"><CheckCheck size={16} /><span><strong>{resolvedCount} human review action{resolvedCount > 1 ? 's' : ''} recorded.</strong> These are audit actions and can be revisited with the next validation run.</span></div>}
  </section></main></div>;
}

function FieldVerification({ navigate }) {
  const { project } = useProjectContext();
  const projectId = project?.backendId || null;
  const [data, setData] = useState({ queue: [], summary: { count: 0, critical: 0, high: 0, medium: 0, low: 0 } });
  const [selectedId, setSelectedId] = useState(null);
  const [outcome, setOutcome] = useState('verified');
  const [notes, setNotes] = useState('');
  const [gnssLat, setGnssLat] = useState('');
  const [gnssLon, setGnssLon] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedMessage, setSavedMessage] = useState('');

  const load = async (id) => {
    setLoading(true);
    try {
      const payload = await getFieldQueue(id);
      setData(payload);
      setSelectedId(prev => prev && payload.queue.some(q => q.parcel_id === prev) ? prev : payload.queue[0]?.parcel_id || null);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load field queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (projectId) load(projectId); else setLoading(false); }, [projectId]);

  const selected = data.queue.find(item => item.parcel_id === selectedId) || null;

  const onSelectParcel = (id) => {
    const item = data.queue.find(q => q.parcel_id === id);
    setSelectedId(id);
    setOutcome('');
    setNotes(item?.notes || '');
    setGnssLat('');
    setGnssLon('');
    setSavedMessage('');
    setError('');
  };

  const verify = async () => {
    if (!projectId || !selected) return;
    if (!outcome) {
      setError('Select a review outcome before recording the field decision.');
      return;
    }
    const trimmed = notes.trim();
    if (trimmed.length < 5) {
      setError('Add a brief field note before recording the outcome.');
      return;
    }
    if ((gnssLat === '') !== (gnssLon === '')) {
      setError('Enter both GNSS latitude and longitude, or leave both blank.');
      return;
    }
    setBusy(true);
    setError('');
    setSavedMessage('');
    try {
      const payload = await verifyParcel(projectId, selected.parcel_id, {
        method: 'Human field verification',
        outcome,
        notes: trimmed,
        gnss_lat: gnssLat === '' ? null : Number(gnssLat),
        gnss_lon: gnssLon === '' ? null : Number(gnssLon),
      });
      setSavedMessage(outcome === 'verified' ? 'Field verification recorded.' : 'Review outcome recorded and parcel remains in the queue.');
      setNotes(''); setGnssLat(''); setGnssLon('');
      setOutcome('');
      setData(payload.queue || data);
      setSelectedId(prev => (payload.queue || []).some(q => q.parcel_id === prev) ? prev : (payload.queue || [])[0]?.parcel_id || null);
    } catch (err) {
      setError(err.message || 'Could not record field outcome.');
    } finally {
      setBusy(false);
    }
  };

  const actionLabel = outcome === 'verified' ? 'Confirm parcel verified' : outcome === 'revisit' ? 'Record revisit required' : outcome === 'not_verified' ? 'Record not verified' : 'Select review outcome';

  return <div className="app-shell"><Sidebar screen="field" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Field verification queue" /><section className="content">
    <div className="map-page-head"><div><div className="section-kicker">SURVEYOR WORKFLOW · LIVE BACKEND</div><h2>Verify the uncertain parcels first</h2><p>Priority is derived from boundary confidence, topology issues and potential encroachment indicators.</p></div><button className="secondary-button" onClick={() => projectId && load(projectId)}><RefreshCw size={15} /> Refresh queue</button></div>
    <div className="field-summary-grid"><SummaryCard label="Awaiting verification" value={data.summary.count ?? 0} note="Open field tasks" icon={MapPinned} tone="sand" /><SummaryCard label="Critical" value={data.summary.critical ?? 0} note="Review first" icon={TriangleAlert} tone="plum" /><SummaryCard label="High" value={data.summary.high ?? 0} note="Boundary / topology" icon={Target} tone="blue" /><SummaryCard label="Medium" value={data.summary.medium ?? 0} note="Below target confidence" icon={ClipboardCheck} tone="olive" /></div>
    {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}
    {savedMessage && <div className="backend-success"><CheckCheck size={16} /><span>{savedMessage}</span></div>}
    <div className="field-layout">
      <section className="field-queue-card"><div className="table-head"><div><div className="section-kicker">TODAY'S QUEUE</div><h3>{loading ? 'Loading field tasks…' : `${data.queue.length} parcels awaiting verification`}</h3></div><span className="qc-note">Priority sorted</span></div>
        {data.queue.length ? data.queue.map((p, i) => <button className={`field-row ${selectedId === p.parcel_id ? 'selected' : ''}`} key={p.parcel_id} onClick={() => onSelectParcel(p.parcel_id)}><div className="priority-number">{String(i + 1).padStart(2, '0')}</div><div className="field-copy"><strong>{p.parcel_id}</strong><span>{p.land_use} · {Number(p.area).toFixed(1)} m²</span></div><div className="field-confidence"><span>Boundary confidence</span><b>{p.boundary_confidence}%</b></div><span className={`field-reason ${p.priority.toLowerCase()}`}>{p.reason}</span><ArrowRight size={16} /></button>) : <div className="empty-state"><CheckCheck size={20} /><strong>{loading ? 'Connecting to backend' : 'Queue is clear'}</strong><span>{loading ? 'Loading field priorities from the project.' : 'No unverified parcel currently meets the review rules.'}</span></div>}
      </section>
      <aside className="field-method-card">
        <div className="section-kicker">FIELD REVIEW</div>
        <h3>{selected ? `Review ${selected.parcel_id}` : 'Select a parcel'}</h3>
        {selected ? <>
          <div className="field-detail-grid"><div><span>Priority</span><strong>{selected.priority}</strong></div><div><span>Confidence</span><strong>{selected.boundary_confidence}%</strong></div><div><span>Topology flags</span><strong>{selected.topology_issue_count}</strong></div><div><span>Encroachment</span><strong>{selected.potential_encroachment ? 'Indicator' : 'None'}</strong></div></div>
          <label className="field-label compact">Review outcome<select className="field-select" value={outcome} onChange={e => setOutcome(e.target.value)}><option value="">Select outcome…</option><option value="verified">Confirmed in field</option><option value="revisit">Needs revisit / correction</option><option value="not_verified">Not verified</option></select></label>
          <label className="field-label compact">Verification notes<textarea rows="4" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Record what the surveyor confirmed in the field…" /></label>
          <div className="gnss-grid"><label className="field-label compact">GNSS latitude<input value={gnssLat} onChange={e => setGnssLat(e.target.value)} placeholder="Optional" /></label><label className="field-label compact">GNSS longitude<input value={gnssLon} onChange={e => setGnssLon(e.target.value)} placeholder="Optional" /></label></div>
          <button className="primary-button wide-button" onClick={verify} disabled={busy || !outcome}>{busy ? 'Saving field outcome…' : actionLabel} <CheckCheck size={16} /></button>
          <div className="field-note"><Target size={16} /><span>Every decision requires a note and is written to the verification audit log. GNSS coordinates are optional; when supplied, both latitude and longitude are stored with the record.</span></div>
        </> : <div className="field-note"><MapPinned size={16} /><span>Select an item from the queue to open its field review form.</span></div>}
      </aside>
    </div>
  </section></main></div>;
}

function Reports({ navigate }) {
  const { project } = useProjectContext();
  const [artifacts, setArtifacts] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(project.backendId));

  useEffect(() => {
    if (!project.backendId) { setLoading(false); return; }
    getArtifacts(project.backendId).then(setArtifacts).catch(err => setError(err.message || 'Could not load report data.')).finally(() => setLoading(false));
  }, [project.backendId]);

  const result = artifacts?.result;
  const outputs = artifacts?.available_outputs || [];
  const download = name => `${window.location.origin}/api/projects/${project.backendId}/outputs/${encodeURIComponent(name)}`;

  return <div className="app-shell"><Sidebar screen="reports" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Survey reports" /><section className="content">
    <div className="map-page-head"><div><div className="section-kicker">REPORTING · LIVE BACKEND</div><h2>Survey results and deliverables</h2><p>Summarize the current GeoAI run and access GIS-ready outputs for review.</p></div><button className="secondary-button" onClick={() => navigate('map')}><Map size={15} /> Open map</button></div>
    {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}
    {!project.backendId ? <div className="empty-state processing-empty"><FileOutput size={24} /><strong>No processed project selected</strong><span>Run a survey project first. The report workspace will populate from its backend outputs.</span><button className="primary-button" onClick={() => navigate('new-project')}>Start a project <ArrowRight size={16} /></button></div> : loading ? <div className="empty-state processing-empty"><CircleDashed size={22} /><strong>Loading report data</strong><span>Reading processing metrics and available GIS outputs.</span></div> : <>
      <div className="summary-grid"><SummaryCard label="Candidate parcels" value={result?.parcel_count ?? '—'} note="Current processing run" icon={Layers3} tone="sand" /><SummaryCard label="Buildings detected" value={result?.building_candidates ?? '—'} note="AI extraction" icon={Building2} tone="olive" /><SummaryCard label="Topology health" value={result?.topology_health != null ? `${result.topology_health}%` : '—'} note="Geometry QA" icon={ShieldCheck} tone="plum" /><SummaryCard label="Needs review" value={result?.review_parcels ?? '—'} note="Field verification" icon={MapPinned} tone="blue" /></div>
      <section className="readiness-strip">
        <div><div className="section-kicker">DELIVERY READINESS</div><h3>GIS package assembled from the current run</h3><p>Includes editable vector outputs plus validation, topology, field-queue and parcel-edit evidence.</p></div>
        <div className="readiness-checks"><span><Check size={14} /> GeoJSON</span><span><Check size={14} /> GeoPackage</span><span><Check size={14} /> Shapefile set</span><span><Check size={14} /> QC + audit records</span></div>
        {project.backendId && <a className="primary-button link-button" href={exportProject(project.backendId)} download><Download size={16} /> Download complete GIS package</a>}
      </section>
      <div className="report-layout"><section className="topology-table-card"><div className="table-head"><div><div className="section-kicker">GIS DELIVERABLES</div><h3>Available outputs</h3></div><span className="qc-note">Backend generated</span></div><div className="check-list">{outputs.map(name => <div className="check-row" key={name}><div className="check-icon"><FileOutput size={16} /></div><div><strong>{name}</strong><span>Generated by the current processing run</span></div><a className="row-action link-button" href={download(name)} target="_blank" rel="noreferrer">Open <ArrowUpRight size={13} /></a></div>)}</div></section><aside className="dataset-summary"><div className="section-kicker">RUN SUMMARY</div><h3>{result?.parcel_mode ? result.parcel_mode.replaceAll('-', ' ') : 'GeoAI extraction'}</h3><div className="summary-line"><span>Source CRS</span><strong>{result?.source_crs || 'Unknown'}</strong></div><div className="summary-line"><span>Boundary evidence</span><strong>{result?.evidence_method ? 'Fused' : 'Available'}</strong></div><div className="summary-line"><span>Potential review flags</span><strong>{result?.potential_encroachment_count ?? 0}</strong></div><div className="summary-rule" /><div className="dataset-callout"><ShieldCheck size={17} /><div><strong>Preliminary cadastral output</strong><span>Review, correct and verify before treating the dataset as final survey evidence.</span></div></div><div className="dataset-callout"><Target size={17} /><div><strong>Reference evidence</strong><span>{project.files?.gt?.name ? `GT: ${project.files.gt.name}` : 'GT not supplied'} · {project.files?.gnss?.name ? `GNSS: ${project.files.gnss.name}` : 'GNSS not supplied'}</span></div></div></aside></div>
    </>}
  </section></main></div>;
}

function Projects({ navigate, project, setProject }) {
  const { startNewProject, selectProject } = useProjectContext();
  const [remoteProjects, setRemoteProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [deleting, setDeleting] = useState(null);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const payload = await listProjects();
      setRemoteProjects(payload.projects || []);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load backend projects.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadProjects(); }, [project?.backendId]);

  const filteredProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    return remoteProjects.filter(item => {
      const matchesQuery = !q || `${item.name} ${item.zone || ''} ${item.source || ''}`.toLowerCase().includes(q);
      let normalized = item.status || 'Draft';
      if (normalized === 'Validated') normalized = 'Ready';
      if (normalized === 'Processed') normalized = 'Processed';
      const matchesStatus = statusFilter === 'All' || normalized === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [remoteProjects, query, statusFilter]);

  const counts = useMemo(() => ({
    total: remoteProjects.length,
    processed: remoteProjects.filter(p => p.status === 'Processed').length,
    ready: remoteProjects.filter(p => p.status === 'Validated').length,
    attention: remoteProjects.filter(p => p.status === 'Error').length,
  }), [remoteProjects]);

  const activateProject = async (item) => {
    try {
      const detail = await getProject(item.id);
      const fileMeta = Object.fromEntries((detail.inputs || []).map(record => [
        record.key,
        {
          name: record.filename,
          size: record.metadata?.size_bytes || 0,
          type: record.metadata?.kind || '',
          persisted: true,
        },
      ]));
      setProject(prev => ({
        ...prev,
        name: detail.name || item.name,
        zone: detail.zone || item.zone || '',
        status: detail.status || item.status || 'Draft',
        backendId: detail.id || item.id,
        files: Object.keys(fileMeta).length ? fileMeta : prev.files,
      }));
      if (detail.status === 'Processed') navigate('map');
      else if (detail.status === 'Processing' || detail.status === 'Validated') navigate('processing');
      else navigate('new-project');
    } catch (err) {
      setError(err.message || 'Could not open project.');
    }
  };

  const removeProject = async (item) => {
    if (!String(item.name || '').startsWith('AeroCAD Project ')) return;
    const ok = window.confirm(`Remove ${item.name}? This deletes the persisted validation record and uploaded files.`);
    if (!ok) return;
    setDeleting(item.id);
    try {
      await deleteProject(item.id);
      if (project?.backendId === item.id) {
        startNewProject();
        navigate('projects');
      }
      await loadProjects();
    } catch (err) {
      setError(err.message || 'Could not remove project.');
    } finally {
      setDeleting(null);
    }
  };

  const statusClass = status => {
    const value = String(status || 'Draft').toLowerCase().replaceAll(' ', '-');
    if (value === 'processed') return 'verified';
    if (value === 'validated') return 'ready';
    return value;
  };

  const statusLabel = status => status === 'Validated' ? 'Ready to process' : status;

  return <div className="app-shell"><Sidebar screen="projects" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Projects" /><section className="content">
    <div className="page-intro project-page-intro"><div><div className="section-kicker">SURVEY PROJECT REGISTER</div><h2>Real survey workspaces</h2><p>Manage persisted cadastral survey runs, review their health, and open the workspace for the next survey action.</p></div><div className="topbar-actions"><button className="secondary-button" onClick={loadProjects}><RefreshCw size={15} /> Refresh</button><button className="primary-button" onClick={() => { startNewProject(); navigate('new-project'); }}><Plus size={17} /> New project</button></div></div>
    <div className="project-kpi-grid">
      <SummaryCard label="Survey projects" value={counts.total} note="Server persisted" icon={FolderOpen} tone="sand" />
      <SummaryCard label="Processed" value={counts.processed} note="Ready for review / export" icon={CheckCheck} tone="olive" />
      <SummaryCard label="Ready to process" value={counts.ready} note="Validated inputs" icon={Sparkles} tone="blue" />
      <SummaryCard label="Needs attention" value={counts.attention} note="Runs with errors" icon={TriangleAlert} tone="plum" />
    </div>
    {error && <div className="backend-error"><TriangleAlert size={16} /><span>{error}</span></div>}
    <section className="project-register-card">
      <div className="project-register-head"><div><div className="section-kicker">BACKEND PROJECT REGISTRY</div><h3>{loading ? 'Loading survey projects…' : `${filteredProjects.length} visible of ${remoteProjects.length} project${remoteProjects.length === 1 ? '' : 's'}`}</h3></div><span className="qc-note">No static demo projects</span></div>
      <div className="project-register-controls"><label className="project-search"><Search size={15} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search project, village, mandal or district" />{query && <button onClick={() => setQuery('')} aria-label="Clear search"><X size={13} /></button>}</label><div className="project-filter-group">{['All', 'Processed', 'Ready', 'Processing', 'Error'].map(filter => <button key={filter} className={statusFilter === filter ? 'active' : ''} onClick={() => setStatusFilter(filter)}>{filter}</button>)}</div></div>
      {!loading && remoteProjects.length === 0 ? <div className="empty-state"><FolderOpen size={21} /><strong>No persisted survey projects yet</strong><span>Start a new project and validate its ORI + DSM inputs to create the first survey record.</span><button className="primary-button" onClick={() => { startNewProject(); navigate('new-project'); }}>Create survey project <ArrowRight size={15} /></button></div> : !loading && filteredProjects.length === 0 ? <div className="empty-state project-filter-empty"><Search size={20} /><strong>No projects match this filter</strong><span>Try a different status or search term.</span></div> : <div className="project-register-table">
        <div className="registry-header"><span>PROJECT</span><span>SURVEY DATA</span><span>HEALTH</span><span>STATUS</span><span>ACTION</span></div>
        {filteredProjects.map(item => {
          const anonymous = String(item.name || '').startsWith('AeroCAD Project ');
          const parcelCount = item.result?.parcel_count ?? item.parcel_count ?? '—';
          const health = item.result?.topology_health;
          const healthLabel = health != null ? `${health}% QC` : item.status === 'Validated' ? 'Validated' : item.status;
          const inputCount = item.input_count ?? item.inputs?.length ?? 0;
          const featureNote = item.result ? `${item.result.building_candidates ?? 0} buildings · ${item.result.road_candidates ?? 0} roads` : `${inputCount} inputs ready`;
          return <div className={`registry-row ${item.id === project?.backendId ? 'active' : ''} ${anonymous ? 'legacy-row' : ''}`} key={item.id}>
            <div className="registry-project"><div className="project-icon"><Map size={17} /></div><div><div className="project-name">{item.name}</div><div className="project-meta">{item.zone || 'Survey zone not specified'}{item.source ? ` · ${item.source}` : ''}</div></div></div>
            <div className="registry-data"><strong>{parcelCount} parcels</strong><span>{featureNote}</span></div>
            <div className="registry-health"><div className="progress-track"><div className={`progress-fill ${statusClass(item.status)}`} style={{ width: health != null ? `${Math.min(100, Math.max(0, Number(health)))}%` : item.status === 'Validated' ? '35%' : item.status === 'Processing' ? '65%' : item.status === 'Error' ? '12%' : '8%' }} /></div><span>{healthLabel}</span></div>
            <span className={`status-chip ${statusClass(item.status)}`}>{statusLabel(item.status)}</span>
            <div className="registry-actions"><button className="row-action" onClick={() => activateProject(item)}>{item.status === 'Processed' ? 'Open' : item.status === 'Error' ? 'Review' : 'Continue'} <ArrowRight size={14} /></button>{anonymous && <button className="icon-danger" onClick={() => removeProject(item)} disabled={deleting === item.id} title="Remove legacy placeholder project" aria-label="Remove legacy placeholder project">{deleting === item.id ? <CircleDashed size={14} /> : <Trash2 size={14} />}</button>}</div>
          </div>;
        })}
      </div>}
    </section>
    <section className="project-register-note"><ShieldCheck size={17} /><div><strong>Survey register rule</strong><span>Only server-persisted workspaces appear here. Candidate geometry remains preliminary until GIS quality checks and surveyor verification are complete.</span></div></section>
  </section></main></div>;
}

function SettingsPage({ navigate, onSignOut }) {
  const { project, remoteProjects } = useProjectContext();
  const active = remoteProjects.find(item => item.id === project?.backendId);
  return <div className="app-shell"><Sidebar screen="settings" navigate={navigate} /><main className="main"><Topbar navigate={navigate} title="Workspace settings" /><section className="content">
    <div className="map-page-head"><div><div className="section-kicker">WORKSPACE CONFIGURATION</div><h2>Survey workspace settings</h2><p>Review the active project context and the rules that guide the AeroCAD review workflow.</p></div><button className="secondary-button" onClick={() => navigate('projects')}>Back to projects <ArrowRight size={15} /></button></div>
    <div className="settings-grid">
      <section className="settings-card account-access-card"><div className="section-kicker">ACCOUNT & ACCESS</div><h3>Workspace account</h3>
        <div className="settings-account-row"><div className="avatar account-avatar">HM</div><div><strong>{localStorage.getItem('aerocad_user') || 'Survey Workspace Admin'}</strong><span>Administrator · Prototype session</span></div></div>
        <div className="settings-line"><span>Session</span><strong>Signed in</strong></div>
        <div className="settings-line"><span>Access level</span><strong>Admin</strong></div>
        <button className="secondary-button settings-wide signout-button" onClick={onSignOut}>Sign out</button>
      </section>
      <section className="settings-card"><div className="section-kicker">ACTIVE CONTEXT</div><h3>{project?.name || 'No project selected'}</h3>
        <div className="settings-line"><span>Status</span><strong>{project?.status || '—'}</strong></div>
        <div className="settings-line"><span>Survey zone</span><strong>{project?.zone || '—'}</strong></div>
        <div className="settings-line"><span>Backend ID</span><strong>{project?.backendId || '—'}</strong></div>
      </section>
      <section className="settings-card"><div className="section-kicker">REVIEW POLICY</div><h3>Human approval gates</h3>
        <div className="settings-policy"><Check size={15} /><div><strong>Candidate geometry is preliminary</strong><span>AI output stays reviewable until GIS QC and survey verification are complete.</span></div></div>
        <div className="settings-policy"><Check size={15} /><div><strong>Field verification remains explicit</strong><span>A parcel is not treated as field-confirmed without an intentional survey decision.</span></div></div>
        <div className="settings-policy"><Check size={15} /><div><strong>Edits trigger revalidation</strong><span>Boundary changes should flow through geometry, topology and confidence checks.</span></div></div>
      </section>
      <section className="settings-card"><div className="section-kicker">DATA WORKSPACE</div><h3>Project register</h3>
        <div className="settings-line"><span>Server-persisted projects</span><strong>{remoteProjects.length}</strong></div>
        <div className="settings-line"><span>Active record</span><strong>{active?.name || 'None selected'}</strong></div>
        <button className="secondary-button settings-wide" onClick={() => navigate('projects')}><FolderOpen size={15} /> Open survey register</button>
      </section>
    </div>
  </section></main></div>;
}


function LoginPage({ onSignIn }) {
  const [email, setEmail] = useState(() => localStorage.getItem('aerocad_user') || '');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const submit = (event) => {
    event.preventDefault();
    const cleanEmail = email.trim();
    if (!cleanEmail || !password.trim()) {
      setError('Enter your workspace email and password.');
      return;
    }
    setError('');
    onSignIn(cleanEmail);
  };

  return <div className="login-shell">
    <div className="login-card">
      <div className="login-brand"><Logo /></div>
      <div className="section-kicker">SURVEY WORKSPACE ACCESS</div>
      <h1>Sign in to AeroCAD</h1>
      <p className="login-copy">Access persisted survey projects, GeoAI processing runs and the cadastral review workspace.</p>
      <form className="login-form" onSubmit={submit}>
        <label className="field-label">Workspace email<input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="surveyor@example.gov" autoComplete="username" /></label>
        <label className="field-label">Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Enter password" autoComplete="current-password" /></label>
        {error && <div className="backend-error login-error"><TriangleAlert size={15} /><span>{error}</span></div>}
        <button className="primary-button login-button" type="submit">Sign in <ArrowRight size={16} /></button>
      </form>
      <div className="login-demo-note"><ShieldCheck size={15} /><div><strong>Prototype access</strong><span>This build uses a local browser session for the prototype. Connect a real identity provider before production deployment.</span></div></div>
    </div>
  </div>;
}
function App() {
  const [screen, setScreen] = useState(() => window.location.hash.replace('#/', '') || 'dashboard');
  const [authenticated, setAuthenticated] = useState(() => localStorage.getItem('aerocad_session') !== 'signed_out');
  const [project, setProject] = useState(() => readSavedProject() || initialProject);
  const [remoteProjects, setRemoteProjects] = useState([]);
  const [projectLoading, setProjectLoading] = useState(true);
  const navigate = next => { setScreen(next); window.location.hash = `/${next}`; window.scrollTo({ top: 0, behavior: 'smooth' }); };

  useEffect(() => {
    const onHash = () => setScreen(window.location.hash.replace('#/', '') || 'dashboard');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const signIn = (email) => {
    localStorage.setItem('aerocad_session', 'active');
    localStorage.setItem('aerocad_user', email);
    setAuthenticated(true);
    navigate('dashboard');
  };

  const signOut = () => {
    localStorage.setItem('aerocad_session', 'signed_out');
    setAuthenticated(false);
    navigate('login');
  };

  useEffect(() => {
    if (!authenticated && screen !== 'login') {
      setScreen('login');
      window.location.hash = '/login';
    }
  }, [authenticated, screen]);

  useEffect(() => {
    try {
      const persistedFiles = Object.fromEntries(Object.entries(project.files || {}).map(([key, file]) => [key, {
        name: file?.name || 'Stored input',
        size: Number(file?.size || 0),
        type: file?.type || '',
        persisted: true,
      }]));
      localStorage.setItem('aerocad_project', JSON.stringify({ ...project, files: persistedFiles }));
    } catch {}
  }, [project]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setProjectLoading(true);
      try {
        const payload = await listProjects();
        if (!cancelled) setRemoteProjects(payload.projects || []);
      } catch {
        if (!cancelled) setRemoteProjects([]);
      } finally {
        if (!cancelled) setProjectLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const saved = readSavedProject();
      if (!saved?.backendId) return;
      try {
        const remote = await getProject(saved.backendId);
        if (cancelled) return;
        const fileMeta = Object.fromEntries((remote.inputs || []).map(record => [
          record.key,
          { name: record.filename, size: record.metadata?.size_bytes || 0, type: record.metadata?.kind || '', persisted: true },
        ]));
        setProject(prev => ({
          ...prev,
          name: saved.name && !saved.name.startsWith('AeroCAD Project ') ? saved.name : (remote.name || prev.name),
          zone: saved.zone || remote.zone || prev.zone,
          status: remote.status || prev.status,
          backendId: remote.id || prev.backendId,
          files: Object.keys(prev.files || {}).length && Object.values(prev.files || {}).some(file => file?.name) ? prev.files : fileMeta,
        }));
      } catch {
        // Keep the local snapshot if the backend is temporarily unavailable.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const selectProject = async (projectId) => {
    if (!projectId || projectId === project.backendId) return;
    try {
      const detail = await getProject(projectId);
      const fileMeta = Object.fromEntries((detail.inputs || []).map(record => [
        record.key,
        { name: record.filename, size: record.metadata?.size_bytes || 0, type: record.metadata?.kind || '', persisted: true },
      ]));
      const nextProject = {
        ...initialProject,
        name: detail.name || 'AeroCAD Project',
        zone: detail.zone || '',
        status: detail.status || 'Draft',
        backendId: detail.id || projectId,
        files: fileMeta,
      };
      setProject(nextProject);
      if (screen === 'new-project' || screen === 'validation') navigate(detail.status === 'Processed' ? 'map' : detail.status === 'Processing' ? 'processing' : 'new-project');
    } catch (err) {
      // The current project remains active when another project cannot be loaded.
    }
  };

  const startNewProject = () => {
    setProject(initialProject);
    try { localStorage.removeItem('aerocad_project'); } catch {}
  };

  const contextValue = { project, setProject, remoteProjects, projectLoading, selectProject, startNewProject };

  const content = screen === 'new-project' ? <NewProject navigate={navigate} project={project} setProject={setProject} />
    : screen === 'validation' ? <Validation navigate={navigate} project={project} setProject={setProject} />
    : screen === 'processing' ? <Processing navigate={navigate} project={project} setProject={setProject} />
    : screen === 'map' ? <MapWorkspace navigate={navigate} />
    : screen === 'topology' ? <Topology navigate={navigate} />
    : screen === 'field' ? <FieldVerification navigate={navigate} />
    : screen === 'reports' ? <Reports navigate={navigate} />
    : screen === 'settings' ? <SettingsPage navigate={navigate} onSignOut={signOut} />
    : screen === 'projects' ? <Projects navigate={navigate} project={project} setProject={setProject} />
    : <Dashboard navigate={navigate} />;

  if (!authenticated) return <LoginPage onSignIn={signIn} />;
  return <ProjectContext.Provider value={contextValue}>{content}</ProjectContext.Provider>;
}

createRoot(document.getElementById('root')).render(<App />);
