/*
 * The Quota page: the reader's own resource position, read-only.
 *
 * One account's compute entitlement, its durable-storage ownership, and the
 * append-only ledger behind both are rendered here from this account's own
 * endpoints. The same canonical projection an administrator's drill-in reads is
 * what this page reads — from endpoints scoped to the reader rather than to an
 * operator — so a user and an operator can never be shown two different
 * positions. Nothing is re-derived: the envelope is what admission decides
 * against, the ledger rows are the immutable facts, and every amount is the
 * server's own.
 *
 * Three facts are deliberately kept apart, because collapsing any of them into a
 * percentage would state something the server never said:
 *
 * * a unit with no allowance is not a zero balance — it is ungated, and it has no
 *   denominator to draw a bar against;
 * * a balance whose authoritative measurement has not arrived is a lower bound —
 *   the bar's reserve is real but the settled fill is incomplete, so the reader
 *   is told the usage is incomplete rather than shown a final number;
 * * usage the ledger did not attribute to a Task stays in the register labelled
 *   *unattributed*, so a bounded page is never read as a complete attribution.
 *
 * This surface only reads. Users cannot mutate a policy from here: a quota change
 * is an audited administrator act made through the endpoint that owns it.
 */

import type {
  GPUCreditWaterfall,
  ResourceEntitlement,
  ResourceLedger,
  ResourceLedgerEntry,
} from '../../api/app-api';
import { getResourceEntitlement, getResourceLedger } from '../../api/app-api';
import { t } from '../../app/i18n';
import { ApiError } from '../../app/session';
import type { AppShell } from '../../app/shell';
import { countLabel, envelopeSection, unitLabel } from './envelope';
import { adminApi } from '../admin/api';
import { element, empty, formatBytes, formatCredits, formatDate, text } from '../../components/dom';
import '../profile/account.css';
import './quota.css';

/** A bar ready to draw, or the explicit statement that no bar is meaningful. */
export type QuotaBar =
  | { kind: 'bar'; usedPercent: number; reservedPercent: number; over: boolean }
  | { kind: 'text'; reason: string };

/**
 * The stacked bar for one entitlement, drawn only against a finite denominator.
 *
 * The bands are settled usage and the reserve held for usage whose authoritative
 * measurement has not arrived; both are drawn against the allowance and never
 * renormalized to each other. An overdraft extends past the track rather than
 * being clamped back to full, and a unit with no allowance or a non-positive
 * allowance is reported as text — a percentage would be a number the server never
 * computed.
 */
export function quotaBar(entitlement: ResourceEntitlement['compute'][number]): QuotaBar {
  const allowance = entitlement.allowance;
  if (allowance === null) return { kind: 'text', reason: t('quota.bar.ungated') };
  if (allowance <= 0) {
    // A granted zero is an enforced zero, not an absence of a ceiling: admission
    // refuses a draw against this unit, so a bar (100% of nothing) would report a
    // ratio the server never computed and the copy must not read as "ungated".
    return {
      kind: 'text',
      reason: entitlement.used || entitlement.reserved
        ? t('quota.bar.zeroWithUsage')
        : t('quota.bar.zero'),
    };
  }
  const used = Math.max(0, entitlement.used);
  const reserved = Math.max(0, entitlement.reserved);
  // An overdraft is drawn past the track at its real ratio, never clamped: a bar
  // pinned to 100% would hide the amount by which the account is over.
  return {
    kind: 'bar',
    usedPercent: (used / allowance) * 100,
    reservedPercent: (reserved / allowance) * 100,
    over: used + reserved > allowance,
  };
}

/** How a ledger row names the work that consumed it, or that nothing did. */
export function attributionLabel(entry: ResourceLedgerEntry): string {
  const parts: string[] = [];
  if (entry.task_id) parts.push(entry.task_id);
  if (entry.stage_id) parts.push(entry.stage_id);
  if (entry.slurm_job_id) parts.push(t('quota.ledger.job', { id: entry.slurm_job_id }));
  return parts.length ? parts.join(' · ') : t('quota.ledger.unattributed');
}

/** Whether the ledger recorded no Task or stage for a row of consumption. */
export function isUnattributed(entry: ResourceLedgerEntry): boolean {
  return !entry.task_id && !entry.stage_id;
}

/**
 * What the ledger window says about how much of it carries an owner.
 *
 * The unattributed count is stated beside the total so a bounded page is never
 * read as a complete attribution, and a fully attributed window is still only a
 * statement about this window.
 */
