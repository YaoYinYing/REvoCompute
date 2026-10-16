import { Check, Copy, KeyRound, ShieldCheck, createIcons } from 'lucide';
import {
  createApiKey,
  getAccess,
  getApiKeyStatus,
  getGpuCredit,
  getSession,
  getUserMetrics,
  requestAccess,
  revokeApiKey,
  updatePassword,
  updateProfile,
  type CurrentUser,
  type GPUCreditSummary,
  type RunnerAccess,
  type UserMetrics,
} from '../../api/app-api';
import type { AcademicPosition } from '../../api/contracts';
import { confirmAction } from '../../app/dialogs';
import { academicPositionLabels, academicPositionOptions, metadataValue, safeExternalUrl } from '../../app/domain-vocabulary';
import type { AccountSection } from '../../app/router';
import type { AppShell } from '../../app/shell';

export const accountIcons = { Check, Copy, KeyRound, ShieldCheck };

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function status(host: HTMLElement, message = '', tone: 'success' | 'error' | 'info' = 'info'): void {
  host.textContent = message; host.className = `form-status status-${tone}`; host.hidden = !message;
}

function text(value: unknown, fallback = 'Not provided'): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

/**
 * A titled page region: the section heading is the page's h1 for its own route.
 *
 * ``slug`` is the route's own section id, so the page announces the destination
 * it is — a stable machine identity rather than a projection of a display title
 * that a translation or a rename would change.
 */
export function accountSection(slug: string, title: string, description: string, body: HTMLElement | string): HTMLElement {
  const section = document.createElement('section');
  section.className = 'account-section';
  section.dataset.section = slug;
  const header = document.createElement('header');
  const heading = document.createElement('h1'); heading.textContent = title;
  header.append(heading);
  if (description) { const copy = document.createElement('p'); copy.textContent = description; header.append(copy); }
  section.append(header);
  if (typeof body === 'string') section.insertAdjacentHTML('beforeend', body);
  else section.append(body);
  return section;
}

function accountMarkup(user: CurrentUser): string {
  const options = academicPositionOptions.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
  const guestFields = user.role === 'guest' ? ['Full name', 'Affiliation', 'Position', 'PI or supervisor'] : [];
  return `
    <dl class="profile-details">
      ${['Username', 'Email', 'Role', 'Email status', ...guestFields].map(label => `<div><dt>${label}</dt><dd></dd></div>`).join('')}
    </dl>
    ${user.role === 'guest' ? '' : `<form class="profile-form account-form" data-account-form>
      <div class="form-columns">
        <label>Full name<input name="full_name" maxlength="128" autocomplete="name" required></label>
        <label>Affiliation<input name="affiliation" maxlength="256" autocomplete="organization" required></label>
        <label>Position<select name="position" required>${options}</select></label>
        <label>PI or supervisor<input name="pi_name" maxlength="128" required></label>
      </div>
      <button class="primary-button" type="submit">Save profile</button>
      <p class="form-status" role="alert" hidden></p>
    </form>`}`;
}

function setAccountValues(root: HTMLElement, user: CurrentUser): void {
  const values = [user.username, user.email, user.role === 'admin' ? 'Administrator' : user.role === 'guest' ? 'Guest account' : 'User', user.email_verified ? 'Verified' : 'Not verified'];
  if (user.role === 'guest') values.push(
    text(user.full_name), text(user.affiliation), academicPositionLabels[user.position as AcademicPosition] || text(user.position), text(user.pi_name),
  );
  root.querySelectorAll<HTMLElement>('.profile-details dd').forEach((element, index) => { element.textContent = values[index] || 'Not provided'; });
  const form = root.querySelector<HTMLFormElement>('[data-account-form]');
  if (!form) return;
  (form.elements.namedItem('full_name') as HTMLInputElement).value = user.full_name || '';
  (form.elements.namedItem('affiliation') as HTMLInputElement).value = user.affiliation || '';
  (form.elements.namedItem('position') as HTMLSelectElement).value = user.position || '';
  (form.elements.namedItem('pi_name') as HTMLInputElement).value = user.pi_name || '';
}

