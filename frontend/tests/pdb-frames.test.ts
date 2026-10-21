import { describe, expect, it } from 'vitest';

import { normalizePdbFrameDelimiters } from '../src/features/structure/pdb-frames';

const NEWLINE = String.fromCharCode(10);
const frame = (n: number): string =>
  `ATOM      1  N   GLY A   1      ${String(n).padStart(6)}.000   1.000   1.000  1.00  0.00           N${NEWLINE}ENDMDL${NEWLINE}`;

describe('normalizePdbFrameDelimiters', () => {
  it('turns ENDMDL-only frames into MODEL/ENDMDL pairs Mol* can count', () => {
    const normalized = normalizePdbFrameDelimiters(frame(1) + frame(2) + frame(3));
    // Mol* reads the first atom block as model 1 and increments at each MODEL
    // record, so one MODEL between frames gives three models and no empty
    // trailing model.
    expect(normalized.match(/^MODEL /gm)?.length).toBe(2);
    expect(normalized.match(/^ENDMDL$/gm)?.length).toBe(3);
    // Coordinates are untouched; only the delimiter between frames changes.
    expect(normalized).toContain(frame(1).split('ENDMDL')[0]);
    expect(normalized).toContain(frame(3).split('ENDMDL')[0]);
  });

  it('leaves a PDB that already declares MODEL records byte-identical', () => {
    const text = ['MODEL        1', frame(1), 'MODEL        2', frame(2), 'ENDMDL', ''].join(NEWLINE);
    expect(normalizePdbFrameDelimiters(text)).toBe(text);
  });

  it('leaves a single-frame structure with no ENDMDL unchanged', () => {
    const text = `ATOM      1  N   GLY A   1       1.000   1.000   1.000  1.00  0.00           N${NEWLINE}`;
    expect(normalizePdbFrameDelimiters(text)).toBe(text);
  });
});
