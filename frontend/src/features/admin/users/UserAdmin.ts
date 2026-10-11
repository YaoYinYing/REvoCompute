import type { CurrentUser } from '../../../api/app-api';
import { academicPositionOptions } from '../../../app/domain-vocabulary';
import type { AppShell } from '../../../app/shell';
import { AccessAdmin } from '../access/AccessAdmin';
import { adminApi, type AdminUser, type AdminUserCreate, type AdminUserUpdate } from '../api';
import { CreditAdmin } from '../credits/CreditAdmin';
import { button, element, empty, formatCredits, openDialog, setBusy, text } from '../shared/dom';
import { mountTabs } from '../shared/tabs';
import { loadEnvelope, loadStorageQuota } from './ResourceEnvelope';

export interface UserFilters { query: string; role: string; status: string }

export function filterUsers(users: AdminUser[], filters: UserFilters): AdminUser[] {
  const query = filters.query.trim().toLowerCase();
  return users.filter(user => {
    const accountMatches = filters.status === 'all'
      || user.user_status === filters.status
      || (filters.status === 'pending' && !['approved', 'rejected'].includes(user.registration_status));
    return (filters.role === 'all' || user.role === filters.role)
      && accountMatches
      && (!query || [user.full_name, user.username, user.email, user.affiliation].filter(Boolean).join(' ').toLowerCase().includes(query));
  });
}

const positions: Array<[string, string]> = [
  ['', 'Not specified'], ...academicPositionOptions,
];

function select(options: Array<[string, string]>, selected?: string | null): HTMLSelectElement {
  const control = element('select');
  for (const [value, label] of options) {
    const option = element('option'); option.value = value; option.textContent = label; option.selected = selected === value; control.append(option);
  }
  return control;
}

function labeled(label: string, control: HTMLElement): HTMLLabelElement {
  return element('label', 'admin-field', [text('span', label), control]);
}

function input(type: string, value = ''): HTMLInputElement {
  const control = element('input'); control.type = type; control.value = value; return control;
}

export class UserAdmin {
  private users: AdminUser[] = [];
  private selected = new Set<number>();
  private tableBody = element('tbody');
  private count = text('span', 'Loading...', 'admin-count');
  private search = input('search');
  private role = select([['all', 'All roles'], ['admin', 'Admin'], ['user', 'User'], ['guest', 'Guest']], 'all');
  private status = select([['all', 'All accounts'], ['active', 'Active'], ['pending', 'Pending'], ['banned', 'Banned']], 'all');
  private selectAll = input('checkbox');
  private batchBar = element('div', 'admin-batch-bar');
  private readonly access: AccessAdmin;
  private readonly credits: CreditAdmin;

  constructor(private readonly shell: AppShell, private readonly currentUser: CurrentUser) {
    this.access = new AccessAdmin(shell);
    this.credits = new CreditAdmin(shell, () => this.loadUsers());
  }

  async mount(root: HTMLElement): Promise<void> {
    const usersPanel = element('section', 'admin-tab-panel');
    const accessPanel = element('section', 'admin-tab-panel');
    const reconciliationPanel = element('section', 'admin-tab-panel');
    mountTabs(root, [
      { id: 'users', label: 'Users', panel: usersPanel },
      { id: 'access', label: 'Runner access', panel: accessPanel },
      { id: 'credits', label: 'GPU reconciliation', panel: reconciliationPanel },
    ]);
    this.mountUsers(usersPanel);
    await Promise.all([this.loadUsers(), this.access.mount(accessPanel), this.credits.renderReconciliation(reconciliationPanel)]);
  }