/** The Account identity panel and its editable profile form. */
export function accountPanel(shell: AppShell, user: CurrentUser): HTMLElement {
  const section = accountSection('account', 'Account', 'Your account and research identity.', accountMarkup(user));
  setAccountValues(section, user);
  // The identity line is the page's own introductory prose: it is the paragraph
  // under the heading, and the marker is an empty attribute so the element is
  // found by identity rather than by a value that happens to name the user.
  const summary = document.createElement('p'); summary.className = 'account-summary';
  summary.dataset.accountSummary = '';
  summary.textContent = user.role === 'guest' ? 'Shared guest account' : `Signed in as ${user.username}`;
  section.querySelector('header')!.append(summary);
  bindAccount(section, shell);
  return section;
}

/** The Security panel and its password form. */
export function securityPanel(shell: AppShell): HTMLElement {
  const section = accountSection('security', 'Security', '', `<form class="profile-form" data-password-form><label>Current password<input name="current_password" type="password" autocomplete="current-password" required></label><label>New password<input name="new_password" type="password" minlength="8" autocomplete="new-password" required></label><label>Confirm new password<input name="confirm_password" type="password" minlength="8" autocomplete="new-password" required></label><button class="primary-button" type="submit">Update password</button><p class="form-status" role="alert" hidden></p></form>`);
  bindPassword(section, shell);
  return section;
}

/** The API key panel: status, generate/regenerate, revoke, and reveal-once value. */
export function apiKeyPanel(shell: AppShell): HTMLElement {
  const section = accountSection('api-key', 'API key', 'A long-lived credential for programmatic access. The secret is shown only once.', `<div class="api-key-workspace"><p data-api-key-status>Loading API key status...</p><div class="profile-actions"><button class="primary-button" type="button" data-generate-key hidden><i data-lucide="key-round"></i><span>Generate API key</span></button><button class="danger-button" type="button" data-revoke-key hidden>Revoke API key</button></div><label class="api-key-secret" hidden>Your new API key<span><input type="text" readonly data-api-key-value><button class="icon-button" type="button" data-copy-key title="Copy API key" aria-label="Copy API key"><i data-lucide="copy"></i></button></span><small>Copy this key now. It will not be shown again.</small></label><p class="form-status" data-api-key-message role="alert" hidden></p></div>`);
  void bindApiKey(section, shell);
  return section;
}

/** The Runner access panel: eligibility plus the request form. */
export function runnerAccessPanel(shell: AppShell): HTMLElement {
  const section = accountSection('runner-access', 'Runner access', '', '');
  const intro = document.createElement('p');
  intro.className = 'account-intro';
  intro.innerHTML = 'Eligibility under each Runner’s authoritative upstream licence is independent of your account role. <a href="/compute/terms#restricted-runner-access">Read how restricted access works</a>.';
  section.append(intro);
  const host = document.createElement('div'); host.className = 'profile-resource'; host.dataset.accessList = '';
  host.innerHTML = '<p class="loading-state">Loading Runner access...</p>';
  section.append(host);
  void loadAccess(section, shell);
  return section;
}

/** The GPU credits panel. */
export function gpuCreditsPanel(): HTMLElement {
  const section = accountSection('gpu-credits', 'GPU credits', 'One credit is one GPU-minute. Queue and CPU time are free.', '');
  const host = document.createElement('div'); host.className = 'profile-resource'; host.dataset.gpuCredit = '';
  host.innerHTML = '<p class="loading-state">Loading GPU credits...</p>';
  section.append(host);
  void loadCredits(section);
  return section;
}

