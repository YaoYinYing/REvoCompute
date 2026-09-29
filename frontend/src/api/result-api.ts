import type { components } from './schema.generated';
import type { ArtifactRole, LogicalResultFile, PreviewCapability, ResultArtifact, ResultFile, ResultManifest, ResultStoryboardDeclaration, ResultView, TaskStatus } from './result-types';
import { ApiError, authorizedJson } from '../app/session';
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
function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} is invalid.`);
  return value as Record<string, unknown>;
}
function string(value: unknown, label: string): string {
  if (typeof value !== 'string') throw new Error(`${label} is invalid.`); return value;
}
function optionalString(value: unknown, label: string): string | undefined {
  return value == null ? undefined : string(value, label);
}
function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) throw new Error(`${label} is invalid.`);
  return [...value];
}
function artifact(value: unknown): ResultArtifact {
  const item = record(value, 'Result artifact'); const role = string(item.role, 'Artifact role') as ArtifactRole;
  if (!ROLES.has(role)) throw new Error('Artifact role is invalid.');
  const declared = item.capability ?? item.preview; let capability: PreviewCapability = 'unknown';
  if (declared != null) {
    if (typeof declared === 'string' && CAPABILITIES.has(declared as PreviewCapability)) capability = declared as PreviewCapability;
  }
  const size = Number(item.size); if (!Number.isFinite(size) || size < 0) throw new Error('Artifact size is invalid.');
  return {
    path: string(item.path, 'Artifact path'), name: optionalString(item.name, 'Artifact name'),
    media_type: string(item.media_type, 'Artifact media type'), size, sha256: string(item.sha256, 'Artifact hash'),
    role, preview: item.preview === null ? null : capability === 'structure' || capability === 'image' || capability === 'table' || capability === 'text' ? capability : null,
    capability: capability === 'structure' ? 'molecular_structure' : capability,
    confidence_encoding: item.confidence_encoding === 'plddt_bfactor' ? 'plddt_bfactor' : undefined,
    url: string(item.url, 'Artifact URL'), ndarray_url: optionalString(item.ndarray_url, 'Projection URL'),
    table_url: optionalString(item.table_url, 'Table URL'), cardinality: item.cardinality === 'many' ? 'many' : 'one',
    id: optionalString(item.id, 'Artifact id'),
  };
}

function view(value: unknown): ResultView {
  const item = record(value, 'Result view'); const rawSources = record(item.sources, 'View sources');
  const sources: Record<string, string[]> = {};
  Object.entries(rawSources).forEach(([key, paths]) => { sources[key] = stringArray(paths, `View source ${key}`); });
  const plugin = string(item.plugin, 'View plugin') as ResultView['plugin'];
  const role = string(item.role, 'View role') as ResultView['role'];
  if (!VIEW_PLUGINS.has(plugin) || !VIEW_ROLES.has(role)) throw new Error('Result view vocabulary is invalid.');
  return { id: string(item.id, 'View id'), plugin, title: string(item.title, 'View title'), role,
    description: optionalString(item.description, 'View description') || '', sources,
    mapping: item.mapping == null ? {} : record(item.mapping, 'View mapping') };
}

function storyboard(value: unknown): ResultStoryboardDeclaration | null {
  if (value == null) return null; const item = record(value, 'Storyboard');
  return { identifier: string(item.identifier, 'Storyboard identifier'), entrypoint: string(item.entrypoint, 'Storyboard entrypoint'), entrypoint_url: string(item.entrypoint_url, 'Storyboard URL'), requires: stringArray(item.requires, 'Storyboard requirements'), optional: stringArray(item.optional, 'Storyboard optional files') };
}
function logicalFile(value: unknown): LogicalResultFile {
  const item = record(value, 'Logical result file'), role = string(item.role, 'Logical file role') as ArtifactRole;
  const capability = string(item.capability, 'Logical file capability') as PreviewCapability;
  if (!ROLES.has(role) || !CAPABILITIES.has(capability)) throw new Error('Logical result file vocabulary is invalid.');
  const cardinality = string(item.cardinality, 'Logical file cardinality'); if (cardinality !== 'one' && cardinality !== 'many') throw new Error('Logical file cardinality is invalid.');
  const size = Number(item.size); if (!Number.isFinite(size) || size < 0) throw new Error('Logical file size is invalid.');
  return { id: string(item.id, 'Logical file id'), name: string(item.name, 'Logical file name'), media_type: string(item.media_type, 'Logical file media type'),
    size, role, cardinality, viewer: string(item.viewer, 'Logical file viewer'), preview: item.preview == null ? null : string(item.preview, 'Logical file preview'),
    capability: capability === 'structure' ? 'molecular_structure' : capability, url: string(item.url, 'Logical file URL'),
    confidence_encoding: item.confidence_encoding === 'plddt_bfactor' ? 'plddt_bfactor' : undefined,
    table_url: optionalString(item.table_url, 'Logical table URL'), ndarray_url: optionalString(item.ndarray_url, 'Logical projection URL') };
}
function resultFiles(value: unknown): ResultManifest['result'] {
  const result = record(value, 'Result file mapping'), rawFiles = record(result.files, 'Result files'), files: Record<string, LogicalResultFile[]> = {};
  Object.entries(rawFiles).forEach(([id, entries]) => { if (!Array.isArray(entries)) throw new Error(`Result files ${id} is invalid.`); files[id] = entries.map(logicalFile); });
  return { files };
}

export function parseResultManifest(value: unknown): ResultManifest | TaskStatus {
  const payload = record(value, 'Result response');
  const status = string(payload.status, 'Task status');
  if (!Array.isArray(payload.artifacts)) {
    return { task_id: string(payload.task_id ?? payload.md5sum, 'Task id'), status, terminal: payload.terminal === true,
      task_type: string(payload.task_type, 'Task type'), display_name: string(payload.display_name, 'Task display name'), status_url: string(payload.status_url, 'Status URL'),
      results_url: string(payload.results_url, 'Results URL'), result_available: payload.result_available === true,
      md5sum: optionalString(payload.md5sum, 'Task id'), error: optionalString(payload.error, 'Task error'),
      message: optionalString(payload.message, 'Message') };
  }
  if (payload.schema_version !== 3 || (status !== 'finished' && status !== 'failed') || payload.terminal !== true ||
      !Object.hasOwn(payload, 'error') || !Object.hasOwn(payload, 'storyboard') || !Object.hasOwn(payload, 'outcome')) {
    throw new Error('Result schema version or status is invalid.');
  }
  if (!Array.isArray(payload.views)) throw new Error('Result views are invalid.');
  const archive = record(payload.archive, 'Result archive');
  const totalSize = Number(payload.total_size); if (!Number.isFinite(totalSize) || totalSize < 0) throw new Error('Result total size is invalid.');
  return { schema_version: 3, task_id: string(payload.task_id, 'Task id'), task_type: string(payload.task_type, 'Task type'), terminal: true,
    created_at: string(payload.created_at, 'Creation time'), status, error: payload.error == null ? null : string(payload.error, 'Result error'),
    artifacts: payload.artifacts.map(artifact), total_size: totalSize, limitations: stringArray(payload.limitations, 'Result limitations'),
    views: payload.views.map(view), run: record(payload.run, 'Run record') as ResultManifest['run'],
    output_check: record(payload.output_check, 'Output check') as ResultManifest['output_check'],
    archive: { ready: archive.ready === true, request_url: string(archive.request_url, 'Archive request URL'), download_url: archive.download_url == null ? null : string(archive.download_url, 'Archive URL') },
    storyboard: storyboard(payload.storyboard), result: resultFiles(payload.result),
    outcome: payload.outcome == null ? null : string(payload.outcome, 'Result outcome'),
    filename: optionalString(payload.filename, 'Filename'), message: optionalString(payload.message, 'Message') };
}

export function getCurrentUser(signal?: AbortSignal): Promise<components['schemas']['CurrentUser']> {
  return requestJson<components['schemas']['CurrentUser']>('/compute/api/auth/me', { signal });
}

export function taskIdFromLocation(location: Pick<Location, 'pathname'> = window.location): string {
  const match = location.pathname.match(/^\/compute\/results\/([a-fA-F0-9]{32})\/?$/);
  if (!match) throw new Error('This Result URL does not contain a valid task identity.');
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
  const manifest = await getResultManifest(taskId, signal);
  return { ...manifest, filename: status.display_name };
}

export function requestResultArchive(url: string): Promise<Record<string, unknown>> {
  return authorizedJson<Record<string, unknown>>(url, { method: 'POST' });
}

export function downloadUrl(artifact: ResultFile): string {
  const separator = artifact.url.includes('?') ? '&' : '?';
  return `${artifact.url}${separator}download=1`;
}

export function beginDownload(url: string): void {
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  link.hidden = true;
  document.body.append(link);
  link.click();
  window.setTimeout(() => link.remove(), 0);
}
