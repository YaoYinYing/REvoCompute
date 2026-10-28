import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearSessionCredential } from '../src/app/session';
import { getResourceEntitlement, getResourceLedger, type GPUCreditWaterfall, type ResourceEntitlement, type ResourceLedger } from '../src/api/app-api';
import { adminApi } from '../src/features/admin/api';
import { formatCredits } from '../src/components/dom';
import { gpuCell } from '../src/features/admin/users/UserAdmin';
import {
  attributionLabel,
  attributionSummary,
  creditAmount,
  formatUtc,
  isUnattributed,
  kindLabel,
  quotaBar,
  quotaBars,
  mountQuotaView,
  quotaLedgerSection,
  quotaPosition,
  waterfallSection,
} from '../src/features/quota/QuotaView';

/*
 * The Account Quota position's accounting facts, driven through the smallest DOM
 * the component builds against.
 *
 * The assertions are on what a reader is told, not on how it is styled: the two
 * facts the surface must never merge (a balance whose measurement has not arrived
 * versus a settled zero, and usage attributed to a Task versus usage nobody
 * attributed) are read from the rendered text, and the bar is asserted on its
 * decision rather than on a pixel width.
 */

type RequestRecord = { url: string; init: RequestInit };

class FakeNode {
  parent: FakeNode | null = null;
  children: FakeNode[] = [];
  ownText = '';
  className = '';
  private attrs = new Map<string, string>();
  readonly style = { setProperty: (): void => undefined };
  readonly dataset: Record<string, string> = {};
  constructor(readonly tagName: string) {}
  append(...nodes: Array<FakeNode | string>): this {
    for (const child of nodes) {
      const node = typeof child === 'string' ? new FakeText(child) : child;
      node.parent = this;
      this.children.push(node);
    }
    return this;
  }
  replaceChildren(...nodes: Array<FakeNode | string>): void { this.children = []; this.append(...nodes); }
  setAttribute(name: string, value: string): void { this.attrs.set(name, value); }
  getAttribute(name: string): string | null { return this.attrs.get(name) ?? null; }
  get childNodes(): FakeNode[] { return this.children; }
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
  querySelector<T extends FakeNode>(tag: string): T | null { return this.querySelectorAll<T>(tag)[0] ?? null; }
  addEventListener(): void {}
  removeEventListener(): void {}
  remove(): void {
    if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
  }
}

class FakeText extends FakeNode {
  constructor(value: string) { super('#text'); this.ownText = value; }
}

beforeEach(() => {
  vi.stubGlobal('Node', FakeNode);
  vi.stubGlobal('document', {
    createElement: (tagName: string) => new FakeNode(tagName),
    createTextNode: (value: string) => new FakeText(value),
  });
});
afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

function mockApi(
  payloads: Record<string, unknown>,
  failures: Record<string, { status: number; error: string; reason: string }> = {},
): { requests: RequestRecord[] } {
  const requests: RequestRecord[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith('/compute/api/auth/token')) return new Response(JSON.stringify({ token: 'token' }), { status: 200 });
    requests.push({ url, init });
    for (const [suffix, failure] of Object.entries(failures)) {
      if (url.endsWith(suffix) || url.includes(suffix)) {
        return new Response(
          JSON.stringify({ error: failure.error, unavailable_reason: failure.reason }),
          { status: failure.status, headers: { 'content-type': 'application/json' } },
        );
      }
    }
    for (const [suffix, payload] of Object.entries(payloads)) {
      if (url.endsWith(suffix) || url.includes(suffix)) {
        return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } });
      }
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return { requests };
}

type Compute = Parameters<typeof quotaBar>[0];

const entry = (overrides: Partial<Compute> = {}): Compute => ({
  unit: 'gpu_second',
  resource_class: '',
  enforced: true,
  allowance: 60_000,
  used: 0,
  reserved: 0,
  unsettled_allocations: 0,
  unsettled_quantity: 0,
  remaining: 60_000,
  usage_complete: true,
  evidence_sources: [],
  ...overrides,
});

const envelope = (compute: Compute[]): ResourceEntitlement => ({
  subject_type: 'user',
  subject_id: 7,
  period: '2026-10',
  compute,
  storage: { logical_owned_bytes: 0, soft_limit_bytes: null, remaining_bytes: null, over_soft_limit: false },
});

