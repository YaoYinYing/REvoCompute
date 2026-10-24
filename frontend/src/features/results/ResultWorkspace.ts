import { ApiError, beginDownload, downloadName, downloadUrl, getResultManifest, loadAuthorizedResult, requestResultArchive, taskIdFromLocation } from '../../api/result-api';
import { resultFileName, type ArtifactRole, type LogicalResultFile, type ResultArtifact, type ResultFile, type ResultManifest,
  type ResultView, type TaskStatus } from '../../api/result-types';
import { setButtonIcon } from '../../components/icons';
import { t } from '../../app/i18n';
import { buildArtifactTree, filterArtifacts, localName, type ArtifactTreeNode } from './artifact-tree';
import { artifactCapability, createBasicRenderers, firstViewSource, RendererRegistry, ViewRendererRegistry,
  type ResolvedViewSources, type RendererContext } from './renderer-registry';
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
import type { LocalResultSource } from './local-source';

/**
 * A demo replay source: the same ResultManifest v3 the workspace already renders,
 * read from a validated replay bundle instead of a Task the reader owns. The
 * workspace still owns every renderer and every artifact route stays bounded;
 * only the manifest's origin changes.
 */
export interface DemoResultSource {
  taskId: string;
  load(signal: AbortSignal): Promise<TaskStatus | ResultManifest>;
}

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

/**
 * The one address a citation may link to.
 *
 * A citation comes from the manifest, and a local result's manifest is a folder's bytes. Only an
 * absolute `https:` address (or a DOI, from which the Server's own form is derived) becomes a
 * live anchor in this origin, so a `javascript:` or `data:` URL can never be clicked into
 * execution on the results page.
 */
const citationHref = (citation: { url?: string; doi?: string }): string | null => {
  if (citation.url) {
    try { const parsed = new URL(citation.url); if (parsed.protocol === 'https:') return parsed.href; }
    catch { /* a relative or malformed address is not a citation locator */ }
  }
  return citation.doi ? `https://doi.org/${encodeURIComponent(citation.doi)}` : null;
};

interface WorkspaceNodes {  status: HTMLElement; outcome: HTMLElement; badge: HTMLElement; title: HTMLElement; meta: HTMLElement; tabs: HTMLElement;
  previewTitle: HTMLElement; previewDescription: HTMLElement; preview: HTMLElement; download: HTMLAnchorElement;
  rail: HTMLElement; railDetails: HTMLDetailsElement; reopen: HTMLButtonElement; search: HTMLInputElement;
  fileList: HTMLElement; integrity: HTMLElement; artifactSummary: HTMLElement; archive: HTMLButtonElement; archiveStatus: HTMLElement;
  limitations: HTMLElement; run: HTMLElement; diagnostics: HTMLElement; viewError: HTMLButtonElement;
}

export class ResultWorkspace {
  private readonly taskId: string;
  /**
   * The opened result folder, when this workspace renders a Local result.
   *
   * A local workspace never requests a result: there is no Task to authorize and no route a
   * folder could be read through, so `load()` projects the folder's own manifest instead.
   */
  private readonly local: LocalResultSource | null;
  /** A recorded demo source, when this page replays a bundle instead of a Task. */
  private readonly demoSource: DemoResultSource | null;
  private readonly rendererRegistry = new RendererRegistry();
  private readonly viewRenderers = new ViewRendererRegistry();
  private readonly structure: StructureController;
  // A declared view's candidate is a different structure from the page's own, so a
  // view stage is a second, independent viewer rather than the page's one.
  private viewStructure: StructureController | null = null;
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
  private storyboardStructure: LogicalResultFile | null = null;
  private structureRepresentation = 'cartoon_ligand';
  private structureColor = 'rainbow';
  private structureTheme = theme();
  // A view stage's toolbar settings are its own, so driving one stage never
  // changes how the page's stage (or the next view's) is drawn.
  private viewStructureRepresentation = 'cartoon_ligand';
  private viewStructureColor = 'rainbow';
  private viewStructureTheme = theme();
  private readonly directoryExpansion = new Map<string, boolean>();
  private readonly listeners = new AbortController();

