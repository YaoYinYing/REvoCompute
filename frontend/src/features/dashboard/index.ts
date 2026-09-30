import { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 } from 'lucide';
import { createIcons } from 'lucide';
import { deleteTaskBatch, getTasks, prepareArchive, runTaskAction, type CurrentUser, type TaskSummary } from '../../api/app-api';
import { ApiError } from '../../app/session';
import type { AppShell } from '../../app/shell';
import { initialTaskQuery, queryTasks, type TaskQuery } from './task-query';

const pollMilliseconds = 12_000;
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-'; }
function formatDuration(seconds: number | null): string { if (seconds == null) return '-'; const total = Math.round(seconds); const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = total % 60; return [hours && `${hours}h`, minutes && `${minutes}m`, `${rest}s`].filter(Boolean).join(' '); }
function button(label: string, action: string, icon: string): HTMLButtonElement { const node = document.createElement('button'); node.type = 'button'; node.className = 'task-action'; node.dataset.action = action; node.title = label; node.setAttribute('aria-label', label); node.innerHTML = `<i data-lucide="${icon}"></i><span>${label}</span>`; return node; }

export class Dashboard {
  private tasks: TaskSummary[] = [];
  private query: TaskQuery = initialTaskQuery();
  private selected = new Set<string>();
  private previewViewers = new Map<string, { dispose(): void }>();
  private poll: number | null = null;
  private controller = new AbortController();
  private list!: HTMLElement; private stats!: HTMLElement; private count!: HTMLElement; private error!: HTMLElement; private batch!: HTMLButtonElement;

  constructor(private root: HTMLElement, private shell: AppShell, private user: CurrentUser) { this.build(); }
  async load(): Promise<void> {
    try { this.tasks = await getTasks(this.controller.signal); this.render(); this.schedule(); }
    catch (error) { if ((error as Error).name !== 'AbortError') this.fail(error); }
  }
  destroy(): void { this.controller.abort(); if (this.poll != null) clearTimeout(this.poll); this.disposePreviews(); }

  private build(): void {
    this.root.replaceChildren(); this.root.className = 'app-outlet dashboard-page';
    const head = document.createElement('header'); head.className = 'page-heading';
    head.innerHTML = '<div><h1>Dashboard</h1></div>';
    const actions = document.createElement('div'); actions.className = 'page-actions'; const refresh = button('Refresh', 'refresh', 'refresh-cw'); const create = document.createElement('a'); create.href = '/compute/create_task'; create.className = 'primary-button'; create.textContent = 'New task'; actions.append(create, refresh); head.append(actions);
    this.stats = document.createElement('section'); this.stats.className = 'dashboard-stats'; this.stats.setAttribute('aria-label', 'Task totals');
    const controls = document.createElement('section'); controls.className = 'work-toolbar'; controls.setAttribute('aria-label', 'Task filters');
    controls.innerHTML = `<label class="search-control"><span>Search</span><span class="input-with-action"><i data-lucide="search"></i><input type="search" data-filter="search" placeholder="Task name" autocomplete="off"><button type="button" data-toggle-regex aria-pressed="false" title="Use regular expression">.*</button></span><small data-query-error></small></label>
      <label><span>Status</span><select data-filter="status"><option value="">All statuses</option><option>pending</option><option>running</option><option>finished</option><option>failed</option><option>cancelled</option></select></label>
      <label><span>Type</span><input type="search" data-filter="taskType" placeholder="All types"></label>
      ${this.user.role === 'admin' ? '<label><span>Owner</span><input type="search" data-filter="owner" placeholder="All owners"></label>' : ''}
      <label><span>Order</span><select data-filter="sort"><option value="submitted">Newest submitted</option><option value="finished">Newest finished</option></select></label>
      <fieldset class="layout-switch"><legend>Layout</legend><button type="button" data-layout="detailed" aria-pressed="true">Detailed</button><button type="button" data-layout="compact" aria-pressed="false">Compact</button><button type="button" data-layout="table" aria-pressed="false">Table</button></fieldset>
      <details class="advanced-filters"><summary>Date filters</summary><div><label><span>Submitted from</span><input type="date" data-filter="submittedFrom"></label><label><span>Submitted to</span><input type="date" data-filter="submittedTo"></label><label><span>Finished from</span><input type="date" data-filter="finishedFrom"></label><label><span>Finished to</span><input type="date" data-filter="finishedTo"></label></div></details>`;
    this.error = controls.querySelector('[data-query-error]')!;
    const listHead = document.createElement('div'); listHead.className = 'list-heading'; this.count = document.createElement('p'); this.batch = button('Delete selected', 'batch-delete', 'trash-2'); this.batch.hidden = true; listHead.append(this.count, this.batch);
    this.list = document.createElement('section'); this.list.className = 'task-list'; this.list.setAttribute('aria-live', 'polite');
    this.root.append(head, this.stats, controls, listHead, this.list);
    controls.addEventListener('input', event => { const target = event.target as HTMLInputElement | HTMLSelectElement; const key = target.dataset.filter as keyof TaskQuery | undefined; if (key) { (this.query as unknown as Record<string, unknown>)[key] = target.value; this.renderList(); } });
    controls.querySelector('[data-toggle-regex]')?.addEventListener('click', event => { this.query.regex = !this.query.regex; const target = event.currentTarget as HTMLButtonElement; target.setAttribute('aria-pressed', String(this.query.regex)); target.classList.toggle('active', this.query.regex); this.renderList(); });
    controls.querySelectorAll<HTMLButtonElement>('[data-layout]').forEach(item => item.addEventListener('click', () => { this.query.layout = item.dataset.layout as TaskQuery['layout']; controls.querySelectorAll('[data-layout]').forEach(button => button.setAttribute('aria-pressed', String(button === item))); this.renderList(); }));
    this.root.addEventListener('click', event => void this.handleAction(event));
    createIcons({ icons: { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 }, root: this.root });
  }

