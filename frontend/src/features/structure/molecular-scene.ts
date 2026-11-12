/*
 * The typed molecular scene contract shared by the Create Task inspector and the
 * Result workspace.
 *
 * One Mol* instance owns rendering and the authoritative selection (see
 * `MolecularViewer`). This module owns the vocabulary every consumer speaks:
 * stable atom/residue identity, the immutable topology identity, Angstrom
 * coordinates, validated numeric operations, and the origin-tagged events that
 * keep a form and its viewer from echoing each other.
 *
 * Coordinate values are Angstrom from the source structure/trajectory. Nothing
 * here converts units; a caller that has a different unit must convert before
 * handing coordinates to the scene.
 */
import { AtomicNumbers, ElementAtomWeights } from 'molstar/lib/mol-model/structure/model/properties/atomic/measures.js';

export const ANGSTROM = 'angstrom' as const;
export type CoordinateUnits = typeof ANGSTROM;

export interface XYZ {
  x: number;
  y: number;
  z: number;
}

/** An axis-aligned box in the same Angstrom frame as every scene coordinate. */
export interface AxisAlignedBox {
  center: XYZ;
  /** Full side lengths (never half-extents). */
  lengths: XYZ;
}

/**
 * Stable identity of one atom.
 *
 * `authChain`/`authSeqId`/`atomName` are the source structure's authored
 * addresses; the label fields are Mol*'s viewer-local keys. `atomSerial` is the
 * source record's serial number and `index` is the viewer-local element index,
 * so the two are never interchangeable. `insertionCode`, `altloc`, and
 * `modelIndex` are part of the key: 42 and 42A, conformer A and B, and model 0
 * and 1 are different atoms.
 */
export interface AtomIdentity {
  authChain: string;
  labelChain: string;
  authSeqId: number;
  labelSeqId: number;
  insertionCode?: string;
  residueName: string;
  atomName: string;
  atomSerial: number;
  altloc?: string;
  modelIndex: number;
  /** Viewer-local element index; not the source serial. */
  index: number;
}

export interface SceneAtom {
  identity: AtomIdentity;
  /** Element symbol used to resolve an atomic mass; uppercase. */
  element: string;
  position: XYZ;
}

/** The immutable identity of the loaded topology. */
export interface TopologyIdentity {
  revision: number;
  digest: string;
  label: string;
}

export interface StructureSource {
  data: string;
  format: 'pdb' | 'mmcif' | 'pqr';
  label?: string;
  /** Precomputed source digest; the viewer computes one when absent. */
  digest?: string;
}

/** One residue selector, addressed in authored or viewer-local numbering. */
export interface MolecularSelection {
  chain?: string;
  entity?: string;
  residue?: number;
  numbering?: 'auth_seq_id' | 'label_seq_id';
  /** PDB insertion code: it distinguishes e.g. residue 42A from residue 42.
   *
   *  Omit it to match the residue regardless of insertion code; pass an empty
   *  string to require the bare residue (no insertion code); pass a non-empty
   *  string to require that exact code. */
  insertionCode?: string;
  /** A bounded set of residues selected together as one operation. */
  residues?: MolecularSelection[];
  /** A spatial focus target: a Cartesian point (Angstrom) and optional radius (Angstrom). */
  focusPoint?: XYZ & { radius?: number };
}

export interface SelectedResidue {
  /** Mol* label identity: label_asym_id plus label_seq_id. Viewer-local. */
  chain: string;
  residue: number;
  /** Authored PDB identity: the one the source structure and Runner use. */
  auth_chain: string;
  auth_seq_id: number;
  label_seq_id: number;
  /** PDB insertion code ('' when absent), part of the residue identity. */
  insertion_code?: string;
  /** Authored residue name, such as ALA or HEM. */
  residue_name: string;
  /** Non-polymer/water entity (a PDB HETATM-like residue), not a polymer residue. */
  hetero: boolean;
}

/** The Mol* properties one selected residue contributes to its authored identity. */
export interface ResidueIdentity {
  authChain: string;
  labelChain: string;
  authSeqId: number;
  labelSeqId: number;
  insCode: string;
  residueName: string;
  /** The source record class: ATOM is a polymer residue, HETATM a hetero one. */
  groupPDB: string;
}

