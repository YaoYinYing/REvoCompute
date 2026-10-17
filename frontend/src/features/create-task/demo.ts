import type { components } from '../../api/schema.generated';
import { t } from '../../app/i18n';
import { CreateTaskApiError } from './api';

/**
 * One declared demo input preset, as the owning Task publishes it.
 *
 * The catalog is public and read-only: fetching it creates, reserves, and
 * authorizes nothing. A demo names the fixture files to bind and the parameter
 * values to set; loading it into the workbench is a local form operation.
 */
export interface TaskDemoFile {
  role: string;
  path: string;
  sha256: string;
  size: number;
  media_type: string;
  download_url: string;
}

export interface TaskDemo {
  id: string;
  title: string;
  purpose: string;
  context: string;
  source: { name: string; url: string };
  license: { id: string; name: string; url: string };
  inputs: Record<string, TaskDemoFile[]>;
  parameters: Record<string, unknown>;
}

type DemoCatalog = components['schemas']['TaskDemoCatalog'];

function fail(message: string): never {
  throw new TypeError(message);
}

/**
 * Read one demo file from its declared URL and present it as an upload.
 *
 * The bytes are fetched from the same origin and named by the demo's own
 * declared path, so the resulting `File` enters the form exactly as a chosen
 * upload does: the same role binding, the same format checks, the same
 * submission payload. The declared digest is verified against the received
 * bytes, so a demo file can never be bound to a role under bytes the owning
 * Task did not declare.
 */
export async function fetchDemoFile(file: TaskDemoFile, signal?: AbortSignal): Promise<File> {
  const url = new URL(file.download_url, window.location.origin);
  if (url.origin !== window.location.origin) fail(t('ct.demo.downloadFailed', { message: file.path }));
  const response = await fetch(`${url.pathname}${url.search}`, { signal, credentials: 'same-origin' });
  if (!response.ok) fail(t('ct.demo.downloadFailed', { message: `${file.path} (${response.status})` }));
  const bytes = await response.blob();
  if (file.sha256) {
    const digest = await crypto.subtle.digest('SHA-256', await bytes.arrayBuffer());
    const hex = Array.from(new Uint8Array(digest)).map(value => value.toString(16).padStart(2, '0')).join('');
    if (hex !== file.sha256.toLowerCase()) fail(t('ct.demo.downloadFailed', { message: file.path }));
  }
  const name = file.path.split('/').pop() || file.path;
  return new File([bytes], name, { type: file.media_type || 'application/octet-stream' });
}

/** Read the declared demo catalog for one Task; an empty list is a valid answer. */
export async function getTaskDemos(name: string, signal?: AbortSignal): Promise<TaskDemo[]> {
  const response = await fetch(`/compute/api/types/${encodeURIComponent(name)}/demos`, { signal, credentials: 'same-origin' });
  if (!response.ok) throw new CreateTaskApiError(t('ct.demo.failed', { message: String(response.status) }), response.status);
  const payload = await response.json() as DemoCatalog;
  if (!payload || payload.version !== 1 || !Array.isArray(payload.demos)) {
    fail(t('ct.demo.failed', { message: 'payload' }));
  }
  return payload.demos.map(demo => ({
    id: demo.id, title: demo.title, purpose: demo.purpose, context: demo.context,
    source: { name: demo.source.name, url: demo.source.url },
    license: { id: demo.license.id, name: demo.license.name, url: demo.license.url },
    inputs: Object.fromEntries(Object.entries(demo.inputs).map(([role, files]) => [role, files as TaskDemoFile[]])),
    parameters: { ...demo.parameters } as Record<string, unknown>,
  }));
}
