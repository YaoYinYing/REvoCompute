import type { AppShell } from '../../../app/shell';
import { adminApi, type AccessPolicySummary, type AccessRequest, type AdminUser, type EntitlementGrant } from '../api';
import { button, element, empty, formatDate, openDialog, reasonContent, setBusy, text } from '../shared/dom';

function identity(user: Partial<AdminUser> & { user_id?: number }): string {
  return user.full_name || user.username || user.email || (user.user_id ? `User ${user.user_id}` : 'Unknown user');
}

function expiryValue(value: string): number | null {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp / 1000 : null;
}

function activeGrant(grant: EntitlementGrant): boolean {
  return !grant.revoked_at && (!grant.expires_at || grant.expires_at * 1000 > Date.now());
}

export class AccessAdmin {
  private root: HTMLElement | null = null;
  private policies: AccessPolicySummary[] = [];

  constructor(private readonly shell: AppShell) {}

  async mount(root: HTMLElement): Promise<void> {
    this.root = root;
    root.replaceChildren(empty('Loading Runner access administration...'));
    await this.refresh();
  }

  private async refresh(): Promise<void> {
    if (!this.root) return;
    try {
      const [requests, policies, events] = await Promise.all([
        adminApi.listAccessRequests(), adminApi.listAccessPolicies(), adminApi.listAccessEvents(undefined, 50),
      ]);
      this.policies = policies;
      this.root.replaceChildren();
      const queue = element('section', 'admin-section');
      queue.append(element('div', 'admin-section-heading', [element('div', '', [text('h2', 'Pending eligibility decisions'), text('p', 'Approval grants an entitlement; it does not alter an upstream license.')])]));
      if (!requests.length) queue.append(empty('No pending access requests.'));
      else requests.forEach(request => queue.append(this.requestRow(request)));

      const overview = element('section', 'admin-section');
      overview.append(element('div', 'admin-section-heading', [element('div', '', [text('h2', 'Restricted policies'), text('p', 'Policy state and entitlement requirements are supplied by the server.')])]));
      if (!policies.length) overview.append(empty('No restricted Runner policies are configured.'));
      else {
        const list = element('div', 'policy-list');
        policies.forEach(policy => list.append(this.policyRow(policy)));
        overview.append(list);
      }

      const activity = element('section', 'admin-section');
      activity.append(element('div', 'admin-section-heading', [element('div', '', [text('h2', 'Recent access activity'), text('p', 'The latest bounded audit events from the Control Plane.')])]));
      if (!events.length) activity.append(empty('No recent restricted Runner activity.'));
      else {
        const feed = element('div', 'admin-event-feed');
        events.forEach(event => {
          const occurred = event.occurred_at ? event.occurred_at : event.created_at;
          const subject = event.full_name || event.username || event.user_name || 'Unknown user';
          const policy = event.label || event.task_type || event.runtime_family || event.policy_id || 'Restricted Runner';
          const outcome = event.outcome || event.decision || 'recorded';
          feed.append(element('article', '', [text('time', formatDate(occurred)), text('strong', subject), text('span', policy), text('b', outcome)]));
        });
        activity.append(feed);
      }
      this.root.append(queue, overview, activity);
    } catch (error) { this.root.replaceChildren(empty((error as Error).message || 'Unable to load Runner access administration.', true)); }
  }

  private requestRow(request: AccessRequest): HTMLElement {
    const approve = button('Approve', 'primary-button');
    approve.addEventListener('click', () => void this.decide(request, 'approved'));
    const reject = button('Reject');
    reject.addEventListener('click', () => void this.decide(request, 'rejected'));
    return element('article', 'access-row', [
      element('div', '', [text('strong', identity(request)), text('span', request.entitlement), text('p', request.reason || 'No request note provided.')]),
      element('div', 'admin-row-actions', [approve, reject]),
    ]);
  }

  private policyRow(policy: AccessPolicySummary): HTMLElement {
    const manage = button('Manage');
    manage.setAttribute('aria-label', `Manage ${policy.label || policy.policy_id}`);
    manage.addEventListener('click', () => void this.openPolicy(policy));
    const counts = element('dl', 'policy-counts');
    ([['Authorized', policy.authorized_users], ['Pending', policy.pending_requests], ['Suspended', policy.suspended_users]] as const)
      .forEach(([label, value]) => counts.append(element('div', '', [text('dt', label), text('dd', String(value))])));
    return element('article', 'policy-row', [
      element('div', '', [text('strong', policy.label || policy.policy_id), text('code', policy.policy_id), text('p', policy.description || '')]),
      counts, manage,
    ]);
  }