/**
 * Project Mol* residue properties onto the workspace's authored identity.
 *
 * Auth chain/residue are the source structure's addresses; label identity is
 * viewer-local and kept beside them. An absent insertion code is omitted, so a
 * bare residue number and an empty code mean the same thing.
 */
export function authoredResidue(properties: ResidueIdentity): SelectedResidue {
  const insCode = String(properties.insCode || '').trim();
  // Non-polymer residues (ligands, waters) may carry no label_seq_id. The
  // authored number is the address that matters; fall back to it rather than
  // publishing NaN as a label. Auth identity stays the Runner-facing value.
  const label = Number.isFinite(properties.labelSeqId) ? properties.labelSeqId : properties.authSeqId;
  return {
    chain: properties.labelChain,
    residue: label,
    auth_chain: properties.authChain,
    auth_seq_id: properties.authSeqId,
    label_seq_id: label,
    ...(insCode ? { insertion_code: insCode } : {}),
    residue_name: String(properties.residueName || '').trim(),
    hetero: String(properties.groupPDB || '').trim().toUpperCase() === 'HETATM',
  };
}

// ---------------------------------------------------------------------------
// Errors: every rejection names the reason the caller has to handle.
// ---------------------------------------------------------------------------

export class MolecularSceneError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MolecularSceneError';
  }
}

/** A selector belongs to a topology that is no longer loaded. */
export class StaleTopologyError extends MolecularSceneError {
  constructor(expected: { revision: number; digest: string }, actual: TopologyIdentity) {
    super(
      `Selection belongs to topology revision ${expected.revision} (${expected.digest || 'no digest'}), `
      + `but revision ${actual.revision} (${actual.digest || 'no digest'}) is loaded.`,
    );
    this.name = 'StaleTopologyError';
  }
}

export class EmptyAtomSubsetError extends MolecularSceneError {
  constructor(operation: string) {
    super(`${operation} needs at least one atom.`);
    this.name = 'EmptyAtomSubsetError';
  }
}

export class MissingAtomicMassError extends MolecularSceneError {
  constructor(element: string) {
    super(`No verified atomic mass is available for element "${element || 'unknown'}".`);
    this.name = 'MissingAtomicMassError';
  }
}

export class InvalidCoordinateError extends MolecularSceneError {
  constructor(label: string) {
    super(`${label} must be a finite XYZ value in Angstrom.`);
    this.name = 'InvalidCoordinateError';
  }
}

export class InvalidBoxError extends MolecularSceneError {
  constructor() {
    super('A box needs a finite center and three non-negative, finite side lengths.');
    this.name = 'InvalidBoxError';
  }
}

export class AmbiguousAltlocError extends MolecularSceneError {
  constructor(key: string) {
    super(`Atoms at ${key} carry different alternate locations; the selection is ambiguous.`);
    this.name = 'AmbiguousAltlocError';
  }
}

// ---------------------------------------------------------------------------
// Runtime type guards for the Mol* boundary and for scene payloads.
// ---------------------------------------------------------------------------

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isXYZ(value: unknown): value is XYZ {
  return isRecord(value) && isFiniteNumber(value.x) && isFiniteNumber(value.y) && isFiniteNumber(value.z);
}

export function isAxisAlignedBox(value: unknown): value is AxisAlignedBox {
  return isRecord(value)
    && isXYZ(value.center)
    && isRecord(value.lengths)
    && isFiniteNumber(value.lengths.x)
    && isFiniteNumber(value.lengths.y)
    && isFiniteNumber(value.lengths.z)
    && value.lengths.x >= 0
    && value.lengths.y >= 0
    && value.lengths.z >= 0;
}

export function isSceneAtom(value: unknown): value is SceneAtom {
  if (!isRecord(value) || !isRecord(value.identity) || !isXYZ(value.position)) return false;
  const identity = value.identity;
  return typeof identity.authChain === 'string'
    && typeof identity.labelChain === 'string'
    && isFiniteNumber(identity.authSeqId)
    && isFiniteNumber(identity.labelSeqId)
    && typeof identity.residueName === 'string'
    && typeof identity.atomName === 'string'
    && isFiniteNumber(identity.atomSerial)
    && isFiniteNumber(identity.modelIndex)
    && isFiniteNumber(identity.index);
}

