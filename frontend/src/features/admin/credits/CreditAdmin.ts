import type { AppShell } from '../../../app/shell';
import { adminApi, idempotencyKey, type AdminUser, type GPUCreditSummary } from '../api';
import { button, element, empty, formatCredits, formatDate, openDialog, reasonContent, setBusy, text } from '../shared/dom';

export const globalResetConfirmation = 'RESET ALL';

export function validateGlobalReset(reason: string, confirmation: string): string | null {
  if (!reason.trim()) return 'Enter a reason for the global reset.';
  return confirmation.trim() === globalResetConfirmation ? null : `Type ${globalResetConfirmation} exactly to confirm.`;
}

function creditSummary(data: GPUCreditSummary): HTMLElement {
  const summary = element('dl', 'admin-stat-strip');
  const entries: Array<[string, number]> = [
    ['Monthly allowance', data.monthly_grant_credits],
    ['Adjustments', data.adjustment_credits],
    ['Used', data.usage_credits],
    ['Remaining', data.remaining_credits],
  ];
  for (const [label, value] of entries) {
    summary.append(element('div', '', [text('dt', label), text('dd', formatCredits(value, label === 'Adjustments'))]));
  }
  return summary;
}

function creditHistory(data: GPUCreditSummary): HTMLElement {
  const history = element('div', 'admin-history');
  if (!data.history.length) return empty('No credit activity has been recorded.');
  for (const entry of data.history) {
    const copy = element('div', '', [
      text('strong', entry.kind.replaceAll('_', ' ')),
      text('span', entry.reason || entry.task_id || 'Recorded usage'),
      text('time', formatDate(entry.created_at)),
    ]);
    history.append(element('article', '', [copy, text('b', `${formatCredits(entry.gpu_seconds / 60, true)} credits`)]));
  }
  return history;
}

export class CreditAdmin {
  constructor(private readonly shell: AppShell, private readonly onChanged: () => Promise<void>) {}

  async open(user: AdminUser): Promise<void> {
    try {
      let data = await adminApi.getUserCredit(user.id);
      const root = element('div', 'credit-admin');
      const accounting = element('section', 'credit-accounting');
      const renderAccounting = (): void => accounting.replaceChildren(
        creditSummary(data),
        text('h3', 'Immutable activity'),
        creditHistory(data),
      );
      renderAccounting();

      const allowance = element('input'); allowance.type = 'number'; allowance.min = '0'; allowance.step = '0.01'; allowance.value = String(data.monthly_grant_credits);
      const allowanceButton = button('Set allowance');
      allowanceButton.addEventListener('click', async () => {
        const credits = Number(allowance.value);
        if (!Number.isFinite(credits) || credits < 0) { this.shell.notify('Enter a non-negative monthly allowance.', 'error'); return; }
        const content = element('div', 'admin-dialog-fields', [text('p', `Set the monthly allowance for ${user.full_name || user.username} from ${formatCredits(data.monthly_grant_credits)} to ${formatCredits(credits)} credits? The server will append the current-period delta.`)]);
        const confirmed = await openDialog({ title: 'Change monthly GPU allowance?', content, confirmLabel: 'Set allowance' });
        if (!confirmed) return;
        setBusy(allowanceButton, true);
        try {
          const result = await adminApi.setAllowance(user.id, Math.round(credits * 60), idempotencyKey(`allowance-${user.id}`));
          data = result.gpu_credit; renderAccounting(); await this.onChanged(); this.shell.notify('Monthly allowance updated.', 'success');
        } catch (error) { this.shell.notify((error as Error).message, 'error'); }
        finally { setBusy(allowanceButton, false); }
      });
      const allowanceField = element('label', 'admin-field', [text('span', 'Monthly allowance in credits'), allowance]);
      const allowanceRow = element('div', 'admin-inline-form', [allowanceField, allowanceButton]);

      const adjustment = element('input'); adjustment.type = 'number'; adjustment.step = '0.01'; adjustment.placeholder = 'Negative values remove credits';
      const reason = element('textarea'); reason.rows = 2; reason.maxLength = 1000;
      const adjustButton = button('Apply adjustment', 'primary-button');
      adjustButton.addEventListener('click', async () => {
        const gpuSeconds = Math.round(Number(adjustment.value) * 60);
        const reasonText = reason.value.trim();
        if (!Number.isFinite(gpuSeconds) || gpuSeconds === 0) { this.shell.notify('Enter a non-zero adjustment of at least 0.02 credits.', 'error'); return; }
        if (!reasonText) { this.shell.notify('A reason is required for credit adjustments.', 'error'); return; }
        const credits = gpuSeconds / 60;
        const content = element('div', 'admin-dialog-fields', [
          text('p', `Apply ${formatCredits(credits, true)} credits to ${user.full_name || user.username}?`),
          text('p', `Resulting balance: ${formatCredits(data.remaining_credits + credits)} credits. Reason: ${reasonText}`, 'admin-dialog-copy'),
        ]);
        const confirmed = await openDialog({ title: 'Apply GPU credit adjustment?', content, confirmLabel: 'Apply adjustment', destructive: gpuSeconds < 0 });
        if (!confirmed) return;
        setBusy(adjustButton, true);
        try {
          const result = await adminApi.adjustCredit(user.id, gpuSeconds, reasonText, idempotencyKey(`adjust-${user.id}`));
          data = result.gpu_credit; adjustment.value = ''; reason.value = ''; renderAccounting(); await this.onChanged(); this.shell.notify('GPU credit adjustment recorded.', 'success');
        } catch (error) { this.shell.notify((error as Error).message, 'error'); }
        finally { setBusy(adjustButton, false); }
      });
      const adjustmentFields = element('div', 'credit-adjustment-grid', [
        element('label', 'admin-field', [text('span', 'Adjustment in credits'), adjustment]),
        element('label', 'admin-field', [text('span', 'Reason'), reason]),
        adjustButton,
      ]);

      const reset = button('Reset to allowance', 'admin-danger-button');
      reset.addEventListener('click', async () => {
        const fields = reasonContent('Restore the current-period balance to this user\'s configured allowance. Usage history remains immutable.');
        const reasonText = await openDialog<string>({
          title: `Reset GPU credits for ${user.full_name || user.username}?`, content: fields.root,
          confirmLabel: 'Reset credits', destructive: true,
          readValue: () => fields.reason.value.trim(), validate: value => value ? null : 'Enter a reason for this reset.',
        });
        if (!reasonText) return;
        try {
          const result = await adminApi.resetUserCredit(user.id, reasonText, idempotencyKey(`reset-${user.id}`));
          data = result.gpu_credit; renderAccounting(); await this.onChanged();
          this.shell.notify(result.changed ? `Credits reset by ${formatCredits(result.reset_delta_gpu_seconds / 60, true)}.` : 'Credits were already at the configured allowance.', 'success');
        } catch (error) { this.shell.notify((error as Error).message, 'error'); }
      });

      root.append(accounting, text('h3', 'Monthly policy'), allowanceRow, text('h3', 'Reasoned adjustment'), adjustmentFields,
        element('section', 'admin-danger-zone', [text('div', 'Reset only this user to the current allowance. GPU permission is unchanged.'), reset]));
      await openDialog({ title: `GPU credits: ${user.full_name || user.username}`, content: root });
    } catch (error) { this.shell.notify((error as Error).message || 'Unable to load GPU credit accounting.', 'error'); }
  }

