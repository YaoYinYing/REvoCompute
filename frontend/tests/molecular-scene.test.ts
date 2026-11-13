import { describe, expect, it } from 'vitest';

import {
  AmbiguousAltlocError,
  EmptyAtomSubsetError,
  InvalidBoxError,
  InvalidCoordinateError,
  LatestRequestGate,
  MissingAtomicMassError,
  SceneState,
  StaleTopologyError,
  atomKey,
  axisAlignedBoxOf,
  centerOfMassOf,
  centroidOf,
  isAxisAlignedBox,
  isSelfEcho,
  isXYZ,
  structuralDigest,
  type SceneAtom,
} from '../src/features/structure/molecular-scene';

const atom = (overrides: {
  element?: string;
  position?: { x: number; y: number; z: number };
  authChain?: string;
  authSeqId?: number;
  insertionCode?: string;
  residueName?: string;
  atomName?: string;
  atomSerial?: number;
  altloc?: string;
  modelIndex?: number;
  index?: number;
  labelChain?: string;
  labelSeqId?: number;
} = {}): SceneAtom => ({
  identity: {
    authChain: overrides.authChain ?? 'A',
    labelChain: overrides.labelChain ?? 'A',
    authSeqId: overrides.authSeqId ?? 42,
    labelSeqId: overrides.labelSeqId ?? 42,
    ...(overrides.insertionCode ? { insertionCode: overrides.insertionCode } : {}),
    residueName: overrides.residueName ?? 'ALA',
    atomName: overrides.atomName ?? 'CA',
    atomSerial: overrides.atomSerial ?? 1,
    ...(overrides.altloc ? { altloc: overrides.altloc } : {}),
    modelIndex: overrides.modelIndex ?? 0,
    index: overrides.index ?? 0,
  },
  element: overrides.element ?? 'C',
  position: overrides.position ?? { x: 0, y: 0, z: 0 },
});

describe('stable atom identity', () => {
  it('keeps author and label numbering, residue, atom, altloc, model and serial distinct', () => {
    const base = atom();
    expect(atomKey({ ...base.identity, labelChain: 'B' })).toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, labelSeqId: 7 })).toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, authChain: 'B' })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, authSeqId: 43 })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, insertionCode: 'A' })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, atomName: 'CB' })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, atomSerial: 2 })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, altloc: 'A' })).not.toBe(atomKey(base.identity));
    expect(atomKey({ ...base.identity, modelIndex: 1 })).not.toBe(atomKey(base.identity));
  });

  it('treats 42 and 42A as different residues and conformers A and B as different atoms', () => {
    expect(atomKey(atom({ insertionCode: 'A' }).identity)).not.toBe(atomKey(atom().identity));
    expect(atomKey(atom({ altloc: 'A', atomSerial: 1 }).identity)).not.toBe(atomKey(atom({ altloc: 'B', atomSerial: 2 }).identity));
  });

  it('does not confuse the source serial with the viewer-local index', () => {
    const serialOne = atom({ atomSerial: 7, index: 3 });
    const serialTwo = atom({ atomSerial: 8, index: 4 });
    expect(atomKey(serialOne.identity)).not.toBe(atomKey(serialTwo.identity));
  });
});