export function attributionSummary(entries: ResourceLedgerEntry[]): string {
  if (!entries.length) return t('quota.ledger.empty');
  const unattributed = entries.filter(isUnattributed).length;
  const total = { count: entries.length, rows: t(entries.length === 1 ? 'quota.ledger.row' : 'quota.ledger.rows') };
  if (!unattributed) return t('quota.ledger.allNamed', total);
  return t('quota.ledger.someUnattributed', { ...total, unattributed });
}

/** The word a ledger kind is shown as, without inventing new vocabulary. */
export function kindLabel(kind: string): string {
  return kind.replaceAll('_', ' ');
}

/** The unit-and-conversion line a credit balance is only meaningful with. */
export function creditLine(summary: ResourceLedger): string {
  return t('quota.ledger.window', { limit: summary.limit, ceiling: summary.limit_ceiling });
}

/** A stacked usage bar for one entitlement, or the text that replaces it. */
function barTrack(entitlement: ResourceEntitlement['compute'][number]): HTMLElement {
  const bar = quotaBar(entitlement);
  if (bar.kind === 'text') return text('p', bar.reason, 'quota-bar-note');
  // The row holds the allowance track plus, when the account is over, the overage
  // band that carries whatever exceeds the allowance. The track is always exactly
  // the allowance, so its own bands are clamped to it; the overage band past it is
  // sized by the fraction over 100% and therefore never folded back into the track.
  const row = element('div', 'quota-bar-row');
  const track = element('div', `quota-bar${bar.over ? ' is-over' : ''}`);
  const total = bar.usedPercent + bar.reservedPercent;
  // The row states the whole position: the track holds the allowance's own width
  // and the overage band takes the rest, so an overdraw is drawn past the track
  // rather than clamped into it. ``--quota-total`` is used+reserved as a fraction
  // of the allowance (100% -> 1), which the row's own flex sizing reads.
  row.style.setProperty('--quota-total', String(total / 100));
  const settled = element('div', 'quota-bar-used');
  settled.style.setProperty('width', `${bar.usedPercent}%`);
  const reserved = element('div', 'quota-bar-reserved');
  reserved.style.setProperty('width', `${bar.reservedPercent}%`);
  track.append(settled, reserved);
  row.append(track);
  if (bar.over) row.append(element('div', 'quota-bar-overage'));
  track.setAttribute('role', 'img');
  track.setAttribute(
    'aria-label',
    t(bar.over ? 'quota.bar.ariaOver' : 'quota.bar.aria', {
      used: bar.usedPercent.toFixed(1),
      reserved: bar.reservedPercent.toFixed(1),
      total: total.toFixed(1),
    }),
  );
  return row;
}

/** The bar panel: one row per gated-or-ungated unit, each stating its own bands. */
export function quotaBars(envelope: ResourceEntitlement): HTMLElement {
  const bars = element('div', 'quota-bars');
  for (const entry of envelope.compute) {
    const item = element('div', 'quota-bar-item');
    item.append(text('h4', `${unitLabel(entry.unit)} · ${entry.resource_class || t('quota.bar.anyClass')}`), barTrack(entry));
    const bar = quotaBar(entry);
    if (bar.kind === 'text') item.append(text('p', t('quota.bar.recorded', { used: countLabel(entry.used), reserved: countLabel(entry.reserved) }), 'quota-bar-note'));
    if (bar.kind === 'bar') {
      item.append(text(
        'p',
        `${t('quota.bar.settled', { used: countLabel(entry.used), reserved: countLabel(entry.reserved), allowance: countLabel(entry.allowance ?? 0) })}${bar.over ? t('quota.bar.overSuffix') : ''}`,
        'quota-bar-note',
      ));
    }
    if (!entry.usage_complete) {
      item.append(text('p', t('quota.bar.incomplete'), 'quota-bar-note'));
    }
    bars.append(item);
  }
  return bars;
}

