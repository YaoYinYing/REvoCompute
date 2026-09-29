export interface StructureSource {
  data: string;
  format: 'pdb' | 'mmcif';
  label?: string;
}

export interface MolecularViewer {
  loadStructure(source: StructureSource): Promise<void>;
  setRepresentation(mode: string): Promise<void>;
  setColor(mode: string): Promise<void>;
  setTheme(theme: 'light' | 'dark'): void;
  resize(): void;
  captureImage(): Promise<string>;
  resetCamera?(): void;
  clear?(): Promise<void>;
  select?(selection: unknown): boolean;
  focus?(selection: unknown): boolean;
  dispose(): void;
}

export type MolecularViewerFactory = (
  host: HTMLElement,
  options: { theme: 'light' | 'dark'; selectionEnabled?: boolean },
) => Promise<MolecularViewer>;