  async resetAll(userCount: number): Promise<void> {
    const fields = reasonContent(
      `Restore every current user's current-period balance to that user's allowance. Usage history remains immutable and GPU permission is unchanged.`,
      globalResetConfirmation,
    );
    const value = await openDialog<{ reason: string; confirmation: string }>({
      title: `Reset GPU credits for all ${userCount} users?`, content: fields.root,
      confirmLabel: 'Reset all users', destructive: true,
      readValue: () => ({ reason: fields.reason.value.trim(), confirmation: fields.confirmation?.value.trim() || '' }),
      validate: candidate => validateGlobalReset(candidate.reason, candidate.confirmation),
    });
    if (!value) return;
    try {
      const result = await adminApi.resetAllCredits(value.reason, idempotencyKey('reset-all'));
      await this.onChanged();
      this.shell.notify(`Reset complete: ${result.users_changed} changed, ${result.users_unchanged} already at allowance.`, 'success');
    } catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  async renderReconciliation(root: HTMLElement): Promise<void> {
    root.replaceChildren(empty('Loading unsettled GPU allocations...'));
    try {
      const data = await adminApi.getReconciliation();
      root.replaceChildren();
      const heading = element('div', 'admin-section-heading', [
        element('div', '', [text('h2', 'GPU reconciliation'), text('p', 'Settle retained Slurm evidence after a missing finish callback.')]),
      ]);
      const reconcile = button('Run reconciliation');
      reconcile.addEventListener('click', async () => {
        const content = element('div', 'admin-dialog-fields', [text('p', 'Reconcile retained Slurm controller evidence now? Terminal allocations with trustworthy runtime evidence may be charged.')]);
        const confirmed = await openDialog({ title: 'Run GPU reconciliation?', content, confirmLabel: 'Run reconciliation' });
        if (!confirmed) return;
        setBusy(reconcile, true, 'Reconciling...');
        try { await adminApi.reconcileCredits(); this.shell.notify('GPU reconciliation completed.', 'success'); await this.renderReconciliation(root); }
        catch (error) { this.shell.notify((error as Error).message, 'error'); }
        finally { setBusy(reconcile, false); }
      });
      heading.append(reconcile); root.append(heading);
      if (!data.allocations.length) { root.append(empty('No GPU allocations require settlement or review.')); return; }
      const table = element('table', 'admin-table');
      table.innerHTML = '<thead><tr><th>Task</th><th>User</th><th>Slurm job</th><th>GPUs</th><th>Started</th><th>Status</th></tr></thead>';
      const body = element('tbody');
      data.allocations.forEach(allocation => {
        body.append(element('tr', '', [
          text('td', allocation.task_id), text('td', String(allocation.user_id)), text('td', allocation.slurm_job_id),
          text('td', String(allocation.gpu_count)), text('td', formatDate(allocation.started_at)), text('td', allocation.status),
        ]));
      });
      table.append(body); root.append(element('div', 'admin-table-scroll', [table]));
    } catch (error) { root.replaceChildren(empty((error as Error).message || 'Unable to load reconciliation state.', true)); }
  }
}
