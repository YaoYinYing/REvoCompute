import type { AppShell } from '../../../app/shell';
import { adminApi, idempotencyKey, type AdminUser, type ComputeEntitlement, type ResourceEntitlement, type StorageEntitlement, type StorageQuotaEntitlement } from '../api';
import { button, element, formatBytes, openDialog, setBusy, text } from '../shared/dom';

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

/*
 * The durable-storage quota control.
 *
 * A quota change is a policy act made here and recorded by the endpoint that
 * owns it: this form sends one of the three decisions and a reason, and the
 * server answers with the effective entitlement it will apply. The form never
 * composes an effective number of its own — no client-side "deployment default
 * plus override" arithmetic — and it never presents a zero ceiling and an
 * unlimited grant as the same choice, because the server distinguishes them and
 * a control that blurred them would be a second, quieter policy.
 */

/** The state selector's options, as the server names the three decisions. */
export const QUOTA_STATES: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'limited', label: 'Limit to a fixed number of bytes' },
  { value: 'unlimited', label: 'No ceiling' },
  { value: 'inherit', label: 'Remove the override (deployment default applies)' },
];

/** The bytes to send for one decision, or a reason the request cannot be made. */
export function quotaRequest(state: string, rawBytes: string): { limitBytes: number | null } | { error: string } {
  if (state !== 'limited') return { limitBytes: null };
  const text = rawBytes.trim();
  if (!text) return { error: 'A limited quota needs a byte ceiling; use 0 to allow no durable storage.' };
  if (!/^\d+$/.test(text)) return { error: 'The byte ceiling must be a whole, non-negative number of bytes.' };
  return { limitBytes: Number(text) };
}

/** What the control states about the position the server reported. */
export function quotaStateLabel(quota: StorageQuotaEntitlement): string {
  if (quota.state === 'unlimited') return 'No ceiling (explicit grant)';
  if (quota.state === 'inherit') return 'Inherited from the deployment default';
  return 'Fixed byte ceiling';
}

export function quotaTransition(before: StorageQuotaEntitlement, after: StorageQuotaEntitlement): string {
  const ceiling = (quota: StorageQuotaEntitlement): string =>
    quota.soft_limit_bytes === null ? 'no ceiling' : formatBytes(quota.soft_limit_bytes);
  return `${ceiling(before)} → ${ceiling(after)}`;
}

function quotaForm(
  user: AdminUser,
  initial: StorageQuotaEntitlement,
  shell: AppShell,
): { root: HTMLElement; reload: () => Promise<void> } {
  let current = initial;
  const summary = element('dl', 'resource-storage-facts');
  const renderSummary = (): void => {
    summary.replaceChildren();
    const fact = (label: string, value: string): HTMLElement => {
      const item = element('div');
      item.append(text('dt', label), text('dd', value));
      return item;
    };
    summary.append(
      fact('Decision in force', quotaStateLabel(current)),
      fact('Effective ceiling', current.soft_limit_bytes === null ? 'No ceiling' : formatBytes(current.soft_limit_bytes)),
      fact('Owned bytes', formatBytes(current.logical_owned_bytes)),
      fact('Over ceiling', current.over_soft_limit ? 'Yes' : 'No'),
    );
  };
  renderSummary();

  const state = element('select');
  for (const option of QUOTA_STATES) {
    const node = element('option');
    node.value = option.value;
    node.textContent = option.label;
    state.append(node);
  }
  state.value = 'limited';

  const bytes = element('input');
  bytes.type = 'number';
  bytes.min = '0';
  bytes.step = '1';
  bytes.placeholder = 'Bytes, e.g. 10737418240';

  const apply = button('Apply quota', 'primary-button');
  apply.addEventListener('click', async () => {
    const request = quotaRequest(state.value, bytes.value);
    if ('error' in request) { shell.notify(request.error, 'error'); return; }
    const content = element('div', 'admin-dialog-fields', [
      text('p', `Change the durable-storage quota for ${user.full_name || user.username}? It changes what they may retain; it never rewrites what they already hold.`),
    ]);
    const confirmed = await openDialog({ title: 'Change durable-storage quota?', content, confirmLabel: 'Apply quota' });
    if (!confirmed) return;
    setBusy(apply, true);
    try {
      const result = await adminApi.setStorageQuota(user.id, state.value, request.limitBytes, `Storage quota set to ${state.value}`, idempotencyKey(`storage-quota-${user.id}`));
      const after = result.storage_quota;
      shell.notify(`Durable-storage quota updated: ${quotaTransition(current, after)}.`, 'success');
      current = after;
      renderSummary();
    } catch (error) { shell.notify((error as Error).message, 'error'); }
    finally { setBusy(apply, false); }
  });

  const fields = element('div', 'admin-inline-form', [
    element('label', 'admin-field', [text('span', 'Decision'), state]),
    element('label', 'admin-field', [text('span', 'Byte ceiling'), bytes]),
    apply,
  ]);
  const root = element('section', 'resource-quota');
  root.append(
    text('h3', 'Durable-storage quota'),
    text('p', 'The decision an administrator has made about this account, and the ceiling admission applies. A limit of 0 means the account may retain no durable bytes; it is not a way to say "no ceiling".', 'admin-dialog-copy'),
    summary,
    fields,
  );
  return { root, reload: async () => { current = await adminApi.getUserStorageQuota(user.id); renderSummary(); } };
}

/** The storage quota section for one account, or the reason it could not be read. */
export async function loadStorageQuota(user: AdminUser, shell: AppShell): Promise<HTMLElement> {
  try {
    const quota = await adminApi.getUserStorageQuota(user.id);
    return quotaForm(user, quota, shell).root;
  } catch (error) {
    const section = element('section', 'resource-quota');
    section.append(text('h3', 'Durable-storage quota'), text('p', (error as Error).message || 'Unable to load the durable-storage quota.', 'error-state'));
    return section;
  }
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
