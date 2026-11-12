import { describe, expect, it } from 'vitest';

import { MolecularViewer, authoredResidue } from '../src/features/structure/MolecularViewer';
import {
  caverAtomParameters,
  caverExplicitPoint,
  caverGroupSpec,
  caverParameterSelection,
  caverSelectionParameters,
  parseCaverTerms,
  serialRanges,
} from '../src/features/create-task/input-workspace/caver-picker';

// The residue matcher is the generic selection contract every storyboard shares.
// These cases pin its insertion-code semantics without mounting a viewer.
const residue = (overrides: Partial<Parameters<typeof MolecularViewer.matchesResidue>[0]> = {}) => ({
  entity: '1', authChain: 'A', labelChain: 'A', authSeqId: 42, labelSeqId: 42, insCode: '',
  ...overrides,
});

describe('MolecularViewer.matchesResidue insertion-code semantics', () => {
  it('treats an unspecified insertion code as "any residue at this number"', () => {
    // Regression: a caller that never mentions an insertion code (e.g. a
    // label_seq_id selection) must still match a residue that HAS one.
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(true);
  });

  it('treats an explicit empty code as "the bare residue only"', () => {
    const selector = { chain: 'A', residue: 42, numbering: 'auth_seq_id' as const, insertionCode: '' };
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), selector)).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), selector)).toBe(false);
    // Whitespace-only is the same as empty.
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), { ...selector, insertionCode: '  ' })).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), { ...selector, insertionCode: '  ' })).toBe(false);
  });

  it('matches an exact non-empty insertion code', () => {
    const selector = { chain: 'A', residue: 42, numbering: 'auth_seq_id' as const, insertionCode: 'A' };
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), selector)).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), selector)).toBe(false);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'B' }), selector)).toBe(false);
  });

  it('still constrains chain and residue number', () => {
    expect(MolecularViewer.matchesResidue(residue({ authChain: 'B' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(false);
    expect(MolecularViewer.matchesResidue(residue({ authSeqId: 43 }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(false);
  });
});

describe('authoredResidue identity', () => {
  const identity = (overrides: Partial<Parameters<typeof authoredResidue>[0]> = {}) => authoredResidue({
    authChain: 'A', labelChain: 'B', authSeqId: 42, labelSeqId: 7, insCode: '', residueName: 'ALA',
    groupPDB: 'ATOM', ...overrides,
  });

  it('keeps auth and label identities distinct', () => {
    expect(identity()).toEqual({
      chain: 'B', residue: 7, auth_chain: 'A', auth_seq_id: 42, label_seq_id: 7,
      residue_name: 'ALA', hetero: false,
    });
  });

  it('publishes an insertion code only when the source has one', () => {
    expect(identity({ insCode: 'A' })).toMatchObject({ insertion_code: 'A' });
    expect(identity({ insCode: '  ' })).not.toHaveProperty('insertion_code');
  });

  it('falls back to the authored number when a ligand has no label sequence id', () => {
    expect(identity({ labelSeqId: Number.NaN, authSeqId: 501, groupPDB: 'HETATM' }))
      .toMatchObject({ residue: 501, label_seq_id: 501, auth_seq_id: 501, hetero: true });
  });

  it('marks HETATM residues as hetero and ATOM residues as polymer', () => {
    expect(identity({ groupPDB: 'HETATM', residueName: 'HEM' })).toMatchObject({ hetero: true, residue_name: 'HEM' });
    expect(identity({ groupPDB: 'ATOM' })).toMatchObject({ hetero: false });
  });
});

describe('MolecularViewer presentation independence', () => {
  it('keeps the camera when representation changes and clears an explicitly empty selection', async () => {
    const snapshot = { position: [18, 20, 60], target: [1, 2, 3], radius: 14 };
    let camera = snapshot;
    let cleared = false;
    const viewer = new MolecularViewer();
    Object.assign(viewer, {
      plugin: { canvas3d: { camera: { getSnapshot: () => camera, setState: (value: typeof snapshot) => { camera = value; } } },
        managers: { structure: { selection: { clear: () => { cleared = true; } } } } },
      applyPresentation: async () => { camera = { ...snapshot, radius: 90 }; },
    });
    await viewer.setRepresentation('sticks');
    expect(camera).toEqual(snapshot);
    expect(viewer.select({ residues: [] })).toBe(true);
    expect(cleared).toBe(true);
  });
});


const paramsOf = (result: { params?: Record<string, string>; error?: string }): Record<string, string> => {
  if (!result.params) throw new Error(result.error || 'expected parameters');
  return result.params;
};

describe('CAVER selection parameter projection', () => {
  const picked = (overrides: Partial<import('../src/features/structure/MolecularViewer').SelectedResidue> = {}) => ({
    chain: 'label', residue: 99, auth_chain: 'A', auth_seq_id: 7, label_seq_id: 99, residue_name: 'ALA', hetero: false, ...overrides,
  });
  it('writes authored residue identity and no label identity', () => {
    expect(paramsOf(caverSelectionParameters([picked()]))).toMatchObject({ start_point_mode: 'residue', start_chain: 'A', start_residue_number: '7' });
  });
  it('writes one ligand and a multi-residue group in the owning vocabulary', () => {
    expect(paramsOf(caverSelectionParameters([picked({ hetero: true, residue_name: 'HEM' })]))).toMatchObject({ start_point_mode: 'ligand', start_residue_name: 'HEM' });
    expect(paramsOf(caverSelectionParameters([picked(), picked({ auth_seq_id: 8 })]))).toMatchObject({ start_point_mode: 'group', start_group: 'A:7,A:8' });
  });
  it('writes a multi-chain group and never a stale residue number', () => {
    const result = caverSelectionParameters([picked(), picked({ auth_chain: 'B', auth_seq_id: 8 })]);
    expect(paramsOf(result)).toMatchObject({ start_point_mode: 'group', start_group: 'A:7,B:8', start_residue_number: '', start_chain: '' });
  });
  it('refuses insertion-coded, chainless, and empty selections', () => {
    const cases: Array<import('../src/features/structure/MolecularViewer').SelectedResidue[]> = [
      [picked({ insertion_code: 'A' })], [picked({ auth_chain: '' })], [],
    ];
    cases.forEach(residues => expect(caverSelectionParameters(residues)).toHaveProperty('error'));
  });
  it('never emits a residue name for a native residue selection', () => {
    const result = caverSelectionParameters([picked()]);
    expect(paramsOf(result)).toMatchObject({ start_point_mode: 'residue', start_chain: 'A', start_residue_number: '7' });
    expect(paramsOf(result).start_residue_name).toBe('');
  });
  it('projects edited canonical parameters back to authored viewer selectors', () => {
    expect(caverParameterSelection({ start_point_mode: 'residue', start_chain: 'A', start_residue_number: '7' }).residues)
      .toEqual([{ chain: 'A', residue: 7, numbering: 'auth_seq_id', insertionCode: '' }]);
    expect(caverParameterSelection({ start_point_mode: 'point', start_x: '1', start_y: '2', start_z: '3' }).point)
      .toEqual({ x: 1, y: 2, z: 3 });
    expect(caverParameterSelection({ start_point_mode: 'group', start_group: 'A:7-8' }).residues).toHaveLength(2);
    expect(parseCaverTerms('A:7-8,B:9')).toEqual({ terms: [
      { chain: 'A', start: 7, end: 8 }, { chain: 'B', start: 9, end: 9 },
    ] });
    expect(parseCaverTerms('A:8-7')).toHaveProperty('error');
    expect(parseCaverTerms('A:1;DROP')).toHaveProperty('error');
  });
});

describe('CAVER explicit point conversion', () => {
  const heme = { chain: 'label', residue: 99, auth_chain: 'A', auth_seq_id: 7, label_seq_id: 99, residue_name: 'HEM', hetero: true };
  const sceneAtom = (
    serial: number,
    element: string,
    position: { x: number; y: number; z: number },
    overrides: Record<string, unknown> = {},
  ) => ({
    identity: {
      authChain: 'A', labelChain: 'A', authSeqId: 7, labelSeqId: 99,
      insertionCode: '', residueName: 'HEM', atomName: element, atomSerial: serial,
      altloc: '', modelIndex: 0, index: serial, ...overrides,
    },
    element,
    position,
  });
  const atoms = [
    sceneAtom(11, 'Fe', { x: 4, y: 4, z: 4 }),
    sceneAtom(12, 'N', { x: 4.5, y: 4, z: 4 }),
    sceneAtom(13, 'H', { x: 4.25, y: 8, z: 4 }),
  ];

  it('serial ranges compress consecutive identities', () => {
    expect(serialRanges([atoms[0]!, atoms[1]!, atoms[2]!])).toBe('11-13');
    expect(serialRanges([atoms[0]!, atoms[2]!])).toBe('11,13');
  });

  it('writes centroid and mass-weighted COM as distinct point-mode values', () => {
    const centroid = caverExplicitPoint([heme], atoms, 'centroid', 'a'.repeat(64));
    const com = caverExplicitPoint([heme], atoms, 'com', 'a'.repeat(64));
    expect(centroid).toMatchObject({ params: {
      start_point_mode: 'point', start_point_source: 'centroid',
      start_selected_residues: 'A:7', start_selected_serials: '11-13',
      start_reference_sha256: 'a'.repeat(64),
    } });
    expect(com).toMatchObject({ params: { start_point_mode: 'point', start_point_source: 'com', start_com_hydrogen_policy: 'include' } });
    const cx = Number((centroid as { params: Record<string, string> }).params.start_x);
    const mx = Number((com as { params: Record<string, string> }).params.start_x);
    expect(cx).not.toBeCloseTo(mx, 6);
  });

  it('honours an explicit hydrogen policy in the centre of mass', () => {
    const included = caverExplicitPoint([heme], atoms, 'com', '', 'include') as { params: Record<string, string> };
    const excluded = caverExplicitPoint([heme], atoms, 'com', '', 'exclude') as { params: Record<string, string> };
    expect(included.params.start_y).not.toBe(excluded.params.start_y);
    expect(excluded.params.start_com_hydrogen_policy).toBe('exclude');
  });

  it('omits a digest the browser could not compute as SHA-256', () => {
    const result = caverExplicitPoint([heme], atoms, 'centroid', 'fnv1a-deadbeef-42');
    expect(result).toMatchObject({ params: { start_reference_sha256: '' } });
  });

  it('refuses an ambiguous alternate location and an unaddressable residue', () => {
    const conformers = [
      sceneAtom(11, 'C', { x: 1, y: 1, z: 1 }, { altloc: 'A' }),
      sceneAtom(12, 'C', { x: 2, y: 2, z: 2 }, { altloc: 'B' }),
    ];
    expect(caverExplicitPoint([heme], conformers, 'centroid', '')).toHaveProperty('error');
    expect(caverExplicitPoint([{ ...heme, insertion_code: 'A' }], atoms, 'centroid', '')).toHaveProperty('error');
  });

  it('refuses ambiguous atom serial or conformer mappings', () => {
    const duplicate = [
      sceneAtom(11, 'C', { x: 1, y: 1, z: 1 }, { atomName: 'C1' }),
      sceneAtom(11, 'C', { x: 2, y: 2, z: 2 }, { atomName: 'C2' }),
    ];
    expect(caverAtomParameters(heme, duplicate[0]!, duplicate)).toHaveProperty('error');
    const conformers = [
      sceneAtom(11, 'C', { x: 1, y: 1, z: 1 }, { atomName: 'C1' }),
      sceneAtom(12, 'C', { x: 2, y: 2, z: 2 }, { atomName: 'C1', altloc: 'A' }),
    ];
    expect(caverAtomParameters(heme, conformers[0]!, conformers)).toHaveProperty('error');
    expect(caverAtomParameters(heme, conformers[1]!, conformers)).toMatchObject({ params: {
      start_point_mode: 'atom', start_chain: 'A', start_residue_number: '7',
      start_atom_name: 'C1', start_altloc: 'A',
    } });
  });

  it('canonical group spelling keeps the blank chain explicit', () => {
    expect(caverGroupSpec([{ ...heme, auth_chain: '', auth_seq_id: 5 }])).toBe('_:5');
  });
});