/** The append-only ledger register, with unattributed rows labelled as such. */
export function quotaLedgerSection(ledger: ResourceLedger): HTMLElement {
  const section = element('section', 'quota-ledger');
  // The waterfall links here as the raw facts behind every plotted step.
  section.id = 'ledger';
  section.append(
    text('h2', t('quota.ledger.heading', { period: ledger.period })),
    text('p', attributionSummary(ledger.entries), 'admin-dialog-copy'),
  );
  if (!ledger.entries.length) {
    section.append(empty(t('quota.ledger.empty')));
    return section;
  }
  const table = element('table', 'admin-table quota-ledger-table');
  const head = element('thead');
  head.append(element('tr', '', [
    t('quota.ledger.when'),
    t('quota.ledger.kind'),
    t('quota.ledger.unit'),
    t('quota.ledger.amount'),
    t('quota.ledger.attribution'),
  ].map(label => text('th', label))));
  const body = element('tbody');
  for (const entry of ledger.entries) {
    const amount = entry.unit === 'storage_byte' ? formatBytes(entry.quantity) : countLabel(entry.quantity);
    const attribution = element('td', isUnattributed(entry) ? 'quota-unattributed' : '');
    attribution.append(text('span', attributionLabel(entry)));
    if (entry.resource_class) attribution.append(text('small', entry.resource_class));
    if (entry.reason) attribution.append(text('small', entry.reason));
    const row = element('tr', '', [
      text('td', formatDate(entry.created_at)),
      text('td', kindLabel(entry.kind)),
      text('td', unitLabel(entry.unit)),
      text('td', amount),
      attribution,
    ]);
    row.id = `ledger-entry-${entry.id}`;
    body.append(row);
  }
  table.append(head, body);
  section.append(element('div', 'admin-table-scroll', [table]));
  section.append(text('p', creditLine(ledger), 'quota-window-note'));
  return section;
}

/**
 * A timestamp as explicit UTC, never as the reader's unstated local zone.
 *
 * The ledger orders by UTC and the period boundary is UTC, so a chart that
 * printed local time without saying so would place a fact on a different month
 * than the one it was charged to.  ``toISOString`` is the same instant in UTC on
 * every device.
 */
