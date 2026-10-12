import type { ResourceEntitlement, ResourceLedger, ResourceLedgerEntry } from '../../../api/app-api';
import { getResourceEntitlement, getResourceLedger } from '../../../api/app-api';
import type { AppShell } from '../../../app/shell';
import { ApiError } from '../../../app/session';
import { adminApi } from '../api';
import { element, empty, formatBytes, formatDate, text } from '../shared/dom';
import { countLabel, envelopeSection, unitLabel } from './ResourceEnvelope';
import './quota.css';

/*
 * The Quota position of one account, read-only.
 *
 * One account's compute entitlement, its durable-storage ownership, and the
 * append-only ledger behind both are rendered here — the same canonical
 * projection an administrator's drill-in reads, from endpoints that serve the
 * same stores, so a user and an operator can never be shown two different
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
  if (allowance === null) return { kind: 'text', reason: 'Not gated: this unit has no allowance to draw against.' };
  if (allowance <= 0) {
    return {
      kind: 'text',
      reason: entitlement.used || entitlement.reserved
        ? 'No allowance is granted; usage is recorded but no ceiling applies.'
        : 'No allowance is granted for this unit.',
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
  if (entry.slurm_job_id) parts.push(`job ${entry.slurm_job_id}`);
  return parts.length ? parts.join(' · ') : 'Unattributed';
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
  if (!entries.length) return 'No ledger activity is recorded for this window.';
  const unattributed = entries.filter(isUnattributed).length;
  const suffix = entries.length === 1 ? 'row' : 'rows';
  if (!unattributed) return `${entries.length} ${suffix} in this window; every one names its Task.`;
  return `${entries.length} ${suffix} in this window; ${unattributed} unattributed.`;
}

/** The word a ledger kind is shown as, without inventing new vocabulary. */
export function kindLabel(kind: string): string {
  return kind.replaceAll('_', ' ');
}

/** The unit-and-conversion line a credit balance is only meaningful with. */
export function creditLine(summary: ResourceLedger): string {
  return `Window: newest ${summary.limit} of at most ${summary.limit_ceiling} rows.`;
}

/** A stacked usage bar for one entitlement, or the text that replaces it. */
function barTrack(entitlement: ResourceEntitlement['compute'][number]): HTMLElement {
  const bar = quotaBar(entitlement);
  if (bar.kind === 'text') return text('p', bar.reason, 'quota-bar-note');
  const track = element('div', `quota-bar${bar.over ? ' is-over' : ''}`);
  const settled = element('div', 'quota-bar-used');
  settled.style.setProperty('width', `${bar.usedPercent}%`);
  const reserved = element('div', 'quota-bar-reserved');
  reserved.style.setProperty('width', `${bar.reservedPercent}%`);
  track.append(settled, reserved);
  track.setAttribute('role', 'img');
  track.setAttribute(
    'aria-label',
    `${bar.usedPercent.toFixed(1)}% settled, ${bar.reservedPercent.toFixed(1)}% reserved${bar.over ? ', over allowance' : ''}`,
  );
  return track;
}

/** The bar panel: one row per gated-or-ungated unit, each stating its own bands. */
export function quotaBars(envelope: ResourceEntitlement): HTMLElement {
  const bars = element('div', 'quota-bars');
  for (const entry of envelope.compute) {
    const item = element('div', 'quota-bar-item');
    item.append(text('h4', `${unitLabel(entry.unit)} · ${entry.resource_class || 'any class'}`), barTrack(entry));
    const bar = quotaBar(entry);
    if (bar.kind === 'bar') {
      item.append(text(
        'p',
        `Settled ${countLabel(entry.used)} · reserved ${countLabel(entry.reserved)} of ${countLabel(entry.allowance ?? 0)}${bar.over ? ' · over allowance' : ''}`,
        'quota-bar-note',
      ));
    }
    if (!entry.usage_complete) {
      item.append(text('p', 'Usage is incomplete: authoritative measurement has not arrived for every allocation.', 'quota-bar-note'));
    }
    bars.append(item);
  }
  return bars;
}