  private mountUsers(root: HTMLElement): void {
    this.search.placeholder = 'Name, username, email, affiliation';
    this.search.autocomplete = 'off';
    this.search.addEventListener('input', () => this.renderUsers());
    this.role.addEventListener('change', () => this.renderUsers());
    this.status.addEventListener('change', () => this.renderUsers());
    const add = button('Create user', 'primary-button'); add.addEventListener('click', () => void this.openCreate());
    const toolbar = element('div', 'admin-toolbar', [labeled('Search', this.search), labeled('Role', this.role), labeled('Account', this.status), this.count, add]);

    this.selectAll.setAttribute('aria-label', 'Select all visible users');
    this.selectAll.addEventListener('change', () => {
      const visible = filterUsers(this.users, this.filters()).filter(user => user.username !== this.currentUser.username);
      visible.forEach(user => this.selectAll.checked ? this.selected.add(user.id) : this.selected.delete(user.id));
      this.renderUsers();
    });
    const table = element('table', 'admin-table user-admin-table');
    const head = element('thead');
    head.append(element('tr', '', [element('th', 'admin-select-cell', [this.selectAll]), text('th', 'User'), text('th', 'Affiliation'), text('th', 'Role'), text('th', 'GPU'), text('th', 'Status'), text('th', 'Actions')]));
    table.append(head, this.tableBody);

    const reset = button('Reset all credits', 'admin-danger-button');
    reset.addEventListener('click', () => void this.credits.resetAll(this.users.length));
    const danger = element('section', 'admin-danger-zone', [
      element('div', '', [text('h2', 'Global GPU credit reset'), text('p', 'Restore current users to their configured monthly allowance without deleting usage history.')]), reset,
    ]);
    root.append(toolbar, this.batchBar, element('div', 'admin-table-scroll', [table]), danger);
  }

  private filters(): UserFilters { return { query: this.search.value, role: this.role.value, status: this.status.value }; }

  private async loadUsers(): Promise<void> {
    this.tableBody.replaceChildren(element('tr', '', [element('td', 'admin-empty', ['Loading users...'])]));
    this.tableBody.querySelector('td')?.setAttribute('colspan', '7');
    try { this.users = await adminApi.listUsers(); this.renderUsers(); }
    catch (error) {
      const cell = element('td', 'admin-empty error-state', [(error as Error).message || 'Unable to load users.']); cell.colSpan = 7;
      this.tableBody.replaceChildren(element('tr', '', [cell]));
    }
  }

  private renderUsers(): void {
    const visible = filterUsers(this.users, this.filters());
    this.count.textContent = `${visible.length} of ${this.users.length} users`;
    this.tableBody.replaceChildren();
    if (!visible.length) {
      const cell = element('td', 'admin-empty', ['No users match these filters.']); cell.colSpan = 7;
      this.tableBody.append(element('tr', '', [cell]));
    } else visible.forEach(user => this.tableBody.append(this.userRow(user)));
    const selectable = visible.filter(user => user.username !== this.currentUser.username);
    this.selectAll.checked = selectable.length > 0 && selectable.every(user => this.selected.has(user.id));
    this.selectAll.indeterminate = selectable.some(user => this.selected.has(user.id)) && !this.selectAll.checked;
    this.renderBatch();
  }

  private userRow(user: AdminUser): HTMLTableRowElement {
    const ownAccount = user.username === this.currentUser.username;
    const checkbox = input('checkbox'); checkbox.checked = this.selected.has(user.id); checkbox.disabled = ownAccount;
    checkbox.setAttribute('aria-label', `Select ${user.full_name || user.username}`);
    checkbox.addEventListener('change', () => { checkbox.checked ? this.selected.add(user.id) : this.selected.delete(user.id); this.renderBatch(); });
    const identity = element('td', 'admin-identity', [text('strong', user.full_name || user.username), text('span', user.username), text('small', user.email)]);
    const gpu = element('td', '', [text('span', user.allow_gpu_use ? 'Admitted' : 'Blocked', `admin-badge ${user.allow_gpu_use ? 'is-good' : ''}`), text('small', `${formatCredits(user.gpu_credit.remaining_credits)} credits`)]);
    const statuses = element('td', 'admin-statuses', [text('span', user.registration_status, 'admin-badge'), text('span', user.user_status, 'admin-badge')]);
    const edit = button('Edit'); edit.addEventListener('click', () => void this.openEdit(user));
    const credit = button('Credits'); credit.addEventListener('click', () => void this.credits.open(user));
    const access = button('Access'); access.addEventListener('click', () => void this.access.openUser(user));
    const envelope = button('Resources'); envelope.addEventListener('click', () => void this.openResourceEnvelope(user));
    const remove = button('Delete', 'admin-text-danger'); remove.disabled = ownAccount; remove.addEventListener('click', () => void this.deleteUser(user));
    return element('tr', '', [element('td', 'admin-select-cell', [checkbox]), identity, text('td', user.affiliation || 'Not provided'), text('td', user.role), gpu, statuses, element('td', 'admin-table-actions', [edit, credit, access, envelope, remove])]);
  }