  constructor(private readonly root: HTMLElement, private readonly createViewer: MolecularViewerFactory, local: LocalResultSource | null = null,
    demoSource: DemoResultSource | null = null) {
    this.local = local;
    this.demoSource = demoSource;
    // The Task identity the page states: the source's own for a local folder, the
    // replayed Task's for a demo bundle, the URL's for a Task. No route is ever
    // composed for the local one -- it is the literal `local`.
    this.taskId = local ? local.taskId : demoSource ? demoSource.taskId : taskIdFromLocation();
    installScientificPrimitives(); this.geometry = new StructureController(createViewer, { controlsCollapsed: true }); this.structure = new StructureController(createViewer, {
      selectionEnabled: true, controlsCollapsed: true,
      onSelectionChanged: (residues) => this.storyboard.setMolecularSelection(residues),
    });
    this.nodes = this.buildShell(); this.storyboard = new StoryboardHost(this.nodes.preview, {
      openFile: (file) => this.openLogicalFile(file), downloadFile: (file) => beginDownload(file.url, downloadName(file)),
      openView: (viewId) => this.openViewById(viewId),
      mountView: async (viewId, host, signal) => {
        const view = this.manifest?.views?.find(item => item.id === viewId);
        if (!view) throw new Error(t('results.viewNoArtifact'));
        const sources = this.sourcesForView(view);
        const artifact = firstViewSource(sources);
        if (!artifact) throw new Error(t('results.viewNoArtifact'));
        const context = this.rendererContext(signal);
        const renderer = this.viewRenderers.resolve(view);
        if (renderer) return renderer.render(view, sources, host, context);
        return this.rendererRegistry.resolve(artifact)?.render(artifact, host, context);
      },
      focusStructure: (selection) => this.structure.focus(selection), selectStructure: (selection) => this.structure.select(selection),
      describeResult: description => { this.nodes.title.textContent = description.title; if (description.subtitle) this.nodes.meta.textContent = `${description.subtitle} · ${this.sourceLabel()}`; },
      setStructureGeometry: artifact => this.structure.setGeometry(artifact),
      resetStructure: () => this.structure.resetCamera(),
      annotateStructure: annotation => this.structure.annotate(annotation),
      openGeometry: (file, description) => this.openGeometry(file, description),
      closeGeometry: () => { this.geometry.dispose(); this.nodes.preview.querySelector('.storyboard-geometry-panel')?.remove(); },
    });
    createBasicRenderers().forEach((renderer) => this.rendererRegistry.register(renderer));
    this.rendererRegistry.register({ id: 'structure', render: (artifact, host) => this.renderStructure(artifact, host, this.structure) });
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
    if (this.local) { this.renderLocal(this.local); return this; }
    try {
      const result = this.demoSource
        ? await this.demoSource.load(this.loadController.signal)
        : await loadAuthorizedResult(this.taskId, this.loadController.signal);
      if (!isResultManifest(result)) { this.renderPending(result); return this; }
      this.manifest = result; this.renderManifest(result);
    } catch (error) {
      if ((error as Error).name === 'AbortError') return this;
      if (!this.demoSource && error instanceof ApiError && error.status === 401) {
        location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return this;
      }
      this.renderFatal((error as Error).message || t('results.unavailable'));
    }
    return this;
  }

  /** The identity line's source: the folder for a local result, the replay scenario for a demo, the Task id otherwise. */
  private sourceLabel(): string { return this.local ? this.local.label : this.demoSource ? `${t('demo.replay.source')} · ${this.taskId}` : this.taskId; }

