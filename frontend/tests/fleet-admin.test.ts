import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSessionCredential } from '../src/app/session';
import { adminApi, type RunnerFleetEntry } from '../src/features/admin/api';
import { activeImageDetail, activeImageLabel, capacityLabel, executorNotice, filterFleet, jobStatusLabel, reasonText, summarizeFleet, summarySentence, weaknessLabel, weaknessOf, workflowLabel } from '../src/features/admin/fleet/FleetAdmin';

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
  readiness: {
    status,
    reason_code: 'READY',
    message: '',
    next_action: 'none',
    active_image: { state: 'ACTIVE', sha256: 'sha256:' + 'a'.repeat(64), reason_code: null },
    evidence: evidence(),
  },
  capacity: { available, reason: available === null ? 'capacity_unknown' : 'scheduler_available' },
  access: { restricted: false, granted: true, policy_id: null },
  in_flight: null,
});

describe('fleet view helpers', () => {
  it('filters by readiness attention and orders by how much work each family needs', () => {
    const rows = [entry('zulu', 'READY'), entry('alpha', 'VALIDATION_STALE'), entry('mike', 'BUILD_STALE')];
    expect(filterFleet(rows, { query: '', filter: 'attention', sort: 'family' }).map(r => r.runner_family)).toEqual(['alpha', 'mike']);
    expect(filterFleet(rows, { query: '', filter: 'ready', sort: 'family' }).map(r => r.runner_family)).toEqual(['zulu']);
    expect(filterFleet(rows, { query: 'mi', filter: 'all', sort: 'family' }).map(r => r.runner_family)).toEqual(['mike']);
    // A family that cannot accept submissions at all sorts above one that only
    // needs validation, and a ready family sorts last: the default order is what
    // an operator has to work on first.
    expect(filterFleet(rows, { query: '', filter: 'all', sort: 'attention' }).map(r => r.runner_family))
      .toEqual(['mike', 'alpha', 'zulu']);
    expect(filterFleet([entry('b', 'NOT_CONFIGURED'), entry('a', 'READY')], { query: '', filter: 'all', sort: 'attention' })
      .map(r => r.runner_family)).toEqual(['b', 'a']);
  });

  it('groups the server verdicts into work bands without inventing a verdict', () => {
    // Every one of the six verdicts lands in exactly one band.
    expect(weaknessOf('NOT_CONFIGURED')).toBe('unavailable');
    expect(weaknessOf('NOT_BUILT')).toBe('unavailable');
    expect(weaknessOf('BUILD_STALE')).toBe('stale_build');
    expect(weaknessOf('NOT_VALIDATED')).toBe('needs_attention');
    expect(weaknessOf('VALIDATION_STALE')).toBe('needs_attention');
    expect(weaknessOf('READY')).toBe('ready');
    expect(weaknessLabel('VALIDATION_STALE')).toBe('Needs attention');
  });

  it('counts the register into actionable bands, in order, with empty bands shown', () => {
    const rows = [entry('a', 'READY'), entry('b', 'BUILD_STALE'), entry('c', 'NOT_BUILT')];
    const { total, entries } = summarizeFleet(rows);
    expect(total).toBe(3);
    // Most work first: unavailable, then stale build, then needs attention, then ready.
    expect(entries.map(band => band.weakness)).toEqual(['unavailable', 'stale_build', 'needs_attention', 'ready']);
    expect(entries.map(band => band.count)).toEqual([1, 1, 0, 1]);
    // A band with no member is still reported: "none is unavailable" is a fact.
    expect(entries.every(band => band.reason.length > 0)).toBe(true);
    // An empty register is its own state, never "all ready".
    expect(summarizeFleet([]).total).toBe(0);
  });

  it('states where the register stands rather than reporting a health number', () => {
    expect(summarySentence([])).toContain('No Runner family is enabled');
    expect(summarySentence([entry('a', 'READY'), entry('b', 'READY')])).toBe('All 2 enabled Runner families are ready.');
    expect(summarySentence([entry('a', 'READY'), entry('b', 'VALIDATION_STALE')]))
      .toBe('1 of 2 enabled Runner families needs work before accepting new submissions.');
    expect(summarySentence([entry('solo', 'READY')])).toBe('All 1 enabled Runner family is ready.');
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

  it('shows an active image only when the server established its identity', () => {
    const identified = entry('demo', 'READY').readiness;
    expect(activeImageLabel(identified)).toBe('Active · aaaaaaaaaaaa…');
    expect(activeImageDetail(identified)).toBe('Active · sha256:' + 'a'.repeat(64));

    expect(activeImageLabel({
      ...identified,
      active_image: { state: 'MISSING', sha256: null, reason_code: 'SIF_MISSING' },
    })).toBe('Missing');

    // A file that is present without an established identity is Unknown, never
    // "present": existence is not identity.
    expect(activeImageLabel({
      ...identified,
      active_image: { state: 'UNKNOWN', sha256: null, reason_code: 'ACTIVE_IMAGE_IDENTITY_UNKNOWN' },
    })).toBe('Unknown');
    expect(activeImageDetail({
      ...identified,
      active_image: { state: 'UNKNOWN', sha256: null, reason_code: 'ACTIVE_IMAGE_IDENTITY_UNKNOWN' },
    })).toContain('Unknown');

    // A staged candidate awaiting activation is not the installed artifact; the
    // dialog says why rather than borrowing the candidate's digest.
    expect(activeImageLabel({
      ...identified,
      active_image: { state: 'UNKNOWN', sha256: null, reason_code: 'STAGED_CANDIDATE_PENDING' },
    })).toBe('Unknown');
    expect(activeImageDetail({
      ...identified,
      active_image: { state: 'UNKNOWN', sha256: null, reason_code: 'STAGED_CANDIDATE_PENDING' },
    })).toContain('staged candidate is awaiting activation');

    // A cached payload from a server that did not project the field is Unknown.
    expect(activeImageLabel({ ...identified, active_image: undefined } as never)).toBe('Unknown');
  });

  it('tells an operator why the host executor is unavailable, not just that it is', () => {
    // The server owns the actionable sentence: it names the missing artifact by
    // role and points at the host CLI. The banner renders it verbatim, so the
    // operator is told where the operation belongs instead of reading a constant.
    const sentence = 'The deployment controller (run/restart.sh) is not reachable from this server process.';
    const unavailable = executorNotice({ available: false, reason: 'operator_executor_unavailable', unavailable_reason: sentence });
    expect(unavailable.title).toBe('Host executor unavailable');
    expect(unavailable.detail).toContain('run/restart.sh');
    expect(unavailable.detail).toContain(sentence);

    // An older server that reports no sentence still says what stays available.
    const older = executorNotice({ available: false, reason: 'operator_executor_unavailable', unavailable_reason: null });
    expect(older.detail).toContain('Readiness, capacity, access, and history stay available');

    const available = executorNotice({ available: true, reason: 'operator_executor_available', unavailable_reason: null });
    expect(available.title).toBe('Host executor available');
    expect(available.detail).toContain('planned and run');
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
