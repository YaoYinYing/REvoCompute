import type { components } from './schema.generated';
import type { ArtifactRole, LogicalResultFile, PreviewCapability, ResultArtifact, ResultFile, ResultManifest, ResultStoryboardDeclaration, ResultView, TaskStatus } from './result-types';
import { resultFileName } from './result-types';
import { ApiError, authorizedJson } from '../app/session';
import { t } from '../app/i18n';
export { ApiError } from '../app/session';

async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'same-origin' });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(String(payload.message || payload.error || `Request failed (HTTP ${response.status})`), response.status);
  }
  return payload as T;
}

const ROLES = new Set<ArtifactRole>(['primary', 'evidence', 'provenance', 'diagnostic', 'artifact']);
const CAPABILITIES = new Set<PreviewCapability>([
  'structure', 'molecular_structure', 'table', 'plot', 'image', 'text', 'archive', 'download_only', 'unknown',
]);
const VIEW_PLUGINS = new Set<ResultView['plugin']>(['structure', 'candidate-collection', 'entity-table', 'evidence-bundle', 'alignment', 'trajectory', 'metric-series', 'matrix', 'scalar-summary']);
const VIEW_ROLES = new Set<ResultView['role']>(['primary', 'evidence']);
const VALIDATION_KEY = 'results.invalid.manifest';
/*
 * Every parse fault the Result manifest projection can raise, as a catalog key.
 *
 * A fault is a frontend-authored response *frame*. The only interpolated value
 * is the server's own projected vocabulary — an artifact name or logical-file id
 * — which is emitted verbatim (§11) and never translated. Field-shape faults
 * share one frame rather than naming an internal field, so no developer jargon
 * reaches a reader in either locale.
 */
const FAULT = {
  role: 'results.fault.role',
  size: 'results.fault.size',
  view: 'results.fault.view',
  logicalFile: 'results.fault.logicalFile',
  logicalCardinality: 'results.fault.logicalCardinality',
  logicalSize: 'results.fault.logicalSize',
  resultFiles: 'results.fault.resultFiles',
  schema: 'results.fault.schema',
  views: 'results.fault.views',
  totalSize: 'results.fault.totalSize',
} as const;
type Fault = keyof typeof FAULT;

/** One localized parse fault; `value` is a server projection and stays verbatim. */
function fault(kind: Fault, value?: string): Error {
  return new Error(value === undefined ? t(FAULT[kind]) : t(FAULT[kind], { value }));
}
/** The single frame every field-shape fault shares, so no field name surfaces. */
function malformed(): Error { return new Error(t(VALIDATION_KEY)); }

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw malformed();
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== 'string') throw malformed(); return value;
}
function optionalString(value: unknown): string | undefined {
  return value == null ? undefined : string(value);
}
function stringArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) throw malformed();
  return [...value];
}
function artifact(value: unknown): ResultArtifact {
  const item = record(value); const role = string(item.role) as ArtifactRole;
  if (!ROLES.has(role)) throw fault('role');
  const declared = item.capability ?? item.preview; let capability: PreviewCapability = 'unknown';
  if (declared != null) {
    if (typeof declared === 'string' && CAPABILITIES.has(declared as PreviewCapability)) capability = declared as PreviewCapability;
  }
  const size = Number(item.size); if (!Number.isFinite(size) || size < 0) throw fault('size');
  return {
    path: string(item.path), name: optionalString(item.name),
    media_type: string(item.media_type), size, sha256: string(item.sha256),
    role, preview: item.preview === null ? null : capability === 'structure' || capability === 'image' || capability === 'table' || capability === 'text' ? capability : null,
    capability: capability === 'structure' ? 'molecular_structure' : capability,
    confidence_encoding: item.confidence_encoding === 'plddt_bfactor' ? 'plddt_bfactor' : undefined,
    url: string(item.url), ndarray_url: optionalString(item.ndarray_url),
    table_url: optionalString(item.table_url), cardinality: item.cardinality === 'many' ? 'many' : 'one',
    id: optionalString(item.id),
  };
}

function view(value: unknown): ResultView {
  const item = record(value); const rawSources = record(item.sources);
  const sources: Record<string, string[]> = {};
  Object.entries(rawSources).forEach(([key, paths]) => { sources[key] = stringArray(paths); });
  const plugin = string(item.plugin) as ResultView['plugin'];
  const role = string(item.role) as ResultView['role'];
  if (!VIEW_PLUGINS.has(plugin) || !VIEW_ROLES.has(role)) throw fault('view');
  return { id: string(item.id), plugin, title: string(item.title), role,
    description: optionalString(item.description) || '', sources,
    mapping: item.mapping == null ? {} : record(item.mapping) };
}

function storyboard(value: unknown): ResultStoryboardDeclaration | null {
  if (value == null) return null; const item = record(value);
  return { identifier: string(item.identifier), entrypoint: string(item.entrypoint), entrypoint_url: string(item.entrypoint_url), requires: stringArray(item.requires), optional: stringArray(item.optional) };
}
function logicalFile(value: unknown): LogicalResultFile {
  const item = record(value), role = string(item.role) as ArtifactRole;
  const capability = string(item.capability) as PreviewCapability;
  if (!ROLES.has(role) || !CAPABILITIES.has(capability)) throw fault('logicalFile');
  const cardinality = string(item.cardinality); if (cardinality !== 'one' && cardinality !== 'many') throw fault('logicalCardinality');
  const size = Number(item.size); if (!Number.isFinite(size) || size < 0) throw fault('logicalSize');
  return { id: string(item.id), name: string(item.name), path: string(item.path), media_type: string(item.media_type),
    size, role, cardinality, viewer: string(item.viewer), preview: item.preview == null ? null : string(item.preview),
    capability: capability === 'structure' ? 'molecular_structure' : capability, url: string(item.url),
    confidence_encoding: item.confidence_encoding === 'plddt_bfactor' ? 'plddt_bfactor' : undefined,
    table_url: optionalString(item.table_url), ndarray_url: optionalString(item.ndarray_url) };
}
function resultFiles(value: unknown): ResultManifest['result'] {
  const result = record(value), rawFiles = record(result.files), files: Record<string, LogicalResultFile[]> = {};
  Object.entries(rawFiles).forEach(([id, entries]) => { if (!Array.isArray(entries)) throw fault('resultFiles', id); files[id] = entries.map(logicalFile); });
  return { files };
}

