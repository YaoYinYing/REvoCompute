import { ApiError, beginDownload, downloadUrl, loadAuthorizedResult, requestResultArchive, taskIdFromLocation } from '../../api/result-api';
import { resultFileName, type LogicalResultFile, type ResultArtifact, type ResultFile, type ResultManifest, type ResultView, type TaskStatus } from '../../api/result-types';
import { setButtonIcon } from '../../components/icons';
import { buildArtifactTree, filterArtifacts, localName, type ArtifactTreeNode } from './artifact-tree';
import { artifactCapability, createBasicRenderers, RendererRegistry } from './renderer-registry';
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
function isResultManifest(value: TaskStatus | ResultManifest): value is ResultManifest {
  return value.schema_version === 3 && Array.isArray(value.artifacts);
}

interface WorkspaceNodes {
  status: HTMLElement; method: HTMLElement; title: HTMLElement; meta: HTMLElement; tabs: HTMLElement;
  previewTitle: HTMLElement; previewDescription: HTMLElement; preview: HTMLElement; download: HTMLAnchorElement;
  rail: HTMLElement; railDetails: HTMLDetailsElement; reopen: HTMLButtonElement; search: HTMLInputElement;
  fileList: HTMLElement; artifactSummary: HTMLElement; archive: HTMLButtonElement; archiveState: HTMLElement;
  limitations: HTMLElement; run: HTMLElement; toast: HTMLElement;
}

export class ResultWorkspace {
  private readonly taskId = taskIdFromLocation();
  private readonly rendererRegistry = new RendererRegistry();
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
  private structureRepresentation = 'cartoon';
  private structureColor = 'chain';
  private readonly listeners = new AbortController();
  private readonly railMedia = matchMedia('(max-width: 64rem)');

  constructor(private readonly root: HTMLElement, createViewer: MolecularViewerFactory) {
    installScientificPrimitives(); this.structure = new StructureController(createViewer);
    this.nodes = this.buildShell(); this.storyboard = new StoryboardHost(this.nodes.preview, {
      openFile: (file) => this.openLogicalFile(file), downloadFile: (file) => beginDownload(file.url),
    });
    createBasicRenderers().forEach((renderer) => this.rendererRegistry.register(renderer));
    this.rendererRegistry.register({ id: 'structure', render: (artifact, host) => this.renderStructure(artifact, host) });
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
    const method = element('p', 'result-method', 'Result'); const title = element('h1', '', `Task ${this.taskId}`);
    const meta = element('p', 'result-meta', this.taskId); identity.append(method, title, meta);
    const actions = element('div', 'result-header-actions'); const dashboard = element('a', 'result-button', 'Dashboard'); dashboard.href = '/compute/dashboard';
    const refresh = element('button', 'result-icon-button') as HTMLButtonElement; refresh.type = 'button'; refresh.title = 'Refresh result'; refresh.setAttribute('aria-label', 'Refresh result'); setButtonIcon(refresh, 'RefreshCw');
    refresh.addEventListener('click', () => void this.load()); actions.append(dashboard, refresh); header.append(identity, actions);
    const status = element('section', 'result-status'); status.setAttribute('aria-live', 'polite');
    const workspace = element('section', 'result-workspace'); const main = element('article', 'result-main');
    const tabs = element('nav', 'result-tabs'); tabs.setAttribute('aria-label', 'Result views');
    const previewHead = element('header', 'result-preview-header'); const copy = element('div');
    const previewTitle = element('h2', '', 'Result'); const previewDescription = element('p', 'result-muted'); copy.append(previewTitle, previewDescription);
    const download = element('a', 'result-button result-button-small', 'Download file') as HTMLAnchorElement; download.hidden = true; download.download = '';
    previewHead.append(copy, download); const preview = element('div', 'result-preview'); preview.setAttribute('aria-busy', 'false'); main.append(tabs, previewHead, preview);
    const rail = element('aside', 'result-rail'); rail.setAttribute('aria-label', 'Files and diagnostics');
    const reopen = element('button', 'result-rail-reopen', 'Files') as HTMLButtonElement; reopen.type = 'button'; reopen.hidden = true; reopen.setAttribute('aria-label', 'Open Files and diagnostics');
    const railDetails = element('details', 'result-files') as HTMLDetailsElement; railDetails.open = true;
    const summary = element('summary', '', 'Files & diagnostics '); const artifactSummary = element('span', 'result-muted'); summary.append(artifactSummary);
    const tools = element('div', 'result-file-tools'); const search = element('input', 'result-search') as HTMLInputElement;
    search.type = 'search'; search.placeholder = 'Filter files'; search.setAttribute('aria-label', 'Filter result artifacts');
    const archive = element('button', 'result-button result-button-small', 'Create ZIP') as HTMLButtonElement; archive.type = 'button';
    const archiveState = element('p', 'result-muted', 'Individual files are available now.'); tools.append(search, archive, archiveState);
    const fileList = element('nav', 'result-file-list'); fileList.setAttribute('aria-label', 'Result artifacts'); railDetails.append(summary, tools, fileList); rail.append(reopen, railDetails);
    workspace.append(main, rail); const record = element('section', 'result-record'); const limitations = element('div'); const run = element('div'); record.append(limitations, run);
    const toast = element('aside', 'result-toasts'); toast.setAttribute('aria-live', 'polite'); page.append(header, status, workspace, record, toast); this.root.append(page);
    return { status, method, title, meta, tabs, previewTitle, previewDescription, preview, download, rail, railDetails, reopen, search, fileList, artifactSummary, archive, archiveState, limitations, run, toast };
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
    this.nodes.method.textContent = payload.task_type; this.nodes.title.textContent = payload.display_name || `Task ${this.taskId}`;
    this.setState(status, terminal ? (payload.error || payload.message || 'No published result manifest is available.') : (payload.message || 'The task is still running. This page updates automatically.'));
    this.nodes.preview.replaceChildren(element('p', 'result-empty', terminal ? 'No result artifacts were published.' : 'Waiting for result artifacts.'));
    if (!terminal && this.poll == null) this.poll = window.setInterval(() => void this.load(), 15_000);
  }

