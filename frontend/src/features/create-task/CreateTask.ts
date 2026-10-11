import { getTaskCatalog, getTaskDefinition, preflightTask, requestAccess, submitTask } from './api';
import { InputWorkspace } from './input-workspace/InputWorkspace';
import { buildSubmissionFormData } from './submission';
import type { TaskCatalog, TaskFormDefinition, TaskPreflight, TaskSummary } from './types';
import { t } from '../../app/i18n';

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string): HTMLElementTagNameMap[K] {
  const value = document.createElement(tag); value.className = className; if (text != null) value.textContent = text; return value;
}

export class CreateTask {
  private catalog: TaskCatalog | null = null;
  private definition: TaskFormDefinition | null = null;
  private preflight: TaskPreflight | null = null;
  private loadController: AbortController | null = null;
  private generation = 0;
  private readonly chooser = node('section', 'ct-chooser');
  private readonly workbench = node('section', 'ct-workbench');
  private readonly workspaceRoot = node('div', 'ct-workspace');
  private readonly status = node('p', 'ct-status');
  private readonly validation = node('ul', 'ct-validation');
  private readonly validationSummary = node('p', 'ct-validation-summary', t('ct.chooseMethod'));
  private readonly snapshot = node('dl', 'ct-snapshot');
  private readonly action = node('button', 'ct-primary', t('ct.run'));
  private readonly clear = node('button', 'ct-secondary', t('ct.clear'));
  private readonly workspace = new InputWorkspace(this.workspaceRoot, { onChange: () => { this.revision++; this.refreshValidation(); }, onError: message => this.setStatus(message, 'error') });
  private busy = false;
  private checking = false;
  private change: HTMLButtonElement | null = null;
  private revision = 0;

  constructor(private readonly root: HTMLElement) {}

  async mount(): Promise<void> {
    this.renderShell();
    try {
      this.catalog = await getTaskCatalog(); this.renderCatalog();
      const requested = new URLSearchParams(window.location.search).get('task_type');
      if (requested && this.catalog.task_types.some(task => task.name === requested)) await this.selectTask(requested);
      else this.showChooser(requested ? t('ct.unavailable') : t('ct.choosePrompt'));
    } catch (error) { this.showChooser(error instanceof Error ? error.message : t('ct.offline')); }
  }

  private renderShell(): void {
    this.root.replaceChildren(); this.root.classList.add('create-task');
    const header = node('header', 'ct-page-header');
    const heading = node('div'); heading.append(node('h1', '', t('ct.title')), node('p', '', t('ct.subtitle')));
    header.append(heading);
    this.chooser.append(node('h2', '', t('ct.chooseMethod')));
    this.workbench.hidden = true;
    this.action.type = 'button'; this.action.addEventListener('click', () => void this.runAction());
    this.clear.type = 'button'; this.clear.addEventListener('click', () => void this.clearWorkspace());
    this.root.append(header, this.chooser, this.workbench);
  }

  private renderCatalog(): void {
    if (!this.catalog) return;
    const controls = node('div', 'ct-catalog-controls');
    const search = node('input', 'ct-control'); search.type = 'search'; search.placeholder = t('catalog.searchMethods'); search.setAttribute('aria-label', t('catalog.searchMethods'));
    const category = node('select', 'ct-control'); category.setAttribute('aria-label', t('ct.filterCategory')); category.append(new Option(t('catalog.allCategories'), ''));
    this.catalog.categories.forEach(item => category.append(new Option(item.label, item.name)));
    const count = node('p', 'ct-catalog-status'); const groups = node('div', 'ct-method-groups');
    const render = () => {
      const query = search.value.trim().toLowerCase(); groups.replaceChildren(); let shown = 0;
      this.catalog!.categories.forEach(item => {
        const tasks = this.catalog!.task_types.filter(task => task.category === item.name && (!category.value || category.value === item.name) && (!query || [task.name, task.display_name, task.summary, task.category].join(' ').toLowerCase().includes(query)));
        if (!tasks.length) return;
        const section = node('section', 'ct-method-group'); section.append(node('h3', '', item.label));
        const grid = node('div', 'ct-method-grid'); tasks.forEach(task => { grid.append(this.methodButton(task)); shown++; }); section.append(grid); groups.append(section);
      });
      count.textContent = shown ? t(shown === 1 ? 'ct.availableOne' : 'ct.availableMany', { count: shown }) : t('ct.noMatch');
    };
    search.addEventListener('input', render); category.addEventListener('change', render); controls.append(search, category); this.chooser.append(controls, count, groups); render();
  }