describe('Angstrom geometry', () => {
  it('computes a geometric centroid as an Angstrom position', () => {
    const positions = [atom({ position: { x: 0, y: 0, z: 0 } }), atom({ position: { x: 2, y: 4, z: 6 } })];
    expect(centroidOf(positions)).toEqual({ x: 1, y: 2, z: 3 });
  });

  it('completes the mass-weighted center of mass with a documented hydrogen policy', () => {
    const carbon = atom({ atomName: 'C1', atomSerial: 1, element: 'C', position: { x: 0, y: 0, z: 0 } });
    const hydrogen = atom({ atomName: 'H1', atomSerial: 2, element: 'H', position: { x: 1, y: 0, z: 0 } });
    const withH = centerOfMassOf([carbon, hydrogen], { hydrogenPolicy: 'include' });
    expect(withH.x).toBeCloseTo(1.008 / (12.011 + 1.008), 10);
    expect(centerOfMassOf([carbon, hydrogen], { hydrogenPolicy: 'exclude' })).toEqual({ x: 0, y: 0, z: 0 });
  });

  it('weights a heavier atom more than a lighter one', () => {
    const carbon = atom({ atomName: 'C1', atomSerial: 1, element: 'C', position: { x: 0, y: 0, z: 0 } });
    const oxygen = atom({ atomName: 'O1', atomSerial: 2, element: 'O', position: { x: 1, y: 0, z: 0 } });
    const com = centerOfMassOf([carbon, oxygen], { hydrogenPolicy: 'include' });
    expect(com.x).toBeCloseTo(15.999 / (12.011 + 15.999), 10);
    expect(com.x).toBeGreaterThan(0.5);
  });

  it('rejects an empty subset, a missing mass, non-finite coordinates and ambiguous altlocs', () => {
    expect(() => centroidOf([])).toThrow(EmptyAtomSubsetError);
    expect(() => centerOfMassOf([], { hydrogenPolicy: 'include' })).toThrow(EmptyAtomSubsetError);
    expect(() => centerOfMassOf([atom({ element: 'Xx' })], { hydrogenPolicy: 'include' })).toThrow(MissingAtomicMassError);
    expect(() => centroidOf([atom({ position: { x: Number.NaN, y: 0, z: 0 } })])).toThrow(InvalidCoordinateError);
    expect(() => axisAlignedBoxOf([atom({ position: { x: Number.POSITIVE_INFINITY, y: 0, z: 0 } })])).toThrow(InvalidCoordinateError);
    const altlocs = [atom({ altloc: 'A', atomSerial: 1 }), atom({ altloc: 'B', atomSerial: 2 })];
    expect(() => centerOfMassOf(altlocs, { hydrogenPolicy: 'include' })).toThrow(AmbiguousAltlocError);
  });

  it('derives an axis-aligned box as a center plus full side lengths', () => {
    const box = axisAlignedBoxOf([
      atom({ atomSerial: 1, position: { x: -1, y: 2, z: 0 } }),
      atom({ atomSerial: 2, position: { x: 3, y: 2, z: 4 } }),
    ]);
    expect(box).toEqual({ center: { x: 1, y: 2, z: 2 }, lengths: { x: 4, y: 0, z: 4 } });
    expect(isAxisAlignedBox(box)).toBe(true);
    expect(isXYZ(box.center)).toBe(true);
  });

  it('rejects negative or non-finite box lengths but allows a degenerate box', () => {
    const state = new SceneState();
    expect(() => state.setBox({ center: { x: 0, y: 0, z: 0 }, lengths: { x: -1, y: 1, z: 1 } })).toThrow(InvalidBoxError);
    expect(() => state.setBox({ center: { x: 0, y: 0, z: 0 }, lengths: { x: Number.NaN, y: 1, z: 1 } })).toThrow(InvalidBoxError);
    expect(state.setBox({ center: { x: 0, y: 0, z: 0 }, lengths: { x: 0, y: 0, z: 0 } })).toEqual({ center: { x: 0, y: 0, z: 0 }, lengths: { x: 0, y: 0, z: 0 } });
  });
});