  private renderManifest(manifest: ResultManifest): void {
    if (this.poll != null) { clearInterval(this.poll); this.poll = null; }
    this.nodes.method.textContent = manifest.run?.method?.name || manifest.task_type || 'Scientific result';
    this.nodes.title.textContent = manifest.filename || `Task ${this.taskId}`; this.nodes.meta.textContent = `${manifest.status} · ${this.taskId}`;
    this.setState(manifest.outcome || manifest.status, manifest.error || manifest.run?.method?.output_summary || `${manifest.artifacts.length} published files.`);
    this.nodes.artifactSummary.textContent = `${manifest.artifacts.length} files · ${formatBytes(manifest.total_size)}`;
    this.renderFiles(); this.renderTabs(); this.renderRecord(); this.syncArchive();
    if (manifest.storyboard?.entrypoint_url) void this.openStoryboard();
    else {
      const primary = this.primaryArtifact();
      if (primary) void this.openArtifact(primary); else this.renderEmpty();
    }
  }

  private primaryArtifact(): ResultArtifact | null {
    const artifacts = this.manifest?.artifacts || [];
    const view = this.manifest?.views?.find((item) => item.role === 'primary');
    const path = view ? Object.values(view.sources || {}).flat()[0] : null;
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
    const path = Object.values(view.sources || {}).flat()[0]; const artifact = this.manifest?.artifacts.find((item) => item.path === path);
    if (!artifact) { this.renderPreviewError('This view has no available artifact.'); return; }
    await this.openArtifact(artifact, generation); if (generation !== this.previewGeneration) return;
    this.nodes.previewTitle.textContent = view.title; this.nodes.previewDescription.textContent = view.description || ''; this.markTab(view.id);
  }

  private async openStoryboard(): Promise<void> {
    const manifest = this.manifest; if (!manifest?.storyboard) return;
    const generation = ++this.previewGeneration;
    this.cancelRender(); this.structure.dispose(); this.nodes.preview.setAttribute('aria-busy', 'true');
    this.nodes.previewTitle.textContent = 'Scientific result'; this.nodes.previewDescription.textContent = 'Runner-provided scientific interpretation'; this.nodes.download.hidden = true;
    try { const current = await this.storyboard.mount(manifest.storyboard, manifest); if (current && generation === this.previewGeneration) this.markTab('storyboard'); }
    catch (error) { if (generation === this.previewGeneration) this.renderPreviewError((error as Error).message || 'Scientific result view unavailable.'); }
    finally { if (generation === this.previewGeneration) this.nodes.preview.setAttribute('aria-busy', 'false'); }
  }

  private openLogicalFile(file: LogicalResultFile): Promise<void> {
    return this.openArtifact(file);
  }