  private renderBatch(): void {
    this.batchBar.replaceChildren();
    if (!this.selected.size) { this.batchBar.hidden = true; return; }
    this.batchBar.hidden = false;
    this.batchBar.append(text('strong', `${this.selected.size} selected`));
    (['enable', 'disable', 'delete'] as const).forEach(action => {
      const control = button(`${action[0]!.toUpperCase()}${action.slice(1)}`, action === 'enable' ? 'secondary-button' : 'admin-text-danger');
      control.addEventListener('click', () => void this.runBatch(action));
      this.batchBar.append(control);
    });
  }

  private async runBatch(action: 'enable' | 'disable' | 'delete'): Promise<void> {
    const content = element('div', 'admin-dialog-fields', [text('p', `${this.selected.size} selected user(s) will be affected.`)]);
    const confirmed = await openDialog({ title: `${action[0]!.toUpperCase()}${action.slice(1)} selected users?`, content, confirmLabel: `${action} ${this.selected.size} users`, destructive: action !== 'enable' });
    if (!confirmed) return;
    try {
      const result = await adminApi.batchUsers(action, [...this.selected]);
      this.selected.clear(); await this.loadUsers(); this.shell.notify(result.message, 'success');
    } catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  private async deleteUser(user: AdminUser): Promise<void> {
    const content = element('div', 'admin-dialog-fields', [text('p', `Delete ${user.full_name || user.username}? The account will be soft-deleted and future task access removed.`)]);
    const confirmed = await openDialog({ title: 'Delete user?', content, confirmLabel: 'Delete user', destructive: true });
    if (!confirmed) return;
    try { await adminApi.deleteUser(user.id); await this.loadUsers(); this.shell.notify('User deleted.', 'success'); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  private async openCreate(): Promise<void> {
    const username = input('text'); username.minLength = 3; username.maxLength = 64; username.autocomplete = 'username';
    const email = input('email'); email.autocomplete = 'email';
    const password = input('password'); password.minLength = 8; password.autocomplete = 'new-password';
    const fullName = input('text'); fullName.maxLength = 128; fullName.autocomplete = 'name';
    const affiliation = input('text'); affiliation.maxLength = 256; affiliation.autocomplete = 'organization';
    const position = select(positions);
    const piName = input('text'); piName.maxLength = 128;
    const role = select([['user', 'User'], ['admin', 'Admin'], ['guest', 'Guest']], 'user');
    const root = element('div', 'admin-form-grid', [labeled('Username', username), labeled('Email', email), labeled('Password', password), labeled('Full name', fullName), labeled('Affiliation', affiliation), labeled('Position', position), labeled('PI or supervisor', piName), labeled('Role', role)]);
    const value = await openDialog<AdminUserCreate>({
      title: 'Create user', content: root, confirmLabel: 'Create user',
      readValue: () => ({ username: username.value.trim(), email: email.value.trim(), password: password.value, full_name: fullName.value.trim() || null, affiliation: affiliation.value.trim() || null, position: position.value || null, pi_name: piName.value.trim() || null, role: role.value as AdminUserCreate['role'] }),
      validate: candidate => !candidate.username || !candidate.email || candidate.password.length < 8 ? 'Username, email, and a password of at least 8 characters are required.' : null,
    });
    if (!value) return;
    try { const result = await adminApi.createUser(value); await this.loadUsers(); this.shell.notify(`Created ${result.username}.`, 'success'); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  private async openEdit(user: AdminUser): Promise<void> {
    const ownAccount = user.username === this.currentUser.username;
    const email = input('email', user.email); const fullName = input('text', user.full_name || '');
    const affiliation = input('text', user.affiliation || ''); const position = select(positions, user.position);
    const piName = input('text', user.pi_name || ''); const password = input('password'); password.minLength = 8; password.autocomplete = 'new-password';
    const role = select([['admin', 'Admin'], ['user', 'User'], ['guest', 'Guest']], user.role); role.disabled = ownAccount;
    const registrationOptions: Array<[string, string]> = ['approved', 'rejected'].includes(user.registration_status)
      ? [['approved', 'Approved'], ['rejected', 'Rejected']]
      : [['', `${user.registration_status.replaceAll('_', ' ')} (unchanged)`], ['approved', 'Approve'], ['rejected', 'Reject']];
    const accountOptions: Array<[string, string]> = ['active', 'banned'].includes(user.user_status)
      ? [['active', 'Active'], ['banned', 'Banned']]
      : [['', `${user.user_status.replaceAll('_', ' ')} (unchanged)`], ['active', 'Activate'], ['banned', 'Ban']];
    const registration = select(registrationOptions, ['approved', 'rejected'].includes(user.registration_status) ? user.registration_status : '');
    const account = select(accountOptions, ['active', 'banned'].includes(user.user_status) ? user.user_status : ''); if (ownAccount) account.querySelector<HTMLOptionElement>('option[value="banned"]')!.disabled = true;
    const gpu = input('checkbox'); gpu.checked = user.allow_gpu_use;
    const root = element('div', 'admin-form-grid', [labeled('Email', email), labeled('Full name', fullName), labeled('Affiliation', affiliation), labeled('Position', position), labeled('PI or supervisor', piName), labeled('Role', role), labeled('Registration', registration), labeled('Account', account), labeled('New password (optional)', password), element('label', 'admin-check-field', [gpu, text('span', 'Admit GPU tasks')])]);
    const value = await openDialog<AdminUserUpdate>({
      title: `Edit ${user.full_name || user.username}`, content: root, confirmLabel: 'Save user',
      readValue: () => ({ email: email.value.trim(), full_name: fullName.value.trim(), affiliation: affiliation.value.trim(), position: position.value || null, pi_name: piName.value.trim(), ...(registration.value ? { registration_status: registration.value as 'approved' | 'rejected' } : {}), ...(account.value ? { user_status: account.value as 'active' | 'banned' } : {}), ...(ownAccount ? {} : { role: role.value as 'admin' | 'user' | 'guest' }), allow_gpu_use: gpu.checked, ...(password.value ? { password: password.value } : {}) }),
      validate: candidate => !candidate.email ? 'Email is required.' : candidate.password && candidate.password.length < 8 ? 'New passwords must contain at least 8 characters.' : null,
    });
    if (!value) return;
    try { await adminApi.updateUser(user.id, value); await this.loadUsers(); this.shell.notify('User updated.', 'success'); }
    catch (error) { this.shell.notify((error as Error).message, 'error'); }
  }

  /**
   * The canonical resource envelope for one account, plus its quota control.
   *
   * It reads the same projection admission decides against, so an operator sees
   * the position the server actually uses rather than a balance re-derived here,
   * and the quota control sends one of the three decisions to the endpoint that
   * owns it instead of composing an effective ceiling locally.
   */
  async openResourceEnvelope(user: AdminUser): Promise<void> {
    const [envelope, quota] = await Promise.all([loadEnvelope(user.id), loadStorageQuota(user, this.shell)]);
    const root = element('div', 'resource-envelope-host', [envelope, quota]);
    await openDialog({ title: `Resource envelope: ${user.full_name || user.username}`, content: root });
  }
}