export function assertFiniteXYZ(value: unknown, label = 'Coordinate'): XYZ {
  if (!isXYZ(value)) throw new InvalidCoordinateError(label);
  return { x: value.x, y: value.y, z: value.z };
}

export function assertAxisAlignedBox(value: unknown): AxisAlignedBox {
  if (!isAxisAlignedBox(value)) throw new InvalidBoxError();
  return { center: { ...value.center }, lengths: { ...value.lengths } };
}

// ---------------------------------------------------------------------------
// Identity keys and numeric operations.
// ---------------------------------------------------------------------------

/** The stable key of one atom within the loaded topology. */
export function atomKey(identity: AtomIdentity): string {
  return [
    identity.authChain,
    identity.authSeqId,
    identity.insertionCode || '',
    identity.residueName,
    identity.atomName,
    identity.atomSerial,
    identity.altloc || '',
    identity.modelIndex,
  ].join('|');
}

/**
 * The identity of an atom's slot, independent of its serial and conformer:
 * two alternate locations of one atom share this key. Used only to reject an
 * ambiguous selection, never as the atom's stable key.
 */
function conformerKey(identity: AtomIdentity): string {
  return [
    identity.authChain,
    identity.authSeqId,
    identity.insertionCode || '',
    identity.residueName,
    identity.atomName,
    identity.modelIndex,
  ].join('|');
}

export function residueKey(residue: SelectedResidue): string {
  return [residue.auth_chain, residue.auth_seq_id, residue.insertion_code || '', residue.residue_name].join('|');
}

export function selectionSignature(residues: readonly SelectedResidue[], atoms: readonly SceneAtom[]): string {
  if (atoms.length) return atoms.map(atom => atomKey(atom.identity)).sort().join(';');
  return residues.map(residueKey).sort().join(';');
}

export type HydrogenPolicy = 'include' | 'exclude';

export interface CenterOfMassOptions {
  /** `include` and `exclude` are the only policies; there is no implicit default. */
  hydrogenPolicy: HydrogenPolicy;
}

/**
 * Average atomic weights used by the mass-weighted center of mass.
 *
 * Mol* ships the IUPAC standard atomic weights (`ElementAtomWeights`). The
 * lookup is deliberately strict: an unknown element is a mass gap and must be
 * reported, never silently approximated as carbon. Deuterium and tritium are
 * hydrogen isotopes for the hydrogen policy and use hydrogen's weight.
 */
export function atomicMass(element: string): number | undefined {
  const symbol = String(element || '').trim().toUpperCase();
  const atomicNumber = AtomicNumbers[symbol];
  if (atomicNumber === undefined) return undefined;
  return ElementAtomWeights[atomicNumber];
}

export function isHydrogen(element: string): boolean {
  const symbol = String(element || '').trim().toUpperCase();
  return symbol === 'H' || symbol === 'D' || symbol === 'T';
}

/** Reject a selection that addresses two conformers of the same atom at once. */
export function assertUnambiguousAtoms(atoms: readonly SceneAtom[]): void {
  const seen = new Map<string, string>();
  for (const atom of atoms) {
    const key = conformerKey(atom.identity);
    const altloc = atom.identity.altloc || '';
    const previous = seen.get(key);
    if (previous !== undefined && previous !== altloc) throw new AmbiguousAltlocError(key);
    seen.set(key, altloc);
  }
}

/**
 * Arithmetic mean position (geometric centroid), in Angstrom.
 *
 * This is explicitly not the centre of mass: unweighted coordinates treat a
 * hydrogen and a heavy atom alike.
 */
export function centroidOf(atoms: readonly SceneAtom[]): XYZ {
  if (!atoms.length) throw new EmptyAtomSubsetError('Centroid');
  assertUnambiguousAtoms(atoms);
  let x = 0;
  let y = 0;
  let z = 0;
  for (const atom of atoms) {
    const position = assertFiniteXYZ(atom.position, `Atom ${atomKey(atom.identity)}`);
    x += position.x;
    y += position.y;
    z += position.z;
  }
  return { x: x / atoms.length, y: y / atoms.length, z: z / atoms.length };
}

