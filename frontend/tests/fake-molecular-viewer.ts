export class MolecularViewer {
  private disposed = false;
  private constructor(private readonly host: HTMLElement) {}
  static async mount(host: HTMLElement): Promise<MolecularViewer> {
    const viewer = new MolecularViewer(host); const state = window as any;
    state.__viewerMounts = (state.__viewerMounts || 0) + 1; host.dataset.viewer = String(state.__viewerMounts); return viewer;
  }
  async loadStructure(source: { label?: string }): Promise<void> {
    const state = window as any; const label = source.label || '';
    state.__viewerLoads ||= []; state.__viewerLoads.push(label);
    if (state.__holdStructure === label) await new Promise<void>((resolve) => { state.__releaseStructure = resolve; });
    if (!this.disposed) this.host.dataset.label = label;
  }
  async setRepresentation(value: string): Promise<void> { this.host.dataset.representation = value; }
  async setColor(value: string): Promise<void> { this.host.dataset.color = value; }
  setTheme(value: string): void { this.host.dataset.theme = value; }
  resize(): void { const state = window as any; state.__viewerResizes = (state.__viewerResizes || 0) + 1; }
  resetCamera(): void { const state = window as any; state.__viewerResets = (state.__viewerResets || 0) + 1; }
  async captureImage(): Promise<string> { const state = window as any; state.__viewerCaptures = (state.__viewerCaptures || 0) + 1; return 'data:image/png;base64,cHJvYmU='; }
  dispose(): void { if (this.disposed) return; this.disposed = true; const state = window as any; state.__viewerDisposals = (state.__viewerDisposals || 0) + 1; this.host.replaceChildren(); }
}
