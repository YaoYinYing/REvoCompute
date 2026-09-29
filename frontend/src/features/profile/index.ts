import { Check, Copy, KeyRound, ShieldCheck } from 'lucide';
import { createIcons } from 'lucide';
import {
  createApiKey,
  getAccess,
  getApiKeyStatus,
  getGpuCredit,
  getUserMetrics,
  requestAccess,
  revokeApiKey,
  updatePassword,
  type CurrentUser,
  type GPUCreditSummary,
  type RunnerAccess,
  type UserMetrics,
} from '../../api/app-api';
import { confirmAction } from '../../app/dialogs';
import type { AppShell } from '../../app/shell';
import './profile.css';

type MetricsWindow = '7d' | '30d' | '90d' | 'quarter';
type ProfileSection = 'account' | 'security' | 'api-key' | 'runner-access' | 'gpu-credits' | 'metrics';

const positionLabels: Record<string, string> = {
  undergraduate_student: 'Undergraduate student', masters_student: "Master's student", phd_student: 'PhD student',
  postdoctoral_researcher: 'Postdoctoral researcher', research_assistant: 'Research assistant', lecturer: 'Lecturer',
  assistant_professor: 'Assistant professor', associate_professor: 'Associate professor', professor: 'Professor',
  industry_researcher: 'Industry researcher', other: 'Other',
};

function text(value: unknown, fallback = 'Not provided'): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function status(host: HTMLElement, message = '', tone: 'success' | 'error' | 'info' = 'info'): void {
  host.textContent = message; host.className = `form-status status-${tone}`; host.hidden = !message;
}

function accountMarkup(user: CurrentUser): string {
  const fields: Array<[string, string]> = [
    ['Username', user.username], ['Email', user.email], ['Full name', text(user.full_name)],
    ['Affiliation', text(user.affiliation)], ['Position', positionLabels[user.position || ''] || text(user.position)],
    ['PI or supervisor', text(user.pi_name)], ['Role', user.role === 'admin' ? 'Administrator' : user.role === 'guest' ? 'Guest account' : 'User'],
    ['Email status', user.email_verified ? 'Verified' : 'Not verified'],
  ];
  return `<dl class="profile-details">${fields.map(([label, value]) => `<div><dt>${label}</dt><dd></dd></div>`).join('')}</dl>`;
}

function setAccountValues(root: HTMLElement, user: CurrentUser): void {
  const values = [user.username, user.email, text(user.full_name), text(user.affiliation), positionLabels[user.position || ''] || text(user.position), text(user.pi_name), user.role === 'admin' ? 'Administrator' : user.role === 'guest' ? 'Guest account' : 'User', user.email_verified ? 'Verified' : 'Not verified'];
  root.querySelectorAll<HTMLElement>('.profile-details dd').forEach((element, index) => { element.textContent = values[index] || 'Not provided'; });
}

function profileMarkup(user: CurrentUser): string {
  const guest = user.role === 'guest';
  return `
    <main class="profile-page">
      <header class="page-heading"><div><p class="page-kicker">Account</p><h1>Profile</h1><p data-profile-summary></p></div></header>
      <div class="profile-layout">
        <nav class="profile-tabs" role="tablist" aria-label="Profile sections">
          <button type="button" role="tab" data-section="account">Account</button>
          ${guest ? '' : '<button type="button" role="tab" data-section="security">Security</button><button type="button" role="tab" data-section="api-key">API key</button>'}
          <button type="button" role="tab" data-section="runner-access">Runner access</button>
          <button type="button" role="tab" data-section="gpu-credits">GPU credits</button>
          <button type="button" role="tab" data-section="metrics">Metrics</button>
        </nav>
        <div class="profile-sections">
          <section class="profile-section" data-panel="account" role="tabpanel"><header><h2>Account</h2><p>Your account and research identity.</p></header>${accountMarkup(user)}</section>
          ${guest ? '' : `
          <section class="profile-section" data-panel="security" role="tabpanel" hidden><header><h2>Security</h2><p>Change the password used for interactive sign-in.</p></header><form class="profile-form" data-password-form><label>Current password<input name="current_password" type="password" autocomplete="current-password" required></label><label>New password<input name="new_password" type="password" minlength="8" autocomplete="new-password" required></label><label>Confirm new password<input name="confirm_password" type="password" minlength="8" autocomplete="new-password" required></label><button class="primary-button" type="submit">Update password</button><p class="form-status" role="alert" hidden></p></form></section>
          <section class="profile-section" data-panel="api-key" role="tabpanel" hidden><header><h2>API key</h2><p>A long-lived credential for programmatic access. The secret is shown only once and is never stored by this browser.</p></header><div class="api-key-workspace"><p data-api-key-status>Loading API key status...</p><div class="profile-actions"><button class="primary-button" type="button" data-generate-key hidden><i data-lucide="key-round"></i><span>Generate API key</span></button><button class="danger-button" type="button" data-revoke-key hidden>Revoke API key</button></div><label class="api-key-secret" hidden>Your new API key<span><input type="text" readonly data-api-key-value><button class="icon-button" type="button" data-copy-key title="Copy API key" aria-label="Copy API key"><i data-lucide="copy"></i></button></span><small>Copy this key now. It will not be shown again.</small></label><p class="form-status" data-api-key-message role="alert" hidden></p></div></section>`}
          <section class="profile-section" data-panel="runner-access" role="tabpanel" hidden><header><h2>Runner access</h2><p>Eligibility under each Runner's authoritative upstream licence is independent of your account role. <a href="/compute/terms#restricted-runner-access">Read how restricted access works</a>.</p></header><div class="profile-resource" data-access-list><p class="loading-state">Loading Runner access...</p></div></section>
          <section class="profile-section" data-panel="gpu-credits" role="tabpanel" hidden><header><h2>GPU credits</h2><p>One credit is one GPU-minute. Queue and CPU time are free.</p></header><div class="profile-resource" data-gpu-credit><p class="loading-state">Loading GPU credits...</p></div></section>
          <section class="profile-section" data-panel="metrics" role="tabpanel" hidden><header class="metrics-header"><div><h2>Metrics</h2><p>Task activity from your persisted compute history.</p></div><div class="segmented-control" role="group" aria-label="Metrics time window"><button type="button" data-window="7d">7 days</button><button type="button" data-window="30d">30 days</button><button type="button" data-window="90d">90 days</button><button type="button" data-window="quarter">Quarter</button></div></header><div class="profile-resource" data-metrics><p class="loading-state">Loading metrics...</p></div></section>
        </div>
      </div>
    </main>`;
}