const waterfallOf = (overrides: Partial<GPUCreditWaterfall> = {}): GPUCreditWaterfall => ({
  unit: 'gpu_second',
  opening_gpu_seconds: 0,
  closing_gpu_seconds: 30_000,
  complete: true,
  truncated: false,
  entry_count: 2,
  total_entry_count: 2,
  steps: [
    { entry_id: 1, delta_gpu_seconds: 60_000, balance_gpu_seconds: 60_000 },
    { entry_id: 2, delta_gpu_seconds: -30_000, balance_gpu_seconds: 30_000 },
  ],
  summary: {
    monthly_grant_gpu_seconds: 60_000,
    usage_gpu_seconds: 30_000,
    adjustment_gpu_seconds: 0,
    settled_balance_gpu_seconds: 30_000,
    reserved_gpu_seconds: 0,
    unsettled_allocations: 0,
    unsettled_gpu_seconds: 0,
    remaining_gpu_seconds: 30_000,
    usage_complete: true,
  },
  ...overrides,
});

const ledgerOf = (
  entries: ResourceLedger['entries'],
  gpu_waterfall: GPUCreditWaterfall = waterfallOf(),
): ResourceLedger => ({
  subject_id: 7, period: '2026-10', limit: 50, limit_ceiling: 200,
  order: 'chronological', gpu_waterfall, entries,
});

const ledgerEntry = (overrides: Record<string, unknown> = {}) => ({
  id: 1, subject_type: 'user', subject_id: 7, period: '2026-10', kind: 'monthly_grant',
  unit: 'gpu_second', resource_class: '', quantity: 60_000, task_id: null, stage_id: null,
  slurm_job_id: null, actor_user_id: null, reason: null, reason_code: null,
  evidence_source: 'policy', created_at: 1_790_636_400,
  ...overrides,
}) as ResourceLedger['entries'][number];

describe('quota usage bars', () => {
  it('draws a bar only against a finite, positive denominator', () => {
    const drawn = quotaBar(entry({ used: 15_000 }));
    expect(drawn.kind).toBe('bar');
    if (drawn.kind === 'bar') expect(drawn.usedPercent).toBe(25);

    // A unit nobody gates has no denominator: it is text, never a 0% bar.
    expect(quotaBar(entry({ enforced: false, allowance: null, remaining: null })).kind).toBe('text');
    // A granted allowance of zero is a real decision, and a bar against it would
    // be a fabricated ratio.
    expect(quotaBar(entry({ allowance: 0, remaining: 0 })).kind).toBe('text');
  });

  it('states a zero allowance as an enforced ceiling, not as no ceiling at all', () => {
    // Zero and "ungated" are different facts: a zero allowance refuses new
    // consumption, while an ungated unit has no policy to enforce. Copy that
    // called zero "no ceiling applies" would tell a reader their usage is
    // unfettered at the moment admission is refusing it.
    const withUsage = quotaBar(entry({ allowance: 0, used: 4_500, remaining: 0 }));
    expect(withUsage.kind).toBe('text');
    if (withUsage.kind === 'text') {
      expect(withUsage.reason).toContain('enforced zero');
      expect(withUsage.reason).toContain('refused');
      expect(withUsage.reason).not.toContain('no ceiling');
    }
    const clean = quotaBar(entry({ allowance: 0, remaining: 0 }));
    if (clean.kind === 'text') {
      expect(clean.reason).toContain('enforced zero');
      expect(clean.reason).not.toContain('no ceiling');
    }
    // The ungated unit keeps its own, distinct wording.
    const ungated = quotaBar(entry({ enforced: false, allowance: null, remaining: null }));
    if (ungated.kind === 'text') expect(ungated.reason).toContain('Not gated');
  });

  it('shows an overdraft past the track rather than clamping it to full', () => {
    const drawn = quotaBar(entry({ used: 72_000, remaining: -12_000 }));
    expect(drawn.kind).toBe('bar');
    if (drawn.kind === 'bar') {
      expect(drawn.usedPercent).toBe(120);
      expect(drawn.over).toBe(true);
    }
  });

  it('keeps usage that has not been measured as a reserve, not as settled usage', () => {
    const drawn = quotaBar(entry({ used: 0, reserved: 6_000, unsettled_allocations: 1, unsettled_quantity: 6_000, usage_complete: false }));
    expect(drawn.kind).toBe('bar');
    if (drawn.kind === 'bar') {
      expect(drawn.usedPercent).toBe(0);
      expect(drawn.reservedPercent).toBe(10);
      expect(drawn.over).toBe(false);
    }
  });
});