  /**
   * Render an opened local folder as this page's result.
   *
   * The page states Local as its source, refuses to pretend it is the Task the archive came
   * from (that Task is not this document's to authorize), and keeps a declared Storyboard as a
   * stated limitation rather than loading code out of the folder.
   */
  private renderLocal(local: LocalResultSource): void {
    const manifest = local.manifest;
    this.manifest = manifest;
    // The folder holds no Task: the Task its manifest records is the archive's provenance,
    // not this page's identity, so the badge states the source instead of that Task's id.
    this.nodes.badge.textContent = t('results.local.badge');
    this.nodes.badge.title = t('results.local.badgeTitle', { label: local.label });
    this.nodes.badge.hidden = false;
    this.renderManifest(manifest);
    const { hashed, unchecked } = local.verification;
    this.nodes.archiveStatus.replaceChildren(element('p', 'result-note', unchecked.length
      ? t('results.local.verifiedPartial', { verified: hashed, sizeOnly: unchecked.length })
      : t(hashed === 1 ? 'results.local.verifiedOne' : 'results.local.verified', { verified: hashed })));
    this.nodes.archiveStatus.dataset.error = 'false';
    if (local.storyboard) {
      this.nodes.status.replaceChildren(element('strong', '', t('results.local.scientific')),
        element('span', '', t('results.local.storyboard', { identifier: local.storyboard })));
      this.nodes.status.hidden = false;
    }
  }

  private buildShell(): WorkspaceNodes {
    this.root.replaceChildren(); const page = element('main', 'result-app');
    const header = element('header', 'result-header'); const identity = element('div', 'result-identity');
    const methodRow = element('p', 'result-method-row');
    const outcome = element('span', 'result-outcome'); outcome.hidden = true; methodRow.append(outcome);
    const badge = element('span', 'result-source-badge'); badge.hidden = true; badge.dataset.source = 'local';
    const title = element('h1', '', this.local ? t('results.title') : t('results.taskTitle', { id: this.taskId }));
    const meta = element('p', 'result-meta', this.sourceLabel()); identity.append(methodRow, title, meta, badge);
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
    return { status, outcome, badge, title, meta, tabs, previewTitle, previewDescription, preview, download, rail, railDetails, reopen, search, fileList, integrity, artifactSummary, archive, archiveStatus, limitations, run, diagnostics, viewError };
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

  private readonly resize = (): void => { this.structure.resize(); this.viewStructure?.resize(); };
  private readonly pagehide = (event: PageTransitionEvent): void => { if (!event.persisted) this.destroy(); };
  private readonly pageshow = (event: PageTransitionEvent): void => { if (event.persisted) this.resize(); };

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
    // A local result states the folder it was read from: the Task identity the archive records
    // is a Task that is not this document's, and a local page never names it as live.
    this.nodes.meta.textContent = this.local ? `${method} · ${this.local.label}` : `${method} · ${manifest.task_id}`;
    this.nodes.meta.title = this.local ? this.local.label : t('results.taskIdTitle', { id: manifest.task_id });
    this.nodes.meta.dataset.source = this.local ? 'local' : 'remote';
    const quiet = isQuietOutcome(manifest);
    // Task diagnostics read the Server's task routes; a folder has no Task to ask about.
    this.renderDiagnostics(!this.local && manifest.status === 'failed');
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
    // A declared path that is also a logical file is that file to a reader: the view
    // then keeps the Task-declared name, the file route, and its table URL. The join
    // is the exact published path, so an artifact no logical file publishes keeps its
    // own path -- that path is its identity, not a name to be shortened.
    const logical = new Map<string, LogicalResultFile>();
    for (const files of Object.values(this.manifest?.result?.files || {})) {
      for (const file of files) if (!logical.has(file.path)) logical.set(file.path, file);
    }
    const sources: ResolvedViewSources = {};
    for (const [name, paths] of Object.entries(view.sources || {})) {
      sources[name] = (paths || []).flatMap((path) => logical.get(path) || byPath.get(path) || []);
    }
    return sources;
  }

