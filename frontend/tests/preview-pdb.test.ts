import { describe, expect, it } from 'vitest';

import { PdbExportError, writePreviewMetadata, writePreviewPdb } from '../src/features/structure/preview-pdb';
import { fitFrame, applyRigidTransform } from '../src/features/structure/trajectory-fit';
import type { SceneAtom } from '../src/features/structure/molecular-scene';

function atom(
  index: number,
  serial: number,
  name: string,
  chain: string,
  residue: number,
  element: string,
  x: number,
  y: number,
  z: number,
  extra: Partial<SceneAtom['identity']> = {},
): SceneAtom {
  return {
    identity: {
      authChain: chain, labelChain: chain, authSeqId: residue, labelSeqId: residue,
      residueName: 'ALA', atomName: name, atomSerial: serial, modelIndex: 0, index, ...extra,
    },
    element,
    position: { x, y, z },
  };
}

const basis = [
  atom(0, 1, 'N', 'A', 1, 'N', 0, 0, 0),
  atom(1, 2, 'CA', 'A', 1, 'C', 1.5, 0, 0),
  atom(2, 3, 'C', 'A', 1, 'C', 0, 1.5, 0),
  atom(3, 4, 'O', 'B', 42, 'O', 0, 0, 1.5),
];

/** Fixed-column PDB slices, 1-based inclusive as the format names them. */
function columns(line: string, from: number, to: number): string {
  return line.slice(from - 1, to);
}

describe('preview PDB writer', () => {
  it('writes one model with atom name, altloc, chain, residue, insertion code and element columns', () => {
    const atoms = [
      atom(0, 7, 'CA', 'A', 42, 'C', 1.25, -2.5, 3.75, { altloc: 'B', insertionCode: 'A', residueName: 'GLY' }),
    ];
    const pdb = writePreviewPdb(atoms, null);
    const lines = pdb.trimEnd().split('\n');
    expect(lines[0]).toBe('MODEL        1');
    const record = lines[1]!;
    expect(columns(record, 1, 6)).toBe('ATOM  ');
    expect(columns(record, 7, 11)).toBe('    7');
    expect(columns(record, 13, 16)).toBe('  CA');
    expect(columns(record, 17, 17)).toBe('B');
    expect(columns(record, 18, 20)).toBe('GLY');
    expect(columns(record, 22, 22)).toBe('A');
    expect(columns(record, 23, 26)).toBe('  42');
    expect(columns(record, 27, 27)).toBe('A');
    expect(columns(record, 31, 38)).toBe('   1.250');
    expect(columns(record, 39, 46)).toBe('  -2.500');
    expect(columns(record, 47, 54)).toBe('   3.750');
    expect(columns(record, 55, 60)).toBe('  1.00');
    expect(columns(record, 61, 66)).toBe('  0.00');
    expect(columns(record, 77, 78)).toBe(' C');
    expect(lines.at(-2)).toBe('ENDMDL');
    expect(lines.at(-1)).toBe('END');
  });

  it('applies the Float64 preview transform to the exported coordinates', () => {
    const result = fitFrame(Float64Array.of(0, 0, 0, 4, 0, 0, 0, 3, 0), Float64Array.of(1, 2, 3, 5, 2, 3, 1, 5, 3), { mode: 'fit' });
    const pdb = writePreviewPdb(basis.slice(0, 3), result.transform);
    const record = pdb.split('\n')[1]!;
    const expected = applyRigidTransform(result.transform, basis[0]!.position);
    expect(Number(columns(record, 31, 38))).toBeCloseTo(expected.x, 3);
    expect(Number(columns(record, 39, 46))).toBeCloseTo(expected.y, 3);
    expect(Number(columns(record, 47, 54))).toBeCloseTo(expected.z, 3);
  });

  it('refuses a topology the fixed PDB columns cannot represent', () => {
    expect(() => writePreviewPdb([atom(0, 1, 'CA', 'LONG', 1, 'C', 0, 0, 0)], null))
      .toThrow(PdbExportError);
    expect(() => writePreviewPdb([atom(0, 1, 'CA', 'A', 1, 'C', 0, 0, 0), atom(1, 1, 'CB', 'A', 1, 'C', 0, 0, 0)], null))
      .toThrow('duplicate atom serials');
    expect(() => writePreviewPdb([atom(0, 100000, 'CA', 'A', 1, 'C', 0, 0, 0)], null))
      .toThrow('serial field');
    expect(() => writePreviewPdb([atom(0, 1, 'LONGNAME', 'A', 1, 'C', 0, 0, 0)], null))
      .toThrow('13-16');
    expect(() => writePreviewPdb([atom(0, 1, 'CA', 'A', 1, '', 0, 0, 0)], null))
      .toThrow('element symbol');
    expect(() => writePreviewPdb([atom(0, 1, 'CA', 'A', 1, 'C', Number.NaN, 0, 0)], null))
      .toThrow('not finite');
    expect(() => writePreviewPdb([], null)).toThrow('no atoms');
  });

  it('writes honest sidecar provenance and never names a text PDB with a binary extension', () => {
    const metadata = JSON.parse(writePreviewMetadata({
      frame: 2,
      frameCount: 10,
      referenceFrame: 0,
      mode: 'fit',
      fitAtomCount: 120,
      selectionSignature: 'A|1||ALA|CA|1||0',
      rmsd: 1.234,
      pbcPolicy: 'periodic',
      pbcSpanning: true,
      box: { lengths: [10, 11, 12] },
      source: {
        taskId: 'a'.repeat(32),
        topologyPath: 'topology.pdb',
        topologySha256: 'b'.repeat(64),
        topologyFormat: 'pdb',
        coordinatesPath: 'samples.xtc',
        coordinatesSha256: 'c'.repeat(64),
        coordinateFormat: 'xtc',
      },
    }, null));
    expect(metadata.format).toBe('pdb');
    expect(metadata.models).toBe(1);
    expect(metadata.units).toBe('angstrom');
    expect(metadata.frame).toEqual({ index: 2, count: 10 });
    expect(metadata.fit.rmsd).toBe(1.234);
    expect(metadata.fit.rmsdNote).toContain('Preview metric');
    expect(metadata.fit.rmsdNote).toContain('not simulation dynamics');
    expect(metadata.periodicBoundary.positionsSpanBoundary).toBe(true);
    expect(metadata.periodicBoundary.note).toContain('No unwrapping');
    expect(metadata.source.coordinates.sha256).toBe('c'.repeat(64));
    expect(metadata.source.taskId).toBe('a'.repeat(32));
    expect(metadata.derived).toContain('Not a server-published scientific output');
    expect(metadata.transform).toBeNull();
  });
});