/** The Metrics panel: task activity with its time window control. */
export function metricsPanel(): HTMLElement {
  const section = accountSection('metrics', 'Metrics', 'Task activity from your compute history.', '');
  const windows = document.createElement('div');
  windows.className = 'segmented-control'; windows.setAttribute('role', 'group'); windows.setAttribute('aria-label', 'Metrics time window');
  windows.innerHTML = '<button type="button" data-window="daily">Daily</button><button type="button" data-window="weekly">Weekly</button><button type="button" data-window="quarterly">Quarterly</button><button type="button" data-window="yearly">Yearly</button>';
  section.querySelector('header')!.append(windows);
  const host = document.createElement('div'); host.className = 'profile-resource'; host.dataset.metrics = '';
  host.innerHTML = '<p class="loading-state">Loading metrics...</p>';
  section.append(host);
  void bindMetrics(section);
  return section;
}

function bindPassword(root: HTMLElement, shell: AppShell): void {
  const form = root.querySelector<HTMLFormElement>('[data-password-form]');
  if (!form) return;
  const message = form.querySelector<HTMLElement>('.form-status')!;
  form.addEventListener('submit', async event => {
    event.preventDefault(); const data = new FormData(form); const button = form.querySelector<HTMLButtonElement>('button')!;
    const next = String(data.get('new_password') || ''); const confirmation = String(data.get('confirm_password') || '');
    if (next !== confirmation) { status(message, 'New passwords do not match.', 'error'); return; }
    button.disabled = true; button.textContent = 'Updating...';
    try {
      await updatePassword(String(data.get('current_password') || ''), next); form.reset();
      status(message, 'Password updated. Sign in again with the new password.', 'success'); shell.notify('Password updated.', 'success');
      window.setTimeout(() => location.assign('/compute/login'), 1200);
    } catch (error) { status(message, errorMessage(error, 'Password could not be updated.'), 'error'); }
    finally { button.disabled = false; button.textContent = 'Update password'; }
  });
}

function bindAccount(root: HTMLElement, shell: AppShell): void {
  const form = root.querySelector<HTMLFormElement>('[data-account-form]');
  if (!form) return;
  const message = form.querySelector<HTMLElement>('.form-status')!;
  const button = form.querySelector<HTMLButtonElement>('button')!;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(form);
    button.disabled = true; button.textContent = 'Saving...'; status(message);
    try {
      await updateProfile({
        full_name: String(data.get('full_name') || '').trim(),
        affiliation: String(data.get('affiliation') || '').trim(),
        position: String(data.get('position') || '') as NonNullable<Parameters<typeof updateProfile>[0]['position']>,
        pi_name: String(data.get('pi_name') || '').trim(),
      });
      const updated = await getSession();
      setAccountValues(root, updated); shell.setUser(updated);
      status(message, 'Profile updated.', 'success'); shell.notify('Profile updated.', 'success');
    } catch (error) { status(message, errorMessage(error, 'Profile could not be updated.'), 'error'); }
    finally { button.disabled = false; button.textContent = 'Save profile'; }
  });
}

