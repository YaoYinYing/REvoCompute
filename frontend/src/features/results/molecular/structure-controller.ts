import { resultFileName, type ResultFile } from '../../../api/result-types';
import { t } from '../../../app/i18n';
import type { MolecularViewer, MolecularViewerFactory } from './viewer-contract';

const MAX_STRUCTURE_BYTES = 64 * 1024 * 1024;

// A runner may publish a compressed structure (`*.cif.gz` is what RFdiffusion3
// writes). The viewer parses the decompressed bytes, so the compression suffix
// is peeled before the format is read and the payload is gunzipped on the way
// in; without that, a `.cif.gz` name selected the PDB parser and the gzip
// payload was handed to it verbatim.
const GZIPPED = /\.gz$/i;

function structureFormat(path: string): 'pdb' | 'mmcif' | 'pqr' {
  if (/\.pqr(?:\.gz)?$/i.test(path)) return 'pqr';
  return /\.(?:cif|mmcif)(?:\.gz)?$/i.test(path) ? 'mmcif' : 'pdb';
}

async function readSource(path: string, response: Response): Promise<string> {
  if (!GZIPPED.test(path)) return response.text();
  if (typeof DecompressionStream === 'undefined') throw new Error(t('results.structure.compressedUnsupported'));
  // `response.body` is already the raw bytes; the stream inflates them without
  // ever materializing the whole compressed file as a buffer.
  if (!response.body) return gunzip(await response.arrayBuffer());
  return new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).text();
}

async function gunzip(buffer: ArrayBuffer): Promise<string> {
  return new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
}

export class StructureController {
  private viewer: MolecularViewer | null = null;
  private host: HTMLElement | null = null;
  private generation = 0;
  private geometryGeneration = 0;
  private geometryAbort: AbortController | null = null;
  private controller: AbortController | null = null;
  private representation = 'cartoon_ligand';
  private color = 'rainbow';
  private operation: Promise<void> = Promise.resolve();
  private viewerMount: Promise<MolecularViewer> | null = null;
  private selectionUnsubscribe: (() => void) | null = null;
  private loading = false;
  private pendingFocus: unknown = null;
  private pendingSelection: unknown = null;

  constructor(private readonly createViewer: MolecularViewerFactory, private readonly options: {
    selectionEnabled?: boolean;
    //: The Result workspace names itself the scientific stage owner, so the
    //: viewer's native panels start closed behind their own disclosure button.
    controlsCollapsed?: boolean;
    onSelectionChanged?: (residues: Array<{ chain: string; residue: number; auth_seq_id: number; label_seq_id: number }>) => void;
  } = {}) {}

