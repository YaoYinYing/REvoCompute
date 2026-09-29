import type { components } from '../../api/schema.generated';
import { authorizedFetch } from '../../app/session';
import type { TaskCatalog, TaskFormDefinition, TaskPreflight, TaskStatus, WorkspaceContract, WorkspaceDescriptor } from './types';
import { parametersFromSchema } from './parameter-controls';

export class CreateTaskApiError extends Error {
  constructor(message: string, readonly status: number, readonly payload?: unknown) {
    super(message);
    this.name = 'CreateTaskApiError';
  }
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} is invalid.`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value) throw new Error(`${label} is invalid.`);
  return value;
}

function approvedAssetUrl(value: unknown, owner: string, pluginId: string, label: string): string {
  const raw = text(value, label);
  const url = new URL(raw, window.location.origin);
  const prefix = `/compute/api/workspace/assets/${encodeURIComponent(owner)}/${encodeURIComponent(pluginId)}/`;
  if (url.origin !== window.location.origin || !url.pathname.startsWith(prefix)) {
    throw new Error(`${label} is not an approved same-origin plugin asset.`);
  }
  return `${url.pathname}${url.search}`;
}

export function parseWorkspaceDescriptor(value: unknown): WorkspaceDescriptor {
  const item = object(value, 'Workspace plugin descriptor');
  const id = text(item.id, 'Workspace plugin id');
  const owner = text(item.owner, 'Workspace plugin owner');
  const module = object(item.module, 'Workspace plugin module');
  if (module.type !== 'module') throw new Error('Workspace plugin module type is invalid.');
  const descriptorUrl = text(item.descriptor_url, 'Workspace plugin descriptor URL');
  const descriptor = new URL(descriptorUrl, window.location.origin);
  const expectedDescriptor = `/compute/api/workspace/plugins/${encodeURIComponent(owner)}/${encodeURIComponent(id)}`;
  if (descriptor.origin !== window.location.origin || descriptor.pathname !== expectedDescriptor) {
    throw new Error('Workspace plugin descriptor URL is invalid.');
  }
  if (!Array.isArray(item.stylesheets)) throw new Error('Workspace plugin stylesheets are invalid.');
  const stylesheets = item.stylesheets.map((entry) => {
    const stylesheet = object(entry, 'Workspace plugin stylesheet');
    if (stylesheet.media_type !== 'text/css') throw new Error('Workspace plugin stylesheet media type is invalid.');
    return { url: approvedAssetUrl(stylesheet.url, owner, id, 'Workspace plugin stylesheet URL'), media_type: 'text/css' as const };
  });
  return {
    id, owner, global_id: text(item.global_id, 'Workspace plugin global id'),
    descriptor_url: `${descriptor.pathname}${descriptor.search}`,
    module: { url: approvedAssetUrl(module.url, owner, id, 'Workspace plugin module URL'), type: 'module' },
    stylesheets,
    ...(item.configuration_schema_url == null ? {} : {
      configuration_schema_url: approvedAssetUrl(item.configuration_schema_url, owner, id, 'Workspace plugin schema URL'),
    }),
  };
}

export function parseWorkspace(value: unknown): WorkspaceContract {
  const workspace = object(value, 'Input workspace');
  if (workspace.version !== 3 || !Array.isArray(workspace.steps) || !Array.isArray(workspace.plugins)) {
    throw new Error('Input workspace contract is invalid.');
  }
  const plugins = workspace.plugins.map(parseWorkspaceDescriptor);
  const steps = workspace.steps.map((rawStep) => {
    const step = object(rawStep, 'Workspace step');
    if (!Array.isArray(step.capabilities)) throw new Error('Workspace step capabilities are invalid.');
    return {
      id: text(step.id, 'Workspace step id'), title: text(step.title, 'Workspace step title'),
      description: typeof step.description === 'string' ? step.description : undefined,
      capabilities: step.capabilities.map((rawCapability) => {
        const capability = object(rawCapability, 'Workspace capability');
        return {
          plugin: text(capability.plugin, 'Workspace capability plugin'),
          id: text(capability.id, 'Workspace capability id'),
          title: text(capability.title, 'Workspace capability title'),
          description: typeof capability.description === 'string' ? capability.description : undefined,
          options: capability.options == null ? {} : object(capability.options, 'Workspace capability options'),
        };
      }),
    };
  });
  return { version: 3, plugins, steps };
}

async function responseJson(response: Response): Promise<unknown> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const item = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {};
    throw new CreateTaskApiError(String(item.error || item.message || `Request failed (HTTP ${response.status})`), response.status, payload);
  }
  return payload;
}

function request(url: string, init: RequestInit = {}): Promise<unknown> {
  return fetch(url, { ...init, credentials: 'same-origin' }).then(responseJson);
}

function mutation(url: string, init: RequestInit): Promise<unknown> {
  return authorizedFetch(url, init).then(responseJson);
}

export async function getTaskCatalog(signal?: AbortSignal): Promise<TaskCatalog> {
  return request('/compute/api/types', { signal }) as Promise<TaskCatalog>;
}

export async function getTaskDefinition(name: string, signal?: AbortSignal): Promise<TaskFormDefinition> {
  const raw = object(await request(`/compute/api/types/${encodeURIComponent(name)}`, { signal }), 'Task type');
  const parametersUrl = text(raw.parameters_url, 'Parameter schema URL');
  const schema = await request(parametersUrl, { signal }) as components['schemas']['TaskParameterSchema'];
  return {
    name: text(raw.name, 'Task type name'), display_name: text(raw.display_name, 'Task type display name'),
    category: text(raw.category, 'Task type category'), summary: text(raw.summary, 'Task type summary'),
    use_when: text(raw.use_when, 'Task type guidance'), input_summary: text(raw.input_summary, 'Task input summary'),
    output_summary: text(raw.output_summary, 'Task output summary'),
    considerations: Array.isArray(raw.considerations) ? raw.considerations.filter((item): item is string => typeof item === 'string') : [],
    runtime_family: typeof raw.runtime_family === 'string' ? raw.runtime_family : undefined,
    gpus: raw.gpus === true, requires_network: raw.requires_network === true,
    access: object(raw.access, 'Task access') as components['schemas']['RunnerAccess'], parameters_url: parametersUrl,
    inputs: Array.isArray(raw.inputs) ? raw.inputs as components['schemas']['TaskInputRole'][] : [],
    input_workspace: parseWorkspace(raw.input_workspace),
    max_request_bytes: typeof raw.max_request_bytes === 'number' ? raw.max_request_bytes : Number.MAX_SAFE_INTEGER,
    params: parametersFromSchema(schema),
  };
}

export async function requestAccess(policyId: string, reason: string): Promise<void> {
  await mutation('/compute/api/access/requests', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ policy_id: policyId, reason }),
  });
}

export async function preflightTask(taskType: string, formData: FormData): Promise<TaskPreflight> {
  try {
    return await mutation(`/compute/api/preflight/${encodeURIComponent(taskType)}`, { method: 'POST', body: formData }) as TaskPreflight;
  } catch (error) {
    if (error instanceof CreateTaskApiError && error.payload && typeof error.payload === 'object' && 'valid' in error.payload) {
      return error.payload as TaskPreflight;
    }
    throw error;
  }
}

export async function submitTask(formData: FormData): Promise<TaskStatus> {
  return mutation('/compute/api/post', { method: 'POST', body: formData }) as Promise<TaskStatus>;
}
