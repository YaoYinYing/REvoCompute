import { ApiError, beginDownload, downloadUrl, loadAuthorizedResult, requestResultArchive, taskIdFromLocation } from '../../api/result-api';
import { resultFileName, type ArtifactRole, type LogicalResultFile, type ResultArtifact, type ResultFile, type ResultManifest,
  type ResultView, type TaskStatus } from '../../api/result-types';
import { setButtonIcon } from '../../components/icons';
import { buildArtifactTree, filterArtifacts, localName, type ArtifactTreeNode } from './artifact-tree';
import { artifactCapability, createBasicRenderers, RendererRegistry, ViewRendererRegistry } from './renderer-registry';
import { createMatrixViewRenderer } from './matrix-view';
import type { MolecularViewerFactory } from './molecular/viewer-contract';
import { StructureController } from './molecular/structure-controller';
import { installScientificPrimitives } from './scientific';
import { StoryboardHost } from './storyboard-host';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node;
}
function formatBytes(value = 0): string {
  if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`; return `${(value / 1024 ** 3).toFixed(2)} GiB`;
}
function theme(): 'light' | 'dark' { return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'; }
// Manifest-declared artifact role → user-facing wording and rail grouping. The vocabulary is the server's; only its projection is here.
// Manifest-declared artifact role → rail grouping. The vocabulary is the server's; only its
// projection is here. A file row states type and size, not which group it already sits in.
const ARTIFACT_ROLE_GROUPS: Array<{ label: string; roles: ArtifactRole[] }> = [
  { label: 'Results', roles: ['primary'] },
  { label: 'Supporting files', roles: ['evidence', 'provenance'] },
  { label: 'Diagnostics', roles: ['diagnostic'] },
  { label: 'Other files', roles: ['artifact'] },
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
  fileList: HTMLElement; integrity: HTMLElement; artifactSummary: HTMLElement; archive: HTMLButtonElement;
  limitations: HTMLElement; run: HTMLElement; toast: HTMLElement;
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
  private renderController: AbortController | null = null;
  private loadController: AbortController | null = null;
  private poll: number | null = null;
  private disposed = false;
  private previewGeneration = 0;
  private storyboardStructureGeneration = 0;
  private structureRepresentation = 'cartoon';
  private structureColor = 'chain';
  private structureTheme = theme();
  private readonly directoryExpansion = new Map<string, boolean>();
  private readonly listeners = new AbortController();
  private readonly railMedia = matchMedia('(max-width: 64rem)');

  constructor(private readonly root: HTMLElement, createViewer: MolecularViewerFactory) {
    installScientificPrimitives(); this.structure = new StructureController(createViewer, {
      selectionEnabled: true, onSelectionChanged: (residues) => this.storyboard.setMolecularSelection(residues),
    });
    this.nodes = this.buildShell(); this.storyboard = new StoryboardHost(this.nodes.preview, {
      openFile: (file) => this.openLogicalFile(file), downloadFile: (file) => beginDownload(file.url),
      openView: (viewId) => this.openViewById(viewId),
      focusStructure: (selection) => this.structure.focus(selection), selectStructure: (selection) => this.structure.select(selection),
    });
    createBasicRenderers().forEach((renderer) => this.rendererRegistry.register(renderer));
    this.rendererRegistry.register({ id: 'structure', render: (artifact, host) => this.renderStructure(artifact, host) });
    this.viewRenderers.register(createMatrixViewRenderer());
    this.bind();
  }

  async load(): Promise<this> {
    this.loadController?.abort(); this.loadController = new AbortController();
    this.setState('Loading result', 'Reading the authorized result manifest.');
    try {
      const result = await loadAuthorizedResult(this.taskId, this.loadController.signal);
      if (!isResultManifest(result)) { this.renderPending(result); return this; }
      this.manifest = result; this.renderManifest(result);
    } catch (error) {
      if ((error as Error).name === 'AbortError') return this;
      if (error instanceof ApiError && error.status === 401) {
        location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname)}`); return this;
      }
      this.renderFatal((error as Error).message || 'This result is unavailable.');
    }
    return this;
  }

  private buildShell(): WorkspaceNodes {
    this.root.replaceChildren(); const page = element('main', 'result-app');
    const header = element('header', 'result-header'); const identity = element('div', 'result-identity');
    const methodRow = element('p', 'result-method-row');
    const outcome = element('span', 'result-outcome'); outcome.hidden = true; methodRow.append(outcome);
    const title = element('h1', '', `Task ${this.taskId}`);
    const meta = element('p', 'result-meta', this.taskId); identity.append(methodRow, title, meta);
    const actions = element('div', 'result-header-actions'); const dashboard = element('a', 'result-button', 'Dashboard'); dashboard.href = '/compute/dashboard';
    const refresh = element('button', 'result-icon-button') as HTMLButtonElement; refresh.type = 'button'; refresh.title = 'Refresh result'; refresh.setAttribute('aria-label', 'Refresh result'); setButtonIcon(refresh, 'RefreshCw');
    refresh.addEventListener('click', () => void this.load()); actions.append(dashboard, refresh); header.append(identity, actions);
    const status = element('section', 'result-status'); status.setAttribute('aria-live', 'polite');
    const workspace = element('section', 'result-workspace'); const main = element('article', 'result-main');
    const tabs = element('nav', 'result-tabs'); tabs.setAttribute('aria-label', 'Result views');
    const previewHead = element('header', 'result-preview-header'); const copy = element('div');
    const previewTitle = element('h2', '', 'Result'); const previewDescription = element('p', 'result-muted'); copy.append(previewTitle, previewDescription);
    const download = element('a', 'result-button result-button-small', 'Download') as HTMLAnchorElement; download.hidden = true; download.download = '';
    previewHead.append(copy, download); const preview = element('div', 'result-preview'); preview.setAttribute('aria-busy', 'false'); main.append(tabs, previewHead, preview);
    const rail = element('aside', 'result-rail'); rail.setAttribute('aria-label', 'Files and diagnostics');
    const reopen = element('button', 'result-rail-reopen', 'Files') as HTMLButtonElement; reopen.type = 'button'; reopen.hidden = true; reopen.setAttribute('aria-label', 'Open Files and diagnostics');
    const railDetails = element('details', 'result-files') as HTMLDetailsElement; railDetails.open = true;
    const summary = element('summary', '', 'Files & diagnostics '); const artifactSummary = element('span', 'result-muted'); summary.append(artifactSummary);
    const tools = element('div', 'result-file-tools'); const search = element('input', 'result-search') as HTMLInputElement;
    search.type = 'search'; search.placeholder = 'Filter files'; search.setAttribute('aria-label', 'Filter result artifacts');
    const archive = element('button', 'result-button result-button-small', 'Create ZIP') as HTMLButtonElement; archive.type = 'button'; archive.hidden = true;
    tools.append(search, archive);
    const fileList = element('nav', 'result-file-list'); fileList.setAttribute('aria-label', 'Result artifacts');
    const integrity = element('div'); railDetails.append(summary, tools, fileList, integrity); rail.append(reopen, railDetails);
    workspace.append(main, rail); const record = element('section', 'result-record'); const limitations = element('div'); const run = element('div'); record.append(limitations, run);
    const toast = element('aside', 'result-toasts'); toast.setAttribute('aria-live', 'polite'); page.append(header, status, workspace, record, toast); this.root.append(page);
    return { status, outcome, title, meta, tabs, previewTitle, previewDescription, preview, download, rail, railDetails, reopen, search, fileList, integrity, artifactSummary, archive, limitations, run, toast };
  }

  private bind(): void {
    const options = { signal: this.listeners.signal };
    this.nodes.search.addEventListener('input', () => this.renderFiles(), options);
    this.nodes.railDetails.addEventListener('toggle', () => this.syncRail(), options);
    this.nodes.reopen.addEventListener('click', () => { this.nodes.railDetails.open = true; this.syncRail(); }, options);
    this.nodes.archive.addEventListener('click', () => void this.archiveAction(), options);
    document.addEventListener('fullscreenchange', this.resize, options); window.addEventListener('resize', this.resize, options);
    window.addEventListener('pagehide', this.pagehide, options); window.addEventListener('pageshow', this.pageshow, options);
    this.railMedia.addEventListener('change', this.syncRail, options); this.syncRail();
  }

  private readonly resize = (): void => this.structure.resize();
  private readonly pagehide = (event: PageTransitionEvent): void => { if (!event.persisted) this.destroy(); };
  private readonly pageshow = (event: PageTransitionEvent): void => { if (event.persisted) this.structure.resize(); };

  private renderPending(payload: TaskStatus): void {
    const terminal = payload.terminal === true; const status = payload.status || 'running';
    if (terminal && this.poll != null) { clearInterval(this.poll); this.poll = null; }
    this.nodes.title.textContent = payload.display_name || `Task ${this.taskId}`;
    this.setState(status, terminal ? (payload.error || payload.message || 'No published result manifest is available.') : (payload.message || 'The task is still running. This page updates automatically.'));
    this.resetPreview();
    this.nodes.preview.replaceChildren(element('p', 'result-empty', terminal ? 'No result artifacts were published.' : 'Waiting for result artifacts.'));
    if (!terminal && this.poll == null) this.poll = window.setInterval(() => void this.load(), 15_000);
  }

  private renderManifest(manifest: ResultManifest): void {
    if (this.poll != null) { clearInterval(this.poll); this.poll = null; }
    // Identity, not storage: the method word plus the task hash. A published file name is a
    // storage artifact and a runner's generic output summary repeats what the views already show.
    this.nodes.title.textContent = manifest.run?.method?.name || manifest.task_type || 'Scientific result';
    this.nodes.meta.textContent = `Task ${manifest.task_id}`; this.nodes.meta.title = `Task ID ${manifest.task_id}`;
    const quiet = isQuietOutcome(manifest);
    this.setState(quiet ? manifest.status : manifest.outcome || manifest.status, manifest.error || '', quiet);
    // The summary is rendered by renderFiles(), which owns the filtered view.
    this.renderFiles(); this.renderTabs(); this.renderRecord(); this.syncArchive();
    if (manifest.storyboard?.entrypoint_url) void this.openStoryboard();
    else {
      // The declared primary view opens the page; a manifest that declares no primary
      // view keeps the generic first-artifact preview.
      const primary = (manifest.views || []).find((view) => view.role === 'primary');
      if (primary) void this.openView(primary);
      else { const artifact = this.primaryArtifact(); if (artifact) void this.openArtifact(artifact); else this.renderEmpty(); }
    }
  }

  private primaryArtifact(): ResultArtifact | null {
    const artifacts = this.manifest?.artifacts || [];
    const view = this.manifest?.views?.find((item) => item.role === 'primary');
    const path = view ? this.artifactForView(view)?.path : null;
    return artifacts.find((artifact) => artifact.path === path) || artifacts.find((artifact) => artifact.role === 'primary') || artifacts[0] || null;
  }

  private renderTabs(): void {
    this.nodes.tabs.replaceChildren(); const manifest = this.manifest; if (!manifest) return;
    if (manifest.storyboard?.entrypoint_url) this.nodes.tabs.append(this.tab('Scientific result', 'storyboard', () => void this.openStoryboard()));
    (manifest.views || []).forEach((view) => this.nodes.tabs.append(this.tab(view.title, view.id, () => void this.openView(view))));
  }
  private tab(label: string, id: string, action: () => void): HTMLButtonElement {
    const button = element('button', 'result-tab', label) as HTMLButtonElement; button.type = 'button'; button.dataset.view = id;
    button.setAttribute('aria-pressed', 'false'); button.addEventListener('click', action); return button;
  }
  private markTab(id: string | null): void { this.nodes.tabs.querySelectorAll<HTMLElement>('[data-view]').forEach((tab) => tab.setAttribute('aria-pressed', tab.dataset.view === id ? 'true' : 'false')); }

  private async openView(view: ResultView): Promise<void> {
    const generation = ++this.previewGeneration;
    const artifact = this.artifactForView(view);
    if (!artifact) { this.renderPreviewError('This view has no available artifact.'); return; }
    await this.renderView(view, artifact, generation); if (generation !== this.previewGeneration) return;
    this.markTab(view.id);
  }

  private artifactForView(view: ResultView): ResultArtifact | null {
    const path = Object.values(view.sources || {}).flat()[0];
    return this.manifest?.artifacts.find((item) => item.path === path) || null;
  }

  private openViewById(viewId: string): Promise<void> {
    const view = this.manifest?.views?.find((item) => item.id === viewId);
    return view ? this.openView(view) : Promise.resolve();
  }

  // A view is rendered by its declared `plugin`. A declared view primitive that cannot load
  // (no table, malformed data, over budget, request failure) states the reason and falls back
  // to the generic artifact renderer, so a view is never blanker than its source artifact.
  private async renderView(view: ResultView, artifact: ResultFile, generation: number): Promise<void> {
    const renderer = this.viewRenderers.resolve(view);
    if (!renderer) { await this.openArtifact(artifact, generation); return; }
    this.storyboardStructureGeneration += 1;
    this.storyboard.destroy(); this.cancelRender(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact);
    this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || '';
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.title = fileName;
    this.nodes.download.textContent = `Download ${localName(fileName)}`;
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { await renderer.render(view, artifact, this.nodes.preview, { signal: controller.signal, taskId: this.taskId }); }
    catch (error) {
      if ((error as Error).name === 'AbortError' || generation !== this.previewGeneration) return;
      await this.renderViewFallback(artifact, generation, (error as Error).message || 'This view could not be rendered.');
    }
    finally { if (!controller.signal.aborted && generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async renderViewFallback(artifact: ResultFile, generation: number, reason: string): Promise<void> {
    if (generation !== this.previewGeneration) return;
    await this.openArtifact(artifact, generation);
    if (generation !== this.previewGeneration) return;
    this.nodes.preview.prepend(element('p', 'result-note', `View shown as a plain artifact instead: ${reason}`));
  }

  private async openStoryboard(): Promise<void> {
    const manifest = this.manifest; if (!manifest?.storyboard) return;
    const generation = ++this.previewGeneration;
    this.storyboardStructureGeneration += 1; this.cancelRender(); this.structure.dispose(); this.nodes.preview.setAttribute('aria-busy', 'true');
    this.nodes.previewTitle.textContent = 'Scientific result'; this.nodes.previewDescription.textContent = ''; this.nodes.download.hidden = true;
    try { const current = await this.storyboard.mount(manifest.storyboard, manifest); if (current && generation === this.previewGeneration) this.markTab('storyboard'); }
    catch (error) { if (generation === this.previewGeneration) this.renderPreviewError((error as Error).message || 'Scientific result view unavailable.'); }
    finally { if (generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async openLogicalFile(file: LogicalResultFile): Promise<void> {
    const capability = artifactCapability(file);
    if (capability !== 'structure' && capability !== 'molecular_structure') return this.openArtifact(file);
    const generation = ++this.storyboardStructureGeneration;
    this.cancelRender(); const controller = new AbortController(); this.renderController = controller;
    this.selectArtifact(file);
    let panel = this.nodes.preview.querySelector<HTMLElement>(':scope > .storyboard-structure-panel');
    if (!panel) { panel = element('section', 'storyboard-structure-panel'); this.nodes.preview.append(panel); }
    panel.setAttribute('aria-busy', 'true');
    try { await this.renderStructure(file, panel); if (generation === this.storyboardStructureGeneration) panel.dataset.ready = 'true'; }
    catch (error) {
      if (generation !== this.storyboardStructureGeneration || (error as Error).name === 'AbortError') return;
      this.structure.dispose(); panel.replaceChildren(element('p', 'result-empty', (error as Error).message || 'Structure preview unavailable.'));
    } finally { if (generation === this.storyboardStructureGeneration && !controller.signal.aborted) panel.setAttribute('aria-busy', 'false'); }
  }

  async openArtifact(artifact: ResultFile, requestedGeneration?: number): Promise<void> {
    const generation = requestedGeneration ?? ++this.previewGeneration;
    this.storyboardStructureGeneration += 1;
    this.storyboard.destroy(); this.cancelRender(); this.selectArtifact(artifact); this.markTab(null);
    const fileName = resultFileName(artifact); this.nodes.previewTitle.textContent = localName(fileName); this.nodes.previewDescription.textContent = formatBytes(artifact.size);
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.title = fileName;
    this.nodes.download.textContent = `Download ${localName(fileName)}`;
    const renderer = this.rendererRegistry.resolve(artifact); if (!renderer) { this.renderPreviewError('No inline preview is available.'); return; }
    if (artifactCapability(artifact) !== 'structure' && artifactCapability(artifact) !== 'molecular_structure') this.structure.dispose();
    const controller = new AbortController(); this.renderController = controller; this.nodes.preview.setAttribute('aria-busy', 'true');
    try { await renderer.render(artifact, this.nodes.preview, { signal: controller.signal, taskId: this.taskId }); }
    catch (error) { if ((error as Error).name !== 'AbortError' && generation === this.previewGeneration) this.renderPreviewError((error as Error).message || 'Preview unavailable.'); }
    finally { if (!controller.signal.aborted && generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private async renderStructure(artifact: ResultFile, host: HTMLElement): Promise<void> {
    let viewport = host.querySelector<HTMLElement>('.structure-viewport'); let viewerHost = viewport?.querySelector<HTMLElement>('.structure-host');
    if (!viewport || !viewerHost) {
      viewport = element('section', 'structure-viewport');
      viewerHost = element('div', 'structure-host'); viewerHost.setAttribute('role', 'img'); viewerHost.setAttribute('aria-label', 'Molecular structure viewer');
      viewport.append(viewerHost); host.replaceChildren(viewport);
    }
    viewport.querySelector('.structure-toolbar')?.remove(); viewport.prepend(this.structureToolbar(artifact, viewport));
    await this.structure.mount(viewerHost, artifact, this.structureTheme);
  }

  private structureToolbar(artifact: ResultFile, viewport: HTMLElement): HTMLElement {
    const toolbar = element('div', 'structure-toolbar'); toolbar.setAttribute('role', 'toolbar'); toolbar.setAttribute('aria-label', 'Structure viewer controls');
    const representations: Array<[string, string]> = [['cartoon', 'Cartoon'], ['cartoon_ligand', 'Cartoon + ligand'], ['sticks', 'Sticks'], ['surface_ligand', 'Surface']];
    const representationGroup = element('div', 'structure-mode-group'); representationGroup.setAttribute('role', 'group'); representationGroup.setAttribute('aria-label', 'Structure representation');
    representations.forEach(([id, label]) => { const button = element('button', 'result-button result-button-small', label) as HTMLButtonElement; button.type = 'button'; button.setAttribute('aria-pressed', String(this.structureRepresentation === id)); button.addEventListener('click', () => { this.structureRepresentation = id; representationGroup.querySelectorAll('button').forEach((node) => node.setAttribute('aria-pressed', String(node === button))); void this.structure.setRepresentation(id); }); representationGroup.append(button); });
    const colours: Array<[string, string]> = [['chain', 'Chain'], ['rainbow', 'Sequence'], ['confidence', 'Confidence']];
    if (this.structureColor === 'confidence' && !('confidence_encoding' in artifact && artifact.confidence_encoding)) this.structureColor = 'chain';
    const colorGroup = element('div', 'structure-mode-group'); colorGroup.setAttribute('role', 'group'); colorGroup.setAttribute('aria-label', 'Structure colour');
    colours.forEach(([id, label]) => { if (id === 'confidence' && !('confidence_encoding' in artifact && artifact.confidence_encoding)) return; const button = element('button', 'result-button result-button-small', label) as HTMLButtonElement; button.type = 'button'; button.setAttribute('aria-pressed', String(this.structureColor === id)); button.addEventListener('click', () => { this.structureColor = id; colorGroup.querySelectorAll('button').forEach((node) => node.setAttribute('aria-pressed', String(node === button))); void this.structure.setColor(id); }); colorGroup.append(button); });
    const actions = element('div', 'structure-toolbar-actions');
    const reset = element('button', 'result-icon-button') as HTMLButtonElement; reset.type = 'button'; reset.title = 'Reset view'; reset.setAttribute('aria-label', 'Reset view'); setButtonIcon(reset, 'RefreshCw'); reset.addEventListener('click', () => this.structure.resetCamera());
    const themeButton = element('button', 'result-button result-button-small') as HTMLButtonElement; themeButton.type = 'button';
    const syncThemeButton = (): void => { const dark = this.structureTheme === 'dark'; themeButton.textContent = dark ? 'Light canvas' : 'Dark canvas'; themeButton.setAttribute('aria-pressed', String(dark)); };
    syncThemeButton(); themeButton.addEventListener('click', () => { this.structureTheme = this.structureTheme === 'dark' ? 'light' : 'dark'; this.structure.setTheme(this.structureTheme); syncThemeButton(); });
    const image = element('button', 'result-button result-button-small', 'Save PNG') as HTMLButtonElement; image.type = 'button'; image.addEventListener('click', async () => beginDownload(await this.structure.captureImage()));
    const source = element('button', 'result-button result-button-small', 'Download') as HTMLButtonElement; source.type = 'button'; source.addEventListener('click', () => beginDownload(downloadUrl(artifact)));
    const fullscreen = element('button', 'result-icon-button') as HTMLButtonElement; fullscreen.type = 'button';
    const syncFullscreen = (): void => { const expanded = document.fullscreenElement === viewport; const label = expanded ? 'Exit fullscreen' : 'Enter fullscreen'; fullscreen.title = label; fullscreen.setAttribute('aria-label', label); fullscreen.setAttribute('aria-pressed', String(expanded)); setButtonIcon(fullscreen, expanded ? 'Minimize' : 'Expand'); };
    syncFullscreen();
    fullscreen.addEventListener('click', async () => { if (document.fullscreenElement === viewport) await document.exitFullscreen(); else await viewport.requestFullscreen(); });
    const controller = this.renderController; if (controller) document.addEventListener('fullscreenchange', syncFullscreen, { signal: controller.signal });
    actions.append(reset, themeButton, image, source, fullscreen);
    toolbar.append(representationGroup, colorGroup, actions);
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
      ? `${artifacts.length} of ${this.manifest?.artifacts.length} files · ${formatBytes(size)}`
      : `${artifacts.length} files · ${formatBytes(size)}`;
    this.nodes.fileList.replaceChildren();
    const renderNode = (node: ArtifactTreeNode, target: HTMLElement, group: string): void => {
      node.directories.forEach((directory) => { const details = element('details', 'result-directory') as HTMLDetailsElement;
        const key = `${group}/${directory.path}`;
        details.open = this.directoryExpansion.get(key) ?? true;
        details.addEventListener('toggle', () => this.directoryExpansion.set(key, details.open));
        const summary = element('summary', '', directory.name); const children = element('div', 'result-directory-children'); details.append(summary, children); target.append(details); renderNode(directory, children, group); });
      node.artifacts.forEach((artifact) => target.append(this.fileRow(artifact)));
    };
    // The scientific list comes first, grouped by the manifest-declared artifact role; the raw directory tree stays inside each group.
    ARTIFACT_ROLE_GROUPS.forEach(({ label, roles }) => { const members = artifacts.filter((artifact) => roles.includes(artifact.role)); if (!members.length) return;
      const section = element('section', 'result-file-group'); section.append(element('h3', '', label)); const list = element('div'); section.append(list); this.nodes.fileList.append(section);
      renderNode(buildArtifactTree(members), list, label); });
    if (!artifacts.length) this.nodes.fileList.append(element('p', 'result-empty', 'No files match this filter.'));
  }

  private fileRow(artifact: ResultArtifact): HTMLElement {
    const row = element('div', 'result-file-row'); const open = element('button', 'result-file-open') as HTMLButtonElement; open.type = 'button';
    open.dataset.artifactPath = artifact.path; open.title = artifact.path; const name = element('strong', '', localName(artifact.path));
    const selectedPath = this.selected && 'path' in this.selected ? this.selected.path : null;
    open.setAttribute('aria-current', String(selectedPath === artifact.path));
    const meta = element('span', '', formatBytes(artifact.size)); open.append(name, meta); open.addEventListener('click', () => void this.openArtifact(artifact));
    const download = element('a', 'result-file-download') as HTMLAnchorElement; download.href = downloadUrl(artifact); download.download = ''; download.title = `Download ${artifact.path}`; download.setAttribute('aria-label', `Download ${artifact.path}`); setButtonIcon(download, 'Download');
    row.append(open, download); return row;
  }

  private renderRecord(): void {
    const manifest = this.manifest; if (!manifest) return; this.nodes.limitations.replaceChildren(); this.nodes.run.replaceChildren();
    if (manifest.limitations?.length) { const title = element('h2', '', 'Limitations'); const list = element('ul'); manifest.limitations.forEach((text) => list.append(element('li', '', text))); this.nodes.limitations.append(title, list); }
    const values: Array<[string, string]> = [['Submitted', manifest.run?.submitted_at || '-'], ['Started', manifest.run?.started_at || '-'], ['Finished', manifest.run?.finished_at || '-']];
    manifest.run?.inputs?.forEach((input) => values.push([`Input${input.role ? ` (${input.role})` : ''}`, `${input.path} [${input.sha256.slice(0, 12)}]`]));
    manifest.run?.parameters?.forEach((parameter) => values.push([parameter.label, `${String(parameter.value)}${parameter.unit ? ` ${parameter.unit}` : ''}`]));
    const title = element('h2', '', 'Run setup and reproducibility'); const list = element('dl', 'result-definition-list');
    values.forEach(([term, value]) => list.append(element('dt', '', term), element('dd', '', value))); this.nodes.run.append(title, list);
    if (manifest.run?.citations?.length) { const citations = element('ul', 'result-citations'); manifest.run.citations.forEach((citation) => { const item = element('li');
      if (citation.url || citation.doi) { const link = element('a', '', citation.title) as HTMLAnchorElement; link.href = citation.url || `https://doi.org/${encodeURIComponent(citation.doi || '')}`; link.rel = 'noopener'; item.append(link); } else item.textContent = citation.title; citations.append(item); }); this.nodes.run.append(citations); }
  }

  private renderIntegrity(): void {
    const check = this.manifest?.output_check; this.nodes.integrity.replaceChildren(); if (!check || check.state === 'not_configured' || check.state === 'not_assessed') return;
    const passed = check.state === 'passed'; const section = element('section', 'result-integrity'); section.dataset.state = check.state;
    section.append(element('h3', '', 'Result integrity'), element('p', '', passed ? '✓ Declared artifacts present' : '✗ Declared artifacts incomplete'));
    const detail = check.problems?.length ? check.problems : (check.checks || []).filter((item) => item.status === 'failed').map((item) => item.file_id || item.source || item.view_id || 'Declared file');
    if (detail.length) { const list = element('ul'); detail.forEach((text) => list.append(element('li', '', String(text)))); section.append(list); }
    this.nodes.integrity.append(section);
  }

  private syncArchive(): void {
    const archive = this.manifest?.archive; const available = Boolean(archive?.request_url || archive?.download_url);
    this.nodes.archive.hidden = !available; this.nodes.archive.disabled = !available;
    this.nodes.archive.textContent = archive?.ready ? 'Download ZIP' : 'Create ZIP';
  }
  private async archiveAction(): Promise<void> {
    const archive = this.manifest?.archive; if (!archive) return;
    if (archive.ready && archive.download_url) { location.assign(archive.download_url); return; }
    if (!archive.request_url) return; this.nodes.archive.disabled = true;
    try { await requestResultArchive(archive.request_url); this.toast('Archive generation requested.'); }
    catch (error) { this.toast((error as Error).message || 'Archive request failed.', true); }
    finally { this.nodes.archive.disabled = false; }
  }

  private readonly syncRail = (): void => {
    const narrow = this.railMedia.matches; const collapsed = !narrow && !this.nodes.railDetails.open;
    this.root.querySelector('.result-app')?.classList.toggle('is-rail-collapsed', collapsed);
    this.nodes.rail.classList.toggle('is-collapsed', collapsed); this.nodes.railDetails.hidden = collapsed; this.nodes.reopen.hidden = !collapsed; this.structure.resize();
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
  private renderEmpty(): void { this.resetPreview(); this.nodes.preview.replaceChildren(element('p', 'result-empty', 'No previewable artifact was published. Download the files from Files & diagnostics.')); }
  private renderPreviewError(message: string): void { this.resetPreview(); this.nodes.preview.replaceChildren(element('p', 'result-empty', message)); this.nodes.preview.setAttribute('aria-busy', 'false'); }
  private renderFatal(message: string): void { this.setState('Result unavailable', message); this.renderPreviewError('Return to the dashboard or refresh after checking task access.'); }
  private toast(message: string, error = false): void { const node = element('div', `result-toast${error ? ' is-error' : ''}`, message); node.setAttribute('role', error ? 'alert' : 'status'); this.nodes.toast.append(node); setTimeout(() => node.remove(), 3600); }
  private cancelRender(): void { this.renderController?.abort(); this.renderController = null; }
  private resetPreview(): void { this.storyboardStructureGeneration += 1; this.cancelRender(); this.storyboard.destroy(); this.structure.dispose(); }

  destroy(): void {
    if (this.disposed) return; this.disposed = true; this.cancelRender(); this.loadController?.abort(); this.storyboard.destroy(); this.structure.dispose();
    if (this.poll != null) clearInterval(this.poll); this.listeners.abort(); this.root.replaceChildren();
  }
}