/**
 * True mass-weighted centre of mass, in Angstrom.
 *
 * Only atoms with a verified element mass participate. A selected hydrogen is
 * included or excluded by the caller's explicit policy. An empty subset, a
 * missing mass, a non-finite coordinate, or two alternate conformers of one
 * atom all raise rather than producing a plausible-looking number.
 */
export function centerOfMassOf(atoms: readonly SceneAtom[], options: CenterOfMassOptions): XYZ {
  if (!atoms.length) throw new EmptyAtomSubsetError('Center of mass');
  const policy = options?.hydrogenPolicy;
  if (policy !== 'include' && policy !== 'exclude') {
    throw new MolecularSceneError('Center of mass requires an explicit hydrogen policy.');
  }
  assertUnambiguousAtoms(atoms);
  let mass = 0;
  let x = 0;
  let y = 0;
  let z = 0;
  let weighted = 0;
  for (const atom of atoms) {
    if (policy === 'exclude' && isHydrogen(atom.element)) continue;
    const atomMass = atomicMass(atom.element);
    if (atomMass === undefined) throw new MissingAtomicMassError(atom.element);
    const position = assertFiniteXYZ(atom.position, `Atom ${atomKey(atom.identity)}`);
    mass += atomMass;
    x += atomMass * position.x;
    y += atomMass * position.y;
    z += atomMass * position.z;
    weighted += 1;
  }
  if (!weighted || mass <= 0) throw new EmptyAtomSubsetError('Center of mass');
  return { x: x / mass, y: y / mass, z: z / mass };
}

/**
 * Axis-aligned bounding box of a set of Angstrom positions.
 *
 * The box is returned as a centre plus full side lengths; a zero length is a
 * legitimate degenerate box (a single atom), a negative length is not.
 */
export function axisAlignedBoxOf(atoms: readonly SceneAtom[]): AxisAlignedBox {
  if (!atoms.length) throw new EmptyAtomSubsetError('Bounding box');
  assertUnambiguousAtoms(atoms);
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;
  for (const atom of atoms) {
    const position = assertFiniteXYZ(atom.position, `Atom ${atomKey(atom.identity)}`);
    minX = Math.min(minX, position.x); maxX = Math.max(maxX, position.x);
    minY = Math.min(minY, position.y); maxY = Math.max(maxY, position.y);
    minZ = Math.min(minZ, position.z); maxZ = Math.max(maxZ, position.z);
  }
  return {
    center: { x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2 },
    lengths: { x: maxX - minX, y: maxY - minY, z: maxZ - minZ },
  };
}

/** A box around an explicit centre, for callers that initialized a COM themselves. */
export function boxAt(center: XYZ, lengths: XYZ): AxisAlignedBox {
  return assertAxisAlignedBox({ center, lengths });
}

// ---------------------------------------------------------------------------
// Selection/event contract and form/viewer synchronization.
// ---------------------------------------------------------------------------

export type SceneOrigin = 'form' | 'viewer';

export interface SceneTopologyReference {
  revision: number;
  digest: string;
}

export interface SceneMutationMeta {
  origin?: SceneOrigin;
  /** Correlates a mutation with the event it produces; echoes reuse it. */
  transactionId?: string;
  /** Refuse to apply a selector captured from a different topology. */
  expectedTopology?: SceneTopologyReference;
}

export interface SceneSelection {
  atoms: SceneAtom[];
  residues: SelectedResidue[];
}

export interface SceneSnapshot {
  topologyRevision: number;
  topologyDigest: string;
  /** Active trajectory frame; the reference topology is revision/digest. */
  coordinateFrame: number;
  units: CoordinateUnits;
  selectedAtoms: SceneAtom[];
  selectedResidues: SelectedResidue[];
}

interface SceneEventBase {
  origin: SceneOrigin;
  transactionId: string;
  topologyRevision: number;
  topologyDigest: string;
  coordinateFrame: number;
}

export interface SceneSelectionEvent extends SceneEventBase {
  type: 'selection';
  selectedAtoms: SceneAtom[];
  selectedResidues: SelectedResidue[];
}

export interface SceneFrameEvent extends SceneEventBase {
  type: 'frame';
}

export interface SceneCrosshairEvent extends SceneEventBase {
  type: 'crosshair';
  crosshair: XYZ | null;
}

