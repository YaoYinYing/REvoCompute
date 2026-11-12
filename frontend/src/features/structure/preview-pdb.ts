/*
 * Honest export of one aligned trajectory frame.
 *
 * The only first-release format is a single-model PDB, because that is the one
 * writer and topology mapping this module proves: fixed-column atom names,
 * chain ID, insertion code and altloc are written from the source identity and
 * coordinates are transformed in Float64. There is deliberately no XTC/DCD/TRR
 * writer, and a text PDB is never named with a binary trajectory extension.
 *
 * An exported file is a new local derived artifact. It is not a server-published
 * scientific output and no authenticated Tool validated it.
 */
import { applyRigidTransform, type FitMode, type PeriodicBox, type PbcPolicy, type RigidTransform } from './trajectory-fit';
import type { SceneAtom } from './molecular-scene';

export class PdbExportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PdbExportError';
  }
}

export interface PreviewExportSource {
  taskId: string;
  topologyPath: string;
  topologySha256: string | null;
  topologyFormat: string;
  coordinatesPath: string;
  coordinatesSha256: string | null;
  coordinateFormat: string;
}

export interface PreviewExportContext {
  /** Zero-based index of the exported frame in the source artifact. */
  frame: number;
  frameCount: number;
  referenceFrame: number;
  mode: FitMode;
  fitAtomCount: number;
  selectionSignature: string;
  /** RMSD on the fit selection in Angstrom; null when no fit was applied. */
  rmsd: number | null;
  pbcPolicy: PbcPolicy;
  pbcSpanning: boolean;
  box: PeriodicBox | null;
  source: PreviewExportSource;
}

const STANDARD_RESIDUE = /^[A-Z0-9]{1,3}$/;
const ELEMENT = /^[A-Z]{1,2}$/;

function fixed(value: string, width: number, align: 'left' | 'right' = 'left'): string {
  const text = String(value).slice(0, width);
  return align === 'right' ? text.padStart(width, ' ') : text.padEnd(width, ' ');
}

function coordinate(value: number, label: string): string {
  if (!Number.isFinite(value)) throw new PdbExportError(`The ${label} coordinate is not finite.`);
  if (Math.abs(value) > 9999.999) throw new PdbExportError(`The ${label} coordinate exceeds the PDB 8.3 field width.`);
  return value.toFixed(3).padStart(8, ' ');
}

/**
 * Align an atom name in PDB columns 13-16.
 *
 * A one-letter element whose name does not begin with a digit starts in column
 * 14, so `CA` reads as carbon-alpha rather than calcium; a two-letter element or
 * a digit-leading name starts in column 13.
 */
function atomNameField(name: string, element: string): string {
  if (name.length >= 4) return name.slice(0, 4);
  if (element.length === 1 && !/^[0-9]/.test(name)) return name.padEnd(3).padStart(4);
  return name.padEnd(4);
}

/**
 * Write one frame as a single-model PDB.
 *
 * The function refuses rather than silently truncating an identity field the
 * fixed PDB columns cannot represent (multi-character chain IDs, long atom or
 * residue names, duplicate/out-of-range serials). A caller whose topology cannot
 * be represented must offer its own supported mmCIF path instead.
 */
