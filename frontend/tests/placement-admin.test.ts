import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearSessionCredential } from '../src/app/session';
import { adminApi, type AdminConfiguration, type ComputeEntitlement, type ExecutionClass, type ResourceEntitlement, type TaskSummary } from '../src/features/admin/api';
import { mountAdmin } from '../src/features/admin/index';
import {
  formatWalltime,
  pageOf,
  pageSummary,
  PlacementAdmin,
  placementDevice,
  placementExclusive,
  placementLabel,
  placementQueue,
  placementSchedulerField,
  placementStateLabel,
  PLACEMENT_PAGE_SIZES,
  selectPlacements,
  type PlacementQuery,
} from '../src/features/admin/placement/PlacementAdmin';
import {
  classLabel,
  countLabel,
  envelopeSection,
  gatedAmount,
  loadEnvelope,
  storageCeiling,
  storageRemaining,
  storageState,
  unitLabel,
  usageState,
} from '../src/features/admin/users/ResourceEnvelope';

/*
 * The Admin placement register.
 *
 * This suite drives the surface through the smallest DOM the component uses —
 * `element`, `text`, and `button` build nodes and read `textContent` — so the
 * assertions are on what an operator would read: the recorded class, the
 * explicit unknown where no decision exists, and a bounded page of rows.
 */

type RequestRecord = { url: string; init: RequestInit };

// -- The minimal DOM the Admin helpers build against ------------------------

class FakeNode {
  parent: FakeNode | null = null;
  children: FakeNode[] = [];
  ownText = '';
  constructor(readonly tagName: string) {}
  append(...nodes: Array<FakeNode | string>): this {
    for (const child of nodes) {
      const node = typeof child === 'string' ? new FakeText(child) : child;
      node.parent = this;
      this.children.push(node);
    }
    return this;
  }
  replaceChildren(...nodes: Array<FakeNode | string>): void {
    this.children = [];
    this.append(...nodes);
  }
  prepend(...nodes: Array<FakeNode | string>): void {
    const existing = this.children;
    this.children = [];
    this.append(...nodes, ...existing);
  }
  get childNodes(): FakeNode[] { return this.children; }
  get firstChild(): FakeNode | null { return this.children[0] ?? null; }
  set textContent(value: string) { this.children = []; this.ownText = value; }
  get textContent(): string { return this.ownText + this.children.map(child => child.textContent).join(''); }
  querySelectorAll<T extends FakeNode>(tag: string): T[] {
    const found: FakeNode[] = [];
    for (const child of this.children) {
      if (child.tagName === tag) found.push(child);
      found.push(...child.querySelectorAll(tag));
    }
    return found as T[];
  }
  querySelector<T extends FakeNode>(tag: string): T | null {
    return this.querySelectorAll<T>(tag)[0] ?? null;
  }
  addEventListener(): void {}
  removeEventListener(): void {}
}

class FakeText extends FakeNode {
  constructor(text: string) { super('#text'); this.ownText = text; }
}

class FakeElement extends FakeNode {
  className = '';
  dataset: Record<string, string> = {};
  hidden = false;
  disabled = false;
  readonly style = { setProperty: (): void => undefined };
  readonly classList = {
    add: (...names: string[]) => { this.className = [this.className, ...names].filter(Boolean).join(' '); },
    remove: (...names: string[]) => { this.className = this.className.split(' ').filter(name => !names.includes(name)).join(' '); },
    toggle: (name: string, force?: boolean) => {
      const on = force ?? !this.className.split(' ').includes(name);
      if (on) this.classList.add(name); else this.classList.remove(name);
    },
  };
  constructor(tagName: string) { super(tagName); }
}

beforeEach(() => {
  vi.stubGlobal('Node', FakeNode);
  vi.stubGlobal('document', {
    createElement: (tagName: string) => new FakeElement(tagName),
    createTextNode: (value: string) => new FakeText(value),
  });
});

afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

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

const query = (overrides: Partial<PlacementQuery> = {}): PlacementQuery =>
  ({ query: '', state: 'all', record: 'all', sort: 'submitted', ...overrides });

const accelerator = (overrides: Partial<ExecutionClass> = {}): ExecutionClass => ({
  id: 'accelerator|gpu|a100x2',
  state: 'accelerator',
  partition: 'gpu',
  device_class: 'a100',
  device_count: 2,
  qos: 'high',
  constraint: 'vram80',
  account: 'science',
  exclusive: true,
  ...overrides,
});

