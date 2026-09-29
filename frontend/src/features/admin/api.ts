import type { components } from '../../api/schema.generated';
import { authorizedFetch, authorizedJson } from '../../app/session';

export type GPUCreditSummary = components['schemas']['GPUCreditSummary'];
export type GPUCreditResetResult = components['schemas']['GPUCreditResetResult'];
export type GPUCreditResetAllResult = components['schemas']['GPUCreditResetAllResult'];
export type GPUCreditReconciliation = components['schemas']['GPUCreditReconciliation'];
export type InfrastructureReadiness = components['schemas']['InfrastructureReadiness'];
export type TaskCatalog = components['schemas']['TaskCatalog'];

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  email_verified: boolean;
  role: string;
  allow_gpu_use: boolean;
  full_name: string | null;
  affiliation: string | null;
  position: string | null;
  pi_name: string | null;
  registration_status: string;
  user_status: string;
  created_at: number | null;
  approved_by: number | null;
  approved_at: number | null;
  registration_ip: string | null;
  registration_country: string | null;
  gpu_credit: GPUCreditSummary;
}

export interface AdminUserCreate {
  username: string;
  email: string;
  password: string;
  full_name: string | null;
  affiliation: string | null;
  position: string | null;
  pi_name: string | null;
  role: string;
}

export interface AdminUserUpdate {
  email?: string;
  password?: string;
  full_name?: string;
  affiliation?: string;
  position?: string | null;
  pi_name?: string;
  registration_status?: 'approved' | 'rejected';
  user_status?: 'active' | 'banned';
  role?: 'admin' | 'user' | 'guest';
  allow_gpu_use?: boolean;
}

export interface AccessRequest extends Partial<AdminUser> {
  id: number;
  request_id?: number;
  user_id: number;
  entitlement: string;
  reason: string;
  status?: string;
  created_at?: number;
}

export interface AccessPolicySummary {
  policy_id: string;
  label: string;
  description: string;
  requires: string[];
  notice?: { summary?: string } | null;
  license?: { name?: string; url?: string } | null;
  authorized_users: number;
  pending_requests: number;
  suspended_users: number;
}

export interface AccessIdentity extends Partial<AdminUser> {
  user_id: number;
  basis?: string | null;
  grant_id?: number | null;
  retry_after_seconds?: number;
}

export interface AccessEvent {
  id?: number;
  occurred_at?: number;
  created_at?: number | string;
  full_name?: string;
  username?: string;
  user_name?: string;
  policy_id?: string;
  label?: string;
  task_type?: string;
  runtime_family?: string;
  outcome?: string;
  decision?: string;
  reason_code?: string;
}

export interface AccessPolicyDetail {
  policy: Pick<AccessPolicySummary, 'policy_id' | 'label' | 'description' | 'requires' | 'notice' | 'license'>;
  authorized_users: AccessIdentity[];
  pending_requests: AccessRequest[];
  suspended_users: AccessIdentity[];
  events: AccessEvent[];
}

export interface EntitlementGrant {
  id: number;
  user_id: number;
  entitlement: string;
  basis: string | null;
  expires_at: number | null;
  revoked_at: number | null;
  created_at?: number;
  note?: string | null;
}

export interface UserAccessPolicy {
  policy_id: string;
  label: string;
  granted: boolean;
  request_status?: string | null;
  missing_entitlements?: string[];
  suspended?: boolean;
  retry_after_seconds?: number;
}

export interface UserEntitlements {
  grants: EntitlementGrant[];
  policies: UserAccessPolicy[];
}

export type ConfigValue = string | number | boolean | null;
export interface TaskTypeConfig {
  tool: string;
  display_name: string;
  enabled: boolean;
  requires_gpu: boolean;
  runtime_family: string;
  is_workflow_stage: boolean;
  category: string;
  inputs: Array<{ id: string; title: string; formats: string[] }>;
  parameter_count: number;
  stage_count: number;
  effective_resources?: Record<string, ConfigValue> | null;
  resource_sources?: Record<string, string>;
  resource_error?: string | null;
  cpus?: ConfigValue;
  memory?: ConfigValue;
  max_runtime_seconds?: ConfigValue;
  slurm_partition?: ConfigValue;
  slurm_gres?: ConfigValue;
  slurm_nodes?: ConfigValue;
  slurm_ntasks?: ConfigValue;
  slurm_qos?: ConfigValue;
  slurm_account?: ConfigValue;
  slurm_constraint?: ConfigValue;
  slurm_exclusive?: ConfigValue;
}

