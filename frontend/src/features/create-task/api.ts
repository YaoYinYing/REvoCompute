import type { components } from '../../api/schema.generated';
import { t } from '../../app/i18n';
import { authorizedFetch } from '../../app/session';
import type { TaskCatalog, TaskFormDefinition, TaskPreflight, TaskStatus, WorkspaceContract, WorkspaceDescriptor } from './types';
import { parametersFromSchema } from './parameter-controls';

export class CreateTaskApiError extends Error {
  constructor(message: string, readonly status: number, readonly payload?: unknown) {
    super(message);
    this.name = 'CreateTaskApiError';
  }
}

/**
 * A server payload that does not match the contract the workbench reads.
 *
 * The message is the frontend's own localized copy; the type is the stable
 * internal signal, so no caller has to match on user-facing prose.
 */
export class PayloadFault extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PayloadFault';
  }
}

function object(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new PayloadFault(t('ct.payload.fault.invalid', { field }));
  return value as Record<string, unknown>;
}

function text(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value) throw new PayloadFault(t('ct.payload.fault.invalid', { field }));
  return value;
}

function approvedAssetUrl(value: unknown, owner: string, pluginId: string, field: string): string {
  const raw = text(value, field);
  const url = new URL(raw, window.location.origin);
  const prefix = `/compute/api/workspace/assets/${encodeURIComponent(owner)}/${encodeURIComponent(pluginId)}/`;
  if (url.origin !== window.location.origin || !url.pathname.startsWith(prefix)) {
    throw new PayloadFault(t('ct.payload.fault.assetOrigin', { field }));
  }
  return `${url.pathname}${url.search}`;
}

export function parseWorkspaceDescriptor(value: unknown): WorkspaceDescriptor {
  const item = object(value, t('ct.payload.field.descriptor'));
  const id = text(item.id, t('ct.payload.field.id'));
  const owner = text(item.owner, t('ct.payload.field.owner'));
  const module = object(item.module, t('ct.payload.field.module'));
  if (module.type !== 'module') throw new PayloadFault(t('ct.payload.fault.moduleType'));
  const descriptorUrl = text(item.descriptor_url, t('ct.payload.field.descriptorUrl'));
  const descriptor = new URL(descriptorUrl, window.location.origin);
  const expectedDescriptor = `/compute/api/workspace/plugins/${encodeURIComponent(owner)}/${encodeURIComponent(id)}`;
  if (descriptor.origin !== window.location.origin || descriptor.pathname !== expectedDescriptor) {
    throw new PayloadFault(t('ct.payload.fault.invalid', { field: t('ct.payload.field.descriptorUrl') }));
  }
  if (!Array.isArray(item.stylesheets)) throw new PayloadFault(t('ct.payload.fault.invalid', { field: t('ct.payload.field.stylesheets') }));
  const stylesheets = item.stylesheets.map((entry) => {
    const stylesheet = object(entry, t('ct.payload.field.stylesheet'));
    if (stylesheet.media_type !== 'text/css') throw new PayloadFault(t('ct.payload.fault.stylesheetMediaType'));
    return { url: approvedAssetUrl(stylesheet.url, owner, id, t('ct.payload.field.stylesheetUrl')), media_type: 'text/css' as const };
  });
  return {
    id, owner, global_id: text(item.global_id, t('ct.payload.field.globalId')),
    descriptor_url: `${descriptor.pathname}${descriptor.search}`,
    module: { url: approvedAssetUrl(module.url, owner, id, t('ct.payload.field.moduleUrl')), type: 'module' },
    stylesheets,
    ...(item.configuration_schema_url == null ? {} : {
      configuration_schema_url: approvedAssetUrl(item.configuration_schema_url, owner, id, t('ct.payload.field.schemaUrl')),
    }),
  };
}