describe('scene state: topology, frames and layout', () => {
  const selection = { atoms: [atom()], residues: [
    { chain: 'A', residue: 42, auth_chain: 'A', auth_seq_id: 42, label_seq_id: 42, residue_name: 'ALA', hetero: false },
  ] };

  it('bumps the immutable revision and clears selectors and overlays on a new topology', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1', label: 'first' });
    const first = state.topologyIdentity();
    state.selectFromForm(selection);
    state.setCrosshair({ x: 1, y: 2, z: 3 });
    state.setBox({ center: { x: 0, y: 0, z: 0 }, lengths: { x: 1, y: 1, z: 1 } });
    state.setFrame(4);

    state.topologyChanged({ digest: 'digest-2', label: 'second' });
    const second = state.topologyIdentity();
    expect(second.revision).toBe(first.revision + 1);
    expect(second.digest).toBe('digest-2');
    expect(state.snapshot().selectedAtoms).toEqual([]);
    expect(state.snapshot().selectedResidues).toEqual([]);
    expect(state.getCrosshair()).toBeNull();
    expect(state.getBox()).toBeNull();
    expect(state.snapshot().coordinateFrame).toBe(0);
  });

  it('refuses a selector captured from a stale topology instead of remapping chain IDs', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    const stale = { revision: 0, digest: 'digest-1' };
    state.topologyChanged({ digest: 'digest-2' });
    expect(() => state.selectFromForm(selection, { expectedTopology: stale })).toThrow(StaleTopologyError);
    expect(() => state.setCrosshair({ x: 0, y: 0, z: 0 }, { expectedTopology: stale })).toThrow(StaleTopologyError);
  });

  it('publishes the active trajectory frame while the topology revision stays fixed', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    const revision = state.topologyIdentity().revision;
    const events: string[] = [];
    state.subscribe(event => events.push(event.type));
    state.setFrame(7);
    expect(state.snapshot().coordinateFrame).toBe(7);
    expect(state.topologyIdentity().revision).toBe(revision);
    expect(events).toEqual(['frame']);
  });

  it('ignores the echo of a form mutation and emits a genuine viewer change once', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    const events: Array<{ origin: string; type: string }> = [];
    state.subscribe(event => events.push({ origin: event.origin, type: event.type }));
    state.selectFromForm(selection, { origin: 'form', transactionId: 'tx-1' });
    expect(events).toEqual([{ origin: 'form', type: 'selection' }]);
    expect(state.adoptViewerSelection(selection)).toBe(false);
    expect(events).toHaveLength(1);

    const other = { atoms: [atom({ authSeqId: 7, atomSerial: 9 })], residues: [{ ...selection.residues[0]!, auth_seq_id: 7, residue: 7, label_seq_id: 7 }] };
    expect(state.adoptViewerSelection(other)).toBe(true);
    expect(events[1]).toEqual({ origin: 'viewer', type: 'selection' });
  });

  it('suppresses the Mol* change notification of a synchronous form mutation', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    state.beginExternalMutation();
    state.adoptViewerSelection(selection);
    state.selectFromForm(selection, { origin: 'form' });
    state.endExternalMutation();
    expect(state.snapshot().selectedResidues).toHaveLength(1);
  });

  it('returns defensive copies so a consumer cannot mutate the published state', () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    state.selectFromForm(selection);
    const crosshair = state.setCrosshair({ x: 1, y: 2, z: 3 })!;
    crosshair.x = 99;
    expect(state.getCrosshair()).toEqual({ x: 1, y: 2, z: 3 });
    const snapshot = state.snapshot();
    snapshot.selectedAtoms[0]!.position.x = 99;
    expect(state.snapshot().selectedAtoms[0]!.position.x).toBe(0);
  });

  it('guards event echo by origin and transaction id', () => {
    const applied = { origin: 'form' as const, transactionId: 'tx-1' };
    expect(isSelfEcho({ origin: 'form', transactionId: 'tx-1' }, applied)).toBe(true);
    expect(isSelfEcho({ origin: 'viewer', transactionId: 'tx-1' }, applied)).toBe(false);
    expect(isSelfEcho({ origin: 'form', transactionId: 'tx-2' }, applied)).toBe(false);
    expect(isSelfEcho({ origin: 'form', transactionId: 'tx-1' }, null)).toBe(false);
  });
});

describe('latest-request gate and source digest', () => {
  it('cancels a superseded asynchronous pick rather than racing it', async () => {
    const gate = new LatestRequestGate();
    const first = gate.begin();
    const second = gate.begin();
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(second)).toBe(true);
    gate.cancel();
    expect(gate.isCurrent(second)).toBe(false);
  });

  it('rejects a superseded scene pick', async () => {
    const state = new SceneState();
    state.topologyChanged({ digest: 'digest-1' });
    const first = state.pickAtoms();
    const second = state.pickAtoms();
    await expect(first).rejects.toMatchObject({ name: 'AbortError' });
    await expect(second).resolves.toEqual([]);
  });

  it('derives a stable digest and changes it with the source', async () => {
    const one = await structuralDigest('ATOM      1  CA  ALA A  42');
    const again = await structuralDigest('ATOM      1  CA  ALA A  42');
    const other = await structuralDigest('ATOM      2  CB  ALA A  42');
    expect(one).toBe(again);
    expect(one).not.toBe(other);
  });
});
