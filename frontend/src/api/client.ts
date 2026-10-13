import type {
  Alert,
  AnalysisCameraRow,
  AnalysisCycleDetail,
  AnalysisCycleRow,
  AnalysisSummary,
  AnalyzerInfo,
  Camera,
  CameraInput,
  CycleRecord,
  Health,
  Heatmap,
  Line,
  LineAnalytics,
  LineInput,
  LineSetupInput,
  LineSetupResult,
  MovementRow,
  ProbeResult,
  ReportRow,
  ReportStatus,
  Overview,
  RangeKey,
  Station,
  StationAnalytics,
  StationInput,
  StationLive,
  Track,
} from './types';

// In dev, Vite proxies /api and /ws to the backend (see vite.config.ts).
// In production the backend serves the built frontend, so relative URLs work too.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return p.length ? '?' + p.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&') : '';
};

export const api = {
  health: () => request<Health>('GET', '/api/health'),
  overview: (range: RangeKey) => request<Overview>('GET', `/api/overview${qs({ range })}`),
  live: () => request<StationLive[]>('GET', '/api/live'),

  // Lines
  lines: () => request<Line[]>('GET', '/api/lines'),
  line: (id: number) => request<Line>('GET', `/api/lines/${id}`),
  createLine: (data: LineInput) => request<Line>('POST', '/api/lines', data),
  updateLine: (id: number, data: Partial<LineInput>) => request<Line>('PUT', `/api/lines/${id}`, data),
  deleteLine: (id: number) => request<void>('DELETE', `/api/lines/${id}`),
  lineAnalytics: (id: number, range: RangeKey) => request<LineAnalytics>('GET', `/api/lines/${id}/analytics${qs({ range })}`),
  reorderStations: (lineId: number, stationIds: number[]) =>
    request<Station[]>('POST', `/api/lines/${lineId}/stations/reorder`, { station_ids: stationIds }),

  // Stations (process steps)
  stations: (lineId?: number) => request<Station[]>('GET', `/api/stations${qs({ line_id: lineId })}`),
  station: (id: number) => request<Station>('GET', `/api/stations/${id}`),
  createStation: (data: StationInput) => request<Station>('POST', '/api/stations', data),
  updateStation: (id: number, data: Partial<StationInput>) => request<Station>('PUT', `/api/stations/${id}`, data),
  deleteStation: (id: number) => request<void>('DELETE', `/api/stations/${id}`),
  stationAnalytics: (id: number, range: RangeKey) =>
    request<StationAnalytics>('GET', `/api/stations/${id}/analytics${qs({ range })}`),
  stationCycles: (id: number, range: RangeKey, limit = 50) =>
    request<CycleRecord[]>('GET', `/api/stations/${id}/cycles${qs({ range, limit })}`),
  addManualCycle: (id: number, data: { cycle_sec: number; work_sec?: number; wait_sec?: number; motion_waste_sec?: number }) =>
    request<CycleRecord>('POST', `/api/stations/${id}/cycles`, data),

  // Cameras
  cameras: (lineId?: number) => request<Camera[]>('GET', `/api/cameras${qs({ line_id: lineId })}`),
  camera: (id: number) => request<Camera>('GET', `/api/cameras/${id}`),
  createCamera: (data: CameraInput) => request<Camera>('POST', '/api/cameras', data),
  updateCamera: (id: number, data: Partial<CameraInput>) => request<Camera>('PUT', `/api/cameras/${id}`, data),
  deleteCamera: (id: number) => request<void>('DELETE', `/api/cameras/${id}`),
  restartCamera: (id: number) => request<Camera>('POST', `/api/cameras/${id}/restart`),
  captureReference: (id: number) => request<Camera>('POST', `/api/cameras/${id}/reference`),
  heatmap: (id: number, range: RangeKey) => request<Heatmap>('GET', `/api/cameras/${id}/heatmap${qs({ range })}`),
  tracks: (id: number, limit = 10) => request<Track[]>('GET', `/api/cameras/${id}/tracks${qs({ limit })}`),
  analyzers: () => request<AnalyzerInfo[]>('GET', '/api/analyzers'),

  // Live video URLs (use directly in <img src>)
  streamUrl: (id: number, overlay = true) => `${BASE}/api/cameras/${id}/stream.mjpg${qs({ overlay: overlay ? 1 : 0 })}`,
  snapshotUrl: (id: number, overlay = false) =>
    `${BASE}/api/cameras/${id}/snapshot.jpg${qs({ overlay: overlay ? 1 : 0, t: Date.now() })}`,

  // Movement / waste analysis
  movement: (range: RangeKey, lineId?: number) => request<MovementRow[]>('GET', `/api/movement${qs({ range, line_id: lineId })}`),

  // Alerts
  alerts: (status: 'open' | 'all' = 'open', limit = 100) => request<Alert[]>('GET', `/api/alerts${qs({ status, limit })}`),
  ackAlert: (id: number) => request<Alert>('POST', `/api/alerts/${id}/ack`),
  ackAllAlerts: () => request<{ acknowledged: number }>('POST', '/api/alerts/ack-all'),

  // Simple setup: check a camera address, save a whole line (steps + cameras) and go live
  probeCamera: (address: string, username = '', password = '') =>
    request<ProbeResult>('POST', '/api/cameras/probe', { address, username, password }),
  saveLineSetup: (data: LineSetupInput) => request<LineSetupResult>('POST', '/api/setup/line', data),

  // Cycle / element analysis
  analysisCameras: () => request<AnalysisCameraRow[]>('GET', '/api/analysis/overview'),
  analysisSummary: (cameraId: number) => request<AnalysisSummary>('GET', `/api/analysis/cameras/${cameraId}`),
  setRecording: (cameraId: number, on: boolean, processFps?: number) =>
    request<{ recording: boolean; process_fps: number }>('POST', `/api/analysis/cameras/${cameraId}/record`, { on, process_fps: processFps ?? null }),
  learnElements: (cameraId: number, minutes = 60) =>
    request<{ elements: number; cycles: number }>('POST', `/api/analysis/cameras/${cameraId}/learn`, { minutes }),
  analyzeNow: (cameraId: number) => request<{ new_cycles: number }>('POST', `/api/analysis/cameras/${cameraId}/analyze`),
  renameElement: (cameraId: number, elementId: number, name: string) =>
    request<{ ok: boolean }>('PUT', `/api/analysis/cameras/${cameraId}/elements/${elementId}`, { name }),
  setCycleStart: (cameraId: number, elementId: number) =>
    request<{ ok: boolean }>('PUT', `/api/analysis/cameras/${cameraId}/cycle-start`, { element_id: elementId }),
  clearMaster: (cameraId: number) => request<{ ok: boolean }>('DELETE', `/api/analysis/cameras/${cameraId}/master`),
  analysisCycles: (cameraId: number, status: 'all' | 'issues' | 'ok' = 'all', limit = 300) =>
    request<AnalysisCycleRow[]>('GET', `/api/analysis/cameras/${cameraId}/cycles${qs({ status, limit })}`),
  analysisCycle: (cycleId: number) => request<AnalysisCycleDetail>('GET', `/api/analysis/cycles/${cycleId}`),
  setMaster: (cycleId: number) => request<{ ok: boolean }>('POST', `/api/analysis/cycles/${cycleId}/master`),
  cycleClipUrl: (cycleId: number) => `${BASE}/api/analysis/cycles/${cycleId}/clip.webm`,
  elementThumbUrl: (cameraId: number, elementId: number, version: number) =>
    `${BASE}/api/analysis/cameras/${cameraId}/elements/${elementId}/thumb.jpg${qs({ v: version })}`,

  // Saved breakup reports
  reports: () => request<ReportRow[]>('GET', '/api/reports'),
  reportStatus: () => request<ReportStatus>('GET', '/api/reports/status'),
  generateReport: (cameraId: number) => request<ReportStatus>('POST', `/api/reports/generate/${cameraId}`),
  reportUrl: (name: string) => `${BASE}/api/reports/${encodeURIComponent(name)}/`,

  // Export / system
  exportCyclesUrl: (range: RangeKey, lineId?: number, stationId?: number) =>
    `${BASE}/api/export/cycles.csv${qs({ range, line_id: lineId, station_id: stationId })}`,
  clearData: () => request<{ deleted: number }>('POST', '/api/system/clear-data'),
};

export function wsUrl(path = '/ws/live'): string {
  if (BASE) return BASE.replace(/^http/, 'ws') + path;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}