  private methodButton(task: TaskSummary): HTMLButtonElement {
    const button = node('button', 'ct-method'); button.type = 'button';
    button.append(node('strong', '', task.display_name), node('span', '', task.summary));
    if (task.access.restricted) button.append(node('small', `ct-access ${task.access.granted ? 'granted' : ''}`, task.access.granted ? t('ct.access.granted') : task.access.request_status === 'pending' ? t('ct.access.requested') : t('ct.access.restricted')));
    button.addEventListener('click', () => void this.selectTask(task.name)); return button;
  }

  private async selectTask(name: string): Promise<void> {
    this.loadController?.abort(); const controller = new AbortController(); this.loadController = controller; const generation = ++this.generation;
    this.chooser.hidden = true; this.workbench.hidden = false; this.workbench.replaceChildren(this.status); this.setStatus(t('ct.loading'), 'busy');
    const url = new URL(window.location.href); url.searchParams.set('task_type', name); history.replaceState(null, '', url);
    try {
      const definition = await getTaskDefinition(name, controller.signal); if (generation !== this.generation) return;
      this.definition = definition; this.preflight = null; this.renderWorkbench(); this.setBusy(false); this.revision++; await this.workspace.mount(definition);
      if (generation !== this.generation) return;
      if (this.status.classList.contains('busy')) this.setStatus('');
      this.refreshValidation(); window.scrollTo({ top: 0, behavior: 'auto' });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      this.showChooser(t('ct.loadFailed'));
    }
  }

  private renderWorkbench(): void {
    const form = this.definition!; this.workbench.replaceChildren();
    const header = node('header', 'ct-method-header');
    const title = node('div'); title.append(node('p', 'ct-category', this.categoryLabel(form.category)), node('h1', '', form.display_name), node('p', 'ct-method-summary', form.summary));
    const change = node('button', 'ct-secondary', t('ct.changeMethod')); change.type = 'button'; change.addEventListener('click', () => this.showChooser(t('ct.chooseAnother'))); this.change = change;
    header.append(title, change);
    const facts = node('details', 'ct-method-context');
    const factsSummary = node('summary', '', t('ct.methodContext')); const factsList = node('dl', 'ct-method-facts');
    const factRows: Array<[string, string]> = [
      [t('ct.useWhen'), form.use_when], [t('ct.input'), form.input_summary],
      [t('ct.output'), form.output_summary], [t('ct.compute'), form.gpus ? t('ct.gpuMethod') : t('ct.cpuMethod')],
    ];
    factRows.forEach(([label, value]) => factsList.append(node('dt', '', label), node('dd', '', value)));
    facts.append(factsSummary, factsList);
    const access = this.renderAccess();
    const main = node('div', 'ct-workbench-grid');
    const protocol = node('div', 'ct-protocol'); protocol.append(this.workspaceRoot);
    const snapshotPanel = node('aside', 'ct-snapshot-panel');
    snapshotPanel.append(node('p', 'ct-snapshot-label', t('ct.snapshot')));
    const identity = node('div', 'ct-snapshot-identity'); identity.append(node('p', 'ct-snapshot-method', form.display_name));
    const actions = node('div', 'ct-actions'); actions.append(this.clear, this.action);
    snapshotPanel.append(identity, this.snapshot, this.validationSummary, this.validation, this.status, actions);
    main.append(protocol, snapshotPanel); this.workbench.append(header, facts); if (access) this.workbench.append(access); this.workbench.append(main);
  }

