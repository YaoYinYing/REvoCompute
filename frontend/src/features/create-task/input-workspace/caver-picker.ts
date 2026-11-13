/*
 * CAVER start-point projection.
 *
 * The owning `task.yaml` declares the canonical `start_point_*` vocabulary.
 * This module is the only place that maps a typed viewer selection onto those
 * values. It is pure so the mapping can be tested without mounting Mol*: the
 * DOM controller below it owns the panel and the viewer synchronization.
 *
 * A native residue/ligand/group selection is passed through as CAVER's own
 * residue directive. Converting that selection to an explicit XYZ point is a
 * different scientific choice: the point is written in point mode with the
 * selected authored residues, atom serials, reference digest and the coordinate
 * method that produced it.
 */
import {
  centroidOf,
  centerOfMassOf,
  type CenterOfMassOptions,
  type MolecularSelection,
  type SceneAtom,
  type SelectedResidue,
  type XYZ,
} from '../../structure/molecular-scene';
import type { WorkspaceContext } from './plugin-contract';
import { element } from './utils';
import { t } from '../../../app/i18n';
import type { SceneSnapshot } from '../../structure/molecular-scene';

export type CaverMode = 'point' | 'atom' | 'residue' | 'group' | 'ligand';
export type CaverPointSource = 'manual' | 'viewer-crosshair' | 'centroid' | 'com';
export type CaverCoordinateMethod = 'centroid' | 'com';

export const CAVER_MODES: readonly CaverMode[] = ['point', 'atom', 'residue', 'group', 'ligand'];

/** Largest residue count one group or converted selection may address. */
export const CAVER_MAX_GROUP_RESIDUES = 1000;

export interface CaverResidueTerm {
  /** Authored chain; '' is the blank chain and is emitted as `_`. */
  chain: string;
  start: number;
  end: number;
}

export type CaverParameterResult =
  | { params: Record<string, string> }
  | { error: string };

const GROUP_TERM = /^(?<chain>[A-Za-z0-9_]):(?<start>[0-9]+)(?:-(?<end>[0-9]+))?$/;

/** The mode the canonical parameters name; unknown values are not guessed. */
export function caverMode(parameters: Record<string, string>): CaverMode | null {
  const mode = parameters.start_point_mode as CaverMode | undefined;
  return mode && CAVER_MODES.includes(mode) ? mode : null;
}

/**
 * Parse CAVER's `CHAIN:RESIDUE` / `CHAIN:START-END` comma list.
 *
 * The Runner splits on commas only and refuses descending or oversized ranges,
 * so this parser does the same and reports the same reasons.
 */
export function parseCaverTerms(spec: string): { terms: CaverResidueTerm[] } | { error: string } {
  const raw = spec.split(',').map(term => term.trim()).filter(Boolean);
  if (!raw.length) return { error: 'Name at least one chain:residue term.' };
  const terms: CaverResidueTerm[] = [];
  for (const term of raw) {
    const match = GROUP_TERM.exec(term);
    if (!match) return { error: `${term} is not CHAIN:RESIDUE or CHAIN:START-END.` };
    const start = Number(match.groups!.start);
    const end = Number(match.groups!.end ?? match.groups!.start);
    if (end < start) return { error: `${term} has a descending residue range.` };
    const chain = match.groups!.chain ?? '';
    terms.push({ chain: chain === '_' ? '' : chain, start, end });
  }
  const total = terms.reduce((sum, term) => sum + term.end - term.start + 1, 0);
  if (total > CAVER_MAX_GROUP_RESIDUES) {
    return { error: `The selection names ${total} residues; the limit is ${CAVER_MAX_GROUP_RESIDUES}.` };
  }
  return { terms };
}

/** Canonical `CHAIN:R1-R2,CHAIN:R3` spelling of a group selection. */
export function caverGroupSpec(residues: readonly SelectedResidue[]): string {
  return residues.map(residue => `${residue.auth_chain || '_'}:${residue.auth_seq_id}`).join(',');
}

/** Expand parsed terms into authored viewer selectors (bare residues only). */
export function caverTermSelectors(terms: readonly CaverResidueTerm[]): MolecularSelection[] {
  const selectors: MolecularSelection[] = [];
  for (const term of terms) {
    for (let residue = term.start; residue <= term.end; residue += 1) {
      selectors.push({
        chain: term.chain || undefined,
        residue,
        numbering: 'auth_seq_id',
        // CAVER addresses bare residues only; an insertion-coded residue is a
        // different residue and must not be highlighted as the selection.
        insertionCode: '',
      });
    }
  }
  return selectors;
}