export function writePreviewPdb(atoms: readonly SceneAtom[], transform: RigidTransform | null): string {
  if (!atoms.length) throw new PdbExportError('There are no atoms to export.');
  const lines = ['MODEL        1'];
  const serials = new Set<number>();
  for (const atom of atoms) {
    const identity = atom.identity;
    const serial = Number(identity.atomSerial);
    if (!Number.isInteger(serial) || serial < 1 || serial > 99999) {
      throw new PdbExportError('A source atom serial cannot be represented in the PDB 5-column serial field.');
    }
    if (serials.has(serial)) throw new PdbExportError('The topology has duplicate atom serials; the export would be ambiguous.');
    serials.add(serial);
    const atomName = String(identity.atomName || '').trim();
    if (!atomName || atomName.length > 4) throw new PdbExportError(`Atom name "${identity.atomName}" cannot be represented in PDB columns 13-16.`);
    const altloc = String(identity.altloc || '').trim();
    if (altloc.length > 1) throw new PdbExportError('An alternate-location identifier is longer than one PDB character.');
    const residueName = String(identity.residueName || '').trim().toUpperCase();
    if (!STANDARD_RESIDUE.test(residueName)) throw new PdbExportError(`Residue name "${identity.residueName}" cannot be represented in PDB columns 18-20.`);
    const chain = String(identity.authChain || '').trim();
    if (chain.length > 1) {
      throw new PdbExportError(
        `Chain "${chain}" cannot be represented by a one-character PDB chain ID. This topology needs an mmCIF export.`,
      );
    }
    if (!Number.isInteger(identity.authSeqId) || identity.authSeqId < -999 || identity.authSeqId > 9999) {
      throw new PdbExportError(`Residue number ${identity.authSeqId} exceeds the PDB 4-column residue field.`);
    }
    const insertionCode = String(identity.insertionCode || '').trim();
    if (insertionCode.length > 1) throw new PdbExportError('An insertion code is longer than one PDB character.');
    const element = String(atom.element || '').trim();
    if (!ELEMENT.test(element)) throw new PdbExportError(`Atom "${atomName}" has no representable element symbol.`);
    const position = transform ? applyRigidTransform(transform, atom.position) : atom.position;
    lines.push(
      'ATOM  '
      + String(serial).padStart(5)
      + ' '
      + atomNameField(atomName, element)
      + (altloc || ' ')
      + fixed(residueName, 3, 'right')
      + ' '
      + (chain || ' ')
      + String(identity.authSeqId).padStart(4)
      + (insertionCode || ' ')
      + '   '
      + coordinate(position.x, 'x')
      + coordinate(position.y, 'y')
      + coordinate(position.z, 'z')
      + '  1.00  0.00          '
      + element.padStart(2),
    );
  }
  lines.push('ENDMDL', 'END');
  return `${lines.join('\n')}\n`;
}

/** The sidecar that makes the exported preview auditable without the viewer. */
export function writePreviewMetadata(context: PreviewExportContext, transform: RigidTransform | null): string {
  return `${JSON.stringify({
    format: 'pdb',
    models: 1,
    units: 'angstrom',
    derived: 'Browser-local derived preview artifact. Not a server-published scientific output and not validated by an authenticated Tool.',
    recordClass: 'ATOM for every atom; the export preserves atom identity fields, not the source ATOM/HETATM class.',
    frame: { index: context.frame, count: context.frameCount },
    referenceFrame: { index: context.referenceFrame },
    fit: {
      mode: context.mode,
      atomCount: context.fitAtomCount,
      selectionSignature: context.selectionSignature,
      rmsd: context.rmsd,
      rmsdUnit: 'angstrom',
      rmsdNote: 'Preview metric computed on the fit selection only. It is not simulation dynamics, stability, or a published result.',
    },
    transform: transform
      ? { rotation: [...transform.rotation], translation: [...transform.translation] }
      : null,
    periodicBoundary: {
      policy: context.pbcPolicy,
      positionsSpanBoundary: context.pbcSpanning,
      box: context.box ? { lengths: [...context.box.lengths], angles: context.box.angles ? [...context.box.angles] : null } : null,
      note: 'No unwrapping or chain reconstruction was performed. Wrapped coordinates may invalidate a rigid fit; unwrap with a validated server Tool for analysis.',
    },
    source: {
      taskId: context.source.taskId,
      topology: { path: context.source.topologyPath, sha256: context.source.topologySha256, format: context.source.topologyFormat },
      coordinates: {
        path: context.source.coordinatesPath,
        sha256: context.source.coordinatesSha256,
        format: context.source.coordinateFormat,
      },
    },
  }, null, 2)}\n`;
}