export function formatUtc(seconds: number): string {
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return t('quota.waterfall.notRecorded');
  return `${date.toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

/**
 * GPU-seconds as the published credit unit.
 *
 * The arithmetic stays integer GPU-seconds; this is the only place a displayed
 * credit amount is derived, and the exact seconds remain in the accessible
 * description so a reader can check the server's own numbers.
 */
export function creditAmount(seconds: number, signed = false): string {
  return `${formatCredits(seconds / 60, signed)} ${t('quota.waterfall.credits')}`;
}

/** How one plotted step names the work behind it, with an explicit unknown. */
function waterfallAttribution(entry: ResourceLedgerEntry | undefined): HTMLElement {
  const cell = element('td', 'quota-waterfall-attribution');
  if (!entry || (!entry.task_id && !entry.stage_id && !entry.slurm_job_id)) {
    cell.className = 'quota-waterfall-attribution quota-waterfall-unattributed';
    cell.append(text('span', t('quota.waterfall.unattributed')));
    return cell;
  }
  if (entry.task_id) {
    const link = element('a', 'quota-waterfall-task');
    link.setAttribute('href', `/compute/results/${entry.task_id}`);
    link.textContent = t('quota.waterfall.task', { id: entry.task_id });
    cell.append(link);
  }
  if (entry.stage_id) cell.append(text('span', t('quota.waterfall.stage', { id: entry.stage_id })));
  if (entry.slurm_job_id) cell.append(text('span', t('quota.waterfall.jobEvidence', { id: entry.slurm_job_id })));
  return cell;
}

/** The period position beside the waterfall, in the same credit unit. */
function waterfallSummary(waterfall: GPUCreditWaterfall): HTMLElement {
  const list = element('dl', 'quota-waterfall-summary');
  const summary = waterfall.summary;
  const fact = (label: string, value: string, negative = false): HTMLElement => {
    const item = element('div', negative ? 'is-negative' : '');
    item.append(text('dt', label), text('dd', value));
    return item;
  };
  list.append(
    fact(t('quota.waterfall.opening'), creditAmount(waterfall.opening_gpu_seconds), waterfall.opening_gpu_seconds < 0),
    fact(t('quota.waterfall.closing'), creditAmount(waterfall.closing_gpu_seconds), waterfall.closing_gpu_seconds < 0),
    fact(t('quota.waterfall.reserved'), creditAmount(summary.reserved_gpu_seconds)),
    fact(
      t('quota.waterfall.unsettled'),
      t('quota.waterfall.unsettledValue', {
        count: summary.unsettled_allocations,
        credits: creditAmount(summary.unsettled_gpu_seconds),
      }),
    ),
    fact(
      t('quota.waterfall.remaining'),
      summary.remaining_gpu_seconds === null
        ? t('quota.gated.notGated')
        : creditAmount(summary.remaining_gpu_seconds),
      (summary.remaining_gpu_seconds ?? 0) < 0,
    ),
  );
  return list;
}

/**
 * The cumulative GPU credit waterfall: opening, signed steps, and closing.
 *
 * Every number is the server's: the opening is the authoritative sum of the
 * facts the bounded window omits, each step's delta is the stored signed
 * quantity, and the closing reconciles to the same summary the bars read. A
 * window that does not hold every fact says so, so a bounded page is never read
 * as a complete history or as a zero balance. Reservations and unsettled
 * allocations are shown beside the settled balance and labelled as live
 * admission state rather than ledger entries, because a release changes what is
 * available without appending a fact.
 */
export function waterfallSection(
  waterfall: GPUCreditWaterfall,
  entries: ResourceLedgerEntry[] = [],
  period = '',
): HTMLElement {
  const section = element('section', 'quota-waterfall');
  const headingId = 'quota-waterfall-heading';
  const heading = text('h2', t('quota.waterfall.heading'));
  heading.id = headingId;
  section.setAttribute('aria-labelledby', headingId);
  section.append(
    heading,
    text('p', t('quota.waterfall.description'), 'admin-dialog-copy'),
    waterfallSummary(waterfall),
  );

  if (!waterfall.complete) {
    section.append(text(
      'p',
      t('quota.waterfall.partial', { shown: waterfall.entry_count, total: waterfall.total_entry_count }),
      'quota-waterfall-note',
    ));
  }
  if (!waterfall.summary.reconciled) {
    section.append(text('p', t('quota.waterfall.mismatch'), 'quota-waterfall-note is-negative'));
  }
  if (!waterfall.summary.usage_complete) {
    section.append(text('p', t('quota.bar.incomplete'), 'quota-waterfall-note'));
  }
  if (waterfall.closing_gpu_seconds < 0) {
    section.append(text('p', t('quota.waterfall.negative'), 'quota-waterfall-note is-negative'));
  }
  section.append(text('p', t('quota.waterfall.commitments'), 'quota-waterfall-note'));
  const status = text('p', t('quota.waterfall.loaded', { count: waterfall.entry_count }), 'quota-waterfall-status');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  section.append(status);

  const table = element('table', 'admin-table quota-waterfall-table');
  table.append(text('caption', t('quota.waterfall.caption', { period })));
  const head = element('thead');
  head.append(element('tr', '', [
    t('quota.waterfall.col.when'),
    t('quota.waterfall.col.kind'),
    t('quota.waterfall.col.delta'),
    t('quota.waterfall.col.balance'),
    t('quota.waterfall.col.attribution'),
  ].map(label => {
    const cell = text('th', label);
    cell.setAttribute('scope', 'col');
    return cell;
  })));

  const body = element('tbody');
  const byId = new Map(entries.map(entry => [entry.id, entry]));
  const openingRow = element('tr', 'quota-waterfall-opening');
  const openingHeader = text('th', t('quota.waterfall.opening'));
  openingHeader.setAttribute('scope', 'row');
  openingRow.append(
    openingHeader,
    text('td', ''),
    text('td', ''),
    text('td', creditAmount(waterfall.opening_gpu_seconds), waterfall.opening_gpu_seconds < 0 ? 'is-negative' : ''),
    text('td', t('quota.waterfall.openingAnchor')),
  );
  body.append(openingRow);
  for (const step of waterfall.steps) {
    const entry = byId.get(step.entry_id);
    const negative = step.balance_gpu_seconds < 0;
    const row = element('tr', negative ? 'is-negative' : '');
    const when = text('th', entry ? formatUtc(entry.created_at) : t('quota.waterfall.notRecorded'));
    when.setAttribute('scope', 'row');
    const delta = text(
      'td',
      creditAmount(step.delta_gpu_seconds, true),
      step.delta_gpu_seconds < 0 ? 'is-negative' : 'is-positive',
    );
    delta.setAttribute(
      'aria-label',
      t('quota.waterfall.deltaAria', {
        credits: creditAmount(step.delta_gpu_seconds, true),
        seconds: step.delta_gpu_seconds,
        balance: creditAmount(step.balance_gpu_seconds),
      }),
    );
    row.append(
      when,
      text('td', entry ? kindLabel(entry.kind) : t('quota.waterfall.unknownKind')),
      delta,
      text('td', creditAmount(step.balance_gpu_seconds), negative ? 'is-negative' : ''),
      waterfallAttribution(entry),
    );
    body.append(row);
  }
  const foot = element('tfoot');
  const closingRow = element('tr', 'quota-waterfall-closing');
  const closingHeader = text('th', t('quota.waterfall.closing'));
  closingHeader.setAttribute('scope', 'row');
  closingRow.append(
    closingHeader,
    text('td', ''),
    text('td', ''),
    text('td', creditAmount(waterfall.closing_gpu_seconds), waterfall.closing_gpu_seconds < 0 ? 'is-negative' : ''),
    text('td', ''),
  );
  foot.append(closingRow);
  table.append(head, body, foot);
  section.append(element('div', 'admin-table-scroll', [table]));

  const raw = element('p', 'quota-waterfall-raw');
  const rawLink = element('a');
  rawLink.setAttribute('href', '#ledger');
  rawLink.textContent = t('quota.waterfall.rawLedger');
  raw.append(rawLink);
  section.append(raw);
  return section;
}

/**
 * The complete read-only position of one account.
 *
 * One renderer for both readers: the shortfall between the user's own view and an
 * administrator's drill-in is which authorized endpoint supplied the same facts,
 * never how they are drawn. The compute table is the canonical envelope section
 * the Admin drill-in already served, so an operator comparing the two sees the
 * identical projection rather than a second one.
 */
export function quotaPosition(envelope: ResourceEntitlement, ledger: ResourceLedger): HTMLElement {
  const root = element('div', 'quota-position');
  const storage = element('section', 'quota-storage-overview');
  storage.append(text('h3', t('quota.storage.heading')), text('p', `${t('quota.storage.owned')}: ${formatBytes(envelope.storage.logical_owned_bytes)}`, 'quota-storage-value'));
  storage.append(text('p', envelope.storage.soft_limit_bytes === null ? t('quota.storage.notConfigured') : `${t('quota.storage.ceiling')}: ${formatBytes(envelope.storage.soft_limit_bytes)}`, 'quota-bar-note'));
  const policy = element('details', 'quota-policy');
  policy.append(text('summary', t('quota.envelope.heading')), envelopeSection(envelope.period, envelope));
  root.append(
    text('h3', t('quota.usage.heading')),
    quotaBars(envelope),
    waterfallSection(ledger.gpu_waterfall, ledger.entries, ledger.period),
    storage,
    policy,
    quotaLedgerSection(ledger),
  );
  return root;
}

/**
 * The Account quota workspace: the reader's own position, read-only.
 *
 * The page owns its single `main` and its own `h1`, exactly as every other route
 * does, so the router names the document and lands focus on this page's identity
 * rather than leaving the previous route's page behind. It returns itself so the
 * route that mounted it has something to dispose: the reader can leave while the
 * reads are still in flight, and the mount that loses that race is released in
 * full instead of writing into a region no longer in the document.
 */
export class QuotaView {
  private readonly root: HTMLElement;
  private readonly body: HTMLElement;

  constructor() {
    const section = element('section', 'account-section');
    section.dataset.section = 'quota';
    section.append(element('header', '', [text('h1', t('quota.title')), text('p', t('quota.description'))]));
    this.body = element('div', 'quota-body', [empty(t('quota.loading'))]);
    section.append(this.body);
    this.root = element('main', 'account-page quota-page', [section]);
  }

  /** Build the page and read this account's own position into it. */
  async mount(outlet: HTMLElement): Promise<void> {
    outlet.replaceChildren(this.root);
    try {
      const [entitlement, ledger] = await Promise.all([getResourceEntitlement(), getResourceLedger()]);
      this.body.replaceChildren(quotaPosition(entitlement, ledger));
    } catch (error) {
      const message = error instanceof ApiError && error.status === 503
        ? t('quota.error.policy')
        : (error as Error).message || t('quota.error.generic');
      this.body.replaceChildren(empty(message, true));
    }
  }

  /** Release the page. The reads own no subscription; the region leaves with the route. */
  destroy(): void {
    this.root.remove();
  }
}

/** The account's Quota page, returning the view so the route can dispose it. */
export async function mountQuotaView(outlet: HTMLElement): Promise<QuotaView> {
  const view = new QuotaView();
  await view.mount(outlet);
  return view;
}

/** The administrator's drill-in: the identical position, from the Admin report. */
export async function loadAdminQuota(userId: number): Promise<HTMLElement> {
  try {
    const report = await adminApi.getResourceReport(userId);
    // The report serves the same canonical ledger window the user's own endpoint
    // does — entries, chronological order, and the GPU waterfall — so the two
    // readers are held to one shape by construction.
    const ledger = report.ledger as unknown as ResourceLedger;
    return quotaPosition(report.canonical_envelope, ledger);
  } catch (error) {
    return empty((error as Error).message || t('quota.error.admin'), true);
  }
}