const cpu = (): ExecutionClass => ({
  id: 'cpu|normal|none',
  state: 'cpu',
  partition: 'normal',
  device_class: null,
  device_count: 0,
  qos: null,
  constraint: null,
  account: null,
  exclusive: false,
});

const task = (overrides: Partial<TaskSummary> = {}): TaskSummary => ({
  task_id: 'a'.repeat(32),
  task_type: 'sequence_demo',
  display_name: 'model.fasta',
  status: 'finished',
  terminal: true,
  submitted_at: '2026-10-01T10:00:00Z',
  finished_at: '2026-10-01T10:10:00Z',
  walltime_seconds: 600,
  owner: null,
  placement: null,
  progress: null,
  outcome: 'SUCCESS',
  error: null,
  result: { available: true, publication: 'available', page_url: '/result', manifest_url: '/manifest', archive_ready: false, archive_request_allowed: true, archive_request_url: '/archive', download_url: null },
  actions: { cancel: { allowed: false, url: '/cancel' }, delete: { allowed: true, url: '/delete' } },
  input_preview: null,
  ...overrides,
});

/** The rendered cells of one row, as an operator reads them. */
function cellsOf(node: FakeNode): string[] {
  return node.querySelectorAll<FakeNode>('td').map(cell => cell.textContent.trim());
}

describe('recorded placement facts', () => {
  it('names the recorded class and never derives one for a Task that has none', () => {
    const placement = accelerator();
    expect(placementLabel(placement)).toBe('accelerator|gpu|a100x2');
    expect(placementStateLabel(placement)).toBe('Accelerator');
    expect(placementQueue(placement)).toBe('gpu');
    expect(placementDevice(placement)).toBe('a100 × 2');
    expect(placementExclusive(placement)).toBe('Exclusive');
    expect(placementLabel(null)).toBe('Not recorded');
    expect(placementQueue(cpu())).toBe('normal');
    expect(placementDevice(cpu())).toBe('None');
  });

  it('keeps an unrecorded placement out of a CPU-state filter', () => {
    const recorded = task({ task_id: 'b'.repeat(32), placement: cpu() });
    const unrecorded = task();
    // An unknown class is not a CPU class: the filter must not invent one.
    expect(selectPlacements([recorded, unrecorded], query({ state: 'cpu' })).map(row => row.task_id)).toEqual(['b'.repeat(32)]);
    expect(selectPlacements([recorded, unrecorded], query({ state: 'accelerator' }))).toEqual([]);
    expect(selectPlacements([recorded, unrecorded], query({ record: 'unrecorded' })).map(row => row.task_id)).toEqual(['a'.repeat(32)]);
    expect(selectPlacements([recorded, unrecorded], query({ record: 'recorded' })).map(row => row.task_id)).toEqual(['b'.repeat(32)]);
  });

  it('names an unset scheduler field as unset rather than as a blank or a zero', () => {
    expect(placementSchedulerField(null)).toBe('Not set');
    expect(placementSchedulerField('')).toBe('Not set');
    expect(placementSchedulerField('high')).toBe('high');
    expect(placementDevice({ ...cpu(), state: 'accelerator', device_class: null, device_count: 1 })).toBe('Untyped × 1');
    expect(formatWalltime(3725)).toBe('1h 2m 5s');
    expect(formatWalltime(45)).toBe('45s');
  });

  it('reads the Task register and one admin resource envelope from the declared endpoints', async () => {
    const { requests } = mockApi({ tasks: [task({ placement: cpu(), owner: 'ada' })] });
    await expect(adminApi.listTasks()).resolves.toHaveLength(1);
    expect(requests[0]!.url).toBe('/compute/api/tasks');

    const { requests: entitlementRequests } = mockApi({
      subject_type: 'user', subject_id: 4, period: '2026-10',
      compute: [], storage: { logical_owned_bytes: 0, soft_limit_bytes: null, remaining_bytes: null, over_soft_limit: false },
    });
    await expect(adminApi.getUserEntitlement(4)).resolves.toMatchObject({ subject_id: 4, period: '2026-10' });
    expect(entitlementRequests[0]!.url).toBe('/compute/api/auth/admin/users/4/resource-entitlement');
  });

  it('renders the envelope section from a mocked endpoint, and its failure reason when it cannot', async () => {
    mockApi({ subject_type: 'user', subject_id: 9, period: '2026-10', compute: [], storage: { logical_owned_bytes: 0, soft_limit_bytes: 4 * 1024 ** 3, remaining_bytes: 4 * 1024 ** 3, over_soft_limit: false } });
    const section = (await loadEnvelope(9)) as unknown as FakeNode;
    expect(section.textContent).toContain('2026-10');
    expect(section.textContent).toContain('No compute entitlement is recorded for this user.');

    clearSessionCredential();
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/compute/api/auth/token')) return new Response(JSON.stringify({ token: 'admin-token' }), { status: 200 });
      return new Response(JSON.stringify({ error: 'User not found' }), { status: 404, headers: { 'content-type': 'application/json' } });
    }));
    const failed = (await loadEnvelope(9)) as unknown as FakeNode;
    expect(failed.textContent).toContain('User not found');
  });
});

