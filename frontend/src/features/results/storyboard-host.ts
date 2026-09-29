import type { LogicalResultFile, ResultManifest, ResultStoryboardDeclaration } from '../../api/result-types';

export interface StoryboardServices {
  openFile(artifact: LogicalResultFile): Promise<void>;
  downloadFile(artifact: LogicalResultFile): void;
}

interface StoryboardInstance { destroy?(): void }
interface StoryboardModule {
  default: { mount(host: HTMLElement, context: unknown): StoryboardInstance | Promise<StoryboardInstance> };
}

export class StoryboardHost {
  private generation = 0;
  private instance: StoryboardInstance | null = null;

  constructor(private readonly host: HTMLElement, private readonly services: StoryboardServices) {}

  async mount(declaration: ResultStoryboardDeclaration, manifest: ResultManifest): Promise<boolean> {
    this.destroy(); const generation = this.generation;
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
      services: Object.freeze(this.services),
    });
    const instance = await module.default.mount(this.host, context);
    if (generation !== this.generation) { instance?.destroy?.(); return false; }
    this.instance = instance || module.default; return true;
  }

  destroy(): void {
    this.generation += 1;
    try { this.instance?.destroy?.(); } finally { this.instance = null; this.host.replaceChildren(); }
  }
}
