import type {
  AxisAlignedBox,
  CenterOfMassOptions,
  MolecularScene,
  MolecularSelection,
  SceneAtom,
  SceneMutationMeta,
  SelectedResidue,
  StructureSource,
  XYZ,
} from '../../structure/molecular-scene';

export type { StructureSource };

/** Topology formats a trajectory view may declare. */
export type TrajectoryTopologyFormat = 'pdb' | 'mmcif';

export interface TrajectorySource {
  /** Topology text the coordinate frames are read against. */
  topology: string;
  /** Format of the topology text; defaults to PDB for views that predate the field. */
  topologyFormat?: TrajectoryTopologyFormat;
  /** Coordinate frames, kept binary (XTC/DCD) or text (multi-model PDB). */
  coordinates: string | Uint8Array;
  coordinateFormat: string;
  label?: string;
}

export interface TrajectoryInfo {
  frame: number;
  frameCount: number;
}

/**
 * The narrow result adapter over the one mounted viewer.
 *
 * `scene` is the typed molecular interaction contract; the remaining members
 * are the presentation lifecycle the Result workspace already owns.
 */
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
  select?(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  focus?(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  setHighlight?(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  clearHighlight?(): void;
  onSelectionChanged?(listener: (residues: SelectedResidue[]) => void): () => void;
  /** The typed scene operations of the same mounted viewer. */
  readonly scene?: MolecularScene;
  getCrosshair?(): XYZ | null;
  setCrosshair?(point: XYZ | null, meta?: SceneMutationMeta): XYZ | null;
  getBox?(): AxisAlignedBox | null;
  setBox?(box: AxisAlignedBox | null, meta?: SceneMutationMeta): AxisAlignedBox | null;
  centroid?(atoms?: readonly SceneAtom[]): XYZ;
  centerOfMass?(options: CenterOfMassOptions, atoms?: readonly SceneAtom[]): XYZ;
  boundingBox?(atoms?: readonly SceneAtom[]): AxisAlignedBox;
  pickAtoms?(): Promise<SceneAtom[]>;
  dispose(): void;
}

export type MolecularViewerFactory = (
  host: HTMLElement,
  options: { theme: 'light' | 'dark'; selectionEnabled?: boolean; controlsCollapsed?: boolean },
) => Promise<MolecularViewer>;