/** The append-only ledger register, with unattributed rows labelled as such. */
export function quotaLedgerSection(ledger: ResourceLedger): HTMLElement {
  const section = element('section', 'quota-ledger');
  section.append(
    text('h2', `Ledger · ${ledger.period}`),
    text('p', attributionSummary(ledger.entries), 'admin-dialog-copy'),
  );
  if (!ledger.entries.length) {
    section.append(empty('No ledger rows are recorded for this window.'));
    return section;
  }
  const table = element('table', 'admin-table quota-ledger-table');
  const head = element('thead');
  head.append(element('tr', '', ['When', 'Kind', 'Unit', 'Amount', 'Attribution'].map(label => text('th', label))));
  const body = element('tbody');
  for (const entry of ledger.entries) {
    const amount = entry.unit === 'storage_byte' ? formatBytes(entry.quantity) : countLabel(entry.quantity);
    const attribution = element('td', isUnattributed(entry) ? 'quota-unattributed' : '');
    attribution.append(text('span', attributionLabel(entry)));
    if (entry.resource_class) attribution.append(text('small', entry.resource_class));
    if (entry.reason) attribution.append(text('small', entry.reason));
    body.append(element('tr', '', [
      text('td', formatDate(entry.created_at)),
      text('td', kindLabel(entry.kind)),
      text('td', unitLabel(entry.unit)),
      text('td', amount),
      attribution,
    ]));
  }
  table.append(head, body);
  section.append(element('div', 'admin-table-scroll', [table]));
  section.append(text('p', creditLine(ledger), 'quota-window-note'));
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
  root.append(
    envelopeSection(envelope.period, envelope),
    text('h3', 'Usage against allowance'),
    quotaBars(envelope),
    quotaLedgerSection(ledger),
  );
  return root;
}

/**
 * The Account quota workspace.
 *
 * A user's own position, read from the endpoints scoped to them: the canonical
 * resource entitlement, their append-only ledger, and the credit summary. A
 * stored policy the server refuses to interpret is reported as the bounded
 * refusal it is rather than as an empty position.
 */
export class QuotaView {
  async mount(root: HTMLElement): Promise<void> {
    root.replaceChildren(empty('Loading your resource position…'));
    try {
      const [entitlement, ledger] = await Promise.all([getResourceEntitlement(), getResourceLedger()]);
      root.replaceChildren(quotaPosition(entitlement, ledger));
    } catch (error) {
      const message = error instanceof ApiError && error.status === 503
        ? 'A stored resource policy for this account cannot be interpreted; an administrator must replace it before this view can report a position.'
        : (error as Error).message || 'Unable to load your resource position.';
      root.replaceChildren(empty(message, true));
    }
  }
}

/** The administrator's drill-in: the identical position, from the Admin report. */
export async function loadAdminQuota(userId: number): Promise<HTMLElement> {
  try {
    const report = await adminApi.getResourceReport(userId);
    // The report's ledger window is the same canonical projection the user's own
    // endpoint serves, so the two readers are held to one shape by construction.
    const entries = (report.ledger.entries ?? []) as ResourceLedgerEntry[];
    const ledger: ResourceLedger = {
      subject_id: report.canonical_envelope.subject_id,
      period: report.canonical_envelope.period,
      limit: report.limit,
      limit_ceiling: report.limit_ceiling,
      entries,
    };
    return quotaPosition(report.canonical_envelope, ledger);
  } catch (error) {
    return empty((error as Error).message || "Unable to load this account's quota position.", true);
  }
}

/**
 * The single integration point for a navigation entry (PR #79 owns the shell).
 *
 * A caller wires this view into the account navigation by importing this module
 * and calling ``mountQuotaView(shell.outlet, shell)`` — one line in the shell's
 * route table, with no other coupling to this module. It stays a plain exported
 * function rather than a route registration so the shell continues to own the
 * route vocabulary and this view never declares one of its own.
 */
export async function mountQuotaView(outlet: HTMLElement, shell: AppShell): Promise<void> {
  void shell;
  await new QuotaView().mount(outlet);
}