  private schedule(): void { if (this.poll != null) clearTimeout(this.poll); if (this.tasks.some(task => !task.terminal)) this.poll = window.setTimeout(() => void this.load(), pollMilliseconds); }
  private render(): void { this.renderStats(); this.renderList(); }
  private renderStats(): void {
    const values: Array<[string, number]> = [['Total', this.tasks.length], ['Pending', this.tasks.filter(t => t.status === 'pending').length], ['Running', this.tasks.filter(t => t.status === 'running').length], ['Finished', this.tasks.filter(t => t.status === 'finished').length], ['Needs attention', this.tasks.filter(t => ['failed', 'cancelled'].includes(t.status)).length]];
    this.stats.replaceChildren(...values.map(([label, value]) => { const item = document.createElement('div'); item.innerHTML = `<span>${label}</span><strong>${value}</strong>`; return item; }));
  }
  private renderList(): void {
    this.disposePreviews();
    const result = queryTasks(this.tasks, this.query); this.error.textContent = result.error || ''; this.count.textContent = `${result.tasks.length} of ${this.tasks.length} tasks`;
    const batchLabel = `Delete selected (${this.selected.size})`;
    this.batch.hidden = this.user.role !== 'admin' || this.selected.size === 0;
    this.batch.title = batchLabel;
    this.batch.setAttribute('aria-label', batchLabel);
    this.batch.querySelector('span')!.textContent = batchLabel;
    this.list.dataset.layout = this.query.layout; this.list.replaceChildren();
    if (!result.tasks.length) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = result.error ? 'Fix the search expression to continue.' : 'No tasks match the current filters.'; this.list.append(empty); return; }
    if (this.query.layout === 'table') this.renderTable(result.tasks); else result.tasks.forEach(task => this.list.append(this.taskCard(task)));
    createIcons({ icons: { Archive, Ban, Download, ExternalLink, Trash2 }, root: this.list });
  }
  private taskCard(task: TaskSummary): HTMLElement {
    const card = document.createElement('article'); card.className = 'task-card'; card.dataset.status = task.status;
    const header = document.createElement('header'); const identity = document.createElement('div'); identity.append(textNode('h2', task.display_name));
    const status = document.createElement('span'); status.className = `status status-${task.status.replace(':', '-')}`; status.textContent = task.outcome || task.status; header.append(identity, status);
    const facts = document.createElement('dl'); const factValues: Array<[string, string]> = [['Type', task.task_type], ['Task ID', task.task_id], ['Submitted', formatDate(task.submitted_at)], ['Finished', formatDate(task.finished_at)], ['Wall time', formatDuration(task.walltime_seconds)], ...(this.user.role === 'admin' ? [['Owner', task.owner || '-'] as [string, string]] : [])]; factValues.forEach(([label, value]) => { const row = document.createElement('div'); const dt = document.createElement('dt'); dt.textContent = label; const dd = document.createElement('dd'); dd.textContent = value; row.append(dt, dd); facts.append(row); });
    if (task.progress != null && !task.terminal) { const progress = document.createElement('p'); progress.className = 'task-progress'; progress.textContent = typeof task.progress === 'string' ? task.progress : JSON.stringify(task.progress); facts.append(progress); }
    const preview = this.inputPreview(task); const actions = this.taskActions(task);
    if (task.error) { const problem = document.createElement('details'); problem.className = 'task-error'; const summary = document.createElement('summary'); summary.textContent = 'Execution error'; const body = document.createElement('p'); body.textContent = task.error; problem.append(summary, body); card.append(header, facts, problem, preview, actions); } else card.append(header, facts, preview, actions);
    return card;
  }
  private inputPreview(task: TaskSummary): HTMLElement {
    const wrap = document.createElement('div'); if (!task.input_preview) return wrap;
    const details = document.createElement('details'); details.className = 'input-preview'; const summary = document.createElement('summary'); summary.textContent = 'Input preview'; const content = document.createElement('div'); content.className = 'input-preview-host'; content.textContent = 'Open to load the structure preview.'; details.append(summary, content);
    details.addEventListener('toggle', () => {
      if (!details.open) { this.previewViewers.get(task.task_id)?.dispose(); this.previewViewers.delete(task.task_id); details.dataset.loaded = ''; content.textContent = 'Open to load the structure preview.'; return; }
      if (details.dataset.loaded) return; details.dataset.loaded = 'true'; content.textContent = 'Loading structure...';
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
    if (task.result.available) { const open = document.createElement('a'); open.href = task.result.page_url; open.className = 'task-action primary-action'; open.innerHTML = '<i data-lucide="external-link"></i><span>Results</span>'; actions.append(open); if (task.result.download_url) { const download = document.createElement('a'); download.href = task.result.download_url; download.className = 'task-action'; download.innerHTML = '<i data-lucide="download"></i><span>Download</span>'; actions.append(download); } else if (task.result.archive_request_allowed && task.result.archive_request_url) actions.append(button('Prepare ZIP', 'archive', 'archive')); }
    if (task.actions.cancel.allowed) actions.append(button('Cancel', 'cancel', 'ban'));
    if (task.actions.delete.allowed) actions.append(button('Delete', 'delete', 'trash-2'));
    if (this.user.role === 'admin' && task.actions.delete.allowed) { const label = document.createElement('label'); label.className = 'task-select'; const input = document.createElement('input'); input.type = 'checkbox'; input.dataset.action = 'select'; input.checked = this.selected.has(task.task_id); const text = document.createElement('span'); text.textContent = 'Select'; label.append(input, text); actions.prepend(label); }
    return actions;
  }
  private renderTable(tasks: TaskSummary[]): void {
    const table = document.createElement('table'); table.className = 'task-table'; table.innerHTML = `<thead><tr><th>Name</th><th>Type</th>${this.user.role === 'admin' ? '<th>Owner</th>' : ''}<th>Submitted</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead>`; const body = document.createElement('tbody');
    tasks.forEach(task => { const row = document.createElement('tr'); const cells = [task.display_name, task.task_type, ...(this.user.role === 'admin' ? [task.owner || '-'] : []), formatDate(task.submitted_at), task.status]; cells.forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }); const actionCell = document.createElement('td'); actionCell.append(this.taskActions(task)); row.append(actionCell); body.append(row); }); table.append(body); this.list.append(table);
  }
  private async handleAction(event: Event): Promise<void> {
    const target = (event.target as Element).closest<HTMLElement>('[data-action]'); if (!target) return; const action = target.dataset.action;
    if (action === 'refresh') { await this.load(); return; }
    if (action === 'batch-delete') { if (!confirm(`Delete ${this.selected.size} selected tasks?`)) return; const taskIds = [...this.selected]; this.selected.clear(); await this.mutate(() => deleteTaskBatch(taskIds), 'Selected tasks deleted.'); return; }
    const footer = target.closest<HTMLElement>('[data-task-id]'); const task = this.tasks.find(item => item.task_id === footer?.dataset.taskId); if (!task) return;
    if (action === 'select') { (target as HTMLInputElement).checked ? this.selected.add(task.task_id) : this.selected.delete(task.task_id); this.renderList(); return; }
    if (action === 'cancel' && confirm(`Cancel ${task.display_name}?`)) await this.mutate(() => runTaskAction(task.actions.cancel, 'POST'), 'Task cancellation requested.');
    if (action === 'delete' && confirm(`Delete ${task.display_name} and its artifacts?`)) await this.mutate(() => runTaskAction(task.actions.delete, 'DELETE'), 'Task deleted.');
    if (action === 'archive' && task.result.archive_request_url) await this.mutate(() => prepareArchive(task.result.archive_request_url!), 'Result archive is being prepared.');
  }
  private async mutate(operation: () => Promise<unknown>, message: string): Promise<void> { try { await operation(); this.shell.notify(message, 'success'); await this.load(); } catch (error) { this.shell.notify((error as Error).message, 'error'); } }
  private disposePreviews(): void { this.previewViewers.forEach(viewer => viewer.dispose()); this.previewViewers.clear(); }
  private fail(error: unknown): void { if (error instanceof ApiError && error.status === 401) { location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return; } this.list.replaceChildren(); const state = document.createElement('p'); state.className = 'empty-state error-state'; state.textContent = (error as Error).message || 'Unable to load tasks.'; this.list.append(state); }
}

export async function mountDashboard(root: HTMLElement, shell: AppShell, user: CurrentUser): Promise<Dashboard> { const view = new Dashboard(root, shell, user); await view.load(); return view; }

function textNode<K extends keyof HTMLElementTagNameMap>(tag: K, value: string, className = ''): HTMLElementTagNameMap[K] { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; }