export function parseResultManifest(value: unknown): ResultManifest | TaskStatus {
  const payload = record(value);
  const status = string(payload.status);
  if (!Array.isArray(payload.artifacts)) {
    return { task_id: string(payload.task_id ?? payload.md5sum), status, terminal: payload.terminal === true,
      task_type: string(payload.task_type), display_name: string(payload.display_name), status_url: string(payload.status_url),
      results_url: string(payload.results_url), result_available: payload.result_available === true,
      md5sum: optionalString(payload.md5sum), error: optionalString(payload.error),
      message: optionalString(payload.message) };
  }
  if (payload.schema_version !== 3 || (status !== 'finished' && status !== 'failed') || payload.terminal !== true ||
      !Object.hasOwn(payload, 'error') || !Object.hasOwn(payload, 'storyboard') || !Object.hasOwn(payload, 'outcome')) {
    throw fault('schema');
  }
  if (!Array.isArray(payload.views)) throw fault('views');
  const archive = record(payload.archive);
  const totalSize = Number(payload.total_size); if (!Number.isFinite(totalSize) || totalSize < 0) throw fault('totalSize');
  return { schema_version: 3, task_id: string(payload.task_id), task_type: string(payload.task_type), terminal: true,
    created_at: string(payload.created_at), status, error: payload.error == null ? null : string(payload.error),
    artifacts: payload.artifacts.map(artifact), total_size: totalSize, limitations: stringArray(payload.limitations),
    views: payload.views.map(view), run: record(payload.run) as ResultManifest['run'],
    output_check: record(payload.output_check) as ResultManifest['output_check'],
    archive: { ready: archive.ready === true, request_url: string(archive.request_url), download_url: archive.download_url == null ? null : string(archive.download_url) },
    storyboard: storyboard(payload.storyboard), result: resultFiles(payload.result),
    outcome: payload.outcome == null ? null : string(payload.outcome),
    filename: optionalString(payload.filename), message: optionalString(payload.message) };
}

export function getCurrentUser(signal?: AbortSignal): Promise<components['schemas']['CurrentUser']> {
  return requestJson<components['schemas']['CurrentUser']>('/compute/api/auth/me', { signal });
}

export function taskIdFromLocation(location: Pick<Location, 'pathname'> = window.location): string {
  const match = location.pathname.match(/^\/compute\/results\/([a-fA-F0-9]{32})\/?$/);
  if (!match) throw new Error(t('results.noResultUrl'));
  return match[1]!.toLowerCase();
}

export function getResultManifest(taskId: string, signal?: AbortSignal): Promise<ResultManifest> {
  return requestJson<unknown>(`/compute/api/results/${encodeURIComponent(taskId)}`, { signal }).then((value) => parseResultManifest(value) as ResultManifest);
}

export function getTaskStatus(taskId: string, signal?: AbortSignal): Promise<TaskStatus> {
  return requestJson<unknown>(`/compute/api/running/${encodeURIComponent(taskId)}`, { signal }).then((value) => parseResultManifest(value) as TaskStatus);
}

export async function loadAuthorizedResult(taskId: string, signal?: AbortSignal): Promise<TaskStatus | ResultManifest> {
  await getCurrentUser(signal);
  const status = await getTaskStatus(taskId, signal);
  if (!status.result_available) return status;
  try {
    const manifest = await getResultManifest(taskId, signal);
    return { ...manifest, filename: status.display_name };
  } catch (error) {
    // A failed Task can retain execution evidence even when publication is
    // unavailable. Keep its failure workspace addressable through that race.
    if (status.status === 'failed' && error instanceof ApiError && [404, 409].includes(error.status)) return status;
    throw error;
  }
}

export function requestResultArchive(url: string): Promise<Record<string, unknown>> {
  return authorizedJson<Record<string, unknown>>(url, { method: 'POST' });
}

export function downloadUrl(artifact: ResultFile): string {
  // A local result's file is a `blob:` handle to the reader's own file, not a
  // Server route: the download flag means nothing to it, and Chromium cancels a
  // download of a blob URL that carries a query.
  if (artifact.url.startsWith('blob:')) return artifact.url;
  const separator = artifact.url.includes('?') ? '&' : '?';
  return `${artifact.url}${separator}download=1`;
}

/**
 * The filename a download is saved under.
 *
 * A Server route names the file itself in `Content-Disposition`. A `blob:` handle carries no
 * name, so the browser falls back to the opaque URL and saves `vina_1.pdbqt` as `<uuid>.txt`;
 * for those the folder's own name for the file is stated instead.
 */
export function downloadName(artifact: ResultFile): string {
  if (!artifact.url.startsWith('blob:')) return '';
  const parts = resultFileName(artifact).split('/').filter(Boolean);
  return parts.at(-1) || '';
}

export function beginDownload(url: string, name = ''): void {
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  window.setTimeout(() => link.remove(), 0);
}