  async openArtifact(artifact: ResultFile, requestedGeneration?: number): Promise<void> {
    const generation = requestedGeneration ?? ++this.previewGeneration;
    this.storyboard.destroy(); this.cancelRender(); this.selected = artifact; this.markTab(null);
    const fileName = resultFileName(artifact); this.nodes.previewTitle.textContent = localName(fileName); this.nodes.previewDescription.textContent = `${artifact.role} · ${formatBytes(artifact.size)}`;
    this.nodes.download.hidden = false; this.nodes.download.href = downloadUrl(artifact); this.nodes.download.title = fileName;
    this.nodes.fileList.querySelectorAll<HTMLElement>('[data-artifact-path]').forEach((node) => node.setAttribute('aria-current', node.dataset.artifactPath === fileName ? 'true' : 'false'));
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
    await this.structure.mount(viewerHost, artifact, theme());
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
    toolbar.append(representationGroup, colorGroup);
    const reset = element('button', 'result-button result-button-small', 'Reset view') as HTMLButtonElement; reset.type = 'button'; reset.addEventListener('click', () => this.structure.resetCamera()); toolbar.append(reset);
    const themeButton = element('button', 'result-button result-button-small', 'Dark canvas') as HTMLButtonElement; themeButton.type = 'button'; let dark = theme() === 'dark'; themeButton.addEventListener('click', () => { dark = !dark; this.structure.setTheme(dark ? 'dark' : 'light'); themeButton.textContent = dark ? 'Light canvas' : 'Dark canvas'; }); toolbar.append(themeButton);
    const image = element('button', 'result-button result-button-small', 'Save PNG') as HTMLButtonElement; image.type = 'button'; image.addEventListener('click', async () => beginDownload(await this.structure.captureImage())); toolbar.append(image);
    const source = element('button', 'result-button result-button-small', 'Download') as HTMLButtonElement; source.type = 'button'; source.addEventListener('click', () => beginDownload(downloadUrl(artifact)));
    const fullscreen = element('button', 'result-icon-button') as HTMLButtonElement; fullscreen.type = 'button'; fullscreen.setAttribute('aria-pressed', 'false'); fullscreen.title = 'Enter fullscreen'; fullscreen.setAttribute('aria-label', 'Enter fullscreen'); setButtonIcon(fullscreen, 'Expand');
    fullscreen.addEventListener('click', async () => { if (document.fullscreenElement === viewport) await document.exitFullscreen(); else await viewport.requestFullscreen(); });
    const controller = this.renderController; if (controller) document.addEventListener('fullscreenchange', () => { const expanded = document.fullscreenElement === viewport; const label = expanded ? 'Exit fullscreen' : 'Enter fullscreen'; fullscreen.title = label; fullscreen.setAttribute('aria-label', label); fullscreen.setAttribute('aria-pressed', String(expanded)); setButtonIcon(fullscreen, expanded ? 'Minimize' : 'Expand'); }, { signal: controller.signal });
    toolbar.append(source, fullscreen); return toolbar;
  }

  private renderFiles(): void {
    const artifacts = filterArtifacts(this.manifest?.artifacts || [], this.nodes.search.value); this.nodes.fileList.replaceChildren();
    const renderNode = (node: ArtifactTreeNode, target: HTMLElement): void => {
      node.directories.forEach((directory) => { const details = element('details', 'result-directory') as HTMLDetailsElement; details.open = true;
        const summary = element('summary', '', directory.name); const children = element('div', 'result-directory-children'); details.append(summary, children); target.append(details); renderNode(directory, children); });
      node.artifacts.forEach((artifact) => target.append(this.fileRow(artifact)));
    };
    renderNode(buildArtifactTree(artifacts), this.nodes.fileList);
    if (!artifacts.length) this.nodes.fileList.append(element('p', 'result-empty', 'No files match this filter.'));
  }

  private fileRow(artifact: ResultArtifact): HTMLElement {
    const row = element('div', 'result-file-row'); const open = element('button', 'result-file-open') as HTMLButtonElement; open.type = 'button';
    open.dataset.artifactPath = artifact.path; open.title = artifact.path; const name = element('strong', '', localName(artifact.path));
    const meta = element('span', '', `${artifact.role === 'diagnostic' ? 'Execution log' : artifact.role} · ${formatBytes(artifact.size)}`); open.append(name, meta); open.addEventListener('click', () => void this.openArtifact(artifact));
    const download = element('a', 'result-file-download') as HTMLAnchorElement; download.href = downloadUrl(artifact); download.download = ''; download.title = `Download ${artifact.path}`; download.setAttribute('aria-label', `Download ${artifact.path}`); setButtonIcon(download, 'Download');
    row.append(open, download); return row;
  }