  // A view's candidate is not the page's structure: it opens in a view-owned stage,
  // with its own viewer and toolbar, so mounting one leaves the page's stage drawn.
  // The one suppression that remains is a structure the page already draws.
  private rendererContext(signal: AbortSignal): RendererContext {
    const structure = this.viewStructure
      || (this.viewStructure = new StructureController(this.createViewer, { selectionEnabled: true, controlsCollapsed: true }));
    return { signal, taskId: this.taskId, localSource: this.local ?? undefined,
      openStructure: (artifact, host) => this.renderStructure(artifact, host, structure),
      closeStructure: (host) => structure.disposeIfIn(host), selectStructure: (selection) => structure.select(selection),
      drawsStructure: (artifact) => this.storyboardStructure !== null
        && this.storyboardStructure.path === artifact.path };
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
    this.storyboardStructureGeneration += 1; this.storyboardStructure = null;
    if ((this.nodes.rail as HTMLDialogElement).open) (this.nodes.rail as HTMLDialogElement).close();
    this.destroyViewRenderer(); this.geometry.dispose(); this.storyboard.destroy(); this.cancelRender(); this.structure.dispose(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact);
    this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.setAttribute('download', downloadName(artifact)); this.nodes.download.title = fileName;
    this.nodes.download.textContent = t('results.downloadNamed', { name: localName(fileName) });
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { this.viewRenderer = (await renderer.render(view, sources, this.nodes.preview, this.rendererContext(controller.signal))) || null; }
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

  private destroyViewRenderer(): void {
    this.viewRenderer?.destroy(); this.viewRenderer = null;
    this.viewStructure?.dispose(); this.viewStructure = null;
  }

  private async openStoryboard(): Promise<void> {
    const manifest = this.manifest; if (!manifest?.storyboard) return;
    const generation = ++this.previewGeneration;
    this.storyboardStructureGeneration += 1; this.storyboardStructure = null;
    this.destroyViewRenderer(); this.cancelRender(); this.structure.dispose(); this.geometry.dispose(); this.nodes.preview.setAttribute('aria-busy', 'true');
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
    try {
      await this.renderStructure(file, panel, this.structure);
      // Only a mount that actually landed makes this the structure the page draws;
      // a failed mount must not suppress the declared view's own stage.
      if (generation === this.storyboardStructureGeneration) { this.storyboardStructure = file; panel.dataset.ready = 'true'; }
    }
    catch (error) {
      if (generation !== this.storyboardStructureGeneration || (error as Error).name === 'AbortError') return;
      this.structure.dispose(); panel.replaceChildren(element('p', 'result-empty', (error as Error).message || t('results.structureUnavailable')));
    } finally { if (generation === this.storyboardStructureGeneration && !controller.signal.aborted) panel.setAttribute('aria-busy', 'false'); }
  }

  async openArtifact(artifact: ResultFile, requestedGeneration?: number): Promise<void> {
    const generation = requestedGeneration ?? ++this.previewGeneration;
    this.storyboardStructureGeneration += 1; this.storyboardStructure = null;
    if ((this.nodes.rail as HTMLDialogElement).open) (this.nodes.rail as HTMLDialogElement).close();
    this.destroyViewRenderer(); this.geometry.dispose(); this.storyboard.destroy(); this.cancelRender(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact); this.nodes.previewTitle.textContent = localName(fileName); this.nodes.previewDescription.textContent = formatBytes(artifact.size);
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.setAttribute('download', downloadName(artifact)); this.nodes.download.title = fileName;
    this.nodes.download.textContent = t('results.downloadNamed', { name: localName(fileName) });
    const renderer = this.rendererRegistry.resolve(artifact); if (!renderer) { this.renderPreviewError(t('results.noInlinePreview')); return; }
    if (artifactCapability(artifact) !== 'structure' && artifactCapability(artifact) !== 'molecular_structure') this.structure.dispose();
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { await renderer.render(artifact, this.nodes.preview, { signal: controller.signal, taskId: this.taskId, localSource: this.local ?? undefined }); }
    catch (error) { if ((error as Error).name !== 'AbortError' && generation === this.previewGeneration) this.renderPreviewError((error as Error).message || t('results.previewFailed')); }
    finally { if (!controller.signal.aborted && generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async renderStructure(artifact: ResultFile, host: HTMLElement, controller: StructureController): Promise<void> {
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
    // The page stage puts its toolbar in the storyboard's own shelf; a view stage
    // keeps its toolbar in its own viewport, so the controls drive its own viewer.
    const shelf = controller === this.structure ? this.nodes.preview.querySelector<HTMLElement>('[data-structure-tools]') : null;
    if (shelf) shelf.replaceChildren(this.structureToolbar(artifact, viewport, controller));
    else viewport.prepend(this.structureToolbar(artifact, viewport, controller));
    await controller.mount(viewerHost, artifact, controller === this.structure ? this.structureTheme : this.viewStructureTheme);
  }

  private structureToolbar(artifact: ResultFile, viewport: HTMLElement, owner: StructureController): HTMLElement {
    const own = owner === this.structure;
    const toolbar = element('div', 'structure-toolbar'); toolbar.setAttribute('role', 'toolbar'); toolbar.setAttribute('aria-label', t('results.structure.controls'));
    const representations: Array<[string, string]> = [['cartoon', t('results.structure.cartoon')], ['cartoon_ligand', t('results.structure.cartoonLigand')], ['sticks', t('results.structure.sticks')], ['surface_ligand', t('results.structure.surface')]];
    const selectControl = (label: string, options: Array<[string, string]>, value: string, changed: (value: string) => void): HTMLElement => {
      const field = element('label', 'structure-tool-field', label); const select = element('select');
      for (const [id, title] of options) select.append(new Option(title, id, false, id === value));
      select.addEventListener('change', () => changed(select.value)); field.append(select); return field;
    };
    const representationGroup = selectControl(t('results.structure.representation'), representations, own ? this.structureRepresentation : this.viewStructureRepresentation, value => {
      if (own) this.structureRepresentation = value; else this.viewStructureRepresentation = value;
      void owner.setRepresentation(value);
    });
    const colours: Array<[string, string]> = [['rainbow', t('results.structure.sequence')], ['chain', t('results.structure.chain')]];
    if ('confidence_encoding' in artifact && artifact.confidence_encoding) colours.push(['confidence', t('results.structure.confidence')]);
    if ((own ? this.structureColor : this.viewStructureColor) === 'confidence' && colours.length === 2) {
      if (own) this.structureColor = 'rainbow'; else this.viewStructureColor = 'rainbow';
    }
    const colorGroup = selectControl(t('results.structure.colour'), colours, own ? this.structureColor : this.viewStructureColor, value => {
      if (own) this.structureColor = value; else this.viewStructureColor = value;
      void owner.setColor(value); const legend = this.nodes.preview.querySelector<HTMLElement>('[data-structure-legend]'); if (legend) legend.textContent = value === 'rainbow' ? 'Sequence N → C' : colours.find(([id]) => id === value)?.[1] || value;
    });
    const actions = element('div', 'structure-toolbar-actions');
    const reset = element('button', 'result-button result-button-small', t('results.structure.whole')) as HTMLButtonElement; reset.type = 'button'; reset.title = t('results.structure.whole'); reset.setAttribute('aria-label', t('results.structure.whole')); reset.addEventListener('click', () => { owner.resetCamera(); viewport.closest('[data-molecular-workspace]')?.dispatchEvent(new Event('structure-reset')); });
    const themeButton = element('button', 'result-button result-button-small') as HTMLButtonElement; themeButton.type = 'button';
    const syncThemeButton = (): void => { const dark = (own ? this.structureTheme : this.viewStructureTheme) === 'dark'; themeButton.textContent = dark ? t('results.structure.lightCanvas') : t('results.structure.darkCanvas'); themeButton.setAttribute('aria-pressed', String(dark)); };
    syncThemeButton(); themeButton.addEventListener('click', () => {
      if (own) this.structureTheme = this.structureTheme === 'dark' ? 'light' : 'dark'; else this.viewStructureTheme = this.viewStructureTheme === 'dark' ? 'light' : 'dark';
      owner.setTheme(own ? this.structureTheme : this.viewStructureTheme); syncThemeButton();
    });
    const image = element('button', 'result-button result-button-small', t('results.structure.savePng')) as HTMLButtonElement; image.type = 'button'; image.addEventListener('click', async () => beginDownload(await owner.captureImage()));
    const source = element('button', 'result-button result-button-small', t('results.download')) as HTMLButtonElement; source.type = 'button'; source.addEventListener('click', () => beginDownload(downloadUrl(artifact), downloadName(artifact)));
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
    const download = element('a', 'result-file-download') as HTMLAnchorElement; download.href = downloadUrl(artifact); download.setAttribute('download', downloadName(artifact)); download.title = t('results.fileDownload', { name: artifact.path }); download.setAttribute('aria-label', t('results.fileDownload', { name: artifact.path })); setButtonIcon(download, 'Download');
    row.append(open, download); return row;
  }

  private renderRecord(): void {
    const manifest = this.manifest; if (!manifest) return; this.nodes.limitations.replaceChildren(); this.nodes.run.replaceChildren();
    if (manifest.limitations?.length) { const title = element('h2', '', t('results.limitations')); const list = element('ul'); manifest.limitations.forEach((text) => list.append(element('li', '', text))); this.nodes.limitations.append(title, list); }
    const exported = this.local?.sourceTaskId;
    const values: Array<[string, string]> = [exported
      ? [t('results.local.exportedFrom'), exported]
      : [t('dashboard.card.taskId'), manifest.task_id], [t('results.run.submitted'), manifest.run?.submitted_at || '-'], [t('results.run.started'), manifest.run?.started_at || '-'], [t('results.run.finished'), manifest.run?.finished_at || '-']];
    manifest.run?.inputs?.forEach((input) => values.push([input.role ? t('results.run.inputRole', { role: input.role }) : t('results.run.input'), `${input.path} [${input.sha256.slice(0, 12)}]`]));
    manifest.run?.parameters?.forEach((parameter) => values.push([parameter.label, `${String(parameter.value)}${parameter.unit ? ` ${parameter.unit}` : ''}`]));
    const title = element('h2', '', t('results.run.title')); const list = element('dl', 'result-definition-list');
    values.forEach(([term, value]) => list.append(element('dt', '', term), element('dd', '', value))); this.nodes.run.append(title, list);
    if (manifest.run?.citations?.length) { const citations = element('ul', 'result-citations'); manifest.run.citations.forEach((citation) => { const item = element('li');
      const href = citationHref(citation);
      if (href) { const link = element('a', '', citation.title) as HTMLAnchorElement; link.href = href; link.rel = 'noopener noreferrer'; item.append(link); } else item.textContent = citation.title; citations.append(item); }); this.nodes.run.append(citations); }
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
    // A local result has no Server archive to prepare or download: the folder is the archive.
    if (this.local) { this.nodes.archive.hidden = true; return; }
    const archive = this.manifest?.archive;
    if (archive?.ready && archive.download_url) {
      this.archiveBusy = false;
      if (this.archiveTimer != null) clearTimeout(this.archiveTimer);
      this.archiveTimer = null;
      this.nodes.archiveStatus.textContent = t('results.archiveReady');
      this.nodes.archiveStatus.dataset.error = 'false';
    }
    const available = Boolean(archive?.request_url || archive?.download_url);
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
    this.resize();
  };
  private selectArtifact(artifact: ResultFile): void {
    // Rows are keyed by published path, so selection is matched by the same identity
    // the initial paint uses — never by the name a reader sees.
    this.selected = artifact; const path = artifact.path;
    this.nodes.fileList.querySelectorAll<HTMLElement>('[data-artifact-path]').forEach((node) => node.setAttribute('aria-current', String(node.dataset.artifactPath === path)));
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
  private resetPreview(): void { this.storyboardStructureGeneration += 1; this.storyboardStructure = null; this.destroyViewRenderer(); this.cancelRender(); this.storyboard.destroy(); this.structure.dispose(); this.geometry.dispose(); }

  destroy(): void {
    if (this.disposed) return; this.disposed = true; this.destroyViewRenderer(); this.cancelRender(); this.loadController?.abort(); this.storyboard.destroy(); this.structure.dispose(); this.geometry.dispose();
    this.diagnosticController?.abort();
    if (this.poll != null) clearInterval(this.poll); if (this.archiveTimer != null) clearTimeout(this.archiveTimer); this.listeners.abort(); this.root.replaceChildren();
  }
}