describe('bounded register rendering', () => {
  it('pages a large register so the DOM never grows with the data', () => {
    const rows = Array.from({ length: 137 }, (_, index) => index);
    const first = pageOf(rows, 1, 50);
    expect(first.rows).toHaveLength(50);
    expect([first.page, first.pages]).toEqual([1, 3]);
    expect(pageSummary(first)).toBe('Showing 1–50 of 137 tasks');

    const last = pageOf(rows, 3, 50);
    expect(last.rows).toHaveLength(37);
    expect([last.first, last.last]).toEqual([101, 137]);
    expect(pageOf(rows, 99, 50).page).toBe(3);
    expect(PLACEMENT_PAGE_SIZES).toContain(50);
  });

  it('renders one bounded page of rows with the page state visible in the DOM', async () => {
    const tasks = Array.from({ length: 120 }, (_, index) => task({
      task_id: String(index).padStart(32, '0'),
      display_name: `task ${index}`,
      placement: index % 2 ? cpu() : null,
    }));
    mockApi({ tasks });
    const admin = new PlacementAdmin();
    admin.setConfiguration({ resources: { slurm_execution_classes: 'cpu=normal;a100=gpu' } } as unknown as AdminConfiguration);
    const root = new FakeElement('main');
    await admin.mount(root as unknown as HTMLElement);

    const body = root.querySelector<FakeNode>('tbody')!;
    const rows = body.querySelectorAll<FakeNode>('tr');
    // A 120-task register renders one page, not the whole register.
    expect(rows).toHaveLength(50);
    expect(root.querySelectorAll<FakeNode>('tr')[0]!.textContent).toContain('Execution class');

    const state = root.querySelectorAll<FakeNode>('span').map(node => node.textContent);
    expect(state.join(' ')).toContain('Showing 1–50 of 120 tasks');
    expect(state.join(' ')).toContain('Page 1 of 3');
    expect(state.join(' ')).toContain('120 of 120 tasks');
  });

  it('states an unrecorded Task as unrecorded in every placement column', async () => {
    mockApi({ tasks: [task()] });
    const admin = new PlacementAdmin();
    const root = new FakeElement('main');
    await admin.mount(root as unknown as HTMLElement);
    const row = root.querySelector<FakeNode>('tbody')!.querySelectorAll<FakeNode>('tr')[0]!;
    const cells = cellsOf(row);
    expect(cells).toHaveLength(13);
    expect(cells[4]).toBe('Not recordedNo recorded execution class');
    // No column asserts a queue, a device, a QoS, a constraint, an account, or
    // exclusivity for a Task whose decision the server does not have.
    expect(cells.slice(5, 11)).toEqual(Array.from({ length: 6 }, () => 'Unknown'));
    expect(cells).not.toContain('0');
  });

  it('renders a recorded class and reports an unknown runtime rather than zero', async () => {
    mockApi({ tasks: [task({ placement: accelerator(), owner: 'ada', walltime_seconds: null })] });
    const admin = new PlacementAdmin();
    const root = new FakeElement('main');
    await admin.mount(root as unknown as HTMLElement);
    const cells = cellsOf(root.querySelector<FakeNode>('tbody')!.querySelectorAll<FakeNode>('tr')[0]!);
    expect(cells[1]).toBe('sequence_demo');
    expect(cells[2]).toBe('ada');
    expect(cells[4]).toBe('accelerator|gpu|a100x2Accelerator');
    expect(cells[5]).toBe('gpu');
    expect(cells[6]).toBe('a100 × 2');
    expect(cells[7]).toBe('high');
    expect(cells[10]).toBe('Exclusive');
    // The server has not reported a runtime; it is not a recorded zero.
    expect(cells[12]).toBe('Not recorded');
    expect(cells).not.toContain('0');
  });
});