/** Project canonical parameters onto the viewer's selection and crosshair. */
export function caverParameterSelection(parameters: Record<string, string>): {
  residues: MolecularSelection[];
  point: XYZ | null;
} {
  const mode = caverMode(parameters);
  if (mode === 'point') {
    const coordinates = [parameters.start_x, parameters.start_y, parameters.start_z].map(Number);
    return {
      residues: [],
      point: coordinates.every(Number.isFinite)
        ? { x: coordinates[0]!, y: coordinates[1]!, z: coordinates[2]! }
        : null,
    };
  }
  if (mode === 'group') {
    const parsed = parseCaverTerms(parameters.start_group || '');
    return { residues: 'terms' in parsed ? caverTermSelectors(parsed.terms) : [], point: null };
  }
  if (mode === 'residue' || mode === 'ligand' || mode === 'atom') {
    const number = Number(parameters.start_residue_number);
    if (Number.isInteger(number)) {
      return {
        residues: [{
          chain: parameters.start_chain || undefined,
          residue: number,
          numbering: 'auth_seq_id',
          insertionCode: '',
        }],
        point: null,
      };
    }
  }
  return { residues: [], point: null };
}

/** Reject identities CAVER's residue directives cannot address. */
function unaddressable(residues: readonly SelectedResidue[]): string | null {
  if (!residues.length) return 'Select one residue, multiple residues, or one ligand.';
  if (residues.some(residue => residue.insertion_code)) {
    return 'CAVER cannot address an insertion-coded residue; choose the residue that shares its number without a code.';
  }
  if (residues.some(residue => !residue.auth_chain)) {
    return 'CAVER cannot address a chainless residue next to named chains; choose a residue in a named chain.';
  }
  return null;
}

/** Empty start-point fields, so a mode change never leaves a stale identity. */
function clearStartFields(parameters: Record<string, string>): Record<string, string> {
  return {
    start_chain: '',
    start_residue_number: '',
    start_atom_name: '',
    start_altloc: '',
    start_residue_name: '',
    start_group: '',
    start_x: '',
    start_y: '',
    start_z: '',
    start_point_source: 'manual',
    start_reference_sha256: '',
    start_selected_residues: '',
    start_selected_serials: '',
    start_com_hydrogen_policy: 'include',
    ...parameters,
  };
}

/** Map a viewer selection onto CAVER's native residue, ligand or group mode. */
export function caverSelectionParameters(residues: readonly SelectedResidue[]): CaverParameterResult {
  const problem = unaddressable(residues);
  if (problem) return { error: problem };
  if (residues.length === 1) {
    const residue = residues[0]!;
    if (residue.hetero) {
      return {
        params: clearStartFields({
          start_point_mode: 'ligand',
          start_chain: residue.auth_chain,
          start_residue_number: String(residue.auth_seq_id),
          start_residue_name: residue.residue_name,
        }),
      };
    }
    return {
      params: clearStartFields({
        start_point_mode: 'residue',
        start_chain: residue.auth_chain,
        start_residue_number: String(residue.auth_seq_id),
      }),
    };
  }
  return {
    params: clearStartFields({
      start_point_mode: 'group',
      start_group: caverGroupSpec(residues),
    }),
  };
}

