export class MolecularViewer {
  private disposed = false;
  private selectionListener: ((residues: Array<{ chain: string; residue: number }>) => void) | null = null;
  private constructor(private readonly host: HTMLElement) {}
  static async mount(host: HTMLElement): Promise<MolecularViewer> {
    const viewer = new MolecularViewer(host); const state = window as any;
    state.__viewerMounts = (state.__viewerMounts || 0) + 1; host.dataset.viewer = String(state.__viewerMounts);
    state.__emitViewerSelection = (residues: Array<{ chain: string; residue: number }>) => {
      viewer.selectionListener?.(residues);
    };
    return viewer;
  }
  async loadStructure(source: { label?: string }): Promise<void> {
    const state = window as any; const label = source.label || '';
    state.__viewerLoads ||= []; state.__viewerLoads.push(label);
    if (state.__holdStructure === label) await new Promise<void>((resolve) => { state.__releaseStructure = resolve; });
    if (!this.disposed) this.host.dataset.label = label;
  }
  async setRepresentation(value: string): Promise<void> { this.host.dataset.representation = value; }
  async setColor(value: string): Promise<void> { this.host.dataset.color = value; }
  async clear(): Promise<void> { this.host.removeAttribute('data-label'); }
  onSelectionChanged(listener: (residues: Array<{ chain: string; residue: number }>) => void): () => void {
    this.selectionListener = listener;
    return () => { if (this.selectionListener === listener) this.selectionListener = null; };
  }
  setTheme(value: string): void { this.host.dataset.theme = value; }
  resize(): void { const state = window as any; state.__viewerResizes = (state.__viewerResizes || 0) + 1; }
  resetCamera(): void { const state = window as any; state.__viewerResets = (state.__viewerResets || 0) + 1; }
  // The record doubles as the shared structure-panel state, so a browser test can
  // assert that a collection applied ONCE rather than as N replacing selections.
  select(selection: any): boolean {
    const state = window as any;
    state.__viewerSelects ||= [];
    const residues = Array.isArray(selection?.residues)
      ? selection.residues.map((entry: any) => `${entry.chain}_${entry.residue}`)
      : selection?.chain != null && selection?.residue != null ? [`${selection.chain}_${selection.residue}`] : [];
    state.__viewerSelects.push({ selection, residues });
    state.__viewerSelection = residues;
    return true;
  }
  focus(selection: any): boolean {
    const state = window as any;
    state.__viewerFocuses ||= [];
    state.__viewerFocuses.push(selection);
    return true;
  }
  async captureImage(): Promise<string> { const state = window as any; state.__viewerCaptures = (state.__viewerCaptures || 0) + 1; return 'data:image/png;base64,cHJvYmU='; }
  dispose(): void {
    if (this.disposed) return; this.disposed = true; this.selectionListener = null;
    const state = window as any; state.__viewerDisposals = (state.__viewerDisposals || 0) + 1;
    delete state.__emitViewerSelection; this.host.replaceChildren();
  }
}