describe('admin gating', () => {
  it('refuses the Admin surface to a non-administrator without loading any endpoint', async () => {
    const { requests } = mockApi({ tasks: [] });
    const outlet = new FakeElement('div');
    await mountAdmin(
      outlet as unknown as HTMLElement,
      'admin-configuration',
      { outlet, notify: vi.fn(), setUser: vi.fn() } as never,
      { role: 'user', username: 'tester' } as never,
    );
    expect(outlet.textContent).toContain('Administrator access required');
    expect(requests).toEqual([]);
  });
});

describe('canonical resource envelope, read only', () => {
  const envelope = (overrides: Partial<ResourceEntitlement> = {}): ResourceEntitlement => ({
    subject_type: 'user',
    subject_id: 4,
    period: '2026-10',
    compute: [{
      unit: 'gpu_second', resource_class: '', enforced: true, allowance: 36000, used: 1200,
      reserved: 0, unsettled_allocations: 0, unsettled_quantity: 0, remaining: 34800,
      usage_complete: true, evidence_sources: ['ledger'],
    }],
    storage: { logical_owned_bytes: 2 * 1024 ** 3, soft_limit_bytes: 10 * 1024 ** 3, remaining_bytes: 8 * 1024 ** 3, over_soft_limit: false },
    ...overrides,
  });

  it('reports an ungated unit as not gated rather than as a zero balance', () => {
    expect(gatedAmount(null)).toBe('Not gated');
    expect(gatedAmount(0)).toBe('0');
    expect(classLabel({ unit: 'gpu_second', resource_class: '' } as ComputeEntitlement)).toBe('Any class');
    expect(classLabel({ unit: 'gpu_second', resource_class: 'a100' } as ComputeEntitlement)).toBe('a100');
    expect(unitLabel('cpu_core_second')).toBe('CPU core seconds');
    expect(countLabel(1200)).toBe('1,200');
  });

  it('states that a balance is not yet exact, with the outstanding quantity', () => {
    const settled = { unit: 'gpu_second', unsettled_allocations: 0, unsettled_quantity: 0, usage_complete: true } as ComputeEntitlement;
    const unsettled = { unit: 'gpu_second', unsettled_allocations: 2, unsettled_quantity: 900, usage_complete: false } as ComputeEntitlement;
    const incomplete = { unit: 'gpu_second', unsettled_allocations: 0, unsettled_quantity: 0, usage_complete: false } as ComputeEntitlement;
    expect(usageState(settled)).toBe('Complete');
    expect(usageState(unsettled)).toBe('Incomplete · 2 allocation(s) unsettled');
    expect(usageState(incomplete)).toBe('Incomplete');
  });

  it('names an unconfigured storage ceiling rather than reporting zero bytes', () => {
    expect(storageCeiling({ logical_owned_bytes: 0, soft_limit_bytes: null, remaining_bytes: null, over_soft_limit: false })).toBe('Not configured');
    expect(storageRemaining({ logical_owned_bytes: 0, soft_limit_bytes: null, remaining_bytes: null, over_soft_limit: false })).toBe('Not limited');
    expect(storageState({ logical_owned_bytes: 0, soft_limit_bytes: null, remaining_bytes: null, over_soft_limit: false })).toBe('Within ceiling');
    expect(storageState({ logical_owned_bytes: 11, soft_limit_bytes: 10, remaining_bytes: -1, over_soft_limit: true })).toBe('Over ceiling');
    expect(storageCeiling({ logical_owned_bytes: 0, soft_limit_bytes: 10 * 1024 ** 3, remaining_bytes: 10 * 1024 ** 3, over_soft_limit: false })).toBe('10 GiB');
  });

  it('renders the envelope the decision is read from, with no editing control', () => {
    // Reuse the browser DOM names the querySelector contract types against, while
    // the tree itself is the fake the stub document built.
    const section = envelopeSection('2026-10', envelope()) as unknown as FakeNode;
    const rows = section.querySelectorAll<FakeNode>('tr');
    expect(rows).toHaveLength(2);
    expect(rows[1]!.textContent).toContain('GPU seconds');
    expect(rows[1]!.textContent).toContain('36,000');
    expect(rows[1]!.textContent).toContain('34,800');
    expect(section.textContent).toContain('2026-10');
    expect(section.textContent).toContain('2.0 GiB');
    // Read-only: nothing in the section commits a change.
    expect(section.querySelectorAll<FakeNode>('button')).toEqual([]);
    expect(section.querySelectorAll<FakeNode>('input')).toEqual([]);
  });
});
