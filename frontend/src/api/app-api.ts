import type { components } from './schema.generated';
import { authorizedJson, requestJson } from '../app/session';

export type CurrentUser = components['schemas']['CurrentUser'];
export type TaskCatalog = components['schemas']['TaskCatalog'];
export type TaskTypeSummary = components['schemas']['TaskTypeSummary'];
export type TaskTypeDetail = components['schemas']['TaskTypeDetail'];
export type InfrastructureReadiness = components['schemas']['InfrastructureReadiness'];

export interface ParameterDefinition {
  type?: string | string[]; title?: string; description?: string; default?: unknown; enum?: unknown[];
  minimum?: number; maximum?: number; unit?: string; advanced?: boolean;
}
export interface ParameterSchema { properties?: Record<string, ParameterDefinition>; required?: string[] }

export type TaskAction = components['schemas']['TaskAction'];
export type TaskSummary = components['schemas']['TaskSummary'];
export type TaskList = components['schemas']['TaskList'];

export const getSession = (signal?: AbortSignal): Promise<CurrentUser> => requestJson('/compute/api/auth/me', { signal });
export const getTaskCatalog = (signal?: AbortSignal): Promise<TaskCatalog> => requestJson('/compute/api/types', { signal });
export const getTaskType = (name: string, signal?: AbortSignal): Promise<TaskTypeDetail> => requestJson(`/compute/api/types/${encodeURIComponent(name)}`, { signal });
export const getParameterSchema = (name: string, signal?: AbortSignal): Promise<ParameterSchema> => requestJson(`/compute/api/task-parameters/${encodeURIComponent(name)}`, { signal });
export const getReadiness = (signal?: AbortSignal): Promise<InfrastructureReadiness> => requestJson('/compute/api/infrastructure', { signal });
export const getTasks = (signal?: AbortSignal): Promise<TaskSummary[]> => requestJson<TaskList>('/compute/api/tasks', { signal }).then(data => data.tasks);

export const runTaskAction = (action: TaskAction, method: 'POST' | 'DELETE'): Promise<Record<string, unknown>> => {
  if (!action.allowed || !action.url) return Promise.reject(new Error('This action is not available.'));
  return authorizedJson(action.url, { method });
};
export const deleteTaskBatch = (taskIds: string[]): Promise<Record<string, unknown>> => authorizedJson('/compute/api/delete', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ md5sums: taskIds }),
});
export const prepareArchive = (url: string): Promise<Record<string, unknown>> => authorizedJson(url, { method: 'POST' });