  private async decide(request: AccessRequest, decision: 'approved' | 'rejected'): Promise<void> {
    if (decision === 'rejected') {
      const fields = reasonContent(`Reject ${identity(request)}'s request for ${request.entitlement}.`);
      const note = await openDialog<string>({
        title: 'Reject access request?', content: fields.root, confirmLabel: 'Reject request', destructive: true,
        readValue: () => fields.reason.value.trim(), validate: value => value ? null : 'Enter a reason for rejecting this request.',
      });
      if (!note) return;
      try { await adminApi.decideAccessRequest(request.id, { decision, note }); this.shell.notify('Access request rejected.', 'success'); await this.refresh(); }
      catch (error) { this.shell.notify((error as Error).message, 'error'); }
      return;
    }
    const form = this.accessDecisionFields(request);
    const value = await openDialog<{ basis: string; expires_at: number | null; note: string | null }>({
      title: 'Approve access request', content: form.root, confirmLabel: 'Confirm eligibility',
      readValue: () => ({ basis: form.basis.value, expires_at: expiryValue(form.expiry.value), note: form.note.value.trim() || null }),
    });
    if (!value) return;
    try { await adminApi.decideAccessRequest(request.id, { decision, ...value }); this.shell.notify('Runner access approved.', 'success'); await this.refresh(); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  private accessDecisionFields(request?: AccessRequest): { root: HTMLElement; basis: HTMLSelectElement; expiry: HTMLInputElement; note: HTMLTextAreaElement } {
    const root = element('div', 'admin-dialog-fields');
    if (request) root.append(element('div', 'access-evidence', [
      text('strong', identity(request)), text('span', request.email || 'Email unavailable'),
      text('span', request.affiliation || 'Affiliation not provided'), text('p', request.reason || 'No request note provided.'),
    ]));
    const basis = element('select');
    [['lab_member', 'Lab member'], ['institutional_collaborator', 'Institutional collaborator'], ['individually_verified', 'Individually verified'], ['other', 'Other']]
      .forEach(([value, label]) => { const option = element('option'); option.value = value!; option.textContent = label!; basis.append(option); });
    const expiry = element('input'); expiry.type = 'datetime-local';
    const note = element('textarea'); note.rows = 3; note.maxLength = 1000;
    root.append(
      element('label', 'admin-field', [text('span', 'Verification basis'), basis]),
      element('label', 'admin-field', [text('span', 'Expiry (optional)'), expiry]),
      element('label', 'admin-field', [text('span', 'Decision note (optional)'), note]),
    );
    return { root, basis, expiry, note };
  }

  private async openPolicy(policy: AccessPolicySummary): Promise<void> {
    const content = element('div', 'policy-detail');
    content.append(empty('Loading policy detail...'));
    void this.renderPolicyDetail(policy, content);
    await openDialog({ title: policy.label || policy.policy_id, content });
  }

  private async renderPolicyDetail(policy: AccessPolicySummary, content: HTMLElement): Promise<void> {
    try {
      const detail = await adminApi.getAccessPolicy(policy.policy_id);
      content.replaceChildren(text('p', detail.policy.description || '', 'admin-dialog-copy'));
      const groups: Array<[string, Array<Record<string, unknown>>, string]> = [
        ['Authorized users', detail.authorized_users as unknown as Array<Record<string, unknown>>, 'No authorized users.'],
        ['Pending requests', detail.pending_requests as unknown as Array<Record<string, unknown>>, 'No pending requests.'],
        ['Suspended users', detail.suspended_users as unknown as Array<Record<string, unknown>>, 'No suspended users.'],
      ];
      groups.forEach(([title, items, emptyMessage]) => {
        const section = element('section', 'policy-detail-group', [text('h3', title)]);
        if (!items.length) section.append(empty(emptyMessage));
        items.forEach(item => {
          const user = item as unknown as Partial<AdminUser> & { user_id: number; grant_id?: number; request_id?: number; id?: number };
          let action: HTMLButtonElement | null = null;
          if (title === 'Authorized users' && user.grant_id) {
            action = button('Revoke');
            action.addEventListener('click', () => void this.revoke(user.user_id, user.grant_id!, identity(user), () => this.renderPolicyDetail(policy, content)));
          } else if (title === 'Pending requests') {
            const request = item as unknown as AccessRequest;
            action = button('Review'); action.addEventListener('click', () => void this.decide({ ...request, id: request.request_id || request.id }, 'approved'));
          } else if (title === 'Suspended users') {
            action = button('Clear suspension');
            action.addEventListener('click', async () => {
              setBusy(action!, true);
              try { await adminApi.clearSuspension(user.user_id, policy.policy_id); this.shell.notify('Suspension cleared.', 'success'); await this.renderPolicyDetail(policy, content); await this.refresh(); }
              catch (error) { this.shell.notify((error as Error).message, 'error'); }
            });
          }
          section.append(element('article', 'policy-person', [element('div', '', [text('strong', identity(user)), text('span', user.email || 'Email unavailable')]), action]));
        });
        content.append(section);
      });
    } catch (error) { content.replaceChildren(empty((error as Error).message || 'Unable to load policy detail.', true)); }
  }

  async openUser(user: AdminUser): Promise<void> {
    const content = element('div', 'user-access-detail');
    content.append(empty('Loading Runner access...'));
    const render = async (): Promise<void> => {
      try {
        const data = await adminApi.getUserEntitlements(user.id);
        content.replaceChildren(text('h3', 'Policy state'));
        if (!data.policies.length) content.append(empty('No restricted Runner policies are configured.'));
        data.policies.forEach(policy => {
          const actions = element('div', 'admin-row-actions');
          if (!policy.granted && policy.missing_entitlements?.[0]) {
            const grant = button('Grant');
            grant.addEventListener('click', () => void this.grant(user, policy.missing_entitlements![0]!, render));
            actions.append(grant);
          }
          if (policy.suspended) {
            const clear = button('Clear suspension');
            clear.addEventListener('click', async () => {
              setBusy(clear, true);
              try { await adminApi.clearSuspension(user.id, policy.policy_id); this.shell.notify('Suspension cleared.', 'success'); await render(); await this.refresh(); }
              catch (error) { this.shell.notify((error as Error).message, 'error'); }
            });
            actions.append(clear);
          }
          const state = `${policy.granted ? 'Granted' : policy.request_status === 'pending' ? 'Pending' : 'Not granted'}${policy.suspended ? `, suspended (${policy.retry_after_seconds || 0}s)` : ''}`;
          content.append(element('article', 'access-row', [element('div', '', [text('strong', policy.label), text('span', state)]), actions]));
        });
        content.append(text('h3', 'Grant history'));
        if (!data.grants.length) content.append(empty('No grant history.'));
        data.grants.forEach(grant => {
          const revoke = activeGrant(grant) ? button('Revoke') : null;
          revoke?.addEventListener('click', () => void this.revoke(user.id, grant.id, identity(user), render));
          const state = grant.revoked_at ? 'Revoked' : grant.expires_at && grant.expires_at * 1000 <= Date.now() ? 'Expired' : 'Active';
          content.append(element('article', 'access-row', [element('div', '', [text('strong', grant.entitlement), text('span', `${state}${grant.basis ? `, ${grant.basis.replaceAll('_', ' ')}` : ''}`)]), revoke]));
        });
      } catch (error) { content.replaceChildren(empty((error as Error).message || 'Unable to load Runner access.', true)); }
    };
    void render();
    await openDialog({ title: `Runner access: ${identity(user)}`, content });
  }

  private async grant(user: AdminUser, entitlement: string, onChanged: () => Promise<void>): Promise<void> {
    const fields = this.accessDecisionFields();
    const value = await openDialog<{ basis: string; expires_at: number | null; note: string | null }>({
      title: `Grant ${entitlement} to ${identity(user)}?`, content: fields.root, confirmLabel: 'Confirm eligibility',
      readValue: () => ({ basis: fields.basis.value, expires_at: expiryValue(fields.expiry.value), note: fields.note.value.trim() || null }),
    });
    if (!value) return;
    try { await adminApi.grantEntitlement(user.id, { entitlement, ...value }); this.shell.notify('Runner entitlement granted.', 'success'); await onChanged(); await this.refresh(); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  private async revoke(userId: number, grantId: number, name: string, onChanged: () => Promise<void>): Promise<void> {
    const content = element('div', 'admin-dialog-fields', [text('p', `Future submissions by ${name} will no longer be authorized by this entitlement.`)]);
    const confirmed = await openDialog({ title: 'Revoke Runner entitlement?', content, confirmLabel: 'Revoke entitlement', destructive: true });
    if (!confirmed) return;
    try { await adminApi.revokeEntitlement(userId, grantId); this.shell.notify('Runner entitlement revoked.', 'success'); await onChanged(); await this.refresh(); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }
}