  private renderRecord(): void {
    const manifest = this.manifest; if (!manifest) return; this.nodes.limitations.replaceChildren(); this.nodes.run.replaceChildren();
    if (manifest.limitations?.length) { const title = element('h2', '', 'Limitations'); const list = element('ul'); manifest.limitations.forEach((text) => list.append(element('li', '', text))); this.nodes.limitations.append(title, list); }
    const values: Array<[string, string]> = [['Submitted', manifest.run?.submitted_at || 'Not recorded'], ['Started', manifest.run?.started_at || 'Not recorded'], ['Finished', manifest.run?.finished_at || 'Not recorded']];
    manifest.run?.inputs?.forEach((input) => values.push([`Input${input.role ? ` (${input.role})` : ''}`, `${input.path} [${input.sha256.slice(0, 12)}]`]));
    manifest.run?.parameters?.forEach((parameter) => values.push([parameter.label, `${String(parameter.value)}${parameter.unit ? ` ${parameter.unit}` : ''}`]));
    const title = element('h2', '', 'Run setup and reproducibility'); const list = element('dl', 'result-definition-list');
    values.forEach(([term, value]) => list.append(element('dt', '', term), element('dd', '', value))); this.nodes.run.append(title, list);
    if (manifest.run?.citations?.length) { const citations = element('ul', 'result-citations'); manifest.run.citations.forEach((citation) => { const item = element('li');
      if (citation.url || citation.doi) { const link = element('a', '', citation.title) as HTMLAnchorElement; link.href = citation.url || `https://doi.org/${encodeURIComponent(citation.doi || '')}`; link.rel = 'noopener'; item.append(link); } else item.textContent = citation.title; citations.append(item); }); this.nodes.run.append(citations); }
  }

  private syncArchive(): void {
    const archive = this.manifest?.archive; this.nodes.archive.disabled = !archive?.request_url && !archive?.download_url;
    this.nodes.archive.textContent = archive?.ready ? 'Download ZIP' : 'Create ZIP'; this.nodes.archiveState.textContent = archive?.ready ? 'The manifest-approved ZIP is ready.' : 'Individual files are available now.';
  }
  private async archiveAction(): Promise<void> {
    const archive = this.manifest?.archive; if (!archive) return;
    if (archive.ready && archive.download_url) { location.assign(archive.download_url); return; }
    if (!archive.request_url) return; this.nodes.archive.disabled = true;
    try { await requestResultArchive(archive.request_url); this.nodes.archiveState.textContent = 'Archive generation requested. Refresh shortly to download it.'; this.toast('Archive generation requested.'); }
    catch (error) { this.toast((error as Error).message || 'Archive request failed.', true); }
    finally { this.nodes.archive.disabled = false; }
  }

  private readonly syncRail = (): void => {
    const narrow = this.railMedia.matches; const collapsed = !narrow && !this.nodes.railDetails.open;
    this.root.querySelector('.result-app')?.classList.toggle('is-rail-collapsed', collapsed);
    this.nodes.rail.classList.toggle('is-collapsed', collapsed); this.nodes.railDetails.hidden = collapsed; this.nodes.reopen.hidden = !collapsed; this.structure.resize();
  };
  private setState(status: string, message: string): void { this.nodes.status.replaceChildren(element('strong', '', status), element('span', '', message)); }
  private renderEmpty(): void { this.nodes.preview.replaceChildren(element('p', 'result-empty', 'No previewable artifact was published. Files remain available for download.')); }
  private renderPreviewError(message: string): void { this.nodes.preview.replaceChildren(element('p', 'result-empty', message)); this.nodes.preview.setAttribute('aria-busy', 'false'); }
  private renderFatal(message: string): void { this.setState('Result unavailable', message); this.renderPreviewError('Return to the dashboard or refresh after checking task access.'); }
  private toast(message: string, error = false): void { const node = element('div', `result-toast${error ? ' is-error' : ''}`, message); node.setAttribute('role', error ? 'alert' : 'status'); this.nodes.toast.append(node); setTimeout(() => node.remove(), 3600); }
  private cancelRender(): void { this.renderController?.abort(); this.renderController = null; }

  destroy(): void {
    if (this.disposed) return; this.disposed = true; this.cancelRender(); this.loadController?.abort(); this.storyboard.destroy(); this.structure.dispose();
    if (this.poll != null) clearInterval(this.poll); this.listeners.abort(); this.root.replaceChildren();
  }
}