describe('ledger attribution', () => {
  it('names the Task, stage, and Slurm job a row was charged to', () => {
    expect(attributionLabel({ task_id: 'a'.repeat(32), stage_id: 'model', slurm_job_id: '9711' } as never))
      .toBe(`${'a'.repeat(32)} · model · job 9711`);
    // A row with a Task but no stage still names its Task.
    expect(attributionLabel({ task_id: 'b'.repeat(32), stage_id: null, slurm_job_id: null } as never)).toBe('b'.repeat(32));
  });

  it('labels a row nobody attributed as unattributed rather than dropping it', () => {
    expect(attributionLabel({ task_id: null, stage_id: null, slurm_job_id: null } as never)).toBe('Unattributed');
    expect(isUnattributed({ task_id: null, stage_id: null } as never)).toBe(true);
    expect(isUnattributed({ task_id: 'c'.repeat(32), stage_id: null } as never)).toBe(false);
  });

  it('states how much of the window carries an owner instead of implying all of it does', () => {
    expect(attributionSummary([])).toContain('No ledger activity');
    expect(attributionSummary([{ task_id: 'a', stage_id: null }, { task_id: null, stage_id: null }] as never))
      .toContain('1 unattributed');
    // Even a fully attributed window is only a statement about the window.
    expect(attributionSummary([{ task_id: 'a', stage_id: null }] as never))
      .toContain('every one names its Task');
  });

  it('reads a ledger kind without inventing new vocabulary', () => {
    expect(kindLabel('monthly_grant')).toBe('monthly grant');
    expect(kindLabel('admin_adjustment')).toBe('admin adjustment');
  });
});

describe('the rendered position', () => {
  it('renders the compute table, the bars, and the ledger from the canonical envelope', () => {
    const position = quotaPosition(envelope([entry({ used: 30_000, remaining: 30_000 })]), ledgerOf([
      { id: 1, subject_type: 'user', subject_id: 7, period: '2026-10', kind: 'monthly_grant', unit: 'gpu_second', resource_class: '', quantity: 60_000, task_id: null, stage_id: null, slurm_job_id: null, actor_user_id: null, reason: null, reason_code: null, evidence_source: 'policy', created_at: 1 },
      { id: 2, subject_type: 'user', subject_id: 7, period: '2026-10', kind: 'usage', unit: 'gpu_second', resource_class: 'a100', quantity: 30_000, task_id: 'd'.repeat(32), stage_id: 'model', slurm_job_id: '42', actor_user_id: null, reason: null, reason_code: null, evidence_source: 'slurm_accounting', created_at: 2 },
    ]));
    const rendered = position as unknown as FakeNode;
    // The canonical envelope table's own labels survive verbatim.
    expect(rendered.textContent).toContain('Resource envelope');
    expect(rendered.textContent).toContain('GPU seconds');
    // The ledger names the unattributed grant row explicitly.
    expect(rendered.textContent).toContain('Unattributed');
    expect(rendered.textContent).toContain('monthly grant');
    expect(rendered.textContent).toContain('1 unattributed');
  });

  it('states the incomplete-usage fact beside the bar instead of a settled number', () => {
    const bars = quotaBars(envelope([entry({ reserved: 6_000, unsettled_allocations: 1, unsettled_quantity: 6_000, usage_complete: false })]));
    expect((bars as unknown as FakeNode).textContent).toContain('Usage is incomplete');
  });
});

