import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSessionCredential } from '../src/app/session';
import { adminApi, type RunnerFleetEntry } from '../src/features/admin/api';
import { capacityLabel, filterFleet, jobStatusLabel, reasonText, workflowLabel } from '../src/features/admin/fleet/FleetAdmin';

type RequestRecord = { url: string; init: RequestInit };

function mockApi(payload: unknown = {}): { requests: RequestRecord[] } {
  const requests: RequestRecord[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith('/compute/api/auth/token')) return new Response(JSON.stringify({ token: 'admin-token' }), { status: 200 });
    requests.push({ url, init });
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return { requests };
}

const body = (request: RequestRecord): Record<string, unknown> => JSON.parse(String(request.init.body || '{}'));

afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

const evidence = (): RunnerFleetEntry['readiness']['evidence'] => ({
  sif_path: '/images/demo/demo.sif',
  sif_exists: true,
  build_provenance_current: true,
  receipt_exists: true,
  receipt_valid: true,
  doctor_ok: true,
});

const entry = (family: string, status: RunnerFleetEntry['readiness']['status'], available: boolean | null = true): RunnerFleetEntry => ({
  runner_family: family,
  readiness: { status, reason_code: 'READY', message: '', next_action: 'none', evidence: evidence() },
  capacity: { available, reason: available === null ? 'capacity_unknown' : 'scheduler_available' },
  access: { restricted: false, granted: true, policy_id: null },
  in_flight: null,
});

describe('fleet view helpers', () => {
  it('filters by readiness attention and orders deterministically', () => {
    const rows = [entry('zulu', 'READY'), entry('alpha', 'VALIDATION_STALE'), entry('mike', 'BUILD_STALE')];
    expect(filterFleet(rows, { query: '', filter: 'attention', sort: 'family' }).map(r => r.runner_family)).toEqual(['alpha', 'mike']);
    expect(filterFleet(rows, { query: '', filter: 'ready', sort: 'family' }).map(r => r.runner_family)).toEqual(['zulu']);
    expect(filterFleet(rows, { query: 'mi', filter: 'all', sort: 'family' }).map(r => r.runner_family)).toEqual(['mike']);
  });

  it('keeps capacity a separate fact from readiness', () => {
    // A READY family with no free compute still reports its capacity plainly.
    expect(capacityLabel('scheduler_busy', false)).toBe('Compute busy');
    expect(capacityLabel('capacity_unknown', null)).toBe('Capacity unknown');
    expect(capacityLabel('rpc_lost', null)).toBe('Unknown');
    expect(capacityLabel('scheduler_available', true)).toBe('Compute available');
  });

  it('renders the server machine reason as understandable copy', () => {
    expect(reasonText({ status: 'VALIDATION_STALE', reason_code: 'RUNTIME_BUNDLE_CHANGED', message: 'raw' } as never))
      .toContain('revalidation');
    expect(reasonText({ status: 'READY', reason_code: 'UNMAPPED_CODE', message: 'server copy' } as never)).toBe('server copy');
    expect(workflowLabel('live_test')).toBe('Live validation');
    expect(workflowLabel('unknown_stage')).toBe('unknown_stage');
  });

  it('labels a job lifecycle word, never a readiness state', () => {
    // A SUCCEEDED job is not "READY" and a FAILED job is not "BUILD_STALE":
    // the two axes use disjoint vocabularies.
    expect(jobStatusLabel('SUCCEEDED')).toBe('Succeeded');
    expect(jobStatusLabel('RUNNING')).toBe('Running');
    expect(jobStatusLabel('FAILED')).toBe('Failed');
    expect(jobStatusLabel('CANCELLED')).toBe('Cancelled');
    expect(jobStatusLabel('UNKNOWN_STATE')).toBe('UNKNOWN_STATE');
  });
});

describe('runner control-plane API contracts', () => {
  it('reads the fleet and reports executor availability separately', async () => {
    const fleet = { runners: [entry('demo', 'READY')], executor: { available: false, reason: 'operator_executor_unavailable' } };
    const { requests } = mockApi(fleet);
    await expect(adminApi.getRunnerFleet()).resolves.toEqual(fleet);
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/runners');
  });

  it('plans an action without a body-supplied family and runs it with the plan digest', async () => {
    const { requests } = mockApi({ action: 'runner.live_test', plan_digest: 'sha256:abc' });
    await adminApi.planRunnerAction('demo', 'runner.live_test');
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/runners/demo/plan');
    expect(body(requests[0]!)).toEqual({ action: 'runner.live_test' });

    const { requests: runRequests } = mockApi({ job: {}, plan: {}, accepted: true });
    await adminApi.runRunnerAction('demo', 'runner.live_test', 'sha256:abc', 'key-1');
    expect(runRequests[0]!.url).toBe('/compute/api/auth/admin/runners/demo/actions');
    expect(body(runRequests[0]!)).toEqual({ action: 'runner.live_test', plan_digest: 'sha256:abc', idempotency_key: 'key-1' });
  });

  it('encodes the family so it can never alter the request path', async () => {
    const { requests } = mockApi({});
    await adminApi.getRunnerDetail('demo/../other');
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/runners/demo%2F..%2Fother');
  });

  it('reads a family history and one operator job', async () => {
    const { requests } = mockApi({ history: [{ job_id: 'j1' }], jobs: [] });
    await expect(adminApi.getRunnerHistory('demo', 10)).resolves.toEqual([{ job_id: 'j1' }]);
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/runners/demo/history?limit=10');

    const { requests: jobRequests } = mockApi({ job_id: 'j1', status: 'RUNNING' });
    await expect(adminApi.getOperatorJob('j1')).resolves.toEqual({ job_id: 'j1', status: 'RUNNING' });
    expect(jobRequests[0]!.url).toBe('/compute/api/auth/admin/operator/jobs/j1');
  });

  it('cancels an operator job through the guarded mutation route', async () => {
    const { requests } = mockApi({ job_id: 'j1', status: 'CANCELLED' });
    await adminApi.cancelOperatorJob('j1');
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/operator/jobs/j1/cancel');
    expect(requests[0]!.init.method).toBe('POST');
  });
});
