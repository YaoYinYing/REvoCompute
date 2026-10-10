import { adminApi, type ComputeEntitlement, type ResourceEntitlement, type StorageEntitlement } from '../api';
import { element, formatBytes, text } from '../shared/dom';

/*
 * The canonical per-user resource envelope, read only.
 *
 * Admission decides against this projection, so an operator reads the same
 * position the server does rather than a second balance derived here. Two facts
 * are deliberately not collapsed into a number:
 *
 * * an ungated unit has no allowance and no remaining balance — it is reported as
 *   not gated, never as zero;
 * * a compute balance whose authoritative measurement has not arrived reports
 *   ``usage_complete`` false with the quantity still outstanding, so a reader is
 *   never told an exact balance that the server does not yet know.
 *
 * This surface only reads. A quota or allowance change is an auditable adjustment
 * made through the endpoint that owns it, not an edit made here.
 */

const UNIT_LABEL: Record<ComputeEntitlement['unit'], string> = {
  gpu_second: 'GPU seconds',
  cpu_core_second: 'CPU core seconds',
  storage_byte: 'Storage bytes',
};

export function unitLabel(unit: ComputeEntitlement['unit']): string {
  return UNIT_LABEL[unit] ?? unit;
}

/** A Slurm resource class, or the class-agnostic allowance it actually governs. */
export function classLabel(entitlement: ComputeEntitlement): string {
  return entitlement.resource_class || 'Any class';
}

/** A gated amount, or the explicit statement that no policy gates this unit. */
export function gatedAmount(value: number | null): string {
  return value === null ? 'Not gated' : value.toLocaleString();
}

export function countLabel(value: number): string {
  return value.toLocaleString();
}

/** Whether the recorded usage is the whole story, and what is still outstanding. */
export function usageState(entitlement: ComputeEntitlement): string {
  if (entitlement.usage_complete) return 'Complete';
  if (!entitlement.unsettled_allocations) return 'Incomplete';
  return `Incomplete · ${entitlement.unsettled_allocations} allocation(s) unsettled`;
}

/** The configured durable-storage ceiling, or the explicit absence of one. */
export function storageCeiling(storage: StorageEntitlement): string {
  return storage.soft_limit_bytes === null ? 'Not configured' : formatBytes(storage.soft_limit_bytes);
}

/** What remains before later submissions are refused, or the fact that nothing does. */
export function storageRemaining(storage: StorageEntitlement): string {
  return storage.remaining_bytes === null ? 'Not limited' : formatBytes(storage.remaining_bytes);
}

export function storageState(storage: StorageEntitlement): string {
  return storage.over_soft_limit ? 'Over ceiling' : 'Within ceiling';
}

function computeTable(entries: ComputeEntitlement[]): HTMLElement {
  if (!entries.length) return text('p', 'No compute entitlement is recorded for this user.', 'admin-empty');
  const table = element('table', 'admin-table resource-envelope-table');
  const head = element('thead');
  head.append(element('tr', '', ['Unit', 'Class', 'Enforced', 'Allowance', 'Used', 'Reserved', 'Remaining', 'Usage'].map(label => text('th', label))));
  const body = element('tbody');
  for (const entry of entries) {
    body.append(element('tr', '', [
      text('td', unitLabel(entry.unit)),
      text('td', classLabel(entry)),
      text('td', entry.enforced ? 'Gated' : 'Recorded only'),
      text('td', gatedAmount(entry.allowance)),
      text('td', countLabel(entry.used)),
      text('td', countLabel(entry.reserved)),
      // Remaining is null exactly when the unit is ungated: a balance nobody
      // gates is not a zero balance.
      text('td', gatedAmount(entry.remaining)),
      text('td', usageState(entry)),
    ]));
  }
  table.append(head, body);
  return element('div', 'admin-table-scroll', [table]);
}

function storageFacts(storage: StorageEntitlement): HTMLElement {
  const facts = element('dl', 'resource-storage-facts');
  const fact = (label: string, value: string, className = ''): HTMLElement => {
    const item = element('div', className);
    item.append(text('dt', label), text('dd', value));
    return item;
  };
  facts.append(
    fact('Owned bytes', formatBytes(storage.logical_owned_bytes)),
    fact('Ceiling', storageCeiling(storage)),
    fact('Remaining', storageRemaining(storage)),
    fact('State', storageState(storage), storage.over_soft_limit ? 'is-attention' : ''),
  );
  return facts;
}

/** The whole envelope: compute entitlement, then durable-storage ownership. */
export function envelopeSection(period: string, envelope: ResourceEntitlement): HTMLElement {
  const section = element('section', 'resource-envelope');
  section.append(
    text('h3', 'Resource envelope'),
    text('p', `Compute entitlement and durable-storage ownership for ${period}, as admission reads it. Read-only.`, 'admin-dialog-copy'),
    computeTable(envelope.compute),
    text('h4', 'Durable storage'),
    storageFacts(envelope.storage),
  );
  return section;
}

/** A read-only envelope section for one account, or the reason it could not be read. */
export async function loadEnvelope(userId: number): Promise<HTMLElement> {
  try {
    const envelope = await adminApi.getUserEntitlement(userId);
    return envelopeSection(envelope.period, envelope);
  } catch (error) {
    const section = element('section', 'resource-envelope');
    section.append(text('h3', 'Resource envelope'), text('p', (error as Error).message || 'Unable to load the resource envelope.', 'error-state'));
    return section;
  }
}