describe('the GPU credit waterfall', () => {
  const entries = [
    ledgerEntry(),
    ledgerEntry({
      id: 2, kind: 'usage', quantity: -30_000, task_id: 'd'.repeat(32), stage_id: 'model',
      slurm_job_id: '42', evidence_source: 'slurm_accounting', created_at: 1_790_636_500,
    }),
  ];

  it('formats timestamps as explicit UTC and credits only at presentation', () => {
    expect(formatUtc(0)).toBe('1970-01-01 00:00:00 UTC');
    expect(creditAmount(120, true)).toBe('+2 credits');
    expect(creditAmount(-120)).toBe('-2 credits');
  });

  it('renders opening, signed steps, closing, and a link to the raw ledger', () => {
    const rendered = waterfallSection(waterfallOf(), entries) as unknown as FakeNode;
    const copy = rendered.textContent;
    expect(copy).toContain('Opening balance');
    expect(copy).toContain('+1,000 credits');
    expect(copy).toContain('-500 credits');
    expect(copy).toContain('Closing balance');
    // Closing reconciles to the summary the bars read.
    expect(copy).toContain(creditAmount(waterfallOf().summary.settled_balance_gpu_seconds));
    expect(copy).toContain('monthly grant');
    expect(copy).toContain(`Task ${'d'.repeat(32)}`);
    expect(copy).toContain('stage model');
    expect(copy).toContain('Scheduler job 42');
    expect(copy).toContain('View the raw append-only ledger');

    const table = rendered.querySelector('table')!;
    expect(table.querySelector('caption')!.textContent).toContain('UTC chronological order');
    // Every header declares its scope, and each row is headed by its timestamp.
    const headers = table.querySelectorAll('th');
    expect(headers.length).toBeGreaterThan(0);
    expect(headers.every(header => header.getAttribute('scope') !== null)).toBe(true);
    // The wide table's scroll container is keyboard-focusable and labelled.
    const scroll = rendered.querySelectorAll('div').find(node => node.getAttribute('tabindex') === '0');
    expect(scroll?.getAttribute('role')).toBe('region');
    expect(scroll?.getAttribute('aria-label')).toContain('arrow keys');
    expect(rendered.querySelectorAll('a').some(link => link.getAttribute('href') === '#ledger')).toBe(true);
    expect(
      rendered.querySelectorAll('a').some(link => link.getAttribute('href') === `/compute/results/${'d'.repeat(32)}`),
    ).toBe(true);
  });

  it('announces what was loaded and exposes exact GPU-seconds to screen readers', async () => {
    const rendered = waterfallSection(waterfallOf(), entries) as unknown as FakeNode;
    const status = rendered.querySelectorAll('p').find(node => node.getAttribute('role') === 'status');
    expect(status?.getAttribute('aria-live')).toBe('polite');
    // The region is empty until the microtask after insertion: a count written
    // during construction would be pre-existing text, not an announcement.
    expect(status?.textContent).toBe('');
    await Promise.resolve();
    expect(status?.textContent).toContain('2 GPU fact');
    const labels = rendered.querySelectorAll('td').map(node => node.getAttribute('aria-label') ?? '');
    expect(labels.some(label => label.includes('-500 credits (-30000 GPU-seconds)'))).toBe(true);
  });

  it('states a partial window with its verified opening instead of a zero history', () => {
    const partial = waterfallOf({
      opening_gpu_seconds: 90_000,
      closing_gpu_seconds: 120_000,
      complete: false,
      truncated: true,
      entry_count: 2,
      total_entry_count: 60,
      steps: [
        { entry_id: 1, delta_gpu_seconds: 40_000, balance_gpu_seconds: 130_000 },
        { entry_id: 2, delta_gpu_seconds: -10_000, balance_gpu_seconds: 120_000 },
      ],
      summary: { ...waterfallOf().summary, settled_balance_gpu_seconds: 120_000, remaining_gpu_seconds: 120_000 },
    });
    const rendered = waterfallSection(partial, entries) as unknown as FakeNode;
    expect(rendered.textContent).toContain('Partial history');
    expect(rendered.textContent).toContain('newest 2 of 60');
    expect(rendered.textContent).toContain('1,500 credits');
    expect(rendered.textContent).toContain('2,000 credits');
  });

  it('reports a negative balance as a recorded fact rather than clamping it', () => {
    const negative = waterfallOf({
      opening_gpu_seconds: -600,
      closing_gpu_seconds: -600,
      steps: [{ entry_id: 1, delta_gpu_seconds: -600, balance_gpu_seconds: -600 }],
      entry_count: 1,
      total_entry_count: 1,
      summary: {
        ...waterfallOf().summary,
        usage_gpu_seconds: 60_600,
        settled_balance_gpu_seconds: -600,
        remaining_gpu_seconds: -600,
      },
    });
    const rendered = waterfallSection(negative, [ledgerEntry({ quantity: -600 })]) as unknown as FakeNode;
    expect(rendered.textContent).toContain('below zero');
    expect(rendered.textContent).toContain('-10 credits');
    expect(rendered.querySelectorAll('tr').some(row => row.className.includes('is-negative'))).toBe(true);
  });

  it('names an unattributed fact explicitly instead of dropping it', () => {
    const rendered = waterfallSection(
      waterfallOf({
        closing_gpu_seconds: 60_000,
        entry_count: 1,
        total_entry_count: 1,
        steps: [{ entry_id: 1, delta_gpu_seconds: 60_000, balance_gpu_seconds: 60_000 }],
      }),
      [ledgerEntry()],
    ) as unknown as FakeNode;
    expect(rendered.textContent).toContain('Unattributed');
  });

  it('is part of the rendered account position', () => {
    const position = quotaPosition(envelope([entry({})]), ledgerOf(entries)) as unknown as FakeNode;
    expect(position.textContent).toContain('GPU credit waterfall');
  });
});