  private renderAccess(): HTMLElement | null {
    const access = this.definition!.access; if (!access.restricted) return null;
    const panel = node('section', 'ct-access-panel');
    panel.append(node('h2', '', access.granted ? t('ct.access.granted') : access.request_status === 'pending' ? t('ct.access.requested') : t('ct.access.panelRestricted')), node('p', '', access.description || t('ct.access.approvalRequired')));
    if (!access.granted && access.request_status !== 'pending' && access.requestable && access.policy_id) {
      const button = node('button', 'ct-secondary', t('ct.access.request')); button.type = 'button';
      button.addEventListener('click', () => void this.openAccessRequest(panel, button)); panel.append(button);
    }
    return panel;
  }

  private async openAccessRequest(panel: HTMLElement, button: HTMLButtonElement): Promise<void> {
    const dialog = node('dialog', 'ct-dialog'); const form = node('form'); form.method = 'dialog';
    const heading = node('h2', '', t('ct.access.heading')); const label = node('label', 'ct-label', t('ct.access.reasonLabel')); const reason = node('textarea', 'ct-sequence'); reason.required = true; reason.maxLength = 1000; label.htmlFor = 'ct-access-reason'; reason.id = 'ct-access-reason';
    const cancel = node('button', 'ct-secondary', t('ct.cancel')); cancel.type = 'button'; cancel.addEventListener('click', () => dialog.close('cancel'));
    const submit = node('button', 'ct-primary', t('ct.access.request')); submit.type = 'submit'; submit.value = 'submit';
    const actions = node('div', 'ct-actions'); actions.append(cancel, submit); form.append(heading, node('p', '', t('ct.access.policyNote')), label, reason, actions); dialog.append(form); document.body.append(dialog); dialog.showModal();
    dialog.addEventListener('close', async () => {
      const value = reason.value.trim(); const accepted = dialog.returnValue === 'submit' && value; dialog.remove(); if (!accepted) return;
      button.disabled = true;
      try {
        await requestAccess(this.definition!.access.policy_id!, value); this.definition!.access.request_status = 'pending';
        panel.replaceChildren(node('h2', '', t('ct.access.requested')), node('p', '', this.definition!.access.description || t('ct.access.awaitingReview')));
        this.setStatus(t('ct.access.requestedNotice'), 'ok'); this.refreshValidation();
      } catch (error) { button.disabled = false; this.setStatus(t('ct.access.requestFailed', { message: error instanceof Error ? error.message : String(error) }), 'error'); }
    }, { once: true });
  }

  private refreshValidation(preservePreflight = false): string[] {
    if (!preservePreflight) this.preflight = null;
    if (!this.definition) return [];
    const errors = this.workspace.validate();
    const access = this.definition.access;
    if (access.restricted && !access.granted) errors.push(access.request_status === 'pending' ? t('ct.access.pending') : t('ct.access.required'));
    const preflight = this.preflight;
    this.validation.replaceChildren();
    if (errors.length) {
      errors.forEach(message => this.validation.append(this.validationRow('error', message)));
    } else if (preflight) {
      const failed = preflight.errors;
      if (failed.length) failed.forEach(item => this.validation.append(this.validationRow('error', item.message)));
      else if (this.checking) this.validation.append(this.validationRow('info', t('ct.checking')));
      else this.validation.append(this.validationRow('ok', t('ct.checksPassed')));
      const admission = preflight.admission;
      if (admission.runner_ready === false) this.validation.append(this.validationRow('error', t('ct.runnerUnavailable')));
      if (admission.infrastructure_status && !admission.infrastructure_ready) this.validation.append(this.validationRow('error', t('ct.infrastructure', { status: admission.infrastructure_status.toLowerCase() })));
      preflight.warnings.forEach(item => this.validation.append(this.validationRow('info', item.message)));
    } else this.validation.append(this.validationRow('info', t('ct.ready')));
    const counts = errors.length ? errors.length : preflight && !preflight.valid ? Math.max(preflight.errors.length, 1) : 0;
    this.validationSummary.hidden = counts === 0;
    this.validationSummary.textContent = t(counts === 1 ? 'ct.issueOne' : 'ct.issueMany', { count: counts });
    this.validationSummary.className = `ct-validation-summary ${counts ? 'blocked' : 'ready'}`;
    this.action.disabled = this.busy || errors.length > 0;
    this.refreshSnapshot();
    return errors;
  }

