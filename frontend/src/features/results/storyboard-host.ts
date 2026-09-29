import type { LogicalResultFile, ResultManifest, ResultStoryboardDeclaration } from '../../api/result-types';
import { ResultSelectionStore } from './scientific';

export interface StoryboardServices {
  openFile(artifact: LogicalResultFile): Promise<void>;
  downloadFile(artifact: LogicalResultFile): void;
  focusStructure?(selection: unknown): boolean;
  selectStructure?(selection: unknown): boolean;
}

interface StoryboardInstance { destroy?(): void }
interface StoryboardModule {
  default: { mount(host: HTMLElement, context: unknown): StoryboardInstance | Promise<StoryboardInstance> };
}

export class StoryboardHost {
  private generation = 0;
  private instance: StoryboardInstance | null = null;
  private selection: ResultSelectionStore | null = null;
  private ownsHost = false;

  constructor(private readonly host: HTMLElement, private readonly services: StoryboardServices) {}

  setMolecularSelection(residues: Array<{ chain: string; residue: number; auth_seq_id: number; label_seq_id: number }>): void {
    const first = residues[0];
    this.selection?.set({
      token: first && Number.isFinite(first.residue) ? first.residue : null,
      entityA: first?.chain || null,
      entityB: null,
    }, this);
  }

  async mount(declaration: ResultStoryboardDeclaration, manifest: ResultManifest): Promise<boolean> {
    this.destroy(); this.ownsHost = true; const generation = this.generation;
    const selection = new ResultSelectionStore({}, (candidate) => { void this.services.openFile(candidate as LogicalResultFile); });
    this.selection = selection;
    const files = new Map<string, LogicalResultFile | LogicalResultFile[] | null>();
    Object.entries(manifest.result?.files || {}).forEach(([id, artifacts]) => {
      const first = artifacts[0]; files.set(id, artifacts.length === 0 ? null : artifacts.length === 1 && first?.cardinality !== 'many' ? first! : artifacts);
    });
    if (declaration.requires.some((id) => !files.get(id))) throw new Error('Required scientific result files are unavailable.');
    const module = await import(/* @vite-ignore */ declaration.entrypoint_url) as StoryboardModule;
    if (generation !== this.generation) return false;
    if (!module.default || typeof module.default.mount !== 'function') throw new Error('Storyboard entrypoint is invalid.');
    const context = Object.freeze({
      files: Object.freeze({ get: (id: string) => files.get(id) || null }),
      metadata: Object.freeze({ taskType: manifest.task_type }),
      selection,
      services: Object.freeze(this.services),
    });
    const instance = await module.default.mount(this.host, context);
    if (generation !== this.generation) { instance?.destroy?.(); selection.destroy(); return false; }
    this.instance = instance || module.default; return true;
  }

  destroy(): void {
    this.generation += 1;
    const clearHost = this.ownsHost; this.ownsHost = false;
    try { this.instance?.destroy?.(); } finally { this.instance = null; this.selection?.destroy(); this.selection = null; if (clearHost) this.host.replaceChildren(); }
  }
}
