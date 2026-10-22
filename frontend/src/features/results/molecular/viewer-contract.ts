export interface StructureSource {
  data: string;
  format: 'pdb' | 'mmcif' | 'pqr';
  label?: string;
}

export interface TrajectorySource {
  /** Topology text the coordinate frames are read against. */
  topology: string;
  /** Coordinate frames, kept binary (XTC/DCD) or text (multi-model PDB). */
  coordinates: string | Uint8Array;
  coordinateFormat: string;
  label?: string;
}

export interface TrajectoryInfo {
  frame: number;
  frameCount: number;
}

export interface MolecularViewer {
  loadStructure(source: StructureSource): Promise<void>;
  loadTrajectory?(source: TrajectorySource): Promise<TrajectoryInfo>;
  setTrajectoryFrame?(action: 'set' | 'advance', value: number): Promise<TrajectoryInfo>;
  setRepresentation(mode: string): Promise<void>;
  setColor(mode: string): Promise<void>;
  setTheme(theme: 'light' | 'dark'): void;
  resize(): void;
  captureImage(): Promise<string>;
  resetCamera?(): void;
  setSphereGeometry?(source: string | null): Promise<void>;
  annotate?(annotation: { point: { x: number; y: number; z: number }; label: string } | null): void;
  clear?(): Promise<void>;
  select?(selection: unknown): boolean;
  focus?(selection: unknown): boolean;
  onSelectionChanged?(listener: (residues: Array<{ chain: string; residue: number; auth_seq_id: number; label_seq_id: number }>) => void): () => void;
  dispose(): void;
}

export type MolecularViewerFactory = (
  host: HTMLElement,
  options: { theme: 'light' | 'dark'; selectionEnabled?: boolean; controlsCollapsed?: boolean },
) => Promise<MolecularViewer>;
