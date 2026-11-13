/*
 * The single Mol* payload boundary for the molecular scene.
 *
 * Mol* exposes deeply generic structures; these guards read one
 * `StructureElement.Location` at a time and either produce a validated scene
 * value or reject it. Consumers never receive an `unknown` cast from here.
 */
import { Structure, StructureElement, StructureProperties } from 'molstar/lib/mol-model/structure.js';
import {
  authoredResidue,
  atomKey,
  isFiniteNumber,
  isRecord,
  type AtomIdentity,
  type SceneAtom,
  type SelectedResidue,
} from './molecular-scene';

/**
 * Validate one Mol* location and return the typed boundary value. A location is
 * usable only when it belongs to an atomistic unit (`kind === 0`) and carries an
 * element index. Coarse units are skipped, never coerced.
 *
 * This is the one place an `unknown` payload crosses into Mol* types.
 */
export function asAtomisticLocation(value: unknown): StructureElement.Location | null {
  if (!isRecord(value) || !isRecord(value.unit)) return null;
  if (value.unit.kind !== 0 || !isFiniteNumber(value.element)) return null;
  return value as unknown as StructureElement.Location;
}

function labelNumber(value: number, fallback: number): number {
  return isFiniteNumber(value) ? value : fallback;
}

/** Stable authored identity of one atom, including the viewer-local index. */
export function atomIdentity(location: StructureElement.Location): AtomIdentity {
  const authSeqId = Number(StructureProperties.residue.auth_seq_id(location));
  const insCode = String(StructureProperties.residue.pdbx_PDB_ins_code(location) || '').trim();
  const altloc = String(StructureProperties.atom.label_alt_id(location) || '').trim();
  return {
    authChain: String(StructureProperties.chain.auth_asym_id(location) || ''),
    labelChain: String(StructureProperties.chain.label_asym_id(location) || ''),
    authSeqId,
    // A ligand may have no label sequence id; the authored number is its address.
    labelSeqId: labelNumber(Number(StructureProperties.residue.label_seq_id(location)), authSeqId),
    ...(insCode ? { insertionCode: insCode } : {}),
    residueName: String(StructureProperties.residue.auth_comp_id(location) || ''),
    atomName: String(StructureProperties.atom.auth_atom_id(location) || ''),
    atomSerial: Number(StructureProperties.atom.id(location)),
    ...(altloc ? { altloc } : {}),
    modelIndex: Number(StructureProperties.unit.model_index(location)) || 0,
    index: Number(location.element),
  };
}

/** One atom in the current coordinate frame. */
export function sceneAtom(location: StructureElement.Location): SceneAtom {
  return {
    identity: atomIdentity(location),
    element: String(StructureProperties.atom.type_symbol(location) || '').trim().toUpperCase(),
    position: {
      x: Number(StructureProperties.atom.x(location)),
      y: Number(StructureProperties.atom.y(location)),
      z: Number(StructureProperties.atom.z(location)),
    },
  };
}

/** Authored residue identity of one Mol* location. */
export function sceneResidue(location: StructureElement.Location): SelectedResidue {
  return authoredResidue({
    authChain: String(StructureProperties.chain.auth_asym_id(location) || ''),
    labelChain: String(StructureProperties.chain.label_asym_id(location) || ''),
    authSeqId: Number(StructureProperties.residue.auth_seq_id(location)),
    labelSeqId: Number(StructureProperties.residue.label_seq_id(location)),
    insCode: String(StructureProperties.residue.pdbx_PDB_ins_code(location) || ''),
    residueName: String(StructureProperties.residue.auth_comp_id(location) || ''),
    groupPDB: String(StructureProperties.residue.group_PDB(location) || ''),
  });
}

/**
 * Every selected atom, keyed by stable identity so a repeated location (for
 * example through a symmetry operator) contributes once. Order follows Mol*.
 */
export function selectionAtoms(loci: StructureElement.Loci): SceneAtom[] {
  const atoms = new Map<string, SceneAtom>();
  StructureElement.Loci.forEachLocation(loci, (location) => {
    const atomistic = asAtomisticLocation(location);
    if (!atomistic) return;
    const atom = sceneAtom(atomistic);
    atoms.set(atomKey(atom.identity), atom);
  });
  return Array.from(atoms.values());
}

/** Every selected residue, keyed by authored identity. */
export function selectionResidues(loci: StructureElement.Loci): SelectedResidue[] {
  const residues = new Map<string, SelectedResidue>();
  StructureElement.Loci.forEachLocation(loci, (location) => {
    const residue = asAtomisticLocation(location);
    if (!residue) return;
    const authored = sceneResidue(residue);
    residues.set(
      `${authored.chain}:${authored.residue}:${authored.auth_chain}:${authored.auth_seq_id}:${authored.insertion_code || ''}`,
      authored,
    );
  });
  return Array.from(residues.values());
}

/** Every atom of a loaded structure, in the active coordinate frame. */
export function allAtoms(structure: Structure): SceneAtom[] {
  const atoms: SceneAtom[] = [];
  for (const unit of structure.units) {
    if (unit.kind !== 0) continue;
    const location = StructureElement.Location.create(structure, unit);
    for (let index = 0; index < unit.elements.length; index += 1) {
      const element = unit.elements[index];
      if (element === undefined) continue;
      location.element = element;
      atoms.push(sceneAtom(location));
    }
  }
  return atoms;
}