  private refreshSnapshot(): void {
    const definition = this.definition; if (!definition) return;
    this.snapshot.replaceChildren();
    const summaries = this.workspace.summaries();
    const rows: Array<[string, string]> = [
      [t('ct.snapshot.compute'), definition.gpus ? 'GPU' : 'CPU'],
      [t('ct.snapshot.access'), definition.access.restricted ? (definition.access.granted ? t('ct.snapshot.granted') : t('ct.snapshot.restricted')) : t('ct.snapshot.open')],
      ...summaries.map(item => [item.label, item.value] as [string, string]),
    ];
    rows.forEach(([label, value]) => this.snapshot.append(node('dt', '', label), node('dd', '', value)));
  }

  private validationRow(kind: 'ok' | 'error' | 'info', message: string): HTMLLIElement {
    const row = node('li', `ct-validation-row ${kind}`); row.append(node('span', 'ct-validation-marker'), document.createTextNode(message)); return row;
  }

  private async runAction(): Promise<void> {
    if (!this.definition || this.busy) return;
    const errors = this.refreshValidation(); if (errors.length) { this.setStatus(t('ct.fixIssues'), 'error'); return; }
    const generation = this.generation; const revision = this.revision;
    const data = buildSubmissionFormData(this.definition, this.workspace, this.workspace.collect());
    this.setBusy(true); this.setStatus(t('ct.checkingTask'), 'busy');
    this.checking = true; this.refreshValidation(true);
    let preflight: TaskPreflight;
    try {
      preflight = await preflightTask(this.definition.name, data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.checking = false; this.preflight = null; this.setStatus(t('ct.checksFailed', { message: error instanceof Error ? error.message : String(error) }), 'error'); this.setBusy(false); this.refreshValidation(); return;
    }
    if (generation !== this.generation) return;
    this.checking = false;
    if (revision !== this.revision) {
      this.preflight = null; this.setBusy(false); this.setStatus(t('ct.inputsChanged'), 'error'); this.refreshValidation(); return;
    }
    this.preflight = preflight; this.refreshValidation(true);
    if (!preflight.valid) { this.setStatus(t('ct.checksFailedFix'), 'error'); this.setBusy(false); this.refreshValidation(true); return; }
    this.setStatus(t('ct.queueing'), 'busy');
    try {
      const task = await submitTask(data);
      this.setStatus(t('ct.queued', { id: task.task_id }), 'ok'); window.location.assign('/compute/dashboard');
    } catch (error) { if (generation !== this.generation) return; this.setStatus(t('ct.submissionFailed', { message: error instanceof Error ? error.message : String(error) }), 'error'); this.preflight = null; this.setBusy(false); this.refreshValidation(); }
  }

  private async clearWorkspace(): Promise<void> {
    if (!this.definition) return; const generation = this.generation; this.preflight = null; this.revision++; await this.workspace.mount(this.definition);
    if (generation !== this.generation) return; this.setStatus(t('ct.cleared'), 'ok'); this.refreshValidation();
  }

  private setBusy(value: boolean): void { this.busy = value; this.action.disabled = value; this.clear.disabled = value; if (this.change) this.change.disabled = value; this.action.setAttribute('aria-busy', String(value)); }
  private setStatus(message: string, kind: 'busy' | 'ok' | 'error' | '' = ''): void { this.status.textContent = message; this.status.className = `ct-status ${kind}`; }
  private categoryLabel(name: string): string { return this.catalog?.categories.find(category => category.name === name)?.label || name; }

  private showChooser(message: string): void {
    this.loadController?.abort(); this.generation++; this.definition = null; this.preflight = null; this.setBusy(false); this.checking = false; this.workspace.destroy();
    this.chooser.hidden = false; this.workbench.hidden = true;
    const status = this.chooser.querySelector('.ct-catalog-status'); if (status) status.textContent = message;
    const url = new URL(window.location.href); url.searchParams.delete('task_type'); history.replaceState(null, '', url);
    this.chooser.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
  }

  destroy(): void { this.loadController?.abort(); this.workspace.destroy(); this.root.replaceChildren(); }
}