async function bindApiKey(root: HTMLElement, shell: AppShell): Promise<void> {
  const statusText = root.querySelector<HTMLElement>('[data-api-key-status]'); if (!statusText) return;
  const generate = root.querySelector<HTMLButtonElement>('[data-generate-key]')!;
  const revoke = root.querySelector<HTMLButtonElement>('[data-revoke-key]')!;
  const secret = root.querySelector<HTMLElement>('.api-key-secret')!;
  const value = root.querySelector<HTMLInputElement>('[data-api-key-value]')!;
  const copy = root.querySelector<HTMLButtonElement>('[data-copy-key]')!;
  const message = root.querySelector<HTMLElement>('[data-api-key-message]')!;
  let hasKey = false;
  const renderStatus = (): void => {
    statusText.textContent = hasKey ? 'An active API key is configured.' : 'No API key is configured.';
    generate.hidden = false; generate.querySelector('span')!.textContent = hasKey ? 'Regenerate API key' : 'Generate API key'; revoke.hidden = !hasKey;
  };
  try { hasKey = (await getApiKeyStatus()).has_api_key; renderStatus(); }
  catch (error) { statusText.textContent = errorMessage(error, 'API key status is unavailable.'); return; }
  generate.addEventListener('click', async () => {
    if (hasKey && !await confirmAction({ title: 'Regenerate API key?', message: 'The existing key will stop working immediately.', confirmLabel: 'Regenerate key' })) return;
    generate.disabled = true; status(message);
    try {
      const response = await createApiKey(); value.value = response.api_key; secret.hidden = false; hasKey = true; renderStatus();
      status(message, response.message, 'success'); shell.notify('API key generated.', 'success');
    } catch (error) { status(message, errorMessage(error, 'API key could not be generated.'), 'error'); }
    finally { generate.disabled = false; }
  });
  revoke.addEventListener('click', async () => {
    if (!await confirmAction({ title: 'Revoke API key?', message: 'Every current use of this key will stop working.', confirmLabel: 'Revoke API key' })) return;
    revoke.disabled = true; status(message);
    try {
      await revokeApiKey(); hasKey = false; value.value = ''; secret.hidden = true; renderStatus();
      status(message, 'API key revoked.', 'success'); shell.notify('API key revoked.', 'success');
    } catch (error) { status(message, errorMessage(error, 'API key could not be revoked.'), 'error'); }
    finally { revoke.disabled = false; }
  });
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(value.value); copy.innerHTML = '<i data-lucide="check"></i>'; createIcons({ icons: { Check }, root: copy });
      window.setTimeout(() => { copy.innerHTML = '<i data-lucide="copy"></i>'; createIcons({ icons: { Copy }, root: copy }); }, 1400);
    } catch { value.select(); shell.notify('Select the key and copy it manually.'); }
  });
}

export function accessState(policy: RunnerAccess): 'Granted' | 'Expired' | 'Pending' | 'Rejected' | 'Requestable' | 'Restricted' {
  if (policy.granted) return 'Granted'; if (policy.expired) return 'Expired';
  if (policy.request_status === 'pending') return 'Pending'; if (policy.request_status === 'rejected') return 'Rejected';
  return policy.requestable ? 'Requestable' : 'Restricted';
}

async function loadAccess(root: HTMLElement, shell: AppShell): Promise<void> {
  const host = root.querySelector<HTMLElement>('[data-access-list]')!;
  try {
    const response = await getAccess(); host.replaceChildren();
    if (!response.policies.length) { host.innerHTML = '<p class="empty-state">No restricted Runner policies are configured.</p>'; return; }
    response.policies.forEach(policy => {
      const state = accessState(policy); const row = document.createElement('article'); row.className = 'access-row';
      const heading = document.createElement('div'); heading.className = 'access-heading';
      const title = document.createElement('h3'); title.textContent = policy.label || policy.policy_id || 'Restricted Runner';
      const badge = document.createElement('span'); badge.className = `badge access-${state.toLowerCase()}`; badge.textContent = state; heading.append(title, badge); row.append(heading);
      const detail = document.createElement('p'); detail.className = 'access-detail';
      if (state === 'Granted' && policy.expires_at) detail.textContent = `Valid until ${new Date(policy.expires_at * 1000).toLocaleString()}.`;
      else if (state === 'Pending') detail.textContent = 'Your request is awaiting an administrator decision.';
      else if (state === 'Expired') detail.textContent = 'A previous grant expired. You may request access again.';
      else if (state === 'Rejected') detail.textContent = 'Your previous request was not approved.';
      else detail.textContent = policy.description || 'Operator verification is required before use.';
      row.append(detail);
      if (!policy.granted && policy.requestable && policy.request_status !== 'pending') {
        const form = document.createElement('form'); form.className = 'access-request profile-form';
        const label = document.createElement('label'); label.textContent = 'Research use and affiliation';
        const reason = document.createElement('textarea'); reason.required = true; reason.maxLength = 1000; reason.rows = 3; reason.placeholder = 'Describe the non-commercial research use and your affiliation.'; label.append(reason);
        const button = document.createElement('button'); button.className = 'primary-button'; button.type = 'submit'; button.textContent = 'Request access';
        const message = document.createElement('p'); message.className = 'form-status'; message.hidden = true; message.setAttribute('role', 'alert'); form.append(label, button, message);
        form.addEventListener('submit', async event => {
          event.preventDefault(); const requestReason = reason.value.trim();
          if (!requestReason) { status(message, 'Describe your research use before requesting access.', 'error'); reason.focus(); return; }
          button.disabled = true;
          try { await requestAccess(policy.policy_id || '', requestReason); status(message, 'Access request submitted.', 'success'); button.remove(); reason.disabled = true; badge.textContent = 'Pending'; badge.className = 'badge access-pending'; shell.notify('Runner access requested.', 'success'); }
          catch (error) { status(message, errorMessage(error, 'Access request could not be submitted.'), 'error'); button.disabled = false; }
        }); row.append(form);
      }
      const licenseName = metadataValue(policy.license, 'name'); const licenseUrl = safeExternalUrl(metadataValue(policy.license, 'url'));
      const noticeTitle = metadataValue(policy.notice, 'title'); const noticeSummary = metadataValue(policy.notice, 'summary');
      if (licenseUrl || noticeTitle || noticeSummary) {
        const more = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Policy details'; more.append(summary);
        if (noticeTitle) { const strong = document.createElement('strong'); strong.textContent = noticeTitle; more.append(strong); }
        if (noticeSummary) { const p = document.createElement('p'); p.textContent = noticeSummary; more.append(p); }
        if (licenseUrl) { const a = document.createElement('a'); a.href = licenseUrl; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = licenseName || 'Upstream terms'; more.append(a); }
        row.append(more);
      }
      host.append(row);
    });
  } catch (error) { host.innerHTML = '<p class="error-state" data-error></p>'; host.querySelector<HTMLElement>('[data-error]')!.textContent = errorMessage(error, 'Runner access is unavailable.'); }
}