export function parseWorkspace(value: unknown): WorkspaceContract {
  const workspace = object(value, t('ct.payload.field.workspace'));
  if (workspace.version !== 3 || !Array.isArray(workspace.steps) || !Array.isArray(workspace.plugins)) {
    throw new PayloadFault(t('ct.payload.fault.invalid', { field: t('ct.payload.field.contract') }));
  }
  const plugins = workspace.plugins.map(parseWorkspaceDescriptor);
  const steps = workspace.steps.map((rawStep) => {
    const step = object(rawStep, t('ct.payload.field.step'));
    if (!Array.isArray(step.capabilities)) throw new PayloadFault(t('ct.payload.fault.invalid', { field: t('ct.payload.field.stepCapabilities') }));
    return {
      id: text(step.id, t('ct.payload.field.stepId')), title: text(step.title, t('ct.payload.field.stepTitle')),
      description: typeof step.description === 'string' ? step.description : undefined,
      capabilities: step.capabilities.map((rawCapability) => {
        const capability = object(rawCapability, t('ct.payload.field.capability'));
        return {
          plugin: text(capability.plugin, t('ct.payload.field.capabilityPlugin')),
          id: text(capability.id, t('ct.payload.field.capabilityId')),
          title: text(capability.title, t('ct.payload.field.capabilityTitle')),
          description: typeof capability.description === 'string' ? capability.description : undefined,
          options: capability.options == null ? {} : object(capability.options, t('ct.payload.field.capabilityOptions')),
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
    throw new CreateTaskApiError(String(item.error || item.message || t('ct.request.failed', { status: response.status })), response.status, payload);
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
  const raw = object(await request(`/compute/api/types/${encodeURIComponent(name)}`, { signal }), t('ct.payload.field.taskType'));
  const parametersUrl = text(raw.parameters_url, t('ct.payload.field.parametersUrl'));
  const schema = await request(parametersUrl, { signal }) as components['schemas']['TaskParameterSchema'];
  return {
    name: text(raw.name, t('ct.payload.field.taskName')), display_name: text(raw.display_name, t('ct.payload.field.taskDisplayName')),
    category: text(raw.category, t('ct.payload.field.taskCategory')), summary: text(raw.summary, t('ct.payload.field.taskSummary')),
    use_when: text(raw.use_when, t('ct.payload.field.taskGuidance')), input_summary: text(raw.input_summary, t('ct.payload.field.taskInputSummary')),
    output_summary: text(raw.output_summary, t('ct.payload.field.taskOutputSummary')),
    considerations: Array.isArray(raw.considerations) ? raw.considerations.filter((item): item is string => typeof item === 'string') : [],
    runtime_family: typeof raw.runtime_family === 'string' ? raw.runtime_family : undefined,
    gpus: raw.gpus === true, requires_network: raw.requires_network === true,
    access: object(raw.access, t('ct.payload.field.taskAccess')) as components['schemas']['RunnerAccess'], parameters_url: parametersUrl,
    submission: raw.submission && typeof raw.submission === 'object' && !Array.isArray(raw.submission)
      ? raw.submission as TaskFormDefinition['submission'] : null,
    inputs: Array.isArray(raw.inputs) ? raw.inputs as components['schemas']['TaskInputRole'][] : [],
    input_workspace: parseWorkspace(raw.input_workspace),
    execution_modes: Array.isArray(raw.execution_modes) ? raw.execution_modes.flatMap((item) => {
      if (!item || typeof item !== 'object') return [];
      const mode = item as Record<string, unknown>;
      if (typeof mode.id !== 'string' || typeof mode.label !== 'string') return [];
      const output_contract = mode.output_contract === 'full' || mode.output_contract === 'stages'
        || mode.output_contract === 'none' ? mode.output_contract : undefined;
      const reuse = Array.isArray(mode.reuse) ? mode.reuse.flatMap((rawReuse) => {
        if (!rawReuse || typeof rawReuse !== 'object') return [];
        const entry = rawReuse as Record<string, unknown>;
        if (typeof entry.port !== 'string' || typeof entry.role !== 'string' || typeof entry.type !== 'string') return [];
        if (!Array.isArray(entry.inputs) || !entry.inputs.every((role): role is string => typeof role === 'string')) return [];
        return [{ port: entry.port, role: entry.role, type: entry.type, inputs: entry.inputs }];
      }) : [];
      return [{
        id: mode.id,
        label: mode.label,
        stages: Array.isArray(mode.stages) ? mode.stages.filter((stage): stage is string => typeof stage === 'string') : [],
        ...(output_contract ? { output_contract } : {}),
        ...(reuse.length ? { reuse } : {}),
      }];
    }) : [],
    max_request_bytes: typeof raw.max_request_bytes === 'number' ? raw.max_request_bytes : Number.MAX_SAFE_INTEGER,
    ...(typeof raw.max_decoded_input_bytes === 'number'
      ? { max_decoded_input_bytes: raw.max_decoded_input_bytes }
      : {}),
    ...(raw.file_encodings && typeof raw.file_encodings === 'object' && !Array.isArray(raw.file_encodings)
      && (raw.file_encodings as Record<string, unknown>).version === 1
      && Array.isArray((raw.file_encodings as Record<string, unknown>).supported)
      ? {
          file_encodings: {
            version: 1 as const,
            supported: ((raw.file_encodings as Record<string, unknown>).supported as unknown[])
              .filter((item): item is 'identity' | 'gzip' => item === 'identity' || item === 'gzip'),
          },
        }
      : {}),
    params: parametersFromSchema(schema),
  };
}

export async function requestAccess(policyId: string, reason: string): Promise<void> {
  await mutation('/compute/api/access/requests', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ policy_id: policyId, reason }),
  });
}

export interface SubmissionRequestOptions {
  signal?: AbortSignal;
}

export async function preflightTask(
  taskType: string,
  formData: FormData,
  options: SubmissionRequestOptions = {},
): Promise<TaskPreflight> {
  try {
    return await mutation(`/compute/api/preflight/${encodeURIComponent(taskType)}`, {
      method: 'POST', body: formData, signal: options.signal,
    }) as TaskPreflight;
  } catch (error) {
    if (error instanceof CreateTaskApiError && error.payload && typeof error.payload === 'object' && 'valid' in error.payload) {
      return error.payload as TaskPreflight;
    }
    throw error;
  }
}

export async function submitTask(
  formData: FormData,
  options: SubmissionRequestOptions = {},
): Promise<TaskStatus> {
  return mutation('/compute/api/post', {
    method: 'POST', body: formData, signal: options.signal,
  }) as Promise<TaskStatus>;
}
