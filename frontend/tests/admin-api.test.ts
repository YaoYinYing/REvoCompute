import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSessionCredential } from '../src/app/session';
import { adminApi, idempotencyKey, type AdminUser } from '../src/features/admin/api';
import { parseRuntime } from '../src/features/admin/configuration/ConfigurationAdmin';
import { globalResetConfirmation, validateGlobalReset } from '../src/features/admin/credits/CreditAdmin';
import { boundLogText } from '../src/features/admin/logs/LogsAdmin';
import { filterUsers } from '../src/features/admin/users/UserAdmin';

type RequestRecord = { url: string; init: RequestInit };

function mockApi(payload: unknown = {}): { requests: RequestRecord[] } {
  const requests: RequestRecord[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith('/compute/api/auth/token')) return new Response(JSON.stringify({ token: 'admin-token' }), { status: 200 });
    requests.push({ url, init });
    return new Response(typeof payload === 'string' ? payload : JSON.stringify(payload), { status: 200, headers: { 'content-type': typeof payload === 'string' ? 'text/plain' : 'application/json' } });
  }));
  return { requests };
}

function body(request: RequestRecord): Record<string, unknown> {
  return JSON.parse(String(request.init.body || '{}')) as Record<string, unknown>;
}

afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

describe('admin user contracts', () => {
  it('lists users and applies search, role, and account filters', async () => {
    const alice = { id: 1, username: 'alice', full_name: 'Alice Zhang', email: 'alice@example.test', affiliation: 'Lab A', role: 'admin', user_status: 'active', registration_status: 'approved' } as AdminUser;
    const bob = { id: 2, username: 'bob', full_name: 'Bob Jones', email: 'bob@example.test', affiliation: 'Lab B', role: 'user', user_status: 'pending', registration_status: 'verified' } as AdminUser;
    mockApi({ users: [alice, bob] });
    await expect(adminApi.listUsers()).resolves.toEqual([alice, bob]);
    expect(filterUsers([alice, bob], { query: 'lab b', role: 'user', status: 'pending' })).toEqual([bob]);
    expect(filterUsers([alice, bob], { query: 'nobody', role: 'all', status: 'all' })).toEqual([]);
  });

  it('uses canonical create, edit, delete, and batch mutations', async () => {
    const { requests } = mockApi({ message: 'ok', username: 'new-user', count: 2 });
    await adminApi.createUser({ username: 'new-user', email: 'new@example.test', password: 'password1', full_name: null, affiliation: null, position: null, pi_name: null, role: 'user' });
    await adminApi.updateUser(7, { role: 'admin', allow_gpu_use: true });
    await adminApi.deleteUser(7);
    await adminApi.batchUsers('disable', [7, 8]);
    expect(requests.map(request => [request.url, request.init.method])).toEqual([
      ['/compute/api/auth/admin/users', 'POST'], ['/compute/api/auth/admin/users/7', 'PUT'],
      ['/compute/api/auth/admin/users/7', 'DELETE'], ['/compute/api/auth/admin/users/batch', 'POST'],
    ]);
    expect(body(requests[1]!)).toEqual({ role: 'admin', allow_gpu_use: true });
    expect(body(requests[3]!)).toEqual({ action: 'disable', user_ids: [7, 8] });
  });
});

describe('admin Runner access contracts', () => {
  it('loads policies, pending requests, user entitlements, and bounded events', async () => {
    const { requests } = mockApi({ policies: [], requests: [], grants: [], events: [] });
    await adminApi.listAccessPolicies();
    await adminApi.listAccessRequests('all');
    await adminApi.getAccessPolicy('licensed/family');
    await adminApi.getUserEntitlements(11);
    await adminApi.listAccessEvents('licensed/family', 50);
    expect(requests.map(request => request.url)).toEqual([
      '/compute/api/auth/admin/access/policies',
      '/compute/api/auth/admin/access/requests?status=all',
      '/compute/api/auth/admin/access/policies/licensed%2Ffamily',
      '/compute/api/auth/admin/users/11/entitlements',
      '/compute/api/auth/admin/access/events?limit=50&policy_id=licensed%2Ffamily',
    ]);
  });

  it('decides requests, grants and revokes entitlements, and clears suspensions', async () => {
    const { requests } = mockApi({ message: 'ok' });
    await adminApi.decideAccessRequest(4, { decision: 'approved', basis: 'lab_member', expires_at: null, note: 'Verified' });
    await adminApi.grantEntitlement(11, { entitlement: 'gpu-license', basis: 'individually_verified', expires_at: null, note: null });
    await adminApi.revokeEntitlement(11, 5);
    await adminApi.clearSuspension(11, 'licensed/family');
    expect(requests.map(request => request.url)).toEqual([
      '/compute/api/auth/admin/access/requests/4/decision',
      '/compute/api/auth/admin/users/11/entitlements',
      '/compute/api/auth/admin/users/11/entitlements/5/revoke',
      '/compute/api/auth/admin/users/11/access/licensed%2Ffamily/clear-suspension',
    ]);
    expect(body(requests[0]!)).toMatchObject({ decision: 'approved', basis: 'lab_member' });
  });
});