function credits(value: number, signed = false): string { const result = value.toLocaleString(undefined, { maximumFractionDigits: 2 }); return signed && value > 0 ? `+${result}` : result; }
function creditLabel(kind: string): string { return ({ monthly_grant: 'Monthly allocation', allowance_adjustment: 'Allowance adjustment', usage: 'GPU usage', admin_adjustment: 'Admin adjustment', admin_reset: 'Administrative reset', reversal: 'Correction', migration_adjustment: 'Imported adjustment' } as Record<string, string>)[kind] || 'Credit activity'; }

function renderGpuCredit(host: HTMLElement, data: GPUCreditSummary): void {
  const period = new Date(`${data.period}-01T00:00:00Z`).toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
  host.innerHTML = `<div class="credit-heading"><p></p><span class="badge"></span></div><dl class="credit-summary"><div><dt>Monthly allocation</dt><dd></dd></div><div><dt>Adjustments</dt><dd></dd></div><div><dt>Used</dt><dd></dd></div><div><dt>Remaining</dt><dd></dd></div></dl><h3>Recent activity</h3><div class="credit-history"></div>`;
  host.querySelector('.credit-heading p')!.textContent = period;
  const access = host.querySelector<HTMLElement>('.credit-heading .badge')!; access.textContent = data.allow_gpu_use ? 'GPU access granted' : 'GPU access not granted'; access.classList.add(data.allow_gpu_use ? 'available' : 'restricted');
  const values = [credits(data.monthly_grant_credits), credits(data.adjustment_credits, true), credits(data.usage_credits), credits(data.remaining_credits)];
  host.querySelectorAll<HTMLElement>('.credit-summary dd').forEach((item, index) => { item.textContent = values[index] || '0'; });
  const history = host.querySelector<HTMLElement>('.credit-history')!;
  if (!data.history.length) { history.innerHTML = '<p class="empty-state">No GPU credit activity in this period.</p>'; return; }
  data.history.forEach(entry => {
    const row = document.createElement('div'); const description = document.createElement('div'); const title = document.createElement('strong'); title.textContent = creditLabel(entry.kind);
    const detail = document.createElement('span'); detail.textContent = entry.reason || new Date(entry.created_at * 1000).toLocaleString(); description.append(title, detail);
    const amount = document.createElement('b'); amount.textContent = credits(entry.gpu_seconds / 60, true); amount.className = entry.gpu_seconds < 0 ? 'credit-debit' : 'credit-credit'; row.append(description, amount); history.append(row);
  });
}

