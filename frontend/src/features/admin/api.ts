import type { components } from '../../api/schema.generated';
import type { AdminLogName } from '../../api/contracts';
import { authorizedFetch, authorizedJson } from '../../app/session';

export type GPUCreditSummary = components['schemas']['GPUCreditSummary'];
export type GPUCreditResetResult = components['schemas']['GPUCreditResetResult'];
export type GPUCreditResetAllResult = components['schemas']['GPUCreditResetAllResult'];
export type GPUCreditReconciliation = components['schemas']['GPUCreditReconciliation'];
export type GPUCreditMutationResult = components['schemas']['GPUCreditMutationResult'];
export type InfrastructureReadiness = components['schemas']['InfrastructureReadiness'];
export type TaskCatalog = components['schemas']['TaskCatalog'];

export type AdminUser = components['schemas']['AdminUser'];
export type AdminUserCreate = components['schemas']['AdminUserCreateRequest'];
export type AdminUserUpdate = components['schemas']['AdminUserUpdateRequest'];

export type AccessRequest = components['schemas']['AdminAccessRequest'];
export type AccessDecision = components['schemas']['AccessDecisionRequest'];
export type EntitlementGrantRequest = components['schemas']['EntitlementGrantRequest'];

export type AccessPolicySummary = components['schemas']['AccessPolicySummary'];

export type AccessEvent = components['schemas']['AccessEvent'];

export type AccessPolicyDetail = components['schemas']['AccessPolicyDetail'];

export type EntitlementGrant = components['schemas']['EntitlementGrant'];

export type UserEntitlements = components['schemas']['UserEntitlements'];

export type ConfigValue = components['schemas']['ConfigValue'];
export type TaskTypeConfig = components['schemas']['TaskTypeConfiguration'];
export type AdminConfiguration = components['schemas']['AdminConfiguration'];

export type LogArchive = components['schemas']['LogArchive'];
export type LogArchiveGroup = components['schemas']['LogArchiveGroup'];

export type RunnerFleet = components['schemas']['RunnerFleet'];
export type RunnerFleetEntry = components['schemas']['RunnerFleetEntry'];
export type RunnerDetail = components['schemas']['RunnerDetail'];
export type RunnerReadiness = components['schemas']['RunnerReadiness'];
export type OperatorAction = components['schemas']['OperatorAction'];
export type OperatorPlan = components['schemas']['OperatorPlan'];
export type OperatorJob = components['schemas']['OperatorJob'];
export type OperatorJobAccepted = components['schemas']['OperatorJobAccepted'];
export type OperatorHistoryList = components['schemas']['OperatorHistoryList'];

export interface BoundedLog {
  text: string;
  truncated: boolean;
}

const json = <T>(url: string, method: string, body?: unknown): Promise<T> => authorizedJson<T>(url, {
  method,
  ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
});

