import { ApiError, beginDownload, downloadUrl, getResultManifest, loadAuthorizedResult, requestResultArchive, taskIdFromLocation } from '../../api/result-api';
import { resultFileName, type ArtifactRole, type LogicalResultFile, type ResultArtifact, type ResultFile, type ResultManifest,
  type ResultView, type TaskStatus } from '../../api/result-types';
import { setButtonIcon } from '../../components/icons';
import { t } from '../../app/i18n';
import { buildArtifactTree, filterArtifacts, localName, type ArtifactTreeNode } from './artifact-tree';
import { artifactCapability, createBasicRenderers, firstViewSource, RendererRegistry, ViewRendererRegistry,
  type ResolvedViewSources } from './renderer-registry';
import { createTrajectoryViewRenderer } from './trajectory-view';
import { createMatrixViewRenderer } from './matrix-view';
import { createScalarSummaryViewRenderer } from './scalar-summary-view';
import { createEntityTableViewRenderer } from './entity-table-view';
import { createMetricSeriesViewRenderer } from './metric-series-view';
import { createEvidenceBundleViewRenderer } from './evidence-bundle-view';
import { createCandidateCollectionViewRenderer } from './candidate-collection-view';
import type { MolecularViewerFactory } from './molecular/viewer-contract';
import { StructureController } from './molecular/structure-controller';
import { installScientificPrimitives } from './scientific';
import { StoryboardHost } from './storyboard-host';
import { mountTaskDiagnostics } from '../tasks/diagnostics';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node;
}
function formatBytes(value = 0): string {
  if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`; return `${(value / 1024 ** 3).toFixed(2)} GiB`;
}
function theme(): 'light' | 'dark' { return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'; }
// Manifest-declared artifact role → rail grouping. The vocabulary is the server's; only its
// projection is here. A file row states type and size, not which group it already sits in.
const ARTIFACT_ROLE_GROUPS: Array<{ labelKey: string; roles: ArtifactRole[] }> = [
  { labelKey: 'results.group.results', roles: ['primary'] },
  { labelKey: 'results.group.supporting', roles: ['evidence', 'provenance'] },
  { labelKey: 'results.group.diagnostics', roles: ['diagnostic'] },
  { labelKey: 'results.group.other', roles: ['artifact'] },
];
function isResultManifest(value: TaskStatus | ResultManifest): value is ResultManifest {
  return value.schema_version === 3 && Array.isArray(value.artifacts);
}
// A finished task states its exit status once, quietly, in the task identity. A runner-declared
// non-success outcome is a real scientific finding and keeps the band.
const QUIET_OUTCOMES = new Set(['success', 'succeeded', 'completed', 'complete', 'ready']);
const isQuietOutcome = (manifest: ResultManifest): boolean => manifest.status === 'finished' &&
  (!manifest.outcome || QUIET_OUTCOMES.has(manifest.outcome.trim().toLowerCase()));

interface WorkspaceNodes {
  status: HTMLElement; outcome: HTMLElement; title: HTMLElement; meta: HTMLElement; tabs: HTMLElement;
  previewTitle: HTMLElement; previewDescription: HTMLElement; preview: HTMLElement; download: HTMLAnchorElement;
  rail: HTMLElement; railDetails: HTMLDetailsElement; reopen: HTMLButtonElement; search: HTMLInputElement;
  fileList: HTMLElement; integrity: HTMLElement; artifactSummary: HTMLElement; archive: HTMLButtonElement; archiveStatus: HTMLElement;
  limitations: HTMLElement; run: HTMLElement; diagnostics: HTMLElement; viewError: HTMLButtonElement;
}

export class ResultWorkspace {
  private readonly taskId = taskIdFromLocation();
  private readonly rendererRegistry = new RendererRegistry();
  private readonly viewRenderers = new ViewRendererRegistry();
  private readonly structure: StructureController;
  private readonly nodes: WorkspaceNodes;
  private readonly storyboard: StoryboardHost;
  private manifest: ResultManifest | null = null;
  private selected: ResultFile | null = null;
  private viewRenderer: { destroy(): void } | null = null;
  private renderController: AbortController | null = null;
  private loadController: AbortController | null = null;
  private diagnosticController: AbortController | null = null;
  private poll: number | null = null;
  private disposed = false;
  private archiveBusy = false;
  private archiveTimer: number | null = null;
  private archiveChecks = 0;
  private readonly geometry: StructureController;
  private previewGeneration = 0;
  private storyboardStructureGeneration = 0;
  private structureRepresentation = 'cartoon_ligand';
  private structureColor = 'rainbow';
  private structureTheme = theme();
  private readonly directoryExpansion = new Map<string, boolean>();
  private readonly listeners = new AbortController();

  constructor(private readonly root: HTMLElement, createViewer: MolecularViewerFactory) {
    installScientificPrimitives(); this.geometry = new StructureController(createViewer, { controlsCollapsed: true }); this.structure = new StructureController(createViewer, {
      selectionEnabled: true, controlsCollapsed: true,
      onSelectionChanged: (residues) => this.storyboard.setMolecularSelection(residues),
    });
    this.nodes = this.buildShell(); this.storyboard = new StoryboardHost(this.nodes.preview, {
      openFile: (file) => this.openLogicalFile(file), downloadFile: (file) => beginDownload(file.url),
      openView: (viewId) => this.openViewById(viewId),
      mountView: async (viewId, host, signal) => {
        const view = this.manifest?.views?.find(item => item.id === viewId);
        if (!view) throw new Error(t('results.viewNoArtifact'));
        const sources = this.sourcesForView(view);
        const artifact = firstViewSource(sources);
        if (!artifact) throw new Error(t('results.viewNoArtifact'));
        const context = { signal, taskId: this.taskId };
        const renderer = this.viewRenderers.resolve(view);
        if (renderer) return renderer.render(view, sources, host, context);
        return this.rendererRegistry.resolve(artifact)?.render(artifact, host, context);
      },
      focusStructure: (selection) => this.structure.focus(selection), selectStructure: (selection) => this.structure.select(selection),
      describeResult: description => { this.nodes.title.textContent = description.title; if (description.subtitle) this.nodes.meta.textContent = `${description.subtitle} · ${this.taskId}`; },
      setStructureGeometry: artifact => this.structure.setGeometry(artifact),
      resetStructure: () => this.structure.resetCamera(),
      annotateStructure: annotation => this.structure.annotate(annotation),
      openGeometry: (file, description) => this.openGeometry(file, description),
      closeGeometry: () => { this.geometry.dispose(); this.nodes.preview.querySelector('.storyboard-geometry-panel')?.remove(); },
    });
    createBasicRenderers().forEach((renderer) => this.rendererRegistry.register(renderer));
    this.rendererRegistry.register({ id: 'structure', render: (artifact, host) => this.renderStructure(artifact, host) });
    this.viewRenderers.register(createMatrixViewRenderer());
    this.viewRenderers.register(createTrajectoryViewRenderer(createViewer, theme));
    this.viewRenderers.register(createEntityTableViewRenderer());
    this.viewRenderers.register(createMetricSeriesViewRenderer());
    this.viewRenderers.register(createScalarSummaryViewRenderer());
    this.viewRenderers.register(createEvidenceBundleViewRenderer());
    this.viewRenderers.register(createCandidateCollectionViewRenderer());
    this.bind();
  }

  async load(): Promise<this> {
    this.loadController?.abort(); this.loadController = new AbortController();
    this.renderDiagnostics(false);
    this.setState(t('results.loadingTitle'), t('results.loadingBody'));
    try {
      const result = await loadAuthorizedResult(this.taskId, this.loadController.signal);
      if (!isResultManifest(result)) { this.renderPending(result); return this; }
      this.manifest = result; this.renderManifest(result);
    } catch (error) {
      if ((error as Error).name === 'AbortError') return this;
      if (error instanceof ApiError && error.status === 401) {
        location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return this;
      }
      this.renderFatal((error as Error).message || t('results.unavailable'));
    }
    return this;
  }

  private buildShell(): WorkspaceNodes {
    this.root.replaceChildren(); const page = element('main', 'result-app');
    const header = element('header', 'result-header'); const identity = element('div', 'result-identity');
    const methodRow = element('p', 'result-method-row');
    const outcome = element('span', 'result-outcome'); outcome.hidden = true; methodRow.append(outcome);
    const title = element('h1', '', t('results.taskTitle', { id: this.taskId }));
    const meta = element('p', 'result-meta', this.taskId); identity.append(methodRow, title, meta);
    const actions = element('div', 'result-header-actions'); const dashboard = element('a', 'result-button', t('shell.nav.dashboard')); dashboard.href = '/compute/dashboard';
    const refresh = element('button', 'result-icon-button') as HTMLButtonElement; refresh.type = 'button'; refresh.title = t('results.refresh'); refresh.setAttribute('aria-label', t('results.refresh')); setButtonIcon(refresh, 'RefreshCw');
    refresh.addEventListener('click', () => void this.load()); actions.append(refresh); header.append(identity, actions);
    const status = element('section', 'result-status'); status.setAttribute('aria-live', 'polite');
    const diagnostics = element('section'); diagnostics.hidden = true; diagnostics.tabIndex = -1;
    const viewError = element('button', 'result-button', t('diagnostics.viewError')); viewError.type = 'button'; viewError.hidden = true;
    viewError.addEventListener('click', () => { diagnostics.scrollIntoView({ block: 'start' }); diagnostics.focus(); }); actions.prepend(viewError);
    const workspace = element('section', 'result-workspace'); const main = element('article', 'result-main');
    const tabs = element('nav', 'result-tabs'); tabs.setAttribute('aria-label', t('results.viewsLabel'));
    const previewHead = element('header', 'result-preview-header'); const copy = element('div');
    const previewTitle = element('h2', '', t('results.previewTitle')); const previewDescription = element('p', 'result-muted'); copy.append(previewTitle, previewDescription);
    const download = element('a', 'result-button result-button-small', t('results.download')) as HTMLAnchorElement; download.hidden = true; download.download = '';
    previewHead.append(copy, download); const preview = element('div', 'result-preview'); preview.setAttribute('aria-busy', 'false'); main.append(previewHead, preview);
    const viewMenu = element('details', 'result-view-menu'); const viewSummary = element('summary', '', t('results.viewsLabel')); const helpActions = element('div', 'result-help-actions'); const viewPanel = element('div', 'result-view-panel'); viewPanel.append(tabs, dashboard, helpActions); viewMenu.append(viewSummary, viewPanel); actions.append(viewMenu);
    const rail = element('dialog', 'result-rail'); rail.setAttribute('aria-label', t('results.filesLabel'));
    const closeFiles = element('button', 'result-button', t('ct.cancel')); closeFiles.type = 'button'; closeFiles.addEventListener('click', () => { rail.close(); });
    rail.addEventListener('close', () => { railDetails.open = false; actions.prepend(archive); identity.append(archiveStatus); });
    const reopen = element('button', 'result-rail-reopen', t('results.filesLabel')) as HTMLButtonElement; reopen.type = 'button'; reopen.hidden = false; reopen.setAttribute('aria-label', t('results.filesReopenLabel'));
    const railDetails = element('details', 'result-files') as HTMLDetailsElement; railDetails.open = false;
    const summary = element('summary', '', t('results.filesSummary')); const artifactSummary = element('span', 'result-muted'); summary.append(artifactSummary);
    const tools = element('div', 'result-file-tools'); const search = element('input', 'result-search') as HTMLInputElement;
    search.type = 'search'; search.placeholder = t('results.filter'); search.setAttribute('aria-label', t('results.filterLabel'));
    const archive = element('button', 'result-button result-button-small', t('results.archiveCreate')) as HTMLButtonElement; archive.type = 'button'; archive.hidden = true;
    const archiveStatus = element('p', 'result-archive-status'); archiveStatus.setAttribute('role', 'status');
    archive.className = 'result-button result-archive-action'; actions.prepend(archive); identity.append(archiveStatus);
    tools.append(search);
    const fileList = element('nav', 'result-file-list'); fileList.setAttribute('aria-label', t('results.fileListLabel'));
    const integrity = element('div'); railDetails.append(summary, tools, fileList, integrity); rail.append(closeFiles, railDetails); actions.prepend(reopen);
    workspace.append(main); const record = element('dialog', 'result-record-dialog'); record.setAttribute('aria-label', t('results.run.title')); const recordSummary = element('h2', '', t('results.run.title')); const recordClose = element('button', 'result-button', t('ct.cancel')); recordClose.type = 'button'; recordClose.addEventListener('click', () => record.close()); const recordOpen = element('button', 'result-button', t('results.run.title')); recordOpen.type = 'button'; recordOpen.addEventListener('click', () => record.showModal()); actions.insertBefore(recordOpen, viewMenu); const recordBody = element('section', 'result-record'); const limitations = element('div'); const run = element('div'); recordBody.append(limitations, run); record.append(recordClose, recordSummary, recordBody);
    page.append(header, status, diagnostics, workspace, record, rail); this.root.append(page);
    return { status, outcome, title, meta, tabs, previewTitle, previewDescription, preview, download, rail, railDetails, reopen, search, fileList, integrity, artifactSummary, archive, archiveStatus, limitations, run, diagnostics, viewError };
  }

  private bind(): void {
    const options = { signal: this.listeners.signal };
    this.nodes.search.addEventListener('input', () => this.renderFiles(), options);
    this.nodes.railDetails.addEventListener('toggle', () => this.syncRail(), options);
    this.nodes.reopen.addEventListener('click', () => { this.nodes.railDetails.open = true; this.syncRail(); }, options);
    this.nodes.archive.addEventListener('click', () => void this.archiveAction(), options);
    document.addEventListener('fullscreenchange', this.resize, options); window.addEventListener('resize', this.resize, options);
    window.addEventListener('pagehide', this.pagehide, options); window.addEventListener('pageshow', this.pageshow, options);
    this.syncRail();
  }

  private readonly resize = (): void => this.structure.resize();
  private readonly pagehide = (event: PageTransitionEvent): void => { if (!event.persisted) this.destroy(); };
  private readonly pageshow = (event: PageTransitionEvent): void => { if (event.persisted) this.structure.resize(); };

  private renderPending(payload: TaskStatus): void {
    const terminal = payload.terminal === true; const status = payload.status || 'running';
    this.renderDiagnostics(status === 'failed');
    if (terminal && this.poll != null) { clearInterval(this.poll); this.poll = null; }
    this.nodes.title.textContent = payload.display_name || t('results.taskTitle', { id: this.taskId });
    this.setState(status, terminal ? (payload.error || payload.message || t('results.noManifest')) : (payload.message || t('results.running')));
    this.resetPreview();
    this.nodes.preview.replaceChildren(element('p', 'result-empty', terminal ? t('results.pendingNone') : t('results.pendingWaiting')));
    if (!terminal && this.poll == null) this.poll = window.setInterval(() => void this.load(), 15_000);
  }

  private renderManifest(manifest: ResultManifest): void {
    if (this.poll != null) { clearInterval(this.poll); this.poll = null; }
    // A single named input is the specimen's identity; multiple inputs keep the method identity.
    const method = manifest.run?.method?.name || manifest.task_type || t('results.scientific');
    const input = manifest.run?.inputs?.length === 1 ? manifest.run.inputs[0]?.path.split('/').pop() : null;
    this.nodes.title.textContent = input || method;
    this.nodes.meta.textContent = `${method} · ${manifest.task_id}`; this.nodes.meta.title = t('results.taskIdTitle', { id: manifest.task_id });
    const quiet = isQuietOutcome(manifest);
    this.renderDiagnostics(manifest.status === 'failed');
    this.setState(quiet ? manifest.status : manifest.outcome || manifest.status, manifest.error || '', quiet);
    if (manifest.output_check.state === 'failed') {
      this.nodes.status.hidden = false;
      if (quiet) this.nodes.status.replaceChildren();
      this.nodes.status.append(element('strong', '', t('results.outputsIncomplete')),
        element('span', '', t('results.availableEvidence')));
    }
    // The summary is rendered by renderFiles(), which owns the filtered view.
    this.renderFiles(); this.renderTabs(); this.renderRecord(); this.syncArchive();
    if (manifest.storyboard) { this.nodes.railDetails.open = false; this.syncRail(); }
    if (manifest.storyboard?.entrypoint_url) void this.openStoryboard();
    else {
      // The declared primary view opens the page; a manifest that declares no primary
      // view keeps the generic first-artifact preview.
      const primary = (manifest.views || []).find((view) => view.role === 'primary');
      if (primary) void this.openView(primary);
      else { const artifact = this.primaryArtifact(); if (artifact) void this.openArtifact(artifact); else this.renderEmpty(); }
    }
  }

  private renderDiagnostics(failed: boolean): void {
    this.diagnosticController?.abort(); this.diagnosticController = null;
    this.nodes.diagnostics.replaceChildren(); this.nodes.diagnostics.hidden = !failed; this.nodes.viewError.hidden = !failed;
    if (failed) {
      this.diagnosticController = new AbortController();
      mountTaskDiagnostics(this.nodes.diagnostics, this.taskId, this.diagnosticController.signal);
    }
  }

  private primaryArtifact(): ResultArtifact | null {
    const artifacts = this.manifest?.artifacts || [];
    const view = this.manifest?.views?.find((item) => item.role === 'primary');
    const source = view ? firstViewSource(this.sourcesForView(view)) : null;
    const path = source && 'path' in source ? source.path : null;
    return artifacts.find((artifact) => artifact.path === path) || artifacts.find((artifact) => artifact.role === 'primary') || artifacts[0] || null;
  }

  private renderTabs(): void {
    this.nodes.tabs.replaceChildren(); const manifest = this.manifest; if (!manifest) return;
    if (manifest.storyboard?.entrypoint_url) this.nodes.tabs.append(this.tab(t('results.scientific'), 'storyboard', () => void this.openStoryboard()));
    (manifest.views || []).forEach((view) => this.nodes.tabs.append(this.tab(view.title, view.id, () => void this.openView(view))));
  }
  private tab(label: string, id: string, action: () => void): HTMLButtonElement {
    const button = element('button', 'result-tab', label) as HTMLButtonElement; button.type = 'button'; button.dataset.view = id;
    button.setAttribute('aria-pressed', 'false'); button.addEventListener('click', action); return button;
  }
  private markTab(id: string | null): void { const menu = this.nodes.tabs.closest('details'); if (menu) menu.open = false; this.nodes.tabs.querySelectorAll<HTMLElement>('[data-view]').forEach((tab) => tab.setAttribute('aria-pressed', tab.dataset.view === id ? 'true' : 'false')); }

  private async openView(view: ResultView): Promise<void> {
    const generation = ++this.previewGeneration;
    const sources = this.sourcesForView(view);
    const artifact = firstViewSource(sources);
    if (!artifact) {
      // Leave no previous renderer observing above the error message.
      this.destroyViewRenderer(); this.storyboard.destroy();
      this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
      this.nodes.download.hidden = true;
      this.renderPreviewError(t('results.viewNoArtifact'));
      return;
    }
    await this.renderView(view, sources, artifact, generation); if (generation !== this.previewGeneration) return;
    this.markTab(view.id);
  }

  /**
   * Resolve every declared source of a view, in declared order.
   *
   * The Server already resolved each selector to published paths; the browser
   * only joins those paths to the manifest artifacts. A source whose paths are
   * absent resolves to an empty list so a renderer can say which source is
   * missing instead of silently receiving a different one.
   */
  private sourcesForView(view: ResultView): ResolvedViewSources {
    const artifacts = this.manifest?.artifacts || [];
    const byPath = new Map(artifacts.map((artifact) => [artifact.path, artifact]));
    const sources: ResolvedViewSources = {};
    for (const [name, paths] of Object.entries(view.sources || {})) {
      sources[name] = (paths || []).flatMap((path) => byPath.get(path) || []);
    }
    return sources;
  }

  private openViewById(viewId: string): Promise<void> {
    const view = this.manifest?.views?.find((item) => item.id === viewId);
    return view ? this.openView(view) : Promise.resolve();
  }

  // A view is rendered by its declared `plugin`. A declared view primitive that cannot load
  // (no table, malformed data, over budget, request failure) states the reason and falls back
  // to the generic artifact renderer, so a view is never blanker than its source artifact.
  // Every declared view keeps its own title and description, including on that fallback.
  private async renderView(view: ResultView, sources: ResolvedViewSources, artifact: ResultFile, generation: number): Promise<void> {
    const renderer = this.viewRenderers.resolve(view);
    if (!renderer) {
      await this.openArtifact(artifact, generation);
      if (generation !== this.previewGeneration) return;
      this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
      return;
    }
    this.storyboardStructureGeneration += 1;
    if ((this.nodes.rail as HTMLDialogElement).open) (this.nodes.rail as HTMLDialogElement).close();
    this.destroyViewRenderer(); this.geometry.dispose(); this.storyboard.destroy(); this.cancelRender(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact);
    this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.title = fileName;
    this.nodes.download.textContent = t('results.downloadNamed', { name: localName(fileName) });
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { this.viewRenderer = (await renderer.render(view, sources, this.nodes.preview, { signal: controller.signal, taskId: this.taskId })) || null; }
    catch (error) {
      if ((error as Error).name === 'AbortError' || generation !== this.previewGeneration) return;
      this.destroyViewRenderer();
      await this.renderViewFallback(view, artifact, generation, (error as Error).message || t('results.viewRenderFailed'));
    }
    finally { if (!controller.signal.aborted && generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async renderViewFallback(view: ResultView, artifact: ResultFile, generation: number, reason: string): Promise<void> {
    if (generation !== this.previewGeneration) return;
    await this.openArtifact(artifact, generation);
    if (generation !== this.previewGeneration) return;
    this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
    this.nodes.preview.prepend(element('p', 'result-note', t('results.viewFallback', { reason })));
  }

  private destroyViewRenderer(): void { this.viewRenderer?.destroy(); this.viewRenderer = null; }

  private async openStoryboard(): Promise<void> {
    const manifest = this.manifest; if (!manifest?.storyboard) return;
    const generation = ++this.previewGeneration;
    this.storyboardStructureGeneration += 1; this.cancelRender(); this.structure.dispose(); this.geometry.dispose(); this.nodes.preview.setAttribute('aria-busy', 'true');
    this.nodes.previewTitle.textContent = t('results.scientific'); this.nodes.previewDescription.textContent = ''; this.nodes.download.hidden = true;
    try { const current = await this.storyboard.mount(manifest.storyboard, manifest); if (current && generation === this.previewGeneration) this.markTab('storyboard'); }
    catch (error) { if (generation === this.previewGeneration) this.renderPreviewError((error as Error).message || t('results.storyboardUnavailable')); }
    finally { if (generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async openLogicalFile(file: LogicalResultFile): Promise<void> {
    const capability = artifactCapability(file);
    if (capability !== 'structure' && capability !== 'molecular_structure') return this.openArtifact(file);
    const generation = ++this.storyboardStructureGeneration;
    this.cancelRender(); const controller = new AbortController(); this.renderController = controller;
    this.selectArtifact(file);
    if (!this.manifest?.run?.inputs?.length) this.nodes.title.textContent = localName(resultFileName(file)).replace(/\.(?:pdb|mmcif|cif)(?:\.gz)?$/i, '');
    const slot = this.nodes.preview.querySelector<HTMLElement>('[data-structure-slot]') || this.nodes.preview;
    let panel = slot.querySelector<HTMLElement>(':scope > .storyboard-structure-panel');
    if (!panel) { panel = element('section', 'storyboard-structure-panel'); slot.append(panel); }
    panel.setAttribute('aria-busy', 'true');
    try { await this.renderStructure(file, panel); if (generation === this.storyboardStructureGeneration) panel.dataset.ready = 'true'; }
    catch (error) {
      if (generation !== this.storyboardStructureGeneration || (error as Error).name === 'AbortError') return;
      this.structure.dispose(); panel.replaceChildren(element('p', 'result-empty', (error as Error).message || t('results.structureUnavailable')));
    } finally { if (generation === this.storyboardStructureGeneration && !controller.signal.aborted) panel.setAttribute('aria-busy', 'false'); }
  }

  async openArtifact(artifact: ResultFile, requestedGeneration?: number): Promise<void> {
    const generation = requestedGeneration ?? ++this.previewGeneration;
    this.storyboardStructureGeneration += 1;
    if ((this.nodes.rail as HTMLDialogElement).open) (this.nodes.rail as HTMLDialogElement).close();
    this.destroyViewRenderer(); this.geometry.dispose(); this.storyboard.destroy(); this.cancelRender(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact); this.nodes.previewTitle.textContent = localName(fileName); this.nodes.previewDescription.textContent = formatBytes(artifact.size);
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.title = fileName;
    this.nodes.download.textContent = t('results.downloadNamed', { name: localName(fileName) });
    const renderer = this.rendererRegistry.resolve(artifact); if (!renderer) { this.renderPreviewError(t('results.noInlinePreview')); return; }
    if (artifactCapability(artifact) !== 'structure' && artifactCapability(artifact) !== 'molecular_structure') this.structure.dispose();
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { await renderer.render(artifact, this.nodes.preview, { signal: controller.signal, taskId: this.taskId }); }
    catch (error) { if ((error as Error).name !== 'AbortError' && generation === this.previewGeneration) this.renderPreviewError((error as Error).message || t('results.previewFailed')); }
    finally { if (!controller.signal.aborted && generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async renderStructure(artifact: ResultFile, host: HTMLElement): Promise<void> {
    // A stage left by another view renderer (the trajectory stage shares these
    // classes) is not reused: the new renderer starts from its own viewport.
    let viewport = host.querySelector<HTMLElement>('.structure-viewport:not(.trajectory-viewport)');
    let viewerHost = viewport?.querySelector<HTMLElement>('.structure-host');
    if (!viewport || !viewerHost) {
      viewport = element('section', 'structure-viewport');
      viewerHost = element('div', 'structure-host'); viewerHost.setAttribute('role', 'region'); viewerHost.setAttribute('aria-label', t('results.structure.viewerLabel'));
      viewport.append(viewerHost); host.replaceChildren(viewport);
    }
    viewport.querySelector('.structure-toolbar')?.remove();
    const shelf = this.nodes.preview.querySelector<HTMLElement>('[data-structure-tools]');
    if (shelf) shelf.replaceChildren(this.structureToolbar(artifact, viewport));
    else viewport.prepend(this.structureToolbar(artifact, viewport));
    await this.structure.mount(viewerHost, artifact, this.structureTheme);
  }

  private structureToolbar(artifact: ResultFile, viewport: HTMLElement): HTMLElement {
    const toolbar = element('div', 'structure-toolbar'); toolbar.setAttribute('role', 'toolbar'); toolbar.setAttribute('aria-label', t('results.structure.controls'));
    const representations: Array<[string, string]> = [['cartoon', t('results.structure.cartoon')], ['cartoon_ligand', t('results.structure.cartoonLigand')], ['sticks', t('results.structure.sticks')], ['surface_ligand', t('results.structure.surface')]];
    const selectControl = (label: string, options: Array<[string, string]>, value: string, changed: (value: string) => void): HTMLElement => {
      const field = element('label', 'structure-tool-field', label); const select = element('select');
      for (const [id, title] of options) select.append(new Option(title, id, false, id === value));
      select.addEventListener('change', () => changed(select.value)); field.append(select); return field;
    };
    const representationGroup = selectControl(t('results.structure.representation'), representations, this.structureRepresentation, value => { this.structureRepresentation = value; void this.structure.setRepresentation(value); });
    const colours: Array<[string, string]> = [['rainbow', t('results.structure.sequence')], ['chain', t('results.structure.chain')]];
    if ('confidence_encoding' in artifact && artifact.confidence_encoding) colours.push(['confidence', t('results.structure.confidence')]);
    if (this.structureColor === 'confidence' && colours.length === 2) this.structureColor = 'rainbow';
    const colorGroup = selectControl(t('results.structure.colour'), colours, this.structureColor, value => { this.structureColor = value; void this.structure.setColor(value); const legend = this.nodes.preview.querySelector<HTMLElement>('[data-structure-legend]'); if (legend) legend.textContent = value === 'rainbow' ? 'Sequence N → C' : colours.find(([id]) => id === value)?.[1] || value; });
    const actions = element('div', 'structure-toolbar-actions');
    const reset = element('button', 'result-button result-button-small', t('results.structure.whole')) as HTMLButtonElement; reset.type = 'button'; reset.title = t('results.structure.whole'); reset.setAttribute('aria-label', t('results.structure.whole')); reset.addEventListener('click', () => { this.structure.resetCamera(); viewport.closest('[data-molecular-workspace]')?.dispatchEvent(new Event('structure-reset')); });
    const themeButton = element('button', 'result-button result-button-small') as HTMLButtonElement; themeButton.type = 'button';
    const syncThemeButton = (): void => { const dark = this.structureTheme === 'dark'; themeButton.textContent = dark ? t('results.structure.lightCanvas') : t('results.structure.darkCanvas'); themeButton.setAttribute('aria-pressed', String(dark)); };
    syncThemeButton(); themeButton.addEventListener('click', () => { this.structureTheme = this.structureTheme === 'dark' ? 'light' : 'dark'; this.structure.setTheme(this.structureTheme); syncThemeButton(); });
    const image = element('button', 'result-button result-button-small', t('results.structure.savePng')) as HTMLButtonElement; image.type = 'button'; image.addEventListener('click', async () => beginDownload(await this.structure.captureImage()));
    const source = element('button', 'result-button result-button-small', t('results.download')) as HTMLButtonElement; source.type = 'button'; source.addEventListener('click', () => beginDownload(downloadUrl(artifact)));
    const fullscreen = element('button', 'result-button result-button-small') as HTMLButtonElement; fullscreen.type = 'button';
    const syncFullscreen = (): void => { const expanded = document.fullscreenElement === (viewport.closest('[data-molecular-workspace]') || viewport); const label = expanded ? t('results.structure.exitFullscreen') : t('results.structure.enterFullscreen'); fullscreen.title = label; fullscreen.setAttribute('aria-label', label); fullscreen.setAttribute('aria-pressed', String(expanded)); fullscreen.textContent = expanded ? label : t('results.structure.expandStage'); };
    syncFullscreen();
    fullscreen.addEventListener('click', async () => { const surface = viewport.closest<HTMLElement>('[data-molecular-workspace]') || viewport; if (document.fullscreenElement === surface) await document.exitFullscreen(); else await surface.requestFullscreen(); });
    const controller = this.renderController; if (controller) document.addEventListener('fullscreenchange', syncFullscreen, { signal: controller.signal });
    const secondary = element('div', 'structure-tool-secondary');
    const native = element('details', 'structure-extra-tools'); native.append(element('summary', '', t('results.structure.advanced')), themeButton, source);
    secondary.append(native, image, element('span', 'structure-gesture', 'Drag to rotate · scroll to zoom'));
    actions.append(reset, fullscreen); toolbar.append(representationGroup, colorGroup, actions, secondary);
    return toolbar;
  }

  private renderFiles(): void {
    this.renderIntegrity();
    const query = this.nodes.search.value;
    // Every artifact the manifest declares is presented; only the search narrows the set.
    const artifacts = filterArtifacts(this.manifest?.artifacts || [], query);
    const showingFiltered = query.trim() !== '' && artifacts.length !== (this.manifest?.artifacts.length || 0);
    const size = artifacts.reduce((sum, artifact) => sum + artifact.size, 0);
    this.nodes.artifactSummary.textContent = showingFiltered
      ? t('results.fileSummaryFiltered', { shown: artifacts.length, total: this.manifest?.artifacts.length ?? artifacts.length, size: formatBytes(size) })
      : t('results.fileSummaryAll', { count: artifacts.length, size: formatBytes(size) });
    // Capture actual disclosure state before replacing nodes. A queued toggle
    // from a detached tree must not overwrite a reader's more recent choice.
    this.nodes.fileList.querySelectorAll<HTMLDetailsElement>('[data-directory-key]').forEach(details => {
      this.directoryExpansion.set(details.dataset.directoryKey!, details.open);
    });
    this.nodes.fileList.replaceChildren();
    const renderNode = (node: ArtifactTreeNode, target: HTMLElement, group: string): void => {
      node.directories.forEach((directory) => { const details = element('details', 'result-directory') as HTMLDetailsElement;
        const key = `${group}/${directory.path}`;
        details.open = this.directoryExpansion.get(key) ?? true;
        details.dataset.directoryKey = key;
        details.addEventListener('toggle', () => { if (details.isConnected) this.directoryExpansion.set(key, details.open); });
        const summary = element('summary', '', directory.name); const children = element('div', 'result-directory-children'); details.append(summary, children); target.append(details); renderNode(directory, children, group); });
      node.artifacts.forEach((artifact) => target.append(this.fileRow(artifact)));
    };
    // The scientific list comes first, grouped by the manifest-declared artifact role; the raw directory tree stays inside each group.
    ARTIFACT_ROLE_GROUPS.forEach(({ labelKey, roles }) => { const members = artifacts.filter((artifact) => roles.includes(artifact.role)); if (!members.length) return;
      const label = t(labelKey);
      const section = element('section', 'result-file-group'); section.append(element('h3', '', label)); const list = element('div'); section.append(list); this.nodes.fileList.append(section);
      renderNode(buildArtifactTree(members), list, label); });
    if (!artifacts.length) this.nodes.fileList.append(element('p', 'result-empty', t('results.noFilesMatch')));
  }

  private fileRow(artifact: ResultArtifact): HTMLElement {
    const row = element('div', 'result-file-row'); const open = element('button', 'result-file-open') as HTMLButtonElement; open.type = 'button';
    open.dataset.artifactPath = artifact.path; open.title = artifact.path; const name = element('strong', '', localName(artifact.path));
    const selectedPath = this.selected && 'path' in this.selected ? this.selected.path : null;
    open.setAttribute('aria-current', String(selectedPath === artifact.path));
    const meta = element('span', '', formatBytes(artifact.size)); open.append(name, meta); open.addEventListener('click', () => void this.openArtifact(artifact));
    const download = element('a', 'result-file-download') as HTMLAnchorElement; download.href = downloadUrl(artifact); download.download = ''; download.title = t('results.fileDownload', { name: artifact.path }); download.setAttribute('aria-label', t('results.fileDownload', { name: artifact.path })); setButtonIcon(download, 'Download');
    row.append(open, download); return row;
  }

  private renderRecord(): void {
    const manifest = this.manifest; if (!manifest) return; this.nodes.limitations.replaceChildren(); this.nodes.run.replaceChildren();
    if (manifest.limitations?.length) { const title = element('h2', '', t('results.limitations')); const list = element('ul'); manifest.limitations.forEach((text) => list.append(element('li', '', text))); this.nodes.limitations.append(title, list); }
    const values: Array<[string, string]> = [[t('dashboard.card.taskId'), manifest.task_id], [t('results.run.submitted'), manifest.run?.submitted_at || '-'], [t('results.run.started'), manifest.run?.started_at || '-'], [t('results.run.finished'), manifest.run?.finished_at || '-']];
    manifest.run?.inputs?.forEach((input) => values.push([input.role ? t('results.run.inputRole', { role: input.role }) : t('results.run.input'), `${input.path} [${input.sha256.slice(0, 12)}]`]));
    manifest.run?.parameters?.forEach((parameter) => values.push([parameter.label, `${String(parameter.value)}${parameter.unit ? ` ${parameter.unit}` : ''}`]));
    const title = element('h2', '', t('results.run.title')); const list = element('dl', 'result-definition-list');
    values.forEach(([term, value]) => list.append(element('dt', '', term), element('dd', '', value))); this.nodes.run.append(title, list);
    if (manifest.run?.citations?.length) { const citations = element('ul', 'result-citations'); manifest.run.citations.forEach((citation) => { const item = element('li');
      if (citation.url || citation.doi) { const link = element('a', '', citation.title) as HTMLAnchorElement; link.href = citation.url || `https://doi.org/${encodeURIComponent(citation.doi || '')}`; link.rel = 'noopener'; item.append(link); } else item.textContent = citation.title; citations.append(item); }); this.nodes.run.append(citations); }
  }

  private renderIntegrity(): void {
    const check = this.manifest?.output_check; this.nodes.integrity.replaceChildren(); if (!check || check.state === 'not_configured' || check.state === 'not_assessed') return;
    const passed = check.state === 'passed'; const section = element('section', 'result-integrity'); section.dataset.state = check.state;
    section.append(element('h3', '', t('results.integrity.title')), element('p', '', passed ? t('results.integrity.present') : t('results.integrity.incomplete')));
    const detail = check.problems?.length ? check.problems : (check.checks || []).filter((item) => item.status === 'failed').map((item) => item.file_id || item.source || item.view_id || t('results.integrity.file'));
    if (detail.length) { const list = element('ul'); detail.forEach((text) => list.append(element('li', '', String(text)))); section.append(list); }
    this.nodes.integrity.append(section);
  }

  private syncArchive(): void {
    const archive = this.manifest?.archive; const available = Boolean(archive?.request_url || archive?.download_url);
    if (archive?.ready && archive.download_url) {
      this.archiveBusy = false;
      if (this.archiveTimer != null) clearTimeout(this.archiveTimer);
      this.archiveTimer = null;
      this.nodes.archiveStatus.textContent = t('results.archiveReady');
      this.nodes.archiveStatus.dataset.error = 'false';
    }
    this.nodes.archive.hidden = !available; this.nodes.archive.disabled = !available || this.archiveBusy;
    this.nodes.archive.textContent = archive?.ready && archive.download_url ? t('results.archiveDownload') : t(this.archiveBusy ? 'results.archiveBuilding' : 'results.archiveCreate');
  }
  private async archiveAction(): Promise<void> {
    const archive = this.manifest?.archive; if (!archive || this.archiveBusy) return;
    if (archive.ready && archive.download_url) { beginDownload(archive.download_url); return; }
    if (!archive.request_url) return;
    this.archiveBusy = true; this.archiveChecks = 0;
    this.nodes.archiveStatus.dataset.error = 'false';
    this.nodes.archiveStatus.textContent = t('results.archiveBuilding'); this.syncArchive();
    try {
      await requestResultArchive(archive.request_url);
      if (!this.disposed) await this.checkArchive();
    } catch (error) { this.archiveError((error as Error).message || t('results.archiveFailed')); }
  }
  private async checkArchive(): Promise<void> {
    try {
      const manifest = await getResultManifest(this.taskId, this.listeners.signal);
      if (this.disposed) return;
      // Refresh only archive state: never tear down an active molecular selection.
      if (this.manifest) this.manifest.archive = manifest.archive;
      if (manifest.archive?.ready && manifest.archive.download_url) { this.syncArchive(); return; }
      if (++this.archiveChecks >= 30) { this.archiveError(t('results.archiveWaiting')); return; }
      this.archiveTimer = window.setTimeout(() => void this.checkArchive(), 4000);
    } catch (error) { if (!this.disposed) this.archiveError((error as Error).message || t('results.archiveFailed')); }
  }
  private archiveError(message: string): void {
    this.archiveBusy = false; this.nodes.archiveStatus.textContent = message;
    this.nodes.archiveStatus.dataset.error = 'true'; this.syncArchive();
  }

  private async openGeometry(file: LogicalResultFile, description: string): Promise<void> {
    let panel = this.nodes.preview.querySelector<HTMLElement>('.storyboard-geometry-panel');
    if (!panel) { panel = element('section', 'storyboard-geometry-panel'); this.nodes.preview.append(panel); }
    this.geometry.dispose();
    const heading = element('h3', '', resultFileName(file));
    const note = element('p', 'result-note', description);
    const close = element('button', 'result-button', t('results.geometryClose'));
    const host = element('div', 'structure-host'); host.style.height = '24rem'; host.style.position = 'relative';
    close.addEventListener('click', () => { this.geometry.dispose(); panel?.remove(); });
    panel.replaceChildren(heading, note, close, host);
    await this.geometry.setRepresentation('points');
    try { await this.geometry.mount(host, file, this.structureTheme); }
    catch (error) { host.replaceChildren(element('p', 'result-empty', (error as Error).message)); }
  }

  private readonly syncRail = (): void => {
    const dialog = this.nodes.rail as HTMLDialogElement;
    if (this.nodes.railDetails.open && dialog.isConnected && !dialog.open) {
      this.nodes.search.before(this.nodes.archive, this.nodes.archiveStatus);
      dialog.showModal();
    }
    if (!this.nodes.railDetails.open && dialog.open) dialog.close();
    this.structure.resize();
  };
  private selectArtifact(artifact: ResultFile): void {
    this.selected = artifact; const fileName = resultFileName(artifact);
    this.nodes.fileList.querySelectorAll<HTMLElement>('[data-artifact-path]').forEach((node) => node.setAttribute('aria-current', node.dataset.artifactPath === fileName ? 'true' : 'false'));
  }
  // `status` is the task lifecycle; `quiet` is the runner's own success outcome, which the header states instead.
  private setState(status: string, message: string, quiet = false): void {
    this.nodes.status.replaceChildren(element('strong', '', status), element('span', '', message));
    this.nodes.status.hidden = quiet;
    this.nodes.outcome.textContent = quiet ? `✓ ${status}` : status;
    this.nodes.outcome.hidden = !quiet;
    this.nodes.outcome.dataset.tone = quiet ? 'ok' : 'attention';
  }
  private renderEmpty(): void { this.resetPreview(); this.nodes.preview.replaceChildren(element('p', 'result-empty', t('results.noPreview'))); }
  private renderPreviewError(message: string): void { this.resetPreview(); this.nodes.preview.replaceChildren(element('p', 'result-empty', message)); this.nodes.preview.setAttribute('aria-busy', 'false'); }
  private renderFatal(message: string): void { this.setState(t('results.fatalTitle'), message); this.renderPreviewError(t('results.fatalHint')); }
  private cancelRender(): void { this.renderController?.abort(); this.renderController = null; }
  private resetPreview(): void { this.storyboardStructureGeneration += 1; this.destroyViewRenderer(); this.cancelRender(); this.storyboard.destroy(); this.structure.dispose(); this.geometry.dispose(); }

  destroy(): void {
    if (this.disposed) return; this.disposed = true; this.destroyViewRenderer(); this.cancelRender(); this.loadController?.abort(); this.storyboard.destroy(); this.structure.dispose(); this.geometry.dispose();
    this.diagnosticController?.abort();
    if (this.poll != null) clearInterval(this.poll); if (this.archiveTimer != null) clearTimeout(this.archiveTimer); this.listeners.abort(); this.root.replaceChildren();
  }
}
