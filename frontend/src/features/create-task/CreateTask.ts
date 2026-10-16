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
  private readonly catalogControls = node('div', 'ct-catalog-controls');
  private readonly catalogGroups = node('div', 'ct-method-groups');
  private readonly catalogStatus = node('p', 'ct-catalog-status');
  private readonly workbench = node('section', 'ct-workbench');
  private readonly pageHeader = node('header', 'ct-page-header');
  private readonly workspaceRoot = node('div', 'ct-workspace');
  private readonly status = node('p', 'ct-status');
  private readonly validation = node('ul', 'ct-validation');
  private readonly validationSummary = node('p', 'ct-validation-summary', t('ct.chooseMethod'));
  private readonly feedback = node('div', 'ct-feedback');
  private readonly snapshot = node('dl', 'ct-snapshot');
  private readonly action = node('button', 'ct-primary', t('ct.run'));
  private readonly clear = node('button', 'ct-secondary', t('ct.clear'));
  private readonly workspace = new InputWorkspace(this.workspaceRoot, { onChange: () => { this.revision++; this.refreshValidation(); }, onError: message => this.setStatus(message, 'error') });
  private busy = false;
  private checking = false;
  // The last action failed. A failed preflight or submission leaves no preflight
  // and no field error behind, so without this the panel would fall through to
  // the success-flavoured ready row while the status line reports the failure.
  private actionFailed = false;
  private change: HTMLButtonElement | null = null;
  private revision = 0;

  constructor(private readonly root: HTMLElement) {
    // The preparation surface owns exactly one visible level-1 heading per state:
    // the chooser shows the persistent page title, and the workbench replaces it
    // with the method's own display name. One feedback region carries the
    // chooser's match count, the workbench validation summary, and the action
    // status; it is reparented into whichever state is on screen, so it is in the
    // document for the whole life of the view. Its accessible name is wired per
    // state, because the snapshot label it was named from exists only in the
    // workbench: naming a live region from a node the state does not hold leaves
    // the region unnamed exactly where its name was relied on.
    this.feedback.setAttribute('role', 'status');
    this.feedback.setAttribute('aria-live', 'polite');
  }

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
    const heading = node('div'); heading.append(node('h1', '', t('ct.title')), node('p', '', t('ct.subtitle')));
    this.pageHeader.replaceChildren(heading);
    this.workbench.hidden = true;
    this.feedback.append(this.validationSummary, this.validation, this.status);
    this.validationSummary.hidden = true;
    this.action.type = 'button'; this.action.addEventListener('click', () => void this.runAction());
    this.clear.type = 'button'; this.clear.addEventListener('click', () => void this.clearWorkspace());
    this.root.append(this.pageHeader, this.chooser, this.workbench);
    // The region is in the document from mount, before the catalog resolves, so a
    // status set while the catalog is still loading is announced rather than
    // inserted into a region no assistive technology had been told about.
    this.renderChooserChrome();
  }

  private renderCatalog(): void {
    if (!this.catalog) return;
    // The chooser's heading, match count, and groups are the same nodes in every
    // chooser state, so a mid-flow reparent reattaches them rather than rebuilding
    // them: a catalog that failed to load never destroys the panel a method-less
    // chooser (the offline fallback) still shows.
    const search = node('input', 'ct-control'); search.type = 'search'; search.placeholder = t('catalog.searchMethods'); search.setAttribute('aria-label', t('catalog.searchMethods'));
    const category = node('select', 'ct-control'); category.setAttribute('aria-label', t('ct.filterCategory')); category.append(new Option(t('catalog.allCategories'), ''));
    this.catalog.categories.forEach(item => category.append(new Option(item.label, item.name)));
    const render = () => {
      const query = search.value.trim().toLowerCase(); this.catalogGroups.replaceChildren(); let shown = 0;
      this.catalog!.categories.forEach(item => {
        const tasks = this.catalog!.task_types.filter(task => task.category === item.name && (!category.value || category.value === item.name) && (!query || [task.name, task.display_name, task.summary, task.category].join(' ').toLowerCase().includes(query)));
        if (!tasks.length) return;
        const section = node('section', 'ct-method-group'); section.append(node('h3', '', item.label));
        const grid = node('div', 'ct-method-grid'); tasks.forEach(task => { grid.append(this.methodButton(task)); shown++; }); section.append(grid); this.catalogGroups.append(section);
      });
      this.catalogStatus.textContent = shown ? t(shown === 1 ? 'ct.availableOne' : 'ct.availableMany', { count: shown }) : t('ct.noMatch');
    };
    search.addEventListener('input', render); category.addEventListener('change', render);
    this.catalogControls.replaceChildren(search, category);
    this.catalogGroups.replaceChildren();
    this.renderChooserChrome();
    render();
  }

  // One home for the chooser's heading, catalog controls, announced region, and
  // method groups. The initial render and a mid-flow return both reparent the
  // same nodes, so neither state duplicates the panel or loses it, including the
  // offline fallback where the catalog never rendered.
  private renderChooserChrome(): void {
    const heading = this.chooser.querySelector('h2') || node('h2', '', t('ct.chooseMethod'));
    heading.id = 'ct-chooser-heading';
    // The region sits with the match count above the methods it describes, so a
    // change to the chooser's status is inside the live region in this state too.
    this.feedback.append(this.catalogStatus);
    this.feedback.setAttribute('aria-labelledby', heading.id);
    this.chooser.append(heading, this.catalogControls, this.feedback, this.catalogGroups);
  }

  private methodButton(task: TaskSummary): HTMLButtonElement {
    const button = node('button', 'ct-method'); button.type = 'button';
    button.append(node('strong', '', task.display_name), node('span', '', task.summary));
    if (task.access.restricted) button.append(node('small', `ct-access ${task.access.granted ? 'granted' : ''}`, task.access.granted ? t('ct.access.granted') : task.access.request_status === 'pending' ? t('ct.access.requested') : t('ct.access.restricted')));
    button.addEventListener('click', () => void this.selectTask(task.name)); return button;
  }

  private async selectTask(name: string): Promise<void> {
    this.loadController?.abort(); const controller = new AbortController(); this.loadController = controller; const generation = ++this.generation;
    // The workbench swaps in for the chooser: the loading status that lived in the
    // chooser's now-hidden region has to be on screen, and the region must travel
    // with it or the loading message would be announced from a hidden panel. The
    // chooser's match count leaves the region with the chooser it counted.
    this.chooser.hidden = true; this.pageHeader.hidden = true; this.workbench.hidden = false;
    this.catalogStatus.remove(); this.workbench.replaceChildren(this.feedback); this.setStatus(t('ct.loading'), 'busy');
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
    this.pageHeader.hidden = true;
    const header = node('header', 'ct-method-header');
    const title = node('div'); title.append(node('p', 'ct-category', `${t('ct.title')} / ${this.categoryLabel(form.category)}`), node('h1', '', form.display_name), node('p', 'ct-method-summary', form.summary));
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
    const snapshotPanel = node('footer', 'ct-snapshot-panel');
    const label = node('p', 'sr-only', t('ct.snapshot')); label.id = 'ct-snapshot-label';
    this.feedback.setAttribute('aria-labelledby', label.id);
    const review = node('details', 'ct-snapshot-details'); review.append(node('summary', '', t('ct.snapshot')), this.snapshot);
    const actions = node('div', 'ct-actions'); actions.append(this.clear, this.action);
    snapshotPanel.append(label, this.feedback, actions, review);
    main.append(protocol, snapshotPanel); this.workbench.append(header, facts); if (access) this.workbench.append(access); this.workbench.append(main);
  }

  private renderAccess(): HTMLElement | null {
    const access = this.definition!.access; if (!access.restricted) return null;
    const panel = node('section', 'ct-access-panel');
    panel.append(node('h2', '', access.granted ? t('ct.access.granted') : access.request_status === 'pending' ? t('ct.access.requested') : t('ct.access.panelRestricted')), node('p', '', access.description || t('ct.access.approvalRequired')));
    if (!access.granted && access.request_status !== 'pending' && access.requestable && access.policy_id) {
      // A declined request is answered state, not a fresh one: the reader is told
      // the previous request was declined before being offered the control again.
      if (access.request_status === 'rejected') panel.append(node('p', 'ct-access-declined', t('ct.access.declined')));
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
    let blockers = 0;
    const blocker = (message: string): void => { this.validation.append(this.validationRow('error', message)); blockers += 1; };
    if (errors.length) {
      errors.forEach(message => blocker(message));
    } else if (preflight) {
      const failed = preflight.errors;
      // The server already names an admission refusal in a blocking finding, so
      // the client's own row for the same condition would state one blocker
      // twice. The match is on the stable finding code, never on its prose.
      const codes = new Set(failed.filter(item => item.blocking).map(item => item.code));
      if (failed.length) failed.forEach(item => blocker(item.message));
      else if (this.checking) this.validation.append(this.validationRow('info', t('ct.checking')));
      else this.validation.append(this.validationRow('ok', t('ct.checksPassed')));
      const admission = preflight.admission;
      if (admission.runner_ready === false && !codes.has('admission_unavailable')) blocker(t('ct.runnerUnavailable'));
      if (admission.infrastructure_status && !admission.infrastructure_ready && !codes.has('infrastructure_unavailable')) blocker(t('ct.infrastructure', { status: admission.infrastructure_status.toLowerCase() }));
      preflight.warnings.forEach(item => this.validation.append(this.validationRow('info', item.message)));
    } else if (!this.actionFailed) this.validation.append(this.validationRow('info', t('ct.ready')));
    const counts = blockers;
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
    this.actionFailed = false;
    this.setBusy(true); this.setStatus(t('ct.checkingTask'), 'busy');
    this.checking = true; this.refreshValidation(true);
    let preflight: TaskPreflight;
    try {
      preflight = await preflightTask(this.definition.name, data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.checking = false; this.preflight = null; this.actionFailed = true; this.setStatus(t('ct.checksFailed', { message: error instanceof Error ? error.message : String(error) }), 'error'); this.setBusy(false); this.refreshValidation(); return;
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
      this.actionFailed = false; this.setStatus(t('ct.queued', { id: task.task_id }), 'ok'); window.location.assign('/compute/dashboard');
    } catch (error) { if (generation !== this.generation) return; this.actionFailed = true; this.setStatus(t('ct.submissionFailed', { message: error instanceof Error ? error.message : String(error) }), 'error'); this.preflight = null; this.setBusy(false); this.refreshValidation(); }
  }

  private async clearWorkspace(): Promise<void> {
    if (!this.definition) return; const generation = this.generation; this.preflight = null; this.actionFailed = false; this.revision++; await this.workspace.mount(this.definition);
    if (generation !== this.generation) return; this.setStatus(t('ct.cleared'), 'ok'); this.refreshValidation();
  }

  private setBusy(value: boolean): void { this.busy = value; this.action.disabled = value; this.clear.disabled = value; if (this.change) this.change.disabled = value; this.action.setAttribute('aria-busy', String(value)); }
  private setStatus(message: string, kind: 'busy' | 'ok' | 'error' | '' = ''): void {
    this.status.textContent = message; this.status.className = `ct-status ${kind}`;
    // An error is announced assertively; the region itself is the polite default.
    if (kind === 'error') this.status.setAttribute('role', 'alert'); else this.status.removeAttribute('role');
  }
  private categoryLabel(name: string): string { return this.catalog?.categories.find(category => category.name === name)?.label || name; }

  private showChooser(message: string): void {
    this.loadController?.abort(); this.generation++; this.definition = null; this.preflight = null; this.setBusy(false); this.checking = false; this.workspace.destroy();
    this.chooser.hidden = false; this.pageHeader.hidden = false; this.workbench.hidden = true;
    // The region and the chooser's methods come home with the state, so the
    // chooser's own status message is always inside the live region, whether or
    // not the catalog rendered before this point.
    this.renderChooserChrome();
    this.catalogStatus.textContent = message;
    const url = new URL(window.location.href); url.searchParams.delete('task_type'); history.replaceState(null, '', url);
    this.chooser.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
  }

  destroy(): void { this.loadController?.abort(); this.workspace.destroy(); this.root.replaceChildren(); }
}