describe('quota API reads', () => {
  it('reads the canonical envelope and the account ledger from their own endpoints', async () => {
    const { requests } = mockApi({
      '/compute/api/resource-entitlement': envelope([]),
      '/compute/api/resource-ledger': ledgerOf([]),
    });
    await getResourceEntitlement();
    await getResourceLedger();
    expect(requests.map(request => request.url)).toEqual([
      '/compute/api/resource-entitlement',
      '/compute/api/resource-ledger',
    ]);
  });

  it('keeps the envelope when only the ledger read is unavailable', async () => {
    mockApi(
      {
        '/compute/api/resource-entitlement': envelope([entry({})]),
        '/compute/api/resource-ledger': ledgerOf([]),
      },
      {
        '/compute/api/resource-ledger': {
          status: 503,
          error: 'The resource ledger is unavailable.',
          reason: 'ledger_unavailable',
        },
      },
    );
    const outlet = new FakeNode('div');
    const view = await mountQuotaView(outlet as unknown as HTMLElement);
    // The succeeded read is still rendered, and the failure is named as the
    // ledger's own reason instead of sending the reader to a policy.
    expect(outlet.textContent).toContain('Usage against allowance');
    expect(outlet.textContent).toContain('Resource envelope');
    expect(outlet.textContent).toContain('GPU credit ledger is currently unavailable');
    expect(outlet.textContent).toContain('The resource ledger is unavailable.');
    expect(outlet.textContent).not.toContain('stored resource policy');
    view.destroy();
  });

  it('reads one account position through the Admin report when an operator drills in', async () => {
    const { requests } = mockApi({});
    await adminApi.getResourceReport(4, 25);
    expect(requests[0]!.url).toBe('/compute/api/auth/admin/reports/resources?subject=4&limit=25');
  });
});

/*
 * The Admin user listing's GPU cell.
 *
 * The reported defect was every listed account reading "0 credits".  The cause
 * was a projection the listing served without the credits the published
 * component requires, and the surface rendered the absent number as zero.  These
 * cases pin what the cell must show: the balance the server computed, with its
 * unit, beside the separate admission fact — and never a zero it did not receive.
 */

const listed = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  username: 'granted',
  full_name: 'Granted User',
  email: 'granted@test.local',
  affiliation: null,
  position: null,
  pi_name: null,
  role: 'user',
  registration_status: 'approved',
  user_status: 'active',
  created_at: 1,
  last_login: null,
  allow_gpu_use: false,
  gpu_credit: { remaining_credits: 1000 },
  ...overrides,
}) as never;

describe('the Admin listing GPU cell', () => {
  it('shows the balance the server computed, with its unit', () => {
    expect((gpuCell(listed()) as unknown as FakeNode).textContent).toContain('1,000 credits');
    // An overdraft is shown as the real negative balance, never clamped.
    expect((gpuCell(listed({ gpu_credit: { remaining_credits: -10 } })) as unknown as FakeNode).textContent)
      .toContain('-10 credits');
    // A granted allowance of zero is a real zero and reads as one.
    expect((gpuCell(listed({ gpu_credit: { remaining_credits: 0 } })) as unknown as FakeNode).textContent)
      .toContain('0 credits');
  });

  it('keeps admission a separate fact from the balance', () => {
    const admitted = (gpuCell(listed({ allow_gpu_use: true })) as unknown as FakeNode).textContent;
    expect(admitted).toContain('Admitted');
    expect((gpuCell(listed({ allow_gpu_use: false })) as unknown as FakeNode).textContent).toContain('Blocked');
  });

  it('never renders an absent balance as a zero the server did not report', () => {
    // The published component requires the field, so its absence is a defect to
    // see: a cell that showed "0 credits" here would report a spend on an account
    // whose position was never measured.
    const missing = (gpuCell(listed({ gpu_credit: {} })) as unknown as FakeNode).textContent;
    expect(missing).toContain('not reported');
    expect(missing).not.toContain('0 credits');
    expect(formatCredits(undefined)).toBe('not reported');
  });
});
