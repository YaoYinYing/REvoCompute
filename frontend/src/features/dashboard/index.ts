import { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 } from 'lucide';
import { createIcons } from 'lucide';
import { deleteTaskBatch, getTasks, prepareArchive, runTaskAction, type CurrentUser, type TaskSummary } from '../../api/app-api';
import { ApiError } from '../../app/session';
import { confirmAction } from '../../app/dialogs';
import { t } from '../../app/i18n';
import { guidedTour, recordTourResult } from '../../app/guided-tour';
import type { AppShell } from '../../app/shell';
import { initialTaskQuery, queryTasks, type TaskQuery } from './task-query';
import './dashboard.css';

const pollMilliseconds = 12_000;
const dashboardIcons = { Archive, Ban, Download, ExternalLink, RefreshCw, Search, Trash2 };

// Machine facts keep a stable, locale-neutral format: dates and durations compare
// across cards and never depend on interface language.
function formatDate(value: string | null): string { return value ? new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value)) : '-'; }
function formatDuration(seconds: number | null): string { if (seconds == null) return '-'; const total = Math.round(seconds); const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = total % 60; return [hours && `${hours}h`, minutes && `${minutes}m`, `${rest}s`].filter(Boolean).join(' '); }
// One status vocabulary for the whole register: the Runner's reported outcome when
// it exists, otherwise the lifecycle enum. Both view modes read the same task, so
// both must name its state the same way.
function statusText(task: TaskSummary): string { return task.outcome || task.status; }
function button(label: string, action: string, icon: string): HTMLButtonElement { const node = document.createElement('button'); node.type = 'button'; node.className = 'task-action'; node.dataset.action = action; node.title = label; node.setAttribute('aria-label', label); node.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`; return node; }
function textNode<K extends keyof HTMLElementTagNameMap>(tag: K, value: string, className = ''): HTMLElementTagNameMap[K] { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; }

export class Dashboard {
  private tasks: TaskSummary[] = [];
  private readonly archiveRequests = new Map<string, number>();
  private query: TaskQuery = initialTaskQuery();
  private selected = new Set<string>();
  private previewViewers = new Map<string, { dispose(): void }>();
  private poll: number | null = null;
  private controller = new AbortController();
  private list!: HTMLElement; private stats!: HTMLElement; private count!: HTMLElement; private error!: HTMLElement; private batch!: HTMLButtonElement;
  private filterDisclosure!: HTMLDetailsElement; private filterSummary!: HTMLElement;
  private advancedToggle!: HTMLButtonElement; private advancedPanel!: HTMLElement;
  private selectAll!: HTMLInputElement; private selectAllLabel!: HTMLElement;
  private selectionBoxes = new Map<string, HTMLInputElement>();
  private page!: HTMLElement;

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
    // The Dashboard's own layout belongs on its own page root, not on the shared
    // outlet: the outlet is chrome the whole application shares.
    this.root.replaceChildren();
    const page = document.createElement('main'); page.className = 'dashboard-page'; this.root.append(page);
    this.page = page;
    const head = document.createElement('header'); head.className = 'page-heading';
    head.innerHTML = `<div><p class="page-kicker">${t('dashboard.register')}</p><h1>${t('dashboard.title')}<span class="heading-stop" aria-hidden="true">.</span></h1><p>${t('dashboard.intro')}</p></div>`;
    const actions = document.createElement('div'); actions.className = 'page-actions';
    const help = document.createElement("details"); help.className = "dashboard-help"; const helpSummary = textNode("summary", "Help"); help.append(helpSummary, guidedTour.launcher()); actions.append(help);
    const refresh = button(t('dashboard.action.refresh'), 'refresh', 'refresh-cw');
    const create = document.createElement('a'); create.href = '/compute/create_task'; create.className = 'primary-button'; create.textContent = t('dashboard.action.newTask');
    actions.append(refresh, create); head.append(actions);
    this.stats = document.createElement('section'); this.stats.className = 'dashboard-stats'; this.stats.setAttribute('aria-label', t('dashboard.stats.label'));

    // Filtering answers "which tasks?" and lives in one aligned tool band.
    const controls = document.createElement('section'); controls.className = 'work-toolbar'; controls.setAttribute('aria-label', t('dashboard.filters.label'));
    controls.innerHTML = `<div class="search-control"><label for="dashboard-search"><span>${t('dashboard.filter.search')}</span><span class="input-with-action"><i data-lucide="search" aria-hidden="true"></i><input type="search" id="dashboard-search" data-filter="search" placeholder="${t('dashboard.filter.searchPlaceholder')}" autocomplete="off"></span></label><small data-query-error role="status" aria-live="polite"></small></div>
      <label><span>${t('dashboard.filter.status')}</span><select data-filter="status"><option value="">${t('dashboard.filter.allStatuses')}</option><option value="pending">${t('dashboard.filter.status.pending')}</option><option value="running">${t('dashboard.filter.status.running')}</option><option value="finished">${t('dashboard.filter.status.finished')}</option><option value="failed">${t('dashboard.filter.status.failed')}</option><option value="cancelled">${t('dashboard.filter.status.cancelled')}</option><option value="attention">${t('dashboard.stats.attention')}</option></select></label>
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
    // A phone opens on the work, with secondary filters available in one disclosure.
    this.filterDisclosure = document.createElement('details'); this.filterDisclosure.className = 'dashboard-filters';
    this.filterSummary = textNode('summary', t('dashboard.filters.summary'));
    const filterFields = document.createElement('div'); filterFields.className = 'dashboard-filter-fields';
    filterFields.append(...Array.from(controls.children).slice(1));
    const method = filterFields.querySelector('[data-filter="taskType"]')!.closest('label')!; const order = filterFields.querySelector('[data-filter="sort"]')!.closest('label')!;
    controls.append(method, order);
    this.filterDisclosure.append(this.filterSummary, filterFields); controls.append(this.filterDisclosure);
    this.filterDisclosure.open = false;
    this.error = controls.querySelector('[data-query-error]')!;
    this.advancedToggle = controls.querySelector('[data-advanced]')!;
    this.advancedPanel = controls.querySelector('[data-advanced-panel]')!;

    // Presentation answers "how should I view this?" — visually separate.
    const viewToolbar = document.createElement('div'); viewToolbar.className = 'view-toolbar';
    this.count = textNode('p', '', 'list-count'); this.count.setAttribute('aria-live', 'polite');
    const layout = document.createElement('fieldset'); layout.className = 'layout-switch';
    layout.innerHTML = `<legend>${t('dashboard.view.label')}</legend><button type="button" data-layout="detailed" aria-pressed="true">${t('dashboard.view.detailed')}</button><button type="button" data-layout="compact" aria-pressed="false">${t('dashboard.view.compact')}</button><button type="button" data-layout="table" aria-pressed="false">${t('dashboard.view.table')}</button>`;
    this.batch = button(t('dashboard.card.deleteSelected'), 'batch-delete', 'trash-2');
    this.batch.hidden = true;
    viewToolbar.append(this.count, this.batch, layout);

    // Selection is a state of the register, independent of how the register is
    // presented. The select-all control lives in the view toolbar rather than in
    // the table's own header, so it survives a switch between the card layouts and
    // the table, and its checked state is derived from what is currently shown.
    this.selectAll = document.createElement('input');
    this.selectAll.type = 'checkbox'; this.selectAll.dataset.action = 'select-all';
    this.selectAll.setAttribute('aria-label', t('dashboard.select.all'));
    const selectAllLabel = document.createElement('label'); selectAllLabel.className = 'task-select-all';
    const selectAllText = document.createElement('span'); selectAllText.textContent = t('dashboard.card.select');
    selectAllLabel.append(this.selectAll, selectAllText);
    selectAllLabel.hidden = true;
    viewToolbar.prepend(selectAllLabel);
    this.selectAllLabel = selectAllLabel;
    this.selectAll.addEventListener('change', () => {
      const shown = queryTasks(this.tasks, this.query).tasks;
      if (this.selectAll.checked) shown.forEach(task => this.selected.add(task.task_id));
      else shown.forEach(task => this.selected.delete(task.task_id));
      this.syncSelectionState();
    });

    this.list = document.createElement('section'); this.list.className = 'task-list'; this.list.setAttribute('aria-live', 'polite');
    this.page.append(head, this.stats, controls, viewToolbar, this.list);
    controls.addEventListener('input', event => { const target = event.target as HTMLInputElement | HTMLSelectElement; const key = target.dataset.filter as keyof TaskQuery | undefined; if (key) { (this.query as unknown as Record<string, unknown>)[key] = target.value; this.renderList(); } });
    controls.querySelector('[data-toggle-regex]')?.addEventListener('click', event => { this.query.regex = !this.query.regex; const target = event.currentTarget as HTMLButtonElement; target.setAttribute('aria-pressed', String(this.query.regex)); target.classList.toggle('active', this.query.regex); this.renderList(); });
    this.advancedToggle.addEventListener('click', () => this.toggleAdvanced());
    controls.addEventListener('change', () => this.updateAdvancedState());
    viewToolbar.querySelectorAll<HTMLButtonElement>('[data-layout]').forEach(item => item.addEventListener('click', () => { this.query.layout = item.dataset.layout as TaskQuery['layout']; viewToolbar.querySelectorAll('[data-layout]').forEach(button => button.setAttribute('aria-pressed', String(button === item))); this.renderList(); }));
    this.page.addEventListener('click', event => void this.handleAction(event));
    createIcons({ icons: dashboardIcons, root: this.page });
    guidedTour.resumeIfActive();
    // The reader may leave this route at any moment. The narrow-behavior listener
    // fires on a media query, which outlives the node, so it is registered with the
    // route's own signal and the router's abort removes it. Nothing else here is
    // dereferenced after destroy(): a handler that fires is inert once the view's
    // nodes are gone.
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
    const keys = ['', 'pending', 'running', 'finished', 'attention'];
    this.stats.replaceChildren(...values.map(([label, value, attention], index) => { const item = document.createElement('button'); item.type = 'button'; item.dataset.status = keys[index]; if (attention) item.dataset.attention = ''; item.setAttribute('aria-pressed', String(this.query.status === keys[index])); item.append(textNode('span', label), textNode('strong', String(value))); item.addEventListener('click', () => { this.query.status = keys[index]!; this.page.querySelector<HTMLSelectElement>('[data-filter="status"]')!.value = this.query.status; this.renderList(); }); return item; }));
  }
  private renderList(): void {
    this.stats.querySelectorAll<HTMLElement>('[data-status]').forEach(node => node.setAttribute('aria-pressed', String(node.dataset.status === this.query.status)));
    this.disposePreviews();
    this.selectionBoxes.clear();
    const result = queryTasks(this.tasks, this.query); this.error.textContent = result.error || '';
    this.count.textContent = t('dashboard.list.count', { shown: result.tasks.length, total: this.tasks.length });
    const batchLabel = `${t('dashboard.card.deleteSelected')} (${this.selected.size})`;
    this.batch.hidden = this.user.role !== 'admin' || this.selected.size === 0;
    this.batch.title = batchLabel;
    this.batch.setAttribute('aria-label', batchLabel);
    this.batch.querySelector('span')!.textContent = batchLabel;
    this.syncSelectionState(result.tasks);
    this.updateAdvancedState();
    const active = Boolean(this.query.status || this.query.taskType || this.query.owner || this.query.submittedFrom || this.query.submittedTo || this.query.finishedFrom || this.query.finishedTo || this.query.regex || this.query.sort !== 'submitted');
    this.filterSummary.textContent = t(active ? 'dashboard.filters.active' : 'dashboard.filters.summary');
    this.list.dataset.layout = this.query.layout; this.list.replaceChildren();
    if (!result.tasks.length) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = result.error ? t('dashboard.list.fixExpression') : t('dashboard.list.empty'); this.list.append(empty); return; }
    if (this.query.layout === 'table') this.renderTable(result.tasks); else result.tasks.forEach(task => this.list.append(this.taskCard(task)));
    createIcons({ icons: dashboardIcons, root: this.list });
  }
  private taskCard(task: TaskSummary): HTMLElement {
    const card = document.createElement('article'); card.className = 'task-card'; card.dataset.status = task.status;
    const identity = document.createElement('div'); identity.className = 'task-identity';
    identity.append(textNode('h2', task.display_name), textNode('p', task.task_type, 'task-card-type'));
    const taskId = textNode('p', task.task_id, 'task-identity-id'); taskId.setAttribute('aria-label', `${t('dashboard.card.taskId')}: ${task.task_id}`); identity.append(taskId);
    if (this.user.role === 'admin' && task.actions.delete.allowed) identity.prepend(this.selectControl(task, ''));
    const state = document.createElement('div'); state.className = 'task-state';
    const status = textNode('span', statusText(task), `status status-${task.status.replace(':', '-')}`); state.append(status);
    if (task.progress != null && !task.terminal) state.append(textNode('p', typeof task.progress === 'string' ? task.progress : JSON.stringify(task.progress), 'task-progress'));
    const timing = document.createElement('div'); timing.className = 'task-time'; timing.append(textNode('p', formatDate(task.submitted_at)), textNode('p', formatDuration(task.walltime_seconds), 'task-runtime'));
    card.append(identity, state, timing);
    if (task.error) { const problem = document.createElement('details'); problem.className = 'task-error'; const summary = document.createElement('summary'); summary.textContent = t('dashboard.card.executionError'); const body = document.createElement('p'); body.textContent = task.error; problem.append(summary, body); card.append(problem); }
    const preview = this.inputPreview(task); if (preview) card.append(preview);
    card.append(this.taskActions(task));
    return card;
  }
  private inputPreview(task: TaskSummary): HTMLDetailsElement | null {
    if (!task.input_preview) return null;
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
      }).catch(error => { if (details.isConnected) content.textContent = t('dashboard.card.structureLoadFailed', { message: (error as Error).message }); });
    }); return details;
  }
  /** The selection control for one task: the card's identity start, or a cell. */
  private selectControl(task: TaskSummary, label: string): HTMLElement {
    const input = document.createElement('input');
    input.type = 'checkbox'; input.dataset.action = 'select'; input.checked = this.selected.has(task.task_id);
    input.setAttribute('aria-label', label || t('dashboard.select.task', { name: task.display_name }));
    // The box carries the task it selects: the card sets it at the task's identity
    // start, where no action row encloses it, so the control names its own subject.
    input.dataset.task = task.task_id;
    this.selectionBoxes.set(task.task_id, input);
    return input;
  }
  /**
   * Update the selection chrome in place after a selection changes.
   *
   * Selection is one state over the whole register, so toggling one box must not
   * rebuild the list: a rebuild would replace the checkbox the reader just moved,
   * drop focus, and make the batch action flicker. Only the boxes' own state, the
   * select-all control, and the batch action's count change here.
   */
  private syncSelectionState(tasks = queryTasks(this.tasks, this.query).tasks): void {
    const batchLabel = `${t('dashboard.card.deleteSelected')} (${this.selected.size})`;
    this.batch.hidden = this.user.role !== 'admin' || this.selected.size === 0;
    this.batch.title = batchLabel; this.batch.setAttribute('aria-label', batchLabel);
    this.batch.querySelector('span')!.textContent = batchLabel;
    this.selectAllLabel.hidden = this.user.role !== 'admin' || !tasks.length;
    this.selectAll.checked = this.user.role === 'admin' && tasks.length > 0 && tasks.every(task => this.selected.has(task.task_id));
    this.selectAll.indeterminate = this.user.role === 'admin' && !this.selectAll.checked && tasks.some(task => this.selected.has(task.task_id));
    this.selectionBoxes.forEach((input, taskId) => { input.checked = this.selected.has(taskId); });
  }
  private taskActions(task: TaskSummary): HTMLElement {
    const actions = document.createElement('footer'); actions.className = 'task-actions'; actions.dataset.taskId = task.task_id;
    if (task.result.available) { const open = document.createElement('a'); open.href = task.result.page_url; open.className = 'task-action primary-action'; open.innerHTML = `<i data-lucide="external-link" aria-hidden="true"></i><span>${t('dashboard.card.results')}</span>`; actions.append(open); if (task.result.download_url) { const download = document.createElement('a'); download.href = task.result.download_url; download.className = 'task-action'; download.innerHTML = `<i data-lucide="download" aria-hidden="true"></i><span>${t('dashboard.card.download')}</span>`; actions.append(download); } else if (task.result.archive_request_allowed && task.result.archive_request_url) {
      const started = this.archiveRequests.get(task.task_id);
      const building = started != null && Date.now() - started < 120_000;
      const archive = button(t(building ? 'results.archiveBuilding' : 'dashboard.card.prepareZip'), 'archive', 'archive');
      archive.disabled = building; actions.append(archive);
      if (started != null && !building) actions.append(textNode('span', t('results.archiveWaiting'), 'task-progress'));
    } }
    if (!task.result.available) {
      const progress = document.createElement('a'); progress.className = 'task-action primary-action';
      progress.href = task.result.page_url;
      progress.textContent = t(task.terminal ? 'dashboard.card.details' : 'dashboard.card.progress');
      actions.prepend(progress);
    }
    if (task.actions.cancel.allowed) actions.append(button(t('dashboard.card.cancel'), 'cancel', 'ban'));
    if (task.actions.delete.allowed) actions.append(button(t('dashboard.card.delete'), 'delete', 'trash-2'));
    const secondary = [...actions.children].filter(node => (node as HTMLElement).dataset.action === 'delete');
    const overflow = document.createElement('details'); overflow.className = 'task-overflow'; const summary = textNode('summary', '···'); summary.setAttribute('aria-label', `${t('dashboard.card.details')}: ${task.display_name}`);
    const menu = document.createElement('div'); menu.className = 'task-overflow-menu'; menu.append(...secondary);
    const facts = document.createElement('dl'); for (const [label, value] of [[t('dashboard.card.submitted'), formatDate(task.submitted_at)], [t('dashboard.card.finished'), formatDate(task.finished_at)], [t('dashboard.card.owner'), task.owner || '—']]) { facts.append(textNode('dt', label!), textNode('dd', value!)); } menu.append(facts); overflow.append(summary, menu); actions.append(overflow);
    return actions;
  }
  private renderTable(tasks: TaskSummary[]): void {
    const table = document.createElement('table'); table.className = 'task-table';
    // The first column is dedicated to selection; the last is dedicated to the
    // task's own independent actions. The two never mix: a selection box is a
    // state, an action is a verb, and the table keeps one column for each.
    const selectionHeading = this.user.role === 'admin' ? `<th><span class="sr-only">${t('dashboard.table.selection')}</span></th>` : '';
    table.innerHTML = `<thead><tr>${selectionHeading}<th>${t('dashboard.table.name')}</th><th>${t('dashboard.card.type')}</th>${this.user.role === 'admin' ? `<th>${t('dashboard.card.owner')}</th>` : ''}<th>${t('dashboard.card.submitted')}</th><th>${t('dashboard.filter.status')}</th><th><span class="sr-only">${t('dashboard.table.actions')}</span></th></tr></thead>`; const body = document.createElement('tbody');
    tasks.forEach(task => { const row = document.createElement('tr'); if (this.user.role === 'admin') { const cell = document.createElement('td'); cell.className = 'task-select-cell'; if (task.actions.delete.allowed) cell.append(this.selectControl(task, t('dashboard.select.task', { name: task.display_name }))); row.append(cell); } const cells = [task.display_name, task.task_type, ...(this.user.role === 'admin' ? [task.owner || '-'] : []), formatDate(task.submitted_at), statusText(task)]; cells.forEach((value, index) => { const cell = document.createElement('td'); cell.textContent = value; if (index === cells.length - 1) cell.className = 'state-cell'; row.append(cell); }); const actionCell = document.createElement('td'); actionCell.append(this.taskActions(task)); row.append(actionCell); body.append(row); }); table.append(body); this.list.append(table);
  }
  private async handleAction(event: Event): Promise<void> {
    const target = (event.target as Element).closest<HTMLElement>('[data-action]'); if (!target) return; const action = target.dataset.action;
    if (action === 'refresh') { await this.load(); return; }
    if (action === 'select-all') return; // handled by the control's own change listener
    // Every destructive operation asks first, through the application's own dialog
    // rather than the browser's confirm(): the confirmation states what is about to
    // be removed and never fires before the reader has answered it.
    if (action === 'batch-delete') {
      const count = this.selected.size;
      if (!await confirmAction({ title: t('dashboard.confirm.batchTitle', { count }), message: t('dashboard.confirm.batchDelete', { count }), confirmLabel: t('dashboard.card.deleteSelected') })) return;
      const taskIds = [...this.selected]; this.selected.clear(); await this.mutate(() => deleteTaskBatch(taskIds), t('dashboard.notice.deletedSelected')); return;
    }
    // The row carries the task, not only its action footer: selection lives in its
    // own leading cell, outside the footer, and still has to name its subject.
    const owner = target.closest<HTMLElement>('[data-task-id], [data-task]');
    const taskId = owner?.dataset.taskId ?? owner?.dataset.task;
    const task = this.tasks.find(item => item.task_id === taskId);
    if (!task) return;
    if (action === 'select') { (target as HTMLInputElement).checked ? this.selected.add(task.task_id) : this.selected.delete(task.task_id); this.syncSelectionState(); return; }
    if (action === 'cancel' && await confirmAction({ title: t('dashboard.confirm.cancelTitle', { name: task.display_name }), message: t('dashboard.confirm.cancel', { name: task.display_name }), confirmLabel: t('dashboard.card.cancel') })) await this.mutate(() => runTaskAction(task.actions.cancel, 'POST'), t('dashboard.notice.cancelled'));
    if (action === 'delete' && await confirmAction({ title: t('dashboard.confirm.deleteTitle', { name: task.display_name }), message: t('dashboard.confirm.delete', { name: task.display_name }), confirmLabel: t('dashboard.card.delete') })) await this.mutate(() => runTaskAction(task.actions.delete, 'DELETE'), t('dashboard.notice.deleted'));
    if (action === 'archive' && task.result.archive_request_url) {
      const started = this.archiveRequests.get(task.task_id);
      if (started != null && Date.now() - started < 120_000) return;
      this.archiveRequests.set(task.task_id, Date.now()); (target as HTMLButtonElement).disabled = true;
      try { await prepareArchive(task.result.archive_request_url); await this.load(); }
      catch (error) { this.archiveRequests.delete(task.task_id); this.shell.notify((error as Error).message, 'error'); await this.load(); }
    }
  }
  private async mutate(operation: () => Promise<unknown>, message: string): Promise<void> { try { await operation(); this.shell.notify(message, 'success'); await this.load(); } catch (error) { this.shell.notify((error as Error).message, 'error'); } }
  private disposePreviews(): void { this.previewViewers.forEach(viewer => viewer.dispose()); this.previewViewers.clear(); }
  private fail(error: unknown): void { if (error instanceof ApiError && error.status === 401) { location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return; } this.list.replaceChildren(); const state = document.createElement('p'); state.className = 'empty-state error-state'; state.textContent = (error as Error).message || t('dashboard.error.load'); this.list.append(state); }
}

/**
 * Build the register and hand it back before its data arrives.
 *
 * The view exists as soon as it is built, so a route whose load is superseded can
 * still dispose it: the caller owns the returned instance, and the first load is
 * a separate step it awaits. A register that returned only once loaded would be
 * unreachable — and so undisposable — for exactly the window in which a route
 * change can strand it.
 */
export function mountDashboard(root: HTMLElement, shell: AppShell, user: CurrentUser): Dashboard { return new Dashboard(root, shell, user); }