describe('admin GPU credit contracts', () => {
  it('inspects, adjusts, changes allowance, and resets one or all users', async () => {
    const { requests } = mockApi({ history: [], allocations: [] });
    await adminApi.getUserCredit(9);
    await adminApi.adjustCredit(9, -120, 'Correction', 'adjust:key');
    await adminApi.setAllowance(9, 3600, 'allowance:key');
    await adminApi.resetUserCredit(9, 'Monthly correction', 'reset:key');
    await adminApi.resetAllCredits('Policy reset', 'reset-all:key');
    expect(requests.map(request => [request.url, request.init.method])).toEqual([
      ['/compute/api/auth/admin/users/9/gpu-credit', undefined],
      ['/compute/api/auth/admin/users/9/gpu-credit/adjustments', 'POST'],
      ['/compute/api/auth/admin/users/9/gpu-credit/allowance', 'PUT'],
      ['/compute/api/auth/admin/users/9/gpu-credit/reset', 'POST'],
      ['/compute/api/auth/admin/gpu-credit/reset', 'POST'],
    ]);
    expect(body(requests[1]!)).toEqual({ gpu_seconds: -120, reason: 'Correction', idempotency_key: 'adjust:key' });
    expect(body(requests[4]!)).toEqual({ reason: 'Policy reset', idempotency_key: 'reset-all:key' });
  });

  it('requires a reason and exact deliberate phrase for global reset', () => {
    expect(validateGlobalReset('', globalResetConfirmation)).toMatch(/reason/);
    expect(validateGlobalReset('Planned reset', 'reset all')).toContain(globalResetConfirmation);
    expect(validateGlobalReset('Planned reset', globalResetConfirmation)).toBeNull();
    expect(idempotencyKey('reset all')).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/);
  });

  it('loads and runs reconciliation using separate GET and POST contracts', async () => {
    const { requests } = mockApi({ result: null, allocations: [] });
    await adminApi.getReconciliation();
    await adminApi.reconcileCredits();
    expect(requests.map(request => request.init.method)).toEqual([undefined, 'POST']);
    expect(requests.every(request => request.url.endsWith('/gpu-credit/reconciliation'))).toBe(true);
  });
});

describe('configuration and logs contracts', () => {
  it('loads and updates task configuration and refreshes infrastructure evidence', async () => {
    const { requests } = mockApi({ task_types: [], resources: {}, ignored_resource_keys: [], slurm: { enabled: false, allowed_queues: [] } });
    await adminApi.getConfiguration();
    await adminApi.updateConfiguration({ task_types: [{ tool: 'fold', enabled: false }] as never });
    await adminApi.getTaskCatalog();
    await adminApi.getInfrastructure();
    await adminApi.refreshInfrastructure();
    expect(requests.map(request => [request.url, request.init.method])).toEqual([
      ['/compute/api/auth/admin/config', undefined], ['/compute/api/auth/admin/config', 'PUT'],
      ['/compute/api/types', undefined], ['/compute/api/infrastructure', undefined],
      ['/compute/api/auth/admin/infrastructure/refresh', 'POST'],
    ]);
    expect(parseRuntime('1:02:03')).toBe(3723);
    expect(parseRuntime('3600')).toBe(3600);
    expect(parseRuntime('1:90:00')).toBeNull();
  });

  it('loads bounded active logs and managed archives', async () => {
    const log = `${Array.from({ length: 5_100 }, (_, index) => `line ${index}`).join('\n')}\n`;
    const { requests } = mockApi(log);
    await expect(adminApi.getLog('gunicorn-error')).resolves.toEqual({ text: log, truncated: false });
    const bounded = boundLogText(log);
    expect(bounded.truncated).toBe(true);
    expect(bounded.text.split('\n').length).toBeLessThanOrEqual(5_000);
    expect(requests[0]?.url).toBe('/compute/api/auth/admin/logs/gunicorn-error');

    clearSessionCredential();
    const archives = mockApi({ logs: [{ id: 'maintenance', filename: 'maintenance.log', archives: [] }] });
    await expect(adminApi.listLogArchives()).resolves.toHaveLength(1);
    expect(archives.requests[0]?.url).toBe('/compute/api/auth/admin/logs/archives');
    expect(adminApi.archiveUrl('../secret.zip')).toBe('/compute/api/auth/admin/logs/archives/..%2Fsecret.zip');
  });
});
