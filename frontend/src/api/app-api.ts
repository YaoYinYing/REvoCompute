import type { components } from './schema.generated';
import { authorizedJson, establishSessionCredential, requestJson } from '../app/session';

export type CurrentUser = components['schemas']['CurrentUser'];
export type CurrentUserUpdate = components['schemas']['UpdateCurrentUserRequest'];
export type TaskCatalog = components['schemas']['TaskCatalog'];
export type TaskTypeSummary = components['schemas']['TaskTypeSummary'];
export type TaskTypeDetail = components['schemas']['TaskTypeDetail'];
export type InfrastructureReadiness = components['schemas']['InfrastructureReadiness'];
export type UserMetrics = components['schemas']['UserMetrics'];
export type GPUCreditSummary = components['schemas']['GPUCreditSummary'];
export type ResourceEntitlement = components['schemas']['ResourceEntitlement'];
export type ResourceLedger = components['schemas']['ResourceLedger'];
export type ResourceLedgerEntry = components['schemas']['ResourceLedgerEntry'];
export type GPUCreditWaterfall = components['schemas']['GPUCreditWaterfall'];
export type GPUCreditWaterfallStep = components['schemas']['GPUCreditWaterfallStep'];
export type GPUCreditWaterfallSummary = components['schemas']['GPUCreditWaterfallSummary'];
export type RunnerAccess = components['schemas']['RunnerAccess'];

export type RegistrationCapability = components['schemas']['RegistrationCapability'];
export type McpCapability = components['schemas']['McpCapability'];
export type CaptchaChallenge = components['schemas']['CaptchaChallenge'];
export type RegistrationRequest = components['schemas']['RegisterRequest'];
export type LegalDocument = components['schemas']['LegalDocument'];
export type SystemNotices = components['schemas']['SystemNotices'];
export type ApiMessage = components['schemas']['MessageResponse'];
export interface ApiKeyStatus { has_api_key: boolean }
export interface ApiKeyCreated extends ApiMessage { api_key: string }
export interface AccessResponse { policies: RunnerAccess[] }

const jsonRequest = <T>(url: string, body: unknown): Promise<T> => requestJson(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export interface ParameterDefinition {
  type?: string | string[]; title?: string; description?: string; default?: unknown; enum?: unknown[];
  minimum?: number; maximum?: number; exclusiveMinimum?: number; exclusiveMaximum?: number; unit?: string; advanced?: boolean;
  'x-unit'?: string; 'x-advanced'?: boolean;
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

export async function login(username: string, password: string): Promise<components['schemas']['LoginResponse']> {
  const response = await jsonRequest<components['schemas']['LoginResponse']>('/compute/api/auth/login', { username, password });
  establishSessionCredential(response.token);
  return response;
}
export const forgotPassword = (email: string): Promise<ApiMessage> =>
  jsonRequest('/compute/api/auth/forgot-password', { email });
export const getRegistrationCapability = (): Promise<RegistrationCapability> =>
  requestJson('/compute/api/auth/registration');
export const getCaptcha = (): Promise<CaptchaChallenge> => requestJson('/compute/api/auth/captcha');
export const register = (payload: RegistrationRequest): Promise<components['schemas']['RegisterResponse']> =>
  jsonRequest('/compute/api/auth/register', payload);
export const resendVerification = (email: string): Promise<ApiMessage> =>
  jsonRequest('/compute/api/auth/resend-verification', { email });
export const resetPassword = (token: string, password: string): Promise<ApiMessage> =>
  jsonRequest('/compute/api/auth/reset-password', { token, password });
export const verifyEmail = (token: string): Promise<components['schemas']['VerifyEmailResponse']> =>
  jsonRequest('/compute/api/auth/verify-email', { token });
export const getTerms = (): Promise<LegalDocument> => requestJson('/compute/api/legal/terms');
export const getSystemNotices = (): Promise<SystemNotices> => requestJson('/compute/api/system/notices');
// Whether this deployment serves the agent MCP endpoint: a public read of one
// deployment fact, so the Home page offers the live endpoint only when it answers.
export const getMcpCapability = (signal?: AbortSignal): Promise<McpCapability> =>
  requestJson('/compute/api/mcp', { signal });

export const updatePassword = (currentPassword: string, newPassword: string): Promise<ApiMessage> =>
  authorizedJson('/compute/api/auth/me', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
export const updateProfile = (profile: Pick<CurrentUserUpdate, 'full_name' | 'affiliation' | 'position' | 'pi_name'>): Promise<ApiMessage> =>
  authorizedJson('/compute/api/auth/me', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(profile),
  });
export const getApiKeyStatus = (): Promise<ApiKeyStatus> => requestJson('/compute/api/auth/me/api-key');
export const createApiKey = (): Promise<ApiKeyCreated> => authorizedJson('/compute/api/auth/me/api-key', { method: 'POST' });
export const revokeApiKey = (): Promise<ApiMessage> => authorizedJson('/compute/api/auth/me/api-key', { method: 'DELETE' });
export const getUserMetrics = (window: 'daily' | 'weekly' | 'quarterly' | 'yearly'): Promise<UserMetrics> =>
  requestJson(`/compute/api/user-metrics?window=${encodeURIComponent(window)}`);
export const getGpuCredit = (): Promise<GPUCreditSummary> => requestJson('/compute/api/gpu-credit');
/** The canonical resource envelope admission decides against, for this account. */
export const getResourceEntitlement = (signal?: AbortSignal): Promise<ResourceEntitlement> =>
  requestJson('/compute/api/resource-entitlement', { signal });
/** This account's own append-only ledger, newest first and bounded by the server. */
export const getResourceLedger = (limit?: number, signal?: AbortSignal): Promise<ResourceLedger> =>
  requestJson(`/compute/api/resource-ledger${limit === undefined ? '' : `?limit=${encodeURIComponent(String(limit))}`}`, { signal });
export const getAccess = (): Promise<AccessResponse> => requestJson('/compute/api/access');
export const requestAccess = (policyId: string, reason: string): Promise<Record<string, unknown>> =>
  authorizedJson('/compute/api/access/requests', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ policy_id: policyId, reason }),
  });

export const runTaskAction = (action: TaskAction, method: 'POST' | 'DELETE'): Promise<Record<string, unknown>> => {
  if (!action.allowed || !action.url) return Promise.reject(new Error('This action is not available.'));
  return authorizedJson(action.url, { method });
};
export const deleteTaskBatch = (taskIds: string[]): Promise<Record<string, unknown>> => authorizedJson('/compute/api/delete', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ md5sums: taskIds }),
});
export const prepareArchive = (url: string): Promise<Record<string, unknown>> => authorizedJson(url, { method: 'POST' });

export type TaskDiagnostics = components['schemas']['TaskDiagnostics'];
export const getTaskDiagnostics = (taskId: string, signal?: AbortSignal): Promise<TaskDiagnostics> =>
  requestJson(`/compute/api/tasks/${encodeURIComponent(taskId)}/diagnostics`, { signal });