export interface SceneBoxEvent extends SceneEventBase {
  type: 'box';
  box: AxisAlignedBox | null;
}

export interface SceneTopologyEvent extends SceneEventBase {
  type: 'topology';
}

export type MolecularSceneEvent =
  | SceneSelectionEvent
  | SceneFrameEvent
  | SceneCrosshairEvent
  | SceneBoxEvent
  | SceneTopologyEvent;

/** True when an event is the echo of the mutation this listener just applied. */
export function isSelfEcho(
  event: { origin: SceneOrigin; transactionId: string },
  applied: { origin: SceneOrigin; transactionId: string } | null,
): boolean {
  return applied !== null && event.origin === applied.origin && event.transactionId === applied.transactionId;
}

/**
 * The typed scene operations.
 *
 * `MolecularViewer` implements this interface; Result and Create Task consumers
 * receive it through the narrow viewer contract rather than reaching into Mol*.
 */
export interface MolecularScene {
  readonly units: CoordinateUnits;
  snapshot(): SceneSnapshot;
  subscribe(listener: (event: MolecularSceneEvent) => void): () => void;
  lastEvent(): MolecularSceneEvent | null;
  select(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  clearSelection(meta?: SceneMutationMeta): void;
  setHighlight(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  clearHighlight(): void;
  focus(selection: MolecularSelection, meta?: SceneMutationMeta): boolean;
  getCrosshair(): XYZ | null;
  setCrosshair(point: XYZ | null, meta?: SceneMutationMeta): XYZ | null;
  getBox(): AxisAlignedBox | null;
  setBox(box: AxisAlignedBox | null, meta?: SceneMutationMeta): AxisAlignedBox | null;
  centroid(atoms?: readonly SceneAtom[]): XYZ;
  centerOfMass(options: CenterOfMassOptions, atoms?: readonly SceneAtom[]): XYZ;
  boundingBox(atoms?: readonly SceneAtom[]): AxisAlignedBox;
  /** Every atom in the active frame, so a whole-structure COM is an explicit call. */
  allAtoms(): SceneAtom[];
  /** Read the current selection through a latest-request gate. */
  pickAtoms(): Promise<SceneAtom[]>;
}

/** An explicit initialization; `null` means "no overlay", never the origin. */
export interface SceneInitialization {
  crosshair: XYZ | null;
  box: AxisAlignedBox | null;
}

/**
 * The latest-request gate used for asynchronous atom picks.
 *
 * Every pick begins a generation; a result whose generation is no longer the
 * latest is discarded. A superseded read is cancelled, not raced.
 */
export class LatestRequestGate {
  private generation = 0;

  begin(): number {
    this.generation += 1;
    return this.generation;
  }

  isCurrent(token: number): boolean {
    return token === this.generation;
  }

  cancel(): void {
    this.generation += 1;
  }
}

/**
 * Mutable read model of the scene state.
 *
 * `MolecularViewer` is the only writer to Mol*; this state publishes the
 * snapshot and events every consumer reads. It never queries or mutates Mol*.
 */
export class SceneState {
  readonly units: CoordinateUnits = ANGSTROM;
  private topology: TopologyIdentity = { revision: 0, digest: '', label: '' };
  private frame = 0;
  private selection: SceneSelection = { atoms: [], residues: [] };
  private crosshair: XYZ | null = null;
  private box: AxisAlignedBox | null = null;
  private readonly listeners = new Set<(event: MolecularSceneEvent) => void>();
  private transaction = 0;
  private lastSelectionSignature = '';
  private pendingEchoSignature: string | null = null;
  private externalMutations = 0;
  private latest: MolecularSceneEvent | null = null;
  private readonly pickGate = new LatestRequestGate();

  topologyIdentity(): TopologyIdentity {
    return { ...this.topology };
  }

  coordinateFrame(): number {
    return this.frame;
  }

  lastEvent(): MolecularSceneEvent | null {
    return this.latest;
  }

  subscribe(listener: (event: MolecularSceneEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): SceneSnapshot {
    return {
      topologyRevision: this.topology.revision,
      topologyDigest: this.topology.digest,
      coordinateFrame: this.frame,
      units: this.units,
      selectedAtoms: this.selection.atoms.map(cloneAtom),
      selectedResidues: this.selection.residues.map(residue => ({ ...residue })),
    };
  }

  selectedAtoms(): SceneAtom[] {
    return this.selection.atoms.map(cloneAtom);
  }

  /** Refuse a selector captured from a different topology before touching Mol*. */
  verifyTopology(expected?: SceneTopologyReference): void {
    this.assertCurrent(expected);
  }

  /** Refresh cached coordinates after a frame change without publishing a selection. */
  refreshSelection(selection: SceneSelection): void {
    this.applySelection(selection);
  }

  /** A new source is loaded: invalidate selectors and overlays, publish identity. */
  topologyChanged(topology: { digest: string; label?: string }): void {
    this.topology = {
      revision: this.topology.revision + 1,
      digest: String(topology.digest || ''),
      label: String(topology.label || ''),
    };
    this.frame = 0;
    this.selection = { atoms: [], residues: [] };
    this.crosshair = null;
    this.box = null;
    this.lastSelectionSignature = '';
    this.pendingEchoSignature = null;
    this.emit({ ...this.eventBase('viewer'), type: 'topology' });
    // Selection is part of the old topology; publish the empty replacement so
    // every consumer drops its view of the previous chain/residue addresses.
    this.publishSelection('viewer');
  }

  setFrame(frame: number): void {
    const next = Number.isFinite(frame) ? Math.max(0, Math.trunc(frame)) : 0;
    if (next === this.frame) return;
    this.frame = next;
    this.emit({ ...this.eventBase('viewer'), type: 'frame' });
  }

  /**
   * Apply a form-originated selection. `expectedTopology` is refused when stale:
   * a chain ID from an older topology is never remapped onto the new one.
   */
  selectFromForm(selection: SceneSelection, meta: SceneMutationMeta = {}): boolean {
    this.assertCurrent(meta.expectedTopology);
    this.applySelection(selection);
    const signature = this.publishSelection(meta.origin ?? 'form', meta.transactionId);
    this.pendingEchoSignature = signature;
    return selection.atoms.length > 0 || selection.residues.length > 0;
  }

  /**
   * Adopt a selection produced by Mol* interaction. The echo of the form's own
   * mutation is consumed without emitting a second event.
   */
  adoptViewerSelection(selection: SceneSelection): boolean {
    if (this.externalMutations > 0) return false;
    const signature = selectionSignature(selection.residues, selection.atoms);
    if (this.pendingEchoSignature !== null && signature === this.pendingEchoSignature) {
      this.pendingEchoSignature = null;
      return false;
    }
    this.pendingEchoSignature = null;
    if (signature === this.lastSelectionSignature) return false;
    this.applySelection(selection);
    this.publishSelection('viewer');
    return true;
  }

  /** Mark a synchronous Mol* mutation whose own change notification is expected. */
  beginExternalMutation(): void {
    this.externalMutations += 1;
  }

  endExternalMutation(): void {
    this.externalMutations = Math.max(0, this.externalMutations - 1);
  }

  clearSelection(meta: SceneMutationMeta = {}): void {
    this.assertCurrent(meta.expectedTopology);
    this.selection = { atoms: [], residues: [] };
    this.publishSelection(meta.origin ?? 'form', meta.transactionId);
  }

  setCrosshair(point: XYZ | null, meta: SceneMutationMeta = {}): XYZ | null {
    this.assertCurrent(meta.expectedTopology);
    const next = point === null ? null : assertFiniteXYZ(point, 'Crosshair');
    this.crosshair = next;
    this.emit({ ...this.eventBase(meta.origin ?? 'form'), type: 'crosshair', crosshair: next ? { ...next } : null });
    return next ? { ...next } : null;
  }

  getCrosshair(): XYZ | null {
    return this.crosshair ? { ...this.crosshair } : null;
  }

  setBox(box: AxisAlignedBox | null, meta: SceneMutationMeta = {}): AxisAlignedBox | null {
    this.assertCurrent(meta.expectedTopology);
    const next = box === null ? null : assertAxisAlignedBox(box);
    this.box = next;
    this.emit({ ...this.eventBase(meta.origin ?? 'form'), type: 'box', box: next ? cloneBox(next) : null });
    return next ? cloneBox(next) : null;
  }

  getBox(): AxisAlignedBox | null {
    return this.box ? cloneBox(this.box) : null;
  }

  /** Explicit initialization of overlays; callers state their choice. */
  initialize(init: SceneInitialization): void {
    this.crosshair = init.crosshair === null ? null : assertFiniteXYZ(init.crosshair, 'Crosshair');
    this.box = init.box === null ? null : assertAxisAlignedBox(init.box);
    this.emit({ ...this.eventBase('form'), type: 'crosshair', crosshair: this.getCrosshair() });
    this.emit({ ...this.eventBase('form'), type: 'box', box: this.getBox() });
  }

  centroid(atoms?: readonly SceneAtom[]): XYZ {
    return centroidOf(atoms ?? this.selection.atoms);
  }

  centerOfMass(options: CenterOfMassOptions, atoms?: readonly SceneAtom[]): XYZ {
    return centerOfMassOf(atoms ?? this.selection.atoms, options);
  }

  boundingBox(atoms?: readonly SceneAtom[]): AxisAlignedBox {
    return axisAlignedBoxOf(atoms ?? this.selection.atoms);
  }

  /** A latest-request read: a superseded pick rejects rather than racing. */
  async pickAtoms(): Promise<SceneAtom[]> {
    const token = this.pickGate.begin();
    const atoms = this.selectedAtoms();
    await Promise.resolve();
    if (!this.pickGate.isCurrent(token)) throw new DOMException('Atom pick was superseded.', 'AbortError');
    return atoms;
  }

  cancelPicks(): void {
    this.pickGate.cancel();
  }

  private assertCurrent(expected?: SceneTopologyReference): void {
    if (!expected) return;
    if (expected.revision !== this.topology.revision || expected.digest !== this.topology.digest) {
      throw new StaleTopologyError(expected, this.topology);
    }
  }

  private applySelection(selection: SceneSelection): void {
    this.selection = {
      atoms: selection.atoms.map(cloneAtom),
      residues: selection.residues.map(residue => ({ ...residue })),
    };
  }

  private publishSelection(origin: SceneOrigin, transactionId?: string): string {
    const signature = selectionSignature(this.selection.residues, this.selection.atoms);
    this.lastSelectionSignature = signature;
    const base = this.eventBase(origin);
    this.emit({
      ...base,
      type: 'selection',
      transactionId: transactionId ?? base.transactionId,
      selectedAtoms: this.selection.atoms.map(cloneAtom),
      selectedResidues: this.selection.residues.map(residue => ({ ...residue })),
    });
    return signature;
  }

  private nextTransactionId(): string {
    this.transaction += 1;
    return `scene-${this.transaction}`;
  }

  private eventBase(origin: SceneOrigin): SceneEventBase {
    return {
      origin,
      transactionId: this.nextTransactionId(),
      topologyRevision: this.topology.revision,
      topologyDigest: this.topology.digest,
      coordinateFrame: this.frame,
    };
  }

  private emit(event: MolecularSceneEvent): void {
    this.latest = event;
    this.listeners.forEach(listener => listener(event));
  }
}

function cloneAtom(atom: SceneAtom): SceneAtom {
  return {
    identity: { ...atom.identity },
    element: atom.element,
    position: { ...atom.position },
  };
}

function cloneBox(box: AxisAlignedBox): AxisAlignedBox {
  return { center: { ...box.center }, lengths: { ...box.lengths } };
}

/**
 * A stable, deterministic digest of source bytes.
 *
 * SHA-256 is used where the platform exposes Web Crypto (including every secure
 * origin); a non-secure local-file origin falls back to a prefixed FNV-1a so the
 * identity still changes with the source instead of becoming empty.
 */
export async function structuralDigest(data: string | Uint8Array): Promise<string> {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    // Copy into a plain ArrayBuffer view: Web Crypto's BufferSource does not
    // accept a SharedArrayBuffer-backed view in every TypeScript/lib version.
    const payload = new Uint8Array(bytes.length);
    payload.set(bytes);
    const hash = await subtle.digest('SHA-256', payload.buffer);
    return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  let hash = 0x811c9dc5;
  for (const byte of bytes) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `fnv1a-${hash.toString(16).padStart(8, '0')}-${bytes.length}`;
}