function bindTabs(root: HTMLElement): void {
  const tabs = [...root.querySelectorAll<HTMLButtonElement>('[data-section]')];
  const panels = [...root.querySelectorAll<HTMLElement>('[data-panel]')];
  const available = new Set(tabs.map(tab => tab.dataset.section));
  const requested = location.hash.slice(1);
  const activate = (name: string, updateLocation = true): void => {
    const section = available.has(name) ? name : 'account';
    tabs.forEach(tab => { const active = tab.dataset.section === section; tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1; });
    panels.forEach(panel => { panel.hidden = panel.dataset.panel !== section; });
    if (updateLocation && location.hash !== `#${section}`) history.replaceState(null, '', `#${section}`);
  };
  tabs.forEach(tab => tab.addEventListener('click', () => activate(tab.dataset.section || 'account')));
  window.addEventListener('hashchange', () => activate(location.hash.slice(1), false));
  activate(requested);
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

function metadataValue(value: unknown, key: string): string | null {
  if (!value || typeof value !== 'object') return null;
  const item = (value as Record<string, unknown>)[key]; return typeof item === 'string' && item ? item : null;
}

function safeExternalUrl(value: string | null): string | null {
  if (!value) return null;
  try { const url = new URL(value, location.origin); return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null; }
  catch { return null; }
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
      const licenseName = metadataValue(policy.license, 'name'); const licenseUrl = safeExternalUrl(metadataValue(policy.license, 'url')); const notice = metadataValue(policy.notice, 'text') || metadataValue(policy.notice, 'message');
      if (licenseUrl || notice) {
        const more = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Policy details'; more.append(summary);
        if (notice) { const p = document.createElement('p'); p.textContent = notice; more.append(p); }
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

function renderMetrics(host: HTMLElement, data: UserMetrics): void {
  host.innerHTML = '<dl class="metrics-summary"></dl><p class="metrics-composition"></p><section><h3>Tasks over time</h3><div class="activity-chart" role="img" aria-label="Tasks submitted over time"></div></section><section><h3>TaskType usage</h3><div class="metrics-distribution"></div></section>';
  const entries: Array<[string, string]> = [['Tasks submitted', String(data.tasks_submitted)], ['Completed', String(data.tasks_completed)], ['Failed', String(data.tasks_failed)], ['Success rate', data.success_rate == null ? 'Not available' : `${Math.round(data.success_rate * 100)}%`], ['GPU minutes', credits(data.gpu_minutes)], ['Median runtime', runtime(data.median_runtime_seconds)]];
  const summary = host.querySelector<HTMLElement>('.metrics-summary')!;
  entries.forEach(([label, value]) => { const item = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd'); dt.textContent = label; dd.textContent = value; item.append(dt, dd); summary.append(item); });
  host.querySelector<HTMLElement>('.metrics-composition')!.textContent = `${data.cpu_tasks} CPU tasks, ${data.gpu_tasks} GPU tasks, ${runtime(data.total_runtime_seconds)} total runtime. Window ending ${data.period}.`;
  const activity = host.querySelector<HTMLElement>('.activity-chart')!; const peak = Math.max(...data.activity.map(item => item.count), 1);
  activity.style.gridTemplateColumns = `repeat(${Math.max(data.activity.length, 1)}, minmax(0, 1fr))`;
  data.activity.forEach(point => { const bar = document.createElement('span'); bar.style.height = `${Math.max(point.count ? 4 : 1, (point.count / peak) * 100)}%`; bar.title = `${point.period}: ${point.count} task${point.count === 1 ? '' : 's'}`; activity.append(bar); });
  const distribution = host.querySelector<HTMLElement>('.metrics-distribution')!;
  if (!data.distribution.length) { distribution.innerHTML = '<p class="empty-state">No TaskType usage in this window.</p>'; }
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
  await load('30d');
}

export async function mountProfile(root: HTMLElement, shell: AppShell, user: CurrentUser): Promise<void> {
  document.title = 'Profile | REvoCompute'; root.innerHTML = profileMarkup(user);
  root.querySelector<HTMLElement>('[data-profile-summary]')!.textContent = user.role === 'guest' ? 'Shared guest account' : `Signed in as ${user.username}`;
  setAccountValues(root, user); bindTabs(root); bindPassword(root, shell);
  createIcons({ icons: { Copy, KeyRound, ShieldCheck }, root });
  await Promise.allSettled([bindApiKey(root, shell), loadAccess(root, shell), loadCredits(root), bindMetrics(root)]);
}