export const adminApi = {
  listUsers: (): Promise<AdminUser[]> => authorizedJson<{ users: AdminUser[] }>('/compute/api/auth/admin/users').then(data => data.users),
  createUser: (user: AdminUserCreate): Promise<{ message: string; username: string }> => json('/compute/api/auth/admin/users', 'POST', user),
  updateUser: (id: number, update: AdminUserUpdate): Promise<{ message: string }> => json(`/compute/api/auth/admin/users/${id}`, 'PUT', update),
  deleteUser: (id: number): Promise<{ message: string }> => json(`/compute/api/auth/admin/users/${id}`, 'DELETE'),
  batchUsers: (action: 'enable' | 'disable' | 'delete', userIds: number[]): Promise<{ message: string; count: number }> => json('/compute/api/auth/admin/users/batch', 'POST', { action, user_ids: userIds }),

  listAccessRequests: (status = 'pending'): Promise<AccessRequest[]> => authorizedJson<{ requests: AccessRequest[] }>(`/compute/api/auth/admin/access/requests?status=${encodeURIComponent(status)}`).then(data => data.requests),
  listAccessPolicies: (): Promise<AccessPolicySummary[]> => authorizedJson<{ policies: AccessPolicySummary[] }>('/compute/api/auth/admin/access/policies').then(data => data.policies),
  getAccessPolicy: (policyId: string): Promise<AccessPolicyDetail> => authorizedJson(`/compute/api/auth/admin/access/policies/${encodeURIComponent(policyId)}`),
  listAccessEvents: (policyId?: string, limit = 100): Promise<AccessEvent[]> => {
    const search = new URLSearchParams({ limit: String(limit) });
    if (policyId) search.set('policy_id', policyId);
    return authorizedJson<{ events: AccessEvent[] }>(`/compute/api/auth/admin/access/events?${search}`).then(data => data.events);
  },
  decideAccessRequest: (requestId: number, payload: AccessDecision): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/access/requests/${requestId}/decision`, 'POST', payload),
  getUserEntitlements: (userId: number): Promise<UserEntitlements> => authorizedJson(`/compute/api/auth/admin/users/${userId}/entitlements`),
  grantEntitlement: (userId: number, payload: EntitlementGrantRequest): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/entitlements`, 'POST', payload),
  revokeEntitlement: (userId: number, grantId: number): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/entitlements/${grantId}/revoke`, 'POST'),
  clearSuspension: (userId: number, policyId: string): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/access/${encodeURIComponent(policyId)}/clear-suspension`, 'POST'),

  getUserCredit: (userId: number): Promise<GPUCreditSummary> => authorizedJson(`/compute/api/auth/admin/users/${userId}/gpu-credit`),
  adjustCredit: (userId: number, gpuSeconds: number, reason: string, idempotencyKey: string): Promise<GPUCreditMutationResult> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/adjustments`, 'POST', { gpu_seconds: gpuSeconds, reason, idempotency_key: idempotencyKey }),
  setAllowance: (userId: number, monthlyGpuSeconds: number, idempotencyKey: string): Promise<GPUCreditMutationResult> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/allowance`, 'PUT', { monthly_gpu_seconds: monthlyGpuSeconds, idempotency_key: idempotencyKey }),
  resetUserCredit: (userId: number, reason: string, idempotencyKey: string): Promise<GPUCreditResetResult> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/reset`, 'POST', { reason, idempotency_key: idempotencyKey }),
  resetAllCredits: (reason: string, idempotencyKey: string): Promise<GPUCreditResetAllResult> => json('/compute/api/auth/admin/gpu-credit/reset', 'POST', { reason, idempotency_key: idempotencyKey }),
  getReconciliation: (): Promise<GPUCreditReconciliation> => authorizedJson('/compute/api/auth/admin/gpu-credit/reconciliation'),
  reconcileCredits: (): Promise<GPUCreditReconciliation> => json('/compute/api/auth/admin/gpu-credit/reconciliation', 'POST'),

  getConfiguration: (): Promise<AdminConfiguration> => authorizedJson('/compute/api/auth/admin/config'),
  updateConfiguration: (update: Partial<Pick<AdminConfiguration, 'task_types' | 'resources' | 'slurm'>>): Promise<{ message: string }> => json('/compute/api/auth/admin/config', 'PUT', update),
  getTaskCatalog: (): Promise<TaskCatalog> => authorizedJson('/compute/api/types'),
  getInfrastructure: (): Promise<InfrastructureReadiness> => authorizedJson('/compute/api/infrastructure'),
  refreshInfrastructure: (): Promise<InfrastructureReadiness> => json('/compute/api/auth/admin/infrastructure/refresh', 'POST'),

  getRunnerFleet: (): Promise<RunnerFleet> => authorizedJson('/compute/api/auth/admin/runners'),
  getRunnerDetail: (family: string): Promise<RunnerDetail> => authorizedJson(`/compute/api/auth/admin/runners/${encodeURIComponent(family)}`),
  getRunnerHistory: (family: string, limit = 50): Promise<OperatorJob[]> =>
    authorizedJson<OperatorHistoryList>(`/compute/api/auth/admin/runners/${encodeURIComponent(family)}/history?limit=${limit}`).then(data => data.history),
  planRunnerAction: (family: string, action: string): Promise<OperatorPlan> =>
    json(`/compute/api/auth/admin/runners/${encodeURIComponent(family)}/plan`, 'POST', { action }),
  runRunnerAction: (family: string, action: string, planDigest: string, idempotencyKey: string): Promise<OperatorJobAccepted> =>
    json(`/compute/api/auth/admin/runners/${encodeURIComponent(family)}/actions`, 'POST', { action, plan_digest: planDigest, idempotency_key: idempotencyKey }),
  getOperatorJob: (jobId: string): Promise<OperatorJob> => authorizedJson(`/compute/api/auth/admin/operator/jobs/${encodeURIComponent(jobId)}`),
  cancelOperatorJob: (jobId: string): Promise<OperatorJob> => json(`/compute/api/auth/admin/operator/jobs/${encodeURIComponent(jobId)}/cancel`, 'POST'),

  getLog: async (name: AdminLogName, signal?: AbortSignal, maxCharacters = 1_000_000): Promise<BoundedLog> => {
    const response = await authorizedFetch(`/compute/api/auth/admin/logs/${encodeURIComponent(name)}?tail_bytes=${maxCharacters}`, { signal });
    if (!response.ok) throw new Error(`Unable to load log (HTTP ${response.status})`);
    const serverTruncated = response.headers.get('X-Log-Truncated') === 'true';
    if (!response.body) {
      const raw = await response.text();
      return { text: raw.slice(-maxCharacters), truncated: serverTruncated || raw.length > maxCharacters };
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let result = '';
    let truncated = serverTruncated;
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      result += decoder.decode(chunk.value, { stream: true });
      if (result.length > maxCharacters) { result = result.slice(-maxCharacters); truncated = true; }
    }
    result += decoder.decode();
    if (result.length > maxCharacters) { result = result.slice(-maxCharacters); truncated = true; }
    return { text: result, truncated };
  },
  listLogArchives: (): Promise<LogArchiveGroup[]> => authorizedJson<{ logs: LogArchiveGroup[] }>('/compute/api/auth/admin/logs/archives').then(data => data.logs),
  archiveUrl: (filename: string): string => `/compute/api/auth/admin/logs/archives/${encodeURIComponent(filename)}`,
};

export function idempotencyKey(scope: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${random}:${scope}`.replace(/[^A-Za-z0-9._:-]/g, '-').slice(0, 128);
}