/** Serial ranges as the Runner parses them (`N` or `N-M`, comma separated). */
export function serialRanges(atoms: readonly SceneAtom[]): string {
  const serials = [...new Set(atoms.map(atom => atom.identity.atomSerial))].sort((left, right) => left - right);
  const ranges: string[] = [];
  let start = serials[0];
  let previous = start;
  for (const serial of serials.slice(1)) {
    if (serial === previous! + 1) {
      previous = serial;
      continue;
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`);
    start = serial;
    previous = serial;
  }
  if (start !== undefined) ranges.push(start === previous ? String(start) : `${start}-${previous}`);
  return ranges.join(',');
}

export function isSha256Digest(value: string): boolean {
  return /^[0-9a-f]{64}$/.test(value);
}

/**
 * Write an explicit XYZ point derived from the selected atoms.
 *
 * `centroid` is the arithmetic mean of the selected atoms. `com` is the
 * mass-weighted centre of mass under an explicit hydrogen policy. Both are
 * point mode: CAVER's own residue/group centre is a different quantity and is
 * never labelled centre of mass.
 *
 * The Task requires a 64-character reference digest for these two sources, so
 * a browser without Web Crypto (a non-secure origin) cannot submit them: the
 * digest would fall back to the non-SHA-256 `fnv1a-` form. Refuse here with a
 * clear reason instead of writing an empty value the server must reject.
 */
export function caverExplicitPoint(
  residues: readonly SelectedResidue[],
  atoms: readonly SceneAtom[],
  method: CaverCoordinateMethod,
  referenceDigest: string,
  hydrogenPolicy: CenterOfMassOptions['hydrogenPolicy'] = 'include',
): CaverParameterResult {
  const problem = unaddressable(residues);
  if (problem) return { error: problem };
  if (!atoms.length) return { error: 'The selection resolves to no atoms.' };
  if (!isSha256Digest(referenceDigest)) {
    return {
      error: 'Centroid and center-of-mass points need a SHA-256 reference digest, '
        + 'which this browser cannot compute without HTTPS. Open the task over HTTPS and try again.',
    };
  }
  let point: XYZ;
  try {
    point = method === 'centroid'
      ? centroidOf(atoms)
      : centerOfMassOf(atoms, { hydrogenPolicy });
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
  const params = clearStartFields({
    start_point_mode: 'point',
    start_x: String(point.x),
    start_y: String(point.y),
    start_z: String(point.z),
    start_point_source: method,
    start_selected_residues: caverGroupSpec(residues),
    start_selected_serials: serialRanges(atoms),
    start_com_hydrogen_policy: method === 'com' ? hydrogenPolicy : 'include',
    start_reference_sha256: referenceDigest,
  });
  return { params };
}

/**
 * Place the point-mode crosshair from a viewer selection.
 *
 * The coordinates are the geometric centroid of the selected atoms. The
 * selected identities travel with them, so the Runner can audit membership;
 * the user may still edit the coordinates, which switches the source to manual.
 */
export function caverCrosshairPoint(
  residues: readonly SelectedResidue[],
  atoms: readonly SceneAtom[],
  referenceDigest: string,
): CaverParameterResult {
  const problem = unaddressable(residues);
  if (problem) return { error: problem };
  if (!atoms.length) return { error: 'The selection resolves to no atoms.' };
  let point: XYZ;
  try {
    point = centroidOf(atoms);
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
  return {
    params: clearStartFields({
      start_point_mode: 'point',
      start_x: String(point.x),
      start_y: String(point.y),
      start_z: String(point.z),
      start_point_source: 'viewer-crosshair',
      start_selected_residues: caverGroupSpec(residues),
      start_selected_serials: serialRanges(atoms),
      start_reference_sha256: isSha256Digest(referenceDigest) ? referenceDigest : '',
    }),
  };
}

/** Atoms that belong to one authored residue identity. */
export function residueAtoms(atoms: readonly SceneAtom[], residue: SelectedResidue): SceneAtom[] {
  return atoms.filter(atom => atom.identity.authChain === residue.auth_chain
    && atom.identity.authSeqId === residue.auth_seq_id
    && (atom.identity.insertionCode || '') === (residue.insertion_code || '')
    && atom.identity.residueName === residue.residue_name);
}

/** One atom's authored identity as the canonical atom-mode parameters. */
export function caverAtomParameters(
  residue: SelectedResidue,
  atom: SceneAtom,
  allAtoms: readonly SceneAtom[],
): CaverParameterResult {
  const problem = unaddressable([residue]);
  if (problem) return { error: problem };
  if (!residueAtoms(allAtoms, residue).some(candidate => candidate.identity.index === atom.identity.index)) {
    return { error: 'The chosen atom does not belong to the selected residue.' };
  }
  const shared = allAtoms.filter(candidate => candidate.identity.atomSerial === atom.identity.atomSerial);
  if (shared.length > 1) {
    return {
      error: `Atom serial ${atom.identity.atomSerial} is shared by ${shared.length} atoms; CAVER would renumber the duplicate, so the pick is ambiguous.`,
    };
  }
  const sameName = residueAtoms(allAtoms, residue).filter(candidate => candidate.identity.atomName === atom.identity.atomName);
  if (sameName.length > 1 && !atom.identity.altloc) {
    return {
      error: `Atom ${atom.identity.atomName} has ${sameName.length} conformers; choose the alternate location explicitly.`,
    };
  }
  return {
    params: clearStartFields({
      start_point_mode: 'atom',
      start_chain: residue.auth_chain,
      start_residue_number: String(residue.auth_seq_id),
      start_atom_name: atom.identity.atomName,
      start_altloc: atom.identity.altloc || '',
    }),
  };
}

/** True when the form owns the CAVER start-point vocabulary. */
export function isCaverForm(parameterNames: Iterable<string>): boolean {
  return [...parameterNames].includes('start_point_mode');
}

export type { SceneAtom, SelectedResidue, XYZ };

// ---------------------------------------------------------------------------
// Panel controller: the only writer of CAVER start-point parameters.
// ---------------------------------------------------------------------------

/** The narrow scene surface the CAVER panel consumes. */
export interface CaverViewer {
  allAtoms(): SceneAtom[];
  snapshot(): SceneSnapshot;
  select(selection: MolecularSelection): boolean;
  setCrosshair(point: XYZ | null): XYZ | null;
  annotate(annotation: { point: XYZ; label: string } | null): void;
  focus(selection: MolecularSelection): boolean;
  pickAtoms(): Promise<SceneAtom[]>;
}

const MODE_FIELDS: Record<CaverMode, readonly string[]> = {
  point: ['start_x', 'start_y', 'start_z'],
  atom: ['start_chain', 'start_residue_number', 'start_atom_name', 'start_altloc'],
  residue: ['start_chain', 'start_residue_number'],
  group: ['start_group'],
  ligand: ['start_chain', 'start_residue_number', 'start_residue_name'],
};

const ALL_START_FIELDS = [
  'start_chain', 'start_residue_number', 'start_atom_name', 'start_altloc',
  'start_residue_name', 'start_group', 'start_x', 'start_y', 'start_z',
] as const;

/** Provenance fields the panel writes; the parameter grid hides them. */
const METADATA_FIELDS = [
  'start_point_source', 'start_reference_sha256',
  'start_selected_residues', 'start_selected_serials',
  'start_com_hydrogen_policy',
] as const;

interface DerivedPoint {
  x: number;
  y: number;
  z: number;
}

export interface CaverPickerOptions {
  viewer(): CaverViewer | null;
}

/**
 * One concise start-point panel.
 *
 * The panel never invents parameter names: every value it writes is one the
 * owning `task.yaml` declares. Native selections keep CAVER's residue, ligand
 * or group semantics; explicit centroid/COM conversions switch to point mode
 * and record the atoms and method they used.
 */
export class CaverPicker {
  private readonly panel: HTMLElement;
  private readonly modeLabel: HTMLElement;
  private readonly sourceLabel: HTMLElement;
  private readonly pointLabel: HTMLElement;
  private readonly status: HTMLElement;
  private readonly actions: HTMLElement;
  private readonly names = element('datalist');
  private selection: SelectedResidue[] = [];
  private atoms: SceneAtom[] = [];
  private error: string | null = null;
  private derived: DerivedPoint | null = null;
  private appliedSignature = '';
  private generation = 0;
  private topologyRevision = -1;
  private destroyed = false;

  constructor(
    private readonly context: WorkspaceContext,
    private readonly options: CaverPickerOptions,
  ) {
    this.names.id = 'ct-caver-residue-names';
    this.modeLabel = element('span', 'ct-caver-mode');
    this.sourceLabel = element('dd', 'ct-caver-source', '—');
    this.pointLabel = element('dd', 'ct-caver-point', '—');
    this.status = element('p', 'ct-caver-status');
    this.status.setAttribute('role', 'status');
    this.status.setAttribute('aria-live', 'polite');
    const reset = element('button', 'ct-caver-reset', t('ct.caver.reset'));
    reset.type = 'button';
    reset.addEventListener('click', () => this.reset());
    const heading = element('div', 'ct-caver-heading');
    heading.append(element('span', 'ct-caver-title', t('ct.caver.title')), this.modeLabel, reset);
    const readout = element('dl', 'ct-caver-readout');
    const source = element('div', 'ct-caver-readout-row');
    source.append(element('dt', '', t('ct.caver.source')), this.sourceLabel);
    const point = element('div', 'ct-caver-readout-row');
    point.append(element('dt', '', t('ct.caver.point')), this.pointLabel);
    readout.append(source, point);
    this.actions = element('div', 'ct-caver-actions');
    this.panel = element('section', 'ct-caver-picker');
    this.panel.setAttribute('aria-label', t('ct.caver.title'));
    this.panel.append(heading, this.status, readout, this.actions, this.names);
  }

  mount(target: HTMLElement): void {
    target.append(this.panel);
    this.render();
  }

  /**
   * A new reference structure resets every topology-derived value.
   *
   * A file-only edit also invalidates the start-point parameters, because they
   * name identities in the old topology. A preset writes its files and
   * parameters together, so `preset` keeps those parameters and only re-derives
   * the viewer state once the new structure has loaded.
   */
  topologyChanged(preset = false): void {
    this.generation += 1;
    this.selection = [];
    this.atoms = [];
    this.appliedSignature = '';
    this.error = null;
    this.topologyRevision = -1;
    this.names.replaceChildren();
    if (preset) {
      // Restored coordinates are the canonical value, not a user edit, so
      // `derived` must match them or the next refresh would demote them to a
      // manual point and drop their provenance.
      const parameters = this.context.parameters();
      const point = {
        x: Number(parameters.start_x),
        y: Number(parameters.start_y),
        z: Number(parameters.start_z),
      };
      this.derived = caverMode(parameters) === 'point' && [point.x, point.y, point.z].every(Number.isFinite)
        ? point
        : null;
    } else {
      this.derived = null;
      this.writeParams(clearStartFields({ start_point_mode: this.mode() ?? 'point' }));
    }
    this.context.changed();
  }

  /** A viewer-originated selection, already normalized by the shared scene. */
  selectionChanged(residues: SelectedResidue[]): void {
    const viewer = this.options.viewer();
    if (!viewer || this.destroyed) return;
    const generation = ++this.generation;
    this.selection = [...residues];
    this.context.setStructureSelections(residues);
    void viewer.pickAtoms().then(atoms => {
      if (this.destroyed || generation !== this.generation) return;
      this.atoms = atoms;
      this.applySelection();
      this.context.changed();
    }).catch((error: unknown) => {
      if (this.destroyed || generation !== this.generation) return;
      if (error instanceof DOMException && error.name === 'AbortError') return;
      this.fail(error instanceof Error ? error.message : String(error));
    });
  }

  /** Re-project the canonical parameters onto the viewer and the panel. */
  refresh(): void {
    if (this.destroyed) return;
    this.ensureMetadataControls();
    const viewer = this.options.viewer();
    if (!viewer) { this.render(); return; }
    const snapshot = viewer.snapshot();
    if (snapshot.topologyRevision !== this.topologyRevision) {
      this.topologyRevision = snapshot.topologyRevision;
      this.generation += 1;
      // The viewer dropped its selection with the old topology, so re-derive it
      // from the canonical parameters even when their signature did not change.
      this.appliedSignature = '';
    }
    this.syncResidueNames(viewer);
    this.sanitizeMode();
    this.promoteEditedCoordinates();
    const selected = caverParameterSelection(this.context.parameters());
    const signature = JSON.stringify(selected);
    if (signature !== this.appliedSignature) {
      const target = selected.residues.length === 1 ? selected.residues[0]! : { residues: selected.residues };
      // The structure may still be loading; a select the viewer rejected must
      // not be recorded as applied, or the next refresh would skip it.
      if (selected.residues.length && !viewer.select(target)) {
        this.render();
        return;
      }
      this.appliedSignature = signature;
      if (selected.residues.length) viewer.focus(target);
      viewer.setCrosshair(selected.point);
      viewer.annotate(selected.point ? { point: selected.point, label: t('ct.caver.crosshair') } : null);
    }
    this.render();
  }

  validate(): string | null {
    return this.error;
  }

  destroy(): void {
    this.destroyed = true;
    this.generation += 1;
    this.panel.remove();
  }

  private mode(): CaverMode | null {
    return caverMode(this.context.parameters());
  }

  private ensureMetadataControls(): void {
    // The panel writes these provenance values but does not ask the user to
    // edit them. The owning schema declares them, so they keep a control (and
    // therefore a collected value) while the visible parameter field is hidden.
    for (const name of METADATA_FIELDS) {
      if (!this.context.form.params.some(parameter => parameter.name === name)) continue;
      let control = document.querySelector(`[data-ct-parameter="${CSS.escape(name)}"]`);
      if (!control) {
        const input = element('input');
        input.type = 'hidden';
        input.dataset.ctParameter = name;
        input.value = name === 'start_point_source' ? 'manual' : '';
        this.panel.append(input);
        control = input;
      }
      const field = control.closest('.ct-parameter');
      if (field instanceof HTMLElement) field.hidden = true;
    }
  }

  private sanitizeMode(): void {
    const mode = this.mode();
    if (!mode) return;
    const allowed = new Set(MODE_FIELDS[mode]);
    for (const name of ALL_START_FIELDS) {
      if (!allowed.has(name)) this.write(name, '');
    }
    if (mode !== 'point') {
      this.write('start_point_source', 'manual');
      this.write('start_selected_residues', '');
      this.write('start_selected_serials', '');
    }
  }

  /** Typing a coordinate makes the point manual, never a stale derived claim. */
  private promoteEditedCoordinates(): void {
    const parameters = this.context.parameters();
    if (caverMode(parameters) !== 'point') return;
    const source = parameters.start_point_source as CaverPointSource | undefined;
    if (!source || source === 'manual') return;
    const point = {
      x: Number(parameters.start_x),
      y: Number(parameters.start_y),
      z: Number(parameters.start_z),
    };
    if (![point.x, point.y, point.z].every(Number.isFinite)) return;
    const same = this.derived
      && Math.abs(point.x - this.derived.x) < 1e-9
      && Math.abs(point.y - this.derived.y) < 1e-9
      && Math.abs(point.z - this.derived.z) < 1e-9;
    if (same) return;
    this.write('start_point_source', 'manual');
    this.write('start_selected_residues', '');
    this.write('start_selected_serials', '');
    this.write('start_reference_sha256', '');
  }

  private syncResidueNames(viewer: CaverViewer): void {
    if (!viewer.allAtoms().length) return;
    const names = [...new Set(viewer.allAtoms().map(atom => atom.identity.residueName).filter(Boolean))].sort();
    const current = [...this.names.options].map(option => option.value);
    if (current.join('\n') === names.join('\n')) return;
    this.names.replaceChildren(...names.map(name => new Option(name, name)));
    for (const parameter of ['start_residue_name', 'include_residue_names', 'exclude_residue_names']) {
      const control = document.querySelector<HTMLInputElement>(`[data-ct-parameter="${CSS.escape(parameter)}"]`);
      if (control) control.setAttribute('list', this.names.id);
    }
  }

  private applySelection(): void {
    const mode = this.mode();
    if (!this.selection.length) {
      if (mode === 'point' && this.derived) return;
      this.error = null;
      this.render();
      return;
    }
    if (!mode) {
      // No mode has been chosen yet: a viewer pick infers CAVER's native
      // residue, ligand or group calculation, exactly as one selection does.
      this.commit(caverSelectionParameters(this.selection));
      return;
    }
    if (mode === 'atom') {
      // Atom mode needs an explicit choice from the atoms of one residue. Any
      // other selection invalidates the atom committed for the old residue: the
      // same atom name can exist in both, so keeping it would silently move the
      // target.
      this.error = null;
      if (this.context.parameters().start_atom_name
        && (this.selection.length !== 1 || !this.atomCommittedIn(this.selection[0]!))) {
        this.write('start_atom_name', '');
        this.write('start_altloc', '');
      }
      this.render();
      return;
    }
    if (mode === 'point') {
      const viewer = this.options.viewer();
      const result = caverCrosshairPoint(this.selection, this.atoms, viewer?.snapshot().topologyDigest || '');
      this.commit(result);
      return;
    }
    this.commit(caverSelectionParameters(this.selection));
  }

  private commit(result: CaverParameterResult): void {
    if ('error' in result) { this.fail(result.error); return; }
    this.error = null;
    const point = {
      x: Number(result.params.start_x),
      y: Number(result.params.start_y),
      z: Number(result.params.start_z),
    };
    this.derived = caverMode(result.params) === 'point' && [point.x, point.y, point.z].every(Number.isFinite)
      ? point
      : null;
    for (const [name, value] of Object.entries(result.params)) this.write(name, value);
    this.context.changed();
    this.render();
  }

  private applyMethod(method: CaverCoordinateMethod): void {
    const viewer = this.options.viewer();
    if (!viewer) return;
    if (!this.selection.length) { this.fail(t('ct.caver.selectFirst')); return; }
    const policy = this.context.parameters().start_com_hydrogen_policy === 'exclude' ? 'exclude' : 'include';
    const result = caverExplicitPoint(
      this.selection,
      this.atoms,
      method,
      viewer.snapshot().topologyDigest || '',
      policy,
    );
    if ('error' in result) { this.fail(result.error); return; }
    this.error = null;
    this.derived = {
      x: Number(result.params.start_x),
      y: Number(result.params.start_y),
      z: Number(result.params.start_z),
    };
    for (const [name, value] of Object.entries(result.params)) this.write(name, value);
    const point = this.derived;
    viewer.setCrosshair(point);
    viewer.annotate({ point, label: t('ct.caver.crosshair') });
    this.context.changed();
    this.render();
  }

  private applyNative(): void {
    if (!this.selection.length) { this.fail(t('ct.caver.selectFirst')); return; }
    const result = caverSelectionParameters(this.selection);
    if ('error' in result) { this.fail(result.error); return; }
    this.error = null;
    this.derived = null;
    for (const [name, value] of Object.entries(result.params)) this.write(name, value);
    this.options.viewer()?.setCrosshair(null);
    this.options.viewer()?.annotate(null);
    this.context.changed();
    this.render();
  }

  private applyAtom(atom: SceneAtom): void {
    if (this.selection.length !== 1) { this.fail(t('ct.caver.oneResidue')); return; }
    const viewer = this.options.viewer();
    const result = caverAtomParameters(this.selection[0]!, atom, viewer?.allAtoms() || []);
    if ('error' in result) { this.fail(result.error); return; }
    this.error = null;
    this.derived = null;
    for (const [name, value] of Object.entries(result.params)) this.write(name, value);
    viewer?.setCrosshair(atom.position);
    viewer?.annotate({ point: atom.position, label: t('ct.caver.crosshair') });
    this.context.changed();
    this.render();
  }

  private reset(): void {
    this.error = null;
    this.selection = [];
    this.atoms = [];
    this.derived = null;
    this.appliedSignature = '';
    const mode = this.mode() ?? 'point';
    this.writeParams(clearStartFields({ start_point_mode: mode }));
    this.context.setStructureSelections([]);
    const viewer = this.options.viewer();
    viewer?.select({ residues: [] });
    viewer?.setCrosshair(null);
    viewer?.annotate(null);
    this.context.changed();
    this.render();
  }

  private write(name: string, value: string): void {
    this.context.setParameter(name, value);
  }

  private writeParams(params: Record<string, string>): void {
    for (const [name, value] of Object.entries(params)) this.write(name, value);
  }

  private fail(message: string): void {
    this.error = message;
    this.render();
  }

  private render(): void {
    if (this.destroyed) return;
    const parameters = this.context.parameters();
    const mode = this.mode();
    this.modeLabel.textContent = mode ? t('ct.caver.mode', { mode }) : t('ct.caver.noMode');
    const source = mode && mode !== 'point'
      ? mode
      : (parameters.start_point_source || 'manual');
    this.sourceLabel.textContent = source;
    const x = Number(parameters.start_x);
    const y = Number(parameters.start_y);
    const z = Number(parameters.start_z);
    this.pointLabel.textContent = [x, y, z].every(Number.isFinite) && parameters.start_x !== ''
      ? `${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)} Å`
      : '—';
    this.status.textContent = this.error
      || (this.selection.length
        ? t('ct.caver.selection', { count: this.selection.length })
        : t('ct.caver.noSelection'));
    this.status.toggleAttribute('data-error', Boolean(this.error));
    this.renderActions(mode);
  }

  private renderActions(mode: CaverMode | null): void {
    this.actions.replaceChildren();
    if (!mode) return;
    if (mode === 'atom') {
      this.renderAtomPicker();
      return;
    }
    if (this.selection.length) {
      const policy = this.hydrogenPolicyControl();
      if (policy) this.actions.append(policy);
      this.actions.append(this.button(t('ct.caver.native'), () => this.applyNative()));
      if (mode !== 'point') {
        this.actions.append(
          this.button(t('ct.caver.centroid'), () => this.applyMethod('centroid')),
          this.button(t('ct.caver.com'), () => this.applyMethod('com')),
        );
      } else {
        this.actions.append(
          this.button(t('ct.caver.crosshairFromSelection'), () => this.applySelection()),
          this.button(t('ct.caver.centroid'), () => this.applyMethod('centroid')),
          this.button(t('ct.caver.com'), () => this.applyMethod('com')),
        );
      }
    }
  }

  private hydrogenPolicyControl(): HTMLElement | null {
    // The choices are the server's own enum, not a second vocabulary.
    const parameter = this.context.form.params.find(item => item.name === 'start_com_hydrogen_policy');
    if (!parameter || !parameter.choices.length) return null;
    const label = element('label', 'ct-caver-atom-label', t('ct.caver.hydrogens'));
    const select = element('select', 'ct-control');
    select.setAttribute('aria-label', t('ct.caver.hydrogens'));
    for (const choice of parameter.choices) {
      const value = String(choice);
      select.append(new Option(value === 'exclude' ? t('ct.caver.hydrogens.exclude') : t('ct.caver.hydrogens.include'), value));
    }
    select.value = this.context.parameters().start_com_hydrogen_policy === 'exclude' ? 'exclude' : 'include';
    select.addEventListener('change', () => {
      this.write('start_com_hydrogen_policy', select.value);
      if (this.context.parameters().start_point_source === 'com') this.applyMethod('com');
      else this.render();
    });
    label.append(select);
    return label;
  }

  /**
   * Whether the canonical atom names an atom in this residue.
   *
   * Atom mode records only the authored residue address, atom name and altloc.
   * A same-named atom in another residue is a different atom, so the option is
   * selected only when the residue address agrees too.
   *
   * The chain is optional in atom mode. An empty `start_chain` leaves the chain
   * to the Runner, so it must not invalidate the canonical atom. It names a
   * residue number rather than a chain, so when two chains carry that number one
   * chain's atom is never presented as the committed atom.
   */
  private atomCommittedIn(residue: SelectedResidue): boolean {
    const parameters = this.context.parameters();
    if (!parameters.start_atom_name
      || residue.insertion_code
      || parameters.start_residue_number !== String(residue.auth_seq_id)) return false;
    if (parameters.start_chain) return parameters.start_chain === residue.auth_chain;
    const chains = new Set(
      (this.options.viewer()?.allAtoms() || [])
        .filter(atom => atom.identity.authSeqId === residue.auth_seq_id && !atom.identity.insertionCode)
        .map(atom => atom.identity.authChain),
    );
    return chains.size <= 1;
  }

  private renderAtomPicker(): void {
    if (this.selection.length !== 1) {
      this.actions.append(element('p', 'ct-caver-hint', t('ct.caver.oneResidue')));
      return;
    }
    const residue = this.selection[0]!;
    const candidates = residueAtoms(this.options.viewer()?.allAtoms() || [], residue);
    if (!candidates.length) {
      this.actions.append(element('p', 'ct-caver-hint', t('ct.caver.noAtoms')));
      return;
    }
    const label = element('label', 'ct-caver-atom-label', t('ct.caver.atom'));
    const select = element('select', 'ct-control');
    select.setAttribute('aria-label', t('ct.caver.atom'));
    const parameters = this.context.parameters();
    const chosenAlt = parameters.start_altloc || '';
    const committedHere = this.atomCommittedIn(residue);
    // The browser displays the first option until one is marked selected, so an
    // unselected canonically-empty state needs its own option; otherwise the
    // displayed atom is silently not the committed one and a one-atom residue
    // cannot be chosen at all.
    const placeholder = new Option(t('ct.caver.chooseAtom'), '');
    placeholder.disabled = true;
    select.append(placeholder);
    let chosen = false;
    candidates.forEach((atom, index) => {
      const name = atom.identity.atomName + (atom.identity.altloc ? ` (${atom.identity.altloc})` : '');
      const matches = committedHere
        && atom.identity.atomName === parameters.start_atom_name
        && (atom.identity.altloc || '') === chosenAlt;
      chosen ||= matches;
      select.append(new Option(`${name} · ${atom.identity.atomSerial}`, String(index), false, matches));
    });
    if (!chosen) placeholder.selected = true;
    select.addEventListener('change', () => {
      if (select.value === '') return;
      const atom = candidates[Number(select.value)];
      if (atom) this.applyAtom(atom);
    });
    label.append(select);
    this.actions.append(label);
  }

  private button(label: string, action: () => void): HTMLButtonElement {
    const button = element('button', 'ct-caver-action', label);
    button.type = 'button';
    button.addEventListener('click', action);
    return button;
  }
}
