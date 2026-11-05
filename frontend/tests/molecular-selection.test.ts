import { describe, expect, it } from 'vitest';

import { MolecularViewer, authoredResidue } from '../src/features/structure/MolecularViewer';
import { caverParameterSelection, caverSelectionParameters } from '../src/features/create-task/input-workspace/builtins';

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


describe('CAVER selection parameter projection', () => {
  const picked = (overrides: Partial<import('../src/features/structure/MolecularViewer').SelectedResidue> = {}) => ({
    chain: 'label', residue: 99, auth_chain: 'A', auth_seq_id: 7, label_seq_id: 99, residue_name: 'ALA', hetero: false, ...overrides,
  });
  it('writes authored residue identity and no label identity', () => {
    expect(caverSelectionParameters([picked()]).params).toMatchObject({ start_point_mode: 'residue', start_chain: 'A', start_residue_number: '7' });
  });
  it('writes one ligand and a multi-residue group in the owning vocabulary', () => {
    expect(caverSelectionParameters([picked({ hetero: true, residue_name: 'HEM' })]).params).toMatchObject({ start_point_mode: 'ligand', start_residue_name: 'HEM' });
    expect(caverSelectionParameters([picked(), picked({ auth_seq_id: 8 })]).params).toMatchObject({ start_point_mode: 'group', start_group: 'A:7,A:8' });
  });
  it('refuses insertion-coded, mixed hetero, multi-chain, and empty selections', () => {
    const cases: Array<import('../src/features/structure/MolecularViewer').SelectedResidue[]> = [
      [picked({ insertion_code: 'A' })], [picked({ hetero: true }), picked()],
      [picked({ auth_chain: 'A' }), picked({ auth_chain: 'B', auth_seq_id: 8 })], [],
    ];
    cases.forEach(residues => expect(caverSelectionParameters(residues)).toHaveProperty('error'));
  });
  it('projects edited canonical parameters back to authored viewer selectors', () => {
    expect(caverParameterSelection({ start_point_mode: 'residue', start_chain: 'A', start_residue_number: '7' }).residues)
      .toEqual([{ chain: 'A', residue: 7, numbering: 'auth_seq_id' }]);
    expect(caverParameterSelection({ start_point_mode: 'point', start_x: '1', start_y: '2', start_z: '3' }).point)
      .toEqual({ x: 1, y: 2, z: 3 });
    expect(caverParameterSelection({ start_point_mode: 'group', start_group: 'A:7,A:8' }).residues).toHaveLength(2);
  });
});
