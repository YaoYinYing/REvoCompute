import { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 } from 'lucide';
import { createIcons } from 'lucide';
import { deleteTaskBatch, getTasks, prepareArchive, runTaskAction, type CurrentUser, type TaskSummary } from '../../api/app-api';
import { ApiError } from '../../app/session';
import { t } from '../../app/i18n';
import { guidedTour, recordTourResult } from '../../app/guided-tour';
import type { AppShell } from '../../app/shell';
import { initialTaskQuery, queryTasks, type TaskQuery } from './task-query';

const pollMilliseconds = 12_000;
const dashboardIcons = { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 };

// Machine facts keep a stable, locale-neutral format: dates and durations compare
// across cards and never depend on interface language.
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value)) : '-'; }
function formatDuration(seconds: number | null): string { if (seconds == null) return '-'; const total = Math.round(seconds); const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = total % 60; return [hours && `${hours}h`, minutes && `${minutes}m`, `${rest}s`].filter(Boolean).join(' '); }
function button(label: string, action: string, icon: string): HTMLButtonElement { const node = document.createElement('button'); node.type = 'button'; node.className = 'task-action'; node.dataset.action = action; node.title = label; node.setAttribute('aria-label', label); node.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`; return node; }
function textNode<K extends keyof HTMLElementTagNameMap>(tag: K, value: string, className = ''): HTMLElementTagNameMap[K] { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; }

export class Dashboard {
  private tasks: TaskSummary[] = [];
  private query: TaskQuery = initialTaskQuery();
  private selected = new Set<string>();
  private previewViewers = new Map<string, { dispose(): void }>();
  private poll: number | null = null;
  private controller = new AbortController();
  private list!: HTMLElement; private stats!: HTMLElement; private count!: HTMLElement; private error!: HTMLElement; private batch!: HTMLButtonElement;
  private advancedToggle!: HTMLButtonElement; private advancedPanel!: HTMLElement;

  constructor(private root: HTMLElement, private shell: AppShell, private user: CurrentUser) { this.build(); }
  async load(): Promise<void> {
    try { this.tasks = await getTasks(this.controller.signal);
      // The result step walks to a real result; record the first available one so the
      // tour never fabricates a task id or requests an id-less result route.
      recordTourResult(this.tasks.find(task => task.result.available)?.result.page_url);
      this.render(); this.schedule(); }
    catch (error) { if ((error as Error).name !== 'AbortError') this.fail(error); }
  }
  destroy(): void { this.controller.abort(); if (this.poll != null) clearTimeout(this.poll); this.disposePreviews(); }

  private build(): void {
    this.root.replaceChildren(); this.root.className = 'app-outlet dashboard-page';
    const head = document.createElement('header'); head.className = 'page-heading';
    head.innerHTML = `<div><h1>${t('dashboard.title')}</h1></div>`;
    const actions = document.createElement('div'); actions.className = 'page-actions';
    actions.append(guidedTour.launcher());
    const refresh = button(t('dashboard.action.refresh'), 'refresh', 'refresh-cw');
    const create = document.createElement('a'); create.href = '/compute/create_task'; create.className = 'primary-button'; create.textContent = t('dashboard.action.newTask');
    actions.append(create, refresh); head.append(actions);
    this.stats = document.createElement('section'); this.stats.className = 'dashboard-stats'; this.stats.setAttribute('aria-label', t('dashboard.stats.label'));

    // Filtering answers "which tasks?" and lives in one aligned tool band.
    const controls = document.createElement('section'); controls.className = 'work-toolbar'; controls.setAttribute('aria-label', t('dashboard.filters.label'));
    controls.innerHTML = `<label class="search-control"><span>${t('dashboard.filter.search')}</span><span class="input-with-action"><i data-lucide="search" aria-hidden="true"></i><input type="search" data-filter="search" placeholder="${t('dashboard.filter.searchPlaceholder')}" autocomplete="off"></span><small data-query-error></small></label>
      <label><span>${t('dashboard.filter.status')}</span><select data-filter="status"><option value="">${t('dashboard.filter.allStatuses')}</option><option value="pending">${t('dashboard.filter.status.pending')}</option><option value="running">${t('dashboard.filter.status.running')}</option><option value="finished">${t('dashboard.filter.status.finished')}</option><option value="failed">${t('dashboard.filter.status.failed')}</option><option value="cancelled">${t('dashboard.filter.status.cancelled')}</option></select></label>
      <label><span>${t('dashboard.filter.type')}</span><input type="search" data-filter="taskType" placeholder="${t('dashboard.filter.typePlaceholder')}"></label>
      ${this.user.role === 'admin' ? `<label><span>${t('dashboard.filter.owner')}</span><input type="search" data-filter="owner" placeholder="${t('dashboard.filter.ownerPlaceholder')}"></label>` : ''}
      <label><span>${t('dashboard.filter.order')}</span><select data-filter="sort"><option value="submitted">${t('dashboard.filter.newestSubmitted')}</option><option value="finished">${t('dashboard.filter.newestFinished')}</option></select></label>
      <button type="button" class="advanced-toggle" data-advanced aria-expanded="false" aria-controls="dashboard-advanced">${t('dashboard.filter.advanced')}</button>
      <div class="advanced-panel" id="dashboard-advanced" data-advanced-panel hidden>
        <label><span>${t('dashboard.filter.submittedFrom')}</span><input type="date" data-filter="submittedFrom"></label>
        <label><span>${t('dashboard.filter.submittedTo')}</span><input type="date" data-filter="submittedTo"></label>
        <label><span>${t('dashboard.filter.finishedFrom')}</span><input type="date" data-filter="finishedFrom"></label>
        <label><span>${t('dashboard.filter.finishedTo')}</span><input type="date" data-filter="finishedTo"></label>
        <label class="advanced-regex"><span>${t('dashboard.filter.regex')}</span><button type="button" data-toggle-regex aria-pressed="false" title="${t('dashboard.filter.regex')}">.*</button></label>
      </div>`;
    this.error = controls.querySelector('[data-query-error]')!;
    this.advancedToggle = controls.querySelector('[data-advanced]')!;
    this.advancedPanel = controls.querySelector('[data-advanced-panel]')!;

    // Presentation answers "how should I view this?" — visually separate.
    const viewToolbar = document.createElement('div'); viewToolbar.className = 'view-toolbar';
    this.count = textNode('p', '', 'list-count'); this.count.setAttribute('aria-live', 'polite');
    const layout = document.createElement('fieldset'); layout.className = 'layout-switch';
    layout.innerHTML = `<legend>${t('dashboard.view.label')}</legend><button type="button" data-layout="detailed" aria-pressed="true">${t('dashboard.view.detailed')}</button><button type="button" data-layout="compact" aria-pressed="false">${t('dashboard.view.compact')}</button><button type="button" data-layout="table" aria-pressed="false">${t('dashboard.view.table')}</button>`;
    this.batch = button(t('dashboard.card.deleteSelected'), 'batch-delete', 'trash-2'); this.batch.hidden = true;
    viewToolbar.append(this.count, this.batch, layout);

    this.list = document.createElement('section'); this.list.className = 'task-list'; this.list.setAttribute('aria-live', 'polite');
    this.root.append(head, this.stats, controls, viewToolbar, this.list);
    controls.addEventListener('input', event => { const target = event.target as HTMLInputElement | HTMLSelectElement; const key = target.dataset.filter as keyof TaskQuery | undefined; if (key) { (this.query as unknown as Record<string, unknown>)[key] = target.value; this.renderList(); } });
    controls.querySelector('[data-toggle-regex]')?.addEventListener('click', event => { this.query.regex = !this.query.regex; const target = event.currentTarget as HTMLButtonElement; target.setAttribute('aria-pressed', String(this.query.regex)); target.classList.toggle('active', this.query.regex); this.renderList(); });
    this.advancedToggle.addEventListener('click', () => this.toggleAdvanced());
    controls.addEventListener('change', () => this.updateAdvancedState());
    viewToolbar.querySelectorAll<HTMLButtonElement>('[data-layout]').forEach(item => item.addEventListener('click', () => { this.query.layout = item.dataset.layout as TaskQuery['layout']; viewToolbar.querySelectorAll('[data-layout]').forEach(button => button.setAttribute('aria-pressed', String(button === item))); this.renderList(); }));
    this.root.addEventListener('click', event => void this.handleAction(event));
    createIcons({ icons: dashboardIcons, root: this.root });
    guidedTour.resumeIfActive();
  }

  private toggleAdvanced(force?: boolean): void {
    const open = force ?? this.advancedPanel.hidden;
    this.advancedPanel.hidden = !open;
    this.advancedToggle.setAttribute('aria-expanded', String(open));
    this.updateAdvancedState();
  }

  private updateAdvancedState(): void {
    const count = ['submittedFrom', 'submittedTo', 'finishedFrom', 'finishedTo'].filter(key => Boolean((this.query as unknown as Record<string, unknown>)[key])).length + (this.query.regex ? 1 : 0);
    this.advancedToggle.classList.toggle('has-active', count > 0);
    const label = count ? t('dashboard.filter.advancedActive', { count }) : t('dashboard.filter.advanced');
    this.advancedToggle.textContent = label;
    if (count) { const badge = document.createElement('span'); badge.className = 'advanced-count'; badge.textContent = String(count); this.advancedToggle.append(badge); }
  }

  private schedule(): void { if (this.poll != null) clearTimeout(this.poll); if (this.tasks.some(task => !task.terminal)) this.poll = window.setTimeout(() => void this.load(), pollMilliseconds); }
  private render(): void { this.renderStats(); this.renderList(); }
  private renderStats(): void {
    const values: Array<[string, number, boolean]> = [
      [t('dashboard.stats.total'), this.tasks.length, false], [t('dashboard.stats.pending'), this.tasks.filter(task => task.status === 'pending').length, false],
      [t('dashboard.stats.running'), this.tasks.filter(task => task.status === 'running').length, false], [t('dashboard.stats.finished'), this.tasks.filter(task => task.status === 'finished').length, false],
      [t('dashboard.stats.attention'), this.tasks.filter(task => ['failed', 'cancelled'].includes(task.status)).length, true],
    ];
    this.stats.replaceChildren(...values.map(([label, value, attention]) => { const item = document.createElement('div'); if (attention) { item.dataset.attention = ''; if (value === 0) item.dataset.empty = ''; } item.innerHTML = `<span>${label}</span><strong>${value}</strong>`; return item; }));
  }
  private renderList(): void {
    this.disposePreviews();
    const result = queryTasks(this.tasks, this.query); this.error.textContent = result.error || '';
    this.count.textContent = t('dashboard.list.count', { shown: result.tasks.length, total: this.tasks.length });
    const batchLabel = `${t('dashboard.card.deleteSelected')} (${this.selected.size})`;
    this.batch.hidden = this.user.role !== 'admin' || this.selected.size === 0;
    this.batch.title = batchLabel;
    this.batch.setAttribute('aria-label', batchLabel);
    this.batch.querySelector('span')!.textContent = batchLabel;
    this.updateAdvancedState();
    this.list.dataset.layout = this.query.layout; this.list.replaceChildren();
    if (!result.tasks.length) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = result.error ? t('dashboard.list.fixExpression') : t('dashboard.list.empty'); this.list.append(empty); return; }
    if (this.query.layout === 'table') this.renderTable(result.tasks); else result.tasks.forEach(task => this.list.append(this.taskCard(task)));
    createIcons({ icons: dashboardIcons, root: this.list });
  }
  private taskCard(task: TaskSummary): HTMLElement {
    const card = document.createElement('article'); card.className = 'task-card'; card.dataset.status = task.status;
    const header = document.createElement('header'); const identity = document.createElement('div');
    identity.append(textNode('h2', task.display_name), textNode('p', task.task_type, 'task-card-type'));
    const status = document.createElement('span'); status.className = `status status-${task.status.replace(':', '-')}`; status.textContent = task.outcome || task.status; header.append(identity, status);
    const facts = document.createElement('dl');
    const factValues: Array<[string, string, boolean]> = [
      [t('dashboard.card.submitted'), formatDate(task.submitted_at), false],
      [t('dashboard.card.taskId'), task.task_id, true],
      [t('dashboard.card.walltime'), formatDuration(task.walltime_seconds), false],
    ];
    if (task.finished_at) factValues.push([t('dashboard.card.finished'), formatDate(task.finished_at), false]);
    if (this.user.role === 'admin') factValues.push([t('dashboard.card.owner'), task.owner || '-', false]);
    factValues.forEach(([label, value, machine]) => { const row = document.createElement('div'); const dt = document.createElement('dt'); dt.textContent = label; const dd = document.createElement('dd'); dd.textContent = value; if (machine) dd.classList.add('machine'); row.append(dt, dd); facts.append(row); });
    if (task.progress != null && !task.terminal) { const progress = document.createElement('p'); progress.className = 'task-progress'; progress.textContent = typeof task.progress === 'string' ? task.progress : JSON.stringify(task.progress); facts.append(progress); }
    const preview = this.inputPreview(task); const actions = this.taskActions(task);
    if (task.error) { const problem = document.createElement('details'); problem.className = 'task-error'; const summary = document.createElement('summary'); summary.textContent = t('dashboard.card.executionError'); const body = document.createElement('p'); body.textContent = task.error; problem.append(summary, body); card.append(header, facts, problem, preview, actions); } else card.append(header, facts, preview, actions);
    return card;
  }
  private inputPreview(task: TaskSummary): HTMLElement {
    const wrap = document.createElement('div'); if (!task.input_preview) return wrap;
    const details = document.createElement('details'); details.className = 'input-preview'; const summary = document.createElement('summary'); summary.textContent = t('dashboard.card.inputPreview'); const content = document.createElement('div'); content.className = 'input-preview-host'; content.textContent = t('dashboard.card.previewHint'); details.append(summary, content);
    details.addEventListener('toggle', () => {
      if (!details.open) { this.previewViewers.get(task.task_id)?.dispose(); this.previewViewers.delete(task.task_id); details.dataset.loaded = ''; content.textContent = t('dashboard.card.previewHint'); return; }
      if (details.dataset.loaded) return; details.dataset.loaded = 'true'; content.textContent = t('dashboard.card.previewLoading');
      Promise.all([
        fetch(task.input_preview!.url, { credentials: 'same-origin' }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text(); }),
        import('../structure/MolecularViewer.js'),
      ]).then(async ([data, { MolecularViewer }]) => {
        if (!details.open || !details.isConnected) return; content.replaceChildren(); const viewer = await MolecularViewer.mount(content, { theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light' });
        if (!details.open || !details.isConnected) { viewer.dispose(); return; } this.previewViewers.set(task.task_id, viewer); await viewer.loadStructure({ data, format: task.input_preview!.format, label: task.display_name });
      }).catch(error => { if (details.isConnected) content.textContent = `Unable to load structure: ${(error as Error).message}`; });
    }); wrap.append(details); return wrap;
  }
  private taskActions(task: TaskSummary): HTMLElement {
    const actions = document.createElement('footer'); actions.className = 'task-actions'; actions.dataset.taskId = task.task_id;
    if (task.result.available) { const open = document.createElement('a'); open.href = task.result.page_url; open.className = 'task-action primary-action'; open.innerHTML = `<i data-lucide="external-link" aria-hidden="true"></i><span>${t('dashboard.card.results')}</span>`; actions.append(open); if (task.result.download_url) { const download = document.createElement('a'); download.href = task.result.download_url; download.className = 'task-action'; download.innerHTML = `<i data-lucide="download" aria-hidden="true"></i><span>${t('dashboard.card.download')}</span>`; actions.append(download); } else if (task.result.archive_request_allowed && task.result.archive_request_url) actions.append(button(t('dashboard.card.prepareZip'), 'archive', 'archive')); }
    if (task.actions.cancel.allowed) actions.append(button(t('dashboard.card.cancel'), 'cancel', 'ban'));
    if (task.actions.delete.allowed) actions.append(button(t('dashboard.card.delete'), 'delete', 'trash-2'));
    if (this.user.role === 'admin' && task.actions.delete.allowed) { const label = document.createElement('label'); label.className = 'task-select'; const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.action = 'select'; input.checked = this.selected.has(task.task_id); const text = document.createElement('span'); text.textContent = t('dashboard.card.select'); label.append(input, text); actions.prepend(label); }
    return actions;
  }
  private renderTable(tasks: TaskSummary[]): void {
    const table = document.createElement('table'); table.className = 'task-table'; table.innerHTML = `<thead><tr><th>${t('dashboard.table.name')}</th><th>${t('dashboard.card.type')}</th>${this.user.role === 'admin' ? `<th>${t('dashboard.card.owner')}</th>` : ''}<th>${t('dashboard.card.submitted')}</th><th>${t('dashboard.filter.status')}</th><th><span class="sr-only">${t('dashboard.table.actions')}</span></th></tr></thead>`; const body = document.createElement('tbody');
    tasks.forEach(task => { const row = document.createElement('tr'); const cells = [task.display_name, task.task_type, ...(this.user.role === 'admin' ? [task.owner || '-'] : []), formatDate(task.submitted_at), task.status]; cells.forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }); const actionCell = document.createElement('td'); actionCell.append(this.taskActions(task)); row.append(actionCell); body.append(row); }); table.append(body); this.list.append(table);
  }
  private async handleAction(event: Event): Promise<void> {
    const target = (event.target as Element).closest<HTMLElement>('[data-action]'); if (!target) return; const action = target.dataset.action;
    if (action === 'refresh') { await this.load(); return; }
    if (action === 'batch-delete') { if (!confirm(t('dashboard.confirm.batchDelete', { count: this.selected.size }))) return; const taskIds = [...this.selected]; this.selected.clear(); await this.mutate(() => deleteTaskBatch(taskIds), t('dashboard.notice.deletedSelected')); return; }
    const footer = target.closest<HTMLElement>('[data-task-id]'); const task = this.tasks.find(item => item.task_id === footer?.dataset.taskId); if (!task) return;
    if (action === 'select') { (target as HTMLInputElement).checked ? this.selected.add(task.task_id) : this.selected.delete(task.task_id); this.renderList(); return; }
    if (action === 'cancel' && confirm(t('dashboard.confirm.cancel', { name: task.display_name }))) await this.mutate(() => runTaskAction(task.actions.cancel, 'POST'), t('dashboard.notice.cancelled'));
    if (action === 'delete' && confirm(t('dashboard.confirm.delete', { name: task.display_name }))) await this.mutate(() => runTaskAction(task.actions.delete, 'DELETE'), t('dashboard.notice.deleted'));
    if (action === 'archive' && task.result.archive_request_url) await this.mutate(() => prepareArchive(task.result.archive_request_url!), t('dashboard.notice.archive'));
  }
  private async mutate(operation: () => Promise<unknown>, message: string): Promise<void> { try { await operation(); this.shell.notify(message, 'success'); await this.load(); } catch (error) { this.shell.notify((error as Error).message, 'error'); } }
  private disposePreviews(): void { this.previewViewers.forEach(viewer => viewer.dispose()); this.previewViewers.clear(); }
  private fail(error: unknown): void { if (error instanceof ApiError && error.status === 401) { location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return; } this.list.replaceChildren(); const state = document.createElement('p'); state.className = 'empty-state error-state'; state.textContent = (error as Error).message || t('dashboard.error.load'); this.list.append(state); }
}

export async function mountDashboard(root: HTMLElement, shell: AppShell, user: CurrentUser): Promise<Dashboard> { const view = new Dashboard(root, shell, user); await view.load(); return view; }