export interface AdminConfiguration {
  task_types: TaskTypeConfig[];
  resources: Record<string, ConfigValue>;
  ignored_resource_keys: string[];
  slurm: { enabled: boolean; allowed_queues: string[] };
}

export interface LogArchive {
  filename: string;
  size: number;
  modified_at: number;
}

export interface LogArchiveGroup {
  id: string;
  filename: string;
  archives: LogArchive[];
}

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
  decideAccessRequest: (requestId: number, payload: { decision: 'approved' | 'rejected'; basis?: string; expires_at?: number | null; note?: string | null }): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/access/requests/${requestId}/decision`, 'POST', payload),
  getUserEntitlements: (userId: number): Promise<UserEntitlements> => authorizedJson(`/compute/api/auth/admin/users/${userId}/entitlements`),
  grantEntitlement: (userId: number, payload: { entitlement: string; basis: string; expires_at: number | null; note: string | null }): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/entitlements`, 'POST', payload),
  revokeEntitlement: (userId: number, grantId: number): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/entitlements/${grantId}/revoke`, 'POST'),
  clearSuspension: (userId: number, policyId: string): Promise<Record<string, unknown>> => json(`/compute/api/auth/admin/users/${userId}/access/${encodeURIComponent(policyId)}/clear-suspension`, 'POST'),

  getUserCredit: (userId: number): Promise<GPUCreditSummary> => authorizedJson(`/compute/api/auth/admin/users/${userId}/gpu-credit`),
  adjustCredit: (userId: number, gpuSeconds: number, reason: string, idempotencyKey: string): Promise<{ entry_id: number; gpu_credit: GPUCreditSummary }> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/adjustments`, 'POST', { gpu_seconds: gpuSeconds, reason, idempotency_key: idempotencyKey }),
  setAllowance: (userId: number, monthlyGpuSeconds: number, idempotencyKey: string): Promise<{ entry_id: number; gpu_credit: GPUCreditSummary }> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/allowance`, 'PUT', { monthly_gpu_seconds: monthlyGpuSeconds, idempotency_key: idempotencyKey }),
  resetUserCredit: (userId: number, reason: string, idempotencyKey: string): Promise<GPUCreditResetResult> => json(`/compute/api/auth/admin/users/${userId}/gpu-credit/reset`, 'POST', { reason, idempotency_key: idempotencyKey }),
  resetAllCredits: (reason: string, idempotencyKey: string): Promise<GPUCreditResetAllResult> => json('/compute/api/auth/admin/gpu-credit/reset', 'POST', { reason, idempotency_key: idempotencyKey }),
  getReconciliation: (): Promise<GPUCreditReconciliation> => authorizedJson('/compute/api/auth/admin/gpu-credit/reconciliation'),
  reconcileCredits: (): Promise<GPUCreditReconciliation> => json('/compute/api/auth/admin/gpu-credit/reconciliation', 'POST'),

  getConfiguration: (): Promise<AdminConfiguration> => authorizedJson('/compute/api/auth/admin/config'),
  updateConfiguration: (update: Partial<Pick<AdminConfiguration, 'task_types' | 'resources' | 'slurm'>>): Promise<{ message: string }> => json('/compute/api/auth/admin/config', 'PUT', update),
  getTaskCatalog: (): Promise<TaskCatalog> => authorizedJson('/compute/api/types'),
  getInfrastructure: (): Promise<InfrastructureReadiness> => authorizedJson('/compute/api/infrastructure'),
  refreshInfrastructure: (): Promise<InfrastructureReadiness> => json('/compute/api/auth/admin/infrastructure/refresh', 'POST'),

  getLog: async (name: string, signal?: AbortSignal, maxCharacters = 1_000_000): Promise<BoundedLog> => {
    const response = await authorizedFetch(`/compute/api/auth/admin/logs/${encodeURIComponent(name)}`, { signal });
    if (!response.ok) throw new Error(`Unable to load log (HTTP ${response.status})`);
    if (!response.body) {
      const raw = await response.text();
      return { text: raw.slice(-maxCharacters), truncated: raw.length > maxCharacters };
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let result = '';
    let truncated = false;
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