async function loadCredits(root: HTMLElement): Promise<void> {
  const host = root.querySelector<HTMLElement>('[data-gpu-credit]')!;
  try { renderGpuCredit(host, await getGpuCredit()); }
  catch (error) { host.innerHTML = '<p class="error-state" data-error></p>'; host.querySelector<HTMLElement>('[data-error]')!.textContent = errorMessage(error, 'GPU credit accounting is unavailable.'); }
}

function runtime(seconds: number | null): string { if (seconds == null) return 'Not available'; if (seconds < 60) return `${Math.round(seconds)}s`; if (seconds < 3600) return `${Math.round(seconds / 60)}m`; if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`; return `${(seconds / 86400).toFixed(1)}d`; }

const ACTIVITY_PERIOD_LABELS: Record<string, string> = { daily: 'day', weekly: 'week', quarterly: 'quarter', yearly: 'year' };

/** Integer task counts with a readable, rounded upper bound. */
function chartScale(peak: number): { max: number; major: number } {
  const max = Math.max(10, Math.ceil(peak / 10) * 10);
  const major = max % 4 === 0 ? max / 4 : max / 2;
  return { max, major };
}

function periodLabel(period: string, window: string): string {
  const [year, month, day] = period.split('-');
  if (window === 'yearly') return year!;
  if (window === 'quarterly') return `${year} Q${Math.floor((Number(month) - 1) / 3) + 1}`;
  return `${month}-${day}`;
}

/**
 * Render integer task counts with a rounded upper bound and thinned period labels.
 */
function activityChart(data: UserMetrics): HTMLElement {
  const counts = data.activity.map(point => point.count);
  const peak = Math.max(...counts, 0);
  const { max, major } = chartScale(peak);
  const granularity = ACTIVITY_PERIOD_LABELS[data.window] || 'period';
  const chart = document.createElement('div');
  chart.className = 'activity-chart';
  chart.setAttribute('role', 'img');
  chart.setAttribute('aria-label', `Tasks submitted per ${granularity}, showing ${counts.length} ${granularity}s, peak ${peak}.`);

  const yAxis = document.createElement('div');
  yAxis.className = 'activity-axis-y';
  yAxis.setAttribute('aria-hidden', 'true');
  for (let value = 0; value <= max; value += major) {
    const tick = document.createElement('span');
    tick.className = 'activity-tick-major';
    tick.style.top = `${100 - value / max * 100}%`;
    tick.textContent = String(value);
    yAxis.append(tick);
  }

  const plot = document.createElement('div');
  plot.className = 'activity-plot';
  const bars = document.createElement('div');
  bars.className = 'activity-bars';
  bars.style.gridTemplateColumns = `repeat(${Math.max(counts.length, 1)}, minmax(0, 1fr))`;
  plot.append(bars);

  const xAxis = document.createElement('div');
  xAxis.className = 'activity-axis-x';
  xAxis.setAttribute('aria-hidden', 'true');
  xAxis.style.gridTemplateColumns = `repeat(${Math.max(counts.length, 1)}, minmax(0, 1fr))`;
  const stride = Math.max(1, Math.ceil(counts.length / 8));

  data.activity.forEach((point, index) => {
    const bar = document.createElement('span');
    bar.className = 'activity-bar';
    bar.style.height = `${(point.count / max) * 100}%`;
    bar.title = `${periodLabel(point.period, data.window)}: ${point.count} task${point.count === 1 ? '' : 's'}`;
    bars.append(bar);

    const xTick = document.createElement('span');
    xTick.className = 'activity-tick-major';
    // Anchor the label to the last bucket so the series always ends labelled.
    const labelled = (index % stride === 0 && index < counts.length - Math.ceil(stride / 2)) || index === counts.length - 1;
    xTick.textContent = labelled ? periodLabel(point.period, data.window) : '';
    xAxis.append(xTick);
  });

  chart.append(yAxis, plot, xAxis);
  return chart;
}

function renderMetrics(host: HTMLElement, data: UserMetrics): void {
  host.innerHTML = '<dl class="metrics-summary"></dl><p class="metrics-composition"></p><section><h3>Tasks over time</h3><div class="activity-chart-host"></div></section><section><h3>Method usage</h3><div class="metrics-distribution"></div></section>';
  const entries: Array<[string, string]> = [['Tasks submitted', String(data.tasks_submitted)], ['Completed', String(data.tasks_completed)], ['Failed', String(data.tasks_failed)], ['Success rate', data.success_rate == null ? 'Not available' : `${Math.round(data.success_rate * 100)}%`], ['GPU minutes', credits(data.gpu_minutes)], ['Median runtime', runtime(data.median_runtime_seconds)]];
  const summary = host.querySelector<HTMLElement>('.metrics-summary')!;
  entries.forEach(([label, value]) => { const item = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd'); dt.textContent = label; dd.textContent = value; item.append(dt, dd); summary.append(item); });
  host.querySelector<HTMLElement>('.metrics-composition')!.textContent = `${data.cpu_tasks} CPU tasks, ${data.gpu_tasks} GPU tasks, ${runtime(data.total_runtime_seconds)} total runtime. Window ending ${data.period}.`;
  host.querySelector<HTMLElement>('.activity-chart-host')!.append(activityChart(data));
  const distribution = host.querySelector<HTMLElement>('.metrics-distribution')!;
  if (!data.distribution.length) { distribution.innerHTML = '<p class="empty-state">No method usage in this window.</p>'; }
  else {
    const total = data.distribution.reduce((sum, item) => sum + item.tasks, 0) || 1;
    data.distribution.forEach(item => { const row = document.createElement('div'); row.innerHTML = '<span></span><i><b></b></i><strong></strong>'; row.querySelector('span')!.textContent = item.label || item.task_type; (row.querySelector('b') as HTMLElement).style.width = `${(item.tasks / total) * 100}%`; row.querySelector('strong')!.textContent = `${item.tasks}${item.gpu ? ' GPU' : ''}`; distribution.append(row); });
  }
}

async function bindMetrics(root: HTMLElement): Promise<void> {
  const host = root.querySelector<HTMLElement>('[data-metrics]')!; const buttons = [...root.querySelectorAll<HTMLButtonElement>('[data-window]')]; let generation = 0;
  const load = async (window: MetricsWindow): Promise<void> => {
    const request = ++generation; host.innerHTML = '<p class="loading-state">Loading metrics...</p>';
    buttons.forEach(button => { const active = button.dataset.window === window; button.setAttribute('aria-pressed', String(active)); button.disabled = active; });
    try { const data = await getUserMetrics(window); if (request === generation) renderMetrics(host, data); }
    catch (error) { if (request === generation) { host.innerHTML = '<p class="error-state" data-error></p>'; host.querySelector<HTMLElement>('[data-error]')!.textContent = errorMessage(error, 'Metrics are unavailable.'); } }
  };
  buttons.forEach(button => button.addEventListener('click', () => { void load(button.dataset.window as MetricsWindow); }));
  await load('daily');
}

/** Build the panel for one Account section. */
export function accountPanelFor(section: AccountSection, shell: AppShell, user: CurrentUser): HTMLElement {
  const guest = user.role === 'guest';
  switch (section) {
    // A guest account has no password, API key, or editable profile: its one page
    // is the identity it reads, and the other sections resolve to it.
    case 'account': case 'security': case 'api-key':
      return guest || section === 'account' ? accountPanel(shell, user) : section === 'security' ? securityPanel(shell) : apiKeyPanel(shell);
    case 'runner-access': return runnerAccessPanel(shell);
    case 'gpu-credits': return gpuCreditsPanel();
    default: return metricsPanel();
  }
}

export type MetricsWindow = 'daily' | 'weekly' | 'quarterly' | 'yearly';