  async mount(host: HTMLElement, artifact: ResultFile, theme: 'light' | 'dark'): Promise<void> {
    if (artifact.size > MAX_STRUCTURE_BYTES) throw new Error(t('results.structure.tooLarge'));
    const generation = ++this.generation;
    const controller = new AbortController();
    this.loading = true; this.pendingFocus = null; this.pendingSelection = null;
    const masksExistingViewer = this.host === host && Boolean(this.viewer || this.viewerMount);
    if (masksExistingViewer && host.dataset) host.dataset.loading = 'true';
    try {
      this.controller?.abort();
      this.controller = controller;
      if (this.host !== host) {
        this.disposeViewer();
        this.host = host;
      }
      if (!this.viewer && !this.viewerMount) {
        this.viewerMount = this.createViewer(host, {
          theme, selectionEnabled: this.options.selectionEnabled, controlsCollapsed: this.options.controlsCollapsed,
        });
      }
      if (!this.viewer) {
        const pending = this.viewerMount!;
        let created: MolecularViewer;
        try { created = await pending; } finally { if (this.viewerMount === pending) this.viewerMount = null; }
        if (this.host !== host) return;
        if (generation !== this.generation) return;
        this.viewer = created;
        if (this.options.onSelectionChanged) this.selectionUnsubscribe = created.onSelectionChanged?.(this.options.onSelectionChanged) || null;
      }
      const response = await fetch(artifact.url, { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error(t('results.structure.downloadFailed', { status: response.status }));
      const name = resultFileName(artifact);
      const data = await readSource(name, response);
      if (generation !== this.generation) return;
      const viewer = this.viewer;
      const apply = async (): Promise<void> => {
        if (generation !== this.generation || viewer !== this.viewer) return;
        await viewer.setRepresentation(this.representation);
        await viewer.setColor(this.color === 'confidence' ? 'plddt' : this.color);
        await viewer.loadStructure({ data, format: structureFormat(name), label: name });
        if (generation !== this.generation || viewer !== this.viewer) {
          if (viewer === this.viewer) await viewer.clear?.();
          return;
        }
        if (this.pendingSelection != null) viewer.select?.(this.pendingSelection);
        if (this.pendingFocus != null) viewer.focus?.(this.pendingFocus);
        this.pendingSelection = null; this.pendingFocus = null;
        viewer.resize();
      };
      const completed = this.operation.then(apply, apply);
      this.operation = completed.then(() => undefined, () => undefined);
      await completed;
    } finally {
      if (this.controller === controller) this.controller = null;
      if (generation === this.generation && this.host === host) {
        await this.operation;
        this.loading = false;
        if (masksExistingViewer && host.dataset) delete host.dataset.loading;
      }
    }
  }

  setRepresentation(mode: string): Promise<void> {
    this.representation = mode;
    return this.viewer?.setRepresentation(mode) || Promise.resolve();
  }

  setColor(mode: string): Promise<void> {
    this.color = mode;
    return this.viewer?.setColor(mode === 'confidence' ? 'plddt' : mode) || Promise.resolve();
  }

  setTheme(theme: 'light' | 'dark'): void { this.viewer?.setTheme(theme); }
  resize(): void { this.viewer?.resize(); }
  async setGeometry(artifact: ResultFile | null): Promise<void> {
    const generation = ++this.geometryGeneration; this.geometryAbort?.abort(); this.geometryAbort = null;
    if (!artifact) { await this.viewer?.setSphereGeometry?.(null); return; }
    if (artifact.size > 4 * 1024 * 1024) throw new Error('Alpha-sphere evidence exceeds the preview limit.');
    const controller = new AbortController(); this.geometryAbort = controller;
    const response = await fetch(artifact.url, { credentials: 'same-origin', signal: controller.signal });
    if (!response.ok) throw new Error('Alpha-sphere evidence could not be opened.');
    const source = await response.text();
    if (source.length > 4 * 1024 * 1024) throw new Error('Alpha-sphere evidence exceeds the preview limit.');
    if (generation !== this.geometryGeneration) return;
    if (!this.viewer?.setSphereGeometry) throw new Error('Recorded sphere display is unavailable.');
    await this.viewer.setSphereGeometry(source);
  }

  annotate(annotation: { point: { x: number; y: number; z: number }; label: string } | null): void { this.viewer?.annotate?.(annotation); }
  resetCamera(): void { this.viewer?.resetCamera?.(); }
  select(selection: unknown): boolean { if (this.loading) { this.pendingSelection = selection; return true; } return this.viewer?.select?.(selection) || false; }
  focus(selection: unknown): boolean { if (this.loading) { this.pendingFocus = selection; return true; } return this.viewer?.focus?.(selection) || false; }
  captureImage(): Promise<string> {
    if (!this.viewer) return Promise.reject(new Error(t('results.structure.notReady')));
    return this.viewer.captureImage();
  }

  dispose(): void {
    this.generation += 1; this.geometryGeneration += 1; this.geometryAbort?.abort(); this.geometryAbort = null;
    this.controller?.abort();
    this.controller = null;
    this.loading = false; this.pendingFocus = null; this.pendingSelection = null;
    this.disposeViewer();
  }

  private disposeViewer(): void {
    this.selectionUnsubscribe?.();
    this.selectionUnsubscribe = null;
    this.viewer?.dispose();
    this.viewer = null;
    const pending = this.viewerMount; this.viewerMount = null;
    if (pending) void pending.then((viewer) => viewer.dispose(), () => undefined);
    this.host = null;
  }
}
