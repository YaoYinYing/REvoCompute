import { getTaskCatalog, getTaskDefinition, preflightTask, requestAccess, submitTask } from './api';
import { InputWorkspace } from './input-workspace/InputWorkspace';
import { buildSubmissionFormData } from './submission';
import type { TaskCatalog, TaskFormDefinition, TaskPreflight, TaskSummary } from './types';

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
  private readonly validationSummary = node('p', 'ct-validation-summary', 'Choose a method');
  private readonly action = node('button', 'ct-primary', 'Review');
  private readonly clear = node('button', 'ct-secondary', 'Clear');
  private readonly workspace = new InputWorkspace(this.workspaceRoot, { onChange: () => this.refreshValidation(), onError: message => this.setStatus(message, 'error') });

  constructor(private readonly root: HTMLElement) {}

  async mount(): Promise<void> {
    this.renderShell();
    try {
      this.catalog = await getTaskCatalog(); this.renderCatalog();
      const requested = new URLSearchParams(window.location.search).get('task_type');
      if (requested && this.catalog.task_types.some(task => task.name === requested)) await this.selectTask(requested);
      else this.showChooser(requested ? 'That method is not available on this server.' : 'Choose a method to begin.');
    } catch (error) { this.showChooser(error instanceof Error ? error.message : 'Could not reach the server.'); }
  }

  private renderShell(): void {
    this.root.replaceChildren(); this.root.classList.add('create-task');
    const header = node('header', 'ct-page-header');
    const heading = node('div'); heading.append(node('h1', '', 'Create task'), node('p', '', 'Choose a method, prepare its inputs, then review and run.'));
    header.append(heading);
    this.chooser.append(node('h2', '', 'Choose a compute method'));
    this.workbench.hidden = true;
    this.action.type = 'button'; this.action.addEventListener('click', () => void this.runAction());
    this.clear.type = 'button'; this.clear.addEventListener('click', () => void this.clearWorkspace());
    this.root.append(header, this.chooser, this.workbench);
  }

  private renderCatalog(): void {
    if (!this.catalog) return;
    const controls = node('div', 'ct-catalog-controls');
    const search = node('input', 'ct-control'); search.type = 'search'; search.placeholder = 'Search methods'; search.setAttribute('aria-label', 'Search methods');
    const category = node('select', 'ct-control'); category.setAttribute('aria-label', 'Filter by category'); category.append(new Option('All categories', ''));
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
      count.textContent = shown ? `${shown} method${shown === 1 ? '' : 's'} available` : 'No methods match that search.';
    };
    search.addEventListener('input', render); category.addEventListener('change', render); controls.append(search, category); this.chooser.append(controls, count, groups); render();
  }

  private methodButton(task: TaskSummary): HTMLButtonElement {
    const button = node('button', 'ct-method'); button.type = 'button';
    button.append(node('strong', '', task.display_name), node('span', '', task.summary));
    if (task.access.restricted) button.append(node('small', `ct-access ${task.access.granted ? 'granted' : ''}`, task.access.granted ? 'Access granted' : task.access.request_status === 'pending' ? 'Access requested' : 'Restricted'));
    button.addEventListener('click', () => void this.selectTask(task.name)); return button;
  }

  private async selectTask(name: string): Promise<void> {
    this.loadController?.abort(); const controller = new AbortController(); this.loadController = controller; const generation = ++this.generation;
    this.chooser.hidden = true; this.workbench.hidden = false; this.workbench.replaceChildren(this.status); this.setStatus('Loading experiment protocol...', 'busy');
    const url = new URL(window.location.href); url.searchParams.set('task_type', name); history.replaceState(null, '', url);
    try {
      const definition = await getTaskDefinition(name, controller.signal); if (generation !== this.generation) return;
      this.definition = definition; this.preflight = null; this.renderWorkbench(); await this.workspace.mount(definition);
      if (generation !== this.generation) return;
      this.refreshValidation(); window.scrollTo({ top: 0, behavior: 'auto' });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      this.showChooser('Could not load the selected method. Check your connection and try again.');
    }
  }

  private renderWorkbench(): void {
    const form = this.definition!; this.workbench.replaceChildren();
    const header = node('header', 'ct-method-header');
    const title = node('div'); title.append(node('p', 'ct-category', this.categoryLabel(form.category)), node('h1', '', form.display_name), node('p', 'ct-method-summary', form.summary));
    const change = node('button', 'ct-secondary', 'Change method'); change.type = 'button'; change.addEventListener('click', () => this.showChooser('Choose another method.'));
    header.append(title, change);
    const facts = node('details', 'ct-method-context');
    const factsSummary = node('summary', '', 'Method context'); const factsList = node('dl', 'ct-method-facts');
    [['Use when', form.use_when], ['Input', form.input_summary], ['Output', form.output_summary], ['Compute', form.gpus ? 'GPU method' : 'CPU method']].forEach(([label, value]) => factsList.append(node('dt', '', label), node('dd', '', value)));
    facts.append(factsSummary, factsList);
    const access = this.renderAccess();
    const main = node('div', 'ct-workbench-grid');
    const protocol = node('div', 'ct-protocol'); protocol.append(this.workspaceRoot);
    const review = node('aside', 'ct-review');
    const identity = node('div', 'ct-snapshot-identity'); identity.append(node('p', 'ct-snapshot-method', form.display_name));
    const snapshot = node('dl', 'ct-snapshot');
    snapshot.append(node('dt', '', 'Compute'), node('dd', '', form.gpus ? 'GPU' : 'CPU'));
    snapshot.append(node('dt', '', 'Access'), node('dd', '', form.access.restricted ? (form.access.granted ? 'Granted' : 'Restricted') : 'Open'));
    const actions = node('div', 'ct-actions'); actions.append(this.clear, this.action);
    review.append(identity, snapshot, this.validationSummary, this.validation, this.status, actions);
    main.append(protocol, review); this.workbench.append(header, facts); if (access) this.workbench.append(access); this.workbench.append(main);
  }

  private renderAccess(): HTMLElement | null {
    const access = this.definition!.access; if (!access.restricted) return null;
    const panel = node('section', 'ct-access-panel');
    panel.append(node('h2', '', access.granted ? 'Access granted' : access.request_status === 'pending' ? 'Access requested' : 'Restricted access'), node('p', '', access.description || 'Approval is required before this method can run.'));
    if (!access.granted && access.request_status !== 'pending' && access.requestable && access.policy_id) {
      const button = node('button', 'ct-secondary', 'Request access'); button.type = 'button';
      button.addEventListener('click', () => void this.openAccessRequest(panel, button)); panel.append(button);
    }
    return panel;
  }

  private async openAccessRequest(panel: HTMLElement, button: HTMLButtonElement): Promise<void> {
    const dialog = node('dialog', 'ct-dialog'); const form = node('form'); form.method = 'dialog';
    const heading = node('h2', '', 'Request Runner access'); const label = node('label', 'ct-label', 'Research use and affiliation'); const reason = node('textarea', 'ct-sequence'); reason.required = true; reason.maxLength = 1000; label.htmlFor = 'ct-access-reason'; reason.id = 'ct-access-reason';
    const cancel = node('button', 'ct-secondary', 'Cancel'); cancel.type = 'button'; cancel.addEventListener('click', () => dialog.close('cancel'));
    const submit = node('button', 'ct-primary', 'Request access'); submit.type = 'submit'; submit.value = 'submit';
    const actions = node('div', 'ct-actions'); actions.append(cancel, submit); form.append(heading, node('p', '', 'The administrator verifies eligibility under this Runner\'s access policy.'), label, reason, actions); dialog.append(form); document.body.append(dialog); dialog.showModal();
    dialog.addEventListener('close', async () => {
      const value = reason.value.trim(); const accepted = dialog.returnValue === 'submit' && value; dialog.remove(); if (!accepted) return;
      button.disabled = true;
      try {
        await requestAccess(this.definition!.access.policy_id!, value); this.definition!.access.request_status = 'pending';
        panel.replaceChildren(node('h2', '', 'Access requested'), node('p', '', this.definition!.access.description || 'Your request is awaiting review.'));
        this.setStatus('Access requested. An administrator reviews it.', 'ok'); this.refreshValidation();
      } catch (error) { button.disabled = false; this.setStatus(`Access request failed: ${error instanceof Error ? error.message : String(error)}`, 'error'); }
    }, { once: true });
  }

  private refreshValidation(preservePreflight = false): string[] {
    if (!preservePreflight) this.preflight = null;
    if (!this.definition) return [];
    const errors = this.workspace.validate();
    const access = this.definition.access;
    if (access.restricted && !access.granted) errors.push(access.request_status === 'pending' ? 'Runner access approval is pending review.' : 'Runner access approval is required.');
    this.validation.replaceChildren();
    if (errors.length) {
      errors.forEach(message => this.validation.append(this.validationRow('error', message)));
    } else {
      if (!this.preflight) this.validation.append(this.validationRow('info', 'Run the review to complete the checks'));
      else {
        const failed = this.preflight.errors;
        if (failed.length) {
          this.validation.append(this.validationRow('error', `${failed.length} check${failed.length === 1 ? '' : 's'} failed`));
          failed.forEach(item => this.validation.append(this.validationRow('error', item.message)));
        } else this.validation.append(this.validationRow('ok', 'All checks passed'));
        const admission = this.preflight.admission;
        if (admission.runner_ready === false) this.validation.append(this.validationRow('error', 'Runner unavailable'));
        if (admission.infrastructure_status && !admission.infrastructure_ready) this.validation.append(this.validationRow('error', `Infrastructure ${admission.infrastructure_status.toLowerCase()}`));
        this.preflight.warnings.forEach(item => this.validation.append(this.validationRow('info', item.message)));
      }
    }
    const blocked = errors.length > 0 || Boolean(this.preflight && !this.preflight.valid);
    this.validationSummary.hidden = errors.length === 0;
    this.validationSummary.textContent = `${errors.length} issue${errors.length === 1 ? '' : 's'} to fix`;
    this.validationSummary.className = `ct-validation-summary ${blocked ? 'blocked' : 'ready'}`;
    this.action.disabled = errors.length > 0;
    this.action.textContent = this.preflight?.valid ? 'Run' : this.preflight ? 'Review again' : 'Review';
    return errors;
  }

  private validationRow(kind: 'ok' | 'error' | 'info', message: string): HTMLLIElement {
    const row = node('li', `ct-validation-row ${kind}`); row.append(node('span', 'ct-validation-marker'), document.createTextNode(message)); return row;
  }

  private async runAction(): Promise<void> {
    if (!this.definition) return;
    const errors = this.refreshValidation(true); if (errors.length) { this.setStatus('Fix the listed issues before review.', 'error'); return; }
    const data = buildSubmissionFormData(this.definition, this.workspace, this.workspace.collect()); this.setBusy(true);
    if (!this.preflight?.valid) {
      this.setStatus('Running security, contract, and admission checks...', 'busy');
      try {
        this.preflight = await preflightTask(this.definition.name, data); this.refreshValidation(true);
        this.setStatus(this.preflight.valid ? 'Checks passed. Review them, then run.' : 'Checks failed. Review them before retrying.', this.preflight.valid ? 'ok' : 'error');
      } catch (error) { this.preflight = null; this.setStatus(`Review failed: ${error instanceof Error ? error.message : String(error)}`, 'error'); }
      finally { this.setBusy(false); this.refreshValidation(true); }
      return;
    }
    this.setStatus('Queueing the task...', 'busy');
    try {
      await submitTask(data); this.setStatus('Task queued. Opening the dashboard...', 'ok'); window.location.assign('/compute/dashboard');
    } catch (error) { this.setStatus(`Submission failed: ${error instanceof Error ? error.message : String(error)}`, 'error'); this.preflight = null; this.setBusy(false); this.refreshValidation(); }
  }

  private async clearWorkspace(): Promise<void> {
    if (!this.definition) return; this.preflight = null; await this.workspace.mount(this.definition); this.setStatus('Workspace cleared.', 'ok'); this.refreshValidation();
  }

  private setBusy(value: boolean): void { this.action.disabled = value; this.clear.disabled = value; this.action.setAttribute('aria-busy', String(value)); }
  private setStatus(message: string, kind: 'busy' | 'ok' | 'error' | '' = ''): void { this.status.textContent = message; this.status.className = `ct-status ${kind}`; }
  private categoryLabel(name: string): string { return this.catalog?.categories.find(category => category.name === name)?.label || name; }

  private showChooser(message: string): void {
    this.loadController?.abort(); this.generation++; this.definition = null; this.preflight = null; this.workspace.destroy();
    this.chooser.hidden = false; this.workbench.hidden = true;
    const status = this.chooser.querySelector('.ct-catalog-status'); if (status) status.textContent = message;
    const url = new URL(window.location.href); url.searchParams.delete('task_type'); history.replaceState(null, '', url);
    this.chooser.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
  }

  destroy(): void { this.loadController?.abort(); this.workspace.destroy(); this.root.replaceChildren(); }
}
