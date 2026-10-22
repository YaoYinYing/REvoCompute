import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseRecordedSpheres } from '../src/features/structure/sphere-geometry';

describe('recorded alpha-sphere geometry', () => {
  it('retains the exact PQR centres and radii from the approved authentic run', () => {
    const source = readFileSync(new URL('../../docker/runners/fpocket/tests/fast/fixtures/1SUO_out/pockets/pocket1_vert.pqr', import.meta.url), 'utf8');
    const lines = source.split(/\r?\n/).filter(line => line.startsWith('ATOM  ') || line.startsWith('HETATM'));
    const spheres = parseRecordedSpheres(source);
    expect(spheres).toHaveLength(lines.length);
    spheres.forEach((sphere, index) => {
      const fields = lines[index]!.trim().split(/\s+/);
      expect(sphere.radius).toBe(Number(fields.at(-1)));
      expect(sphere.center).toEqual([Number(lines[index]!.slice(30, 38)), Number(lines[index]!.slice(38, 46)), Number(lines[index]!.slice(46, 54))]);
    });
  });
  it('rejects absent or malformed evidence instead of drawing inferred geometry', () => {
    expect(() => parseRecordedSpheres('HEADER only')).toThrow();
    expect(() => parseRecordedSpheres('ATOM      1  C   STP     1      invalid   0.000   0.000  0.00 -1')).toThrow();
  });
});
