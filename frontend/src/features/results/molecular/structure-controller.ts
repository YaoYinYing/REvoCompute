import { resultFileName, type ResultFile } from '../../../api/result-types';
import type { MolecularViewer, MolecularViewerFactory } from './viewer-contract';

const MAX_STRUCTURE_BYTES = 64 * 1024 * 1024;

function structureFormat(path: string): 'pdb' | 'mmcif' {
  return /\.(?:cif|mmcif)$/i.test(path) ? 'mmcif' : 'pdb';
}

export class StructureController {
  private viewer: MolecularViewer | null = null;
  private host: HTMLElement | null = null;
  private generation = 0;
  private controller: AbortController | null = null;
  private representation = 'cartoon';
  private color = 'chain';
  private operation: Promise<void> = Promise.resolve();
  private viewerMount: Promise<MolecularViewer> | null = null;

  constructor(private readonly createViewer: MolecularViewerFactory) {}

  async mount(host: HTMLElement, artifact: ResultFile, theme: 'light' | 'dark'): Promise<void> {
    if (artifact.size > MAX_STRUCTURE_BYTES) throw new Error('This structure exceeds the safe inline preview limit.');
    const generation = ++this.generation;
    this.controller?.abort();
    this.controller = new AbortController();
    if (this.host !== host) {
      this.disposeViewer();
      this.host = host;
    }
    if (!this.viewer && !this.viewerMount) this.viewerMount = this.createViewer(host, { theme });
    if (!this.viewer) {
      const pending = this.viewerMount!;
      let created: MolecularViewer;
      try { created = await pending; } finally { if (this.viewerMount === pending) this.viewerMount = null; }
      if (this.host !== host) { created.dispose(); return; }
      this.viewer = created;
    }
    const response = await fetch(artifact.url, { credentials: 'same-origin', signal: this.controller.signal });
    if (!response.ok) throw new Error(`Structure download failed (HTTP ${response.status}).`);
    const data = await response.text();
    if (generation !== this.generation) return;
    const viewer = this.viewer; const name = resultFileName(artifact);
    const apply = async (): Promise<void> => {
      if (generation !== this.generation || viewer !== this.viewer) return;
      await viewer.setRepresentation(this.representation);
      await viewer.setColor(this.color === 'confidence' ? 'plddt' : this.color);
      await viewer.loadStructure({ data, format: structureFormat(name), label: name });
      if (generation === this.generation && viewer === this.viewer) viewer.resize();
    };
    const completed = this.operation.then(apply, apply);
    this.operation = completed.then(() => undefined, () => undefined);
    await completed;
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
  resetCamera(): void { this.viewer?.resetCamera?.(); }
  captureImage(): Promise<string> {
    if (!this.viewer) return Promise.reject(new Error('The structure viewer is not ready.'));
    return this.viewer.captureImage();
  }

  dispose(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
    this.disposeViewer();
  }

  private disposeViewer(): void {
    this.viewer?.dispose();
    this.viewer = null;
    const pending = this.viewerMount; this.viewerMount = null;
    if (pending) void pending.then((viewer) => viewer.dispose(), () => undefined);
    this.host = null;
  }
}
