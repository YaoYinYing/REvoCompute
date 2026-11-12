import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  DegenerateSelectionError,
  TrajectoryFitError,
  applyRigidTransform,
  fitFrame,
  fromColumnMajorMatrix,
  invertRigidTransform,
  pbcPolicyOf,
  positionsSpanPeriodicBoundary,
  rotationDeterminant,
  toColumnMajorMatrix,
  validateFitSelection,
} from '../src/features/structure/trajectory-fit';

interface FixtureCase {
  reference: number[][];
  mobile: number[][];
  weights: number[] | null;
  rotation?: number[][];
  translation?: number[];
  rmsd?: number;
}

// Expected matrices were produced by NumPy's SVD Kabsch implementation. They are
// independent reference values, not snapshots of this implementation.
const fixtures: Record<string, FixtureCase> = JSON.parse(
  readFileSync(new URL('./fixtures/kabsch-reference.json', import.meta.url), 'utf8'),
);

function flat(points: number[][]): Float64Array {
  const values = new Float64Array(points.length * 3);
  points.forEach((point, index) => {
    values[index * 3] = point[0]!;
    values[index * 3 + 1] = point[1]!;
    values[index * 3 + 2] = point[2]!;
  });
  return values;
}

function position(point: number[]): { x: number; y: number; z: number } {
  return { x: point[0]!, y: point[1]!, z: point[2]! };
}

function centroid(points: number[][]): { x: number; y: number; z: number } {
  const sums = [0, 0, 0];
  for (const point of points) {
    sums[0]! += point[0]!;
    sums[1]! += point[1]!;
    sums[2]! += point[2]!;
  }
  return { x: sums[0]! / points.length, y: sums[1]! / points.length, z: sums[2]! / points.length };
}

function distance(a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

function expectMatrix(actual: readonly number[], expected: readonly number[]): void {
  expected.forEach((value, index) => expect(actual[index]!).toBeCloseTo(value, 9));
}

function expectTransformToMatch(
  result: { rotation: readonly number[]; translation: readonly number[] },
  fixture: FixtureCase,
): void {
  if (!fixture.rotation || !fixture.translation) return;
  expectMatrix(result.rotation, fixture.rotation.flat());
  fixture.translation.forEach((value, index) => expect(result.translation[index]!).toBeCloseTo(value, 9));
}

describe('Kabsch preview fit', () => {
  it('recovers an exact rigid rotation and translation', () => {
    const fixture = fixtures.rigid_rotation_translation!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expectTransformToMatch(result.transform, fixture);
    expect(result.rmsd).toBeCloseTo(fixture.rmsd!, 9);
    expect(rotationDeterminant(result.transform)).toBeCloseTo(1, 12);
  });

  it('keeps identity and translation-only inputs exact', () => {
    const identity = fitFrame(flat(fixtures.identity!.reference), flat(fixtures.identity!.mobile), { mode: 'fit' });
    expectMatrix(identity.transform.rotation, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
    identity.transform.translation.forEach((value) => expect(value).toBeCloseTo(0, 12));
    expect(identity.rmsd).toBeCloseTo(0, 12);

    const translation = fitFrame(flat(fixtures.translation_only!.reference), flat(fixtures.translation_only!.mobile), { mode: 'fit' });
    expectMatrix(translation.transform.rotation, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
    expectTransformToMatch(translation.transform, fixtures.translation_only!);
    expect(translation.rmsd).toBeCloseTo(0, 12);
  });

  it('handles a 180 degree rotation without collapsing the axis', () => {
    const fixture = fixtures.rotation_180!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expectTransformToMatch(result.transform, fixture);
    expect(rotationDeterminant(result.transform)).toBeCloseTo(1, 12);
    expect(result.rmsd).toBeCloseTo(0, 9);
  });

  it('chooses a proper rotation for mirrored input instead of a reflection', () => {
    const fixture = fixtures.reflection!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expect(rotationDeterminant(result.transform)).toBeCloseTo(1, 12);
    expectTransformToMatch(result.transform, fixture);
    expect(result.rmsd).toBeGreaterThan(0);
  });

  it('fits a planar rank-two selection through the right-handed completion', () => {
    const fixture = fixtures.planar_rank_two!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expectTransformToMatch(result.transform, fixture);
    expect(result.rmsd).toBeCloseTo(0, 9);
    expect(rotationDeterminant(result.transform)).toBeCloseTo(1, 12);
  });

  it('uses weights so a mass-like selection has a different centroid and matrix', () => {
    const fixture = fixtures.weighted!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), {
      mode: 'fit', weights: new Float64Array(fixture.weights!),
    });
    expectTransformToMatch(result.transform, fixture);
    expect(result.rmsd).toBeCloseTo(fixture.rmsd!, 9);
    const uniform = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expect(result.transform.rotation[0]).not.toBeCloseTo(uniform.transform.rotation[0]!, 6);
  });

  it('is invariant to atom order because correspondence is row order', () => {
    const fixture = fixtures.permuted_order!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    expectTransformToMatch(result.transform, fixture);
    expect(result.rmsd).toBeCloseTo(fixture.rmsd!, 9);
  });

  it('preserves pairwise distances and is invertible', () => {
    const fixture = fixtures.rigid_rotation_translation!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    const inverse = invertRigidTransform(result.transform);
    for (const point of fixture.reference) {
      const original = position(point);
      expect(distance(applyRigidTransform(inverse, applyRigidTransform(result.transform, original)), original)).toBeLessThan(1e-9);
    }
    const [first, second] = [position(fixture.mobile[0]!), position(fixture.mobile[1]!)];
    expect(distance(
      applyRigidTransform(result.transform, first),
      applyRigidTransform(result.transform, second),
    )).toBeCloseTo(distance(first, second), 12);
  });

  it('translates the mobile centroid onto the reference centroid in center-only mode', () => {
    const fixture = fixtures.rigid_rotation_translation!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'center' });
    expectMatrix(result.transform.rotation, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
    expect(result.rmsd).toBeGreaterThan(0);
    expect(distance(
      applyRigidTransform(result.transform, centroid(fixture.mobile)),
      centroid(fixture.reference),
    )).toBeLessThan(1e-9);
  });

  it('round-trips the column-major matrix layout', () => {
    const fixture = fixtures.rigid_rotation_translation!;
    const result = fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' });
    const restored = fromColumnMajorMatrix(toColumnMajorMatrix(result.transform));
    expectMatrix(restored.rotation, result.transform.rotation);
    restored.translation.forEach((value, index) => expect(value).toBeCloseTo(result.transform.translation[index]!, 12));
  });

  it('never mutates the source coordinate arrays', () => {
    const fixture = fixtures.rigid_rotation_translation!;
    const reference = flat(fixture.reference);
    const mobile = flat(fixture.mobile);
    const referenceCopy = Float64Array.from(reference);
    const mobileCopy = Float64Array.from(mobile);
    fitFrame(reference, mobile, { mode: 'fit' });
    expect(Array.from(reference)).toEqual(Array.from(referenceCopy));
    expect(Array.from(mobile)).toEqual(Array.from(mobileCopy));
  });

  it('rejects fewer than three atoms', () => {
    expect(() => validateFitSelection(Float64Array.of(0, 0, 0, 1, 1, 1)))
      .toThrow('at least three atoms');
  });

  it('rejects a collinear selection instead of inventing a rotation', () => {
    const fixture = fixtures.collinear!;
    expect(() => validateFitSelection(flat(fixture.reference))).toThrow(DegenerateSelectionError);
    expect(() => fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'fit' }))
      .toThrow(DegenerateSelectionError);
    expect(() => fitFrame(flat(fixture.reference), flat(fixture.mobile), { mode: 'center' }))
      .toThrow(DegenerateSelectionError);
  });

  it('rejects a numerically near-collinear selection', () => {
    // Offsets of 1e-9 Angstrom around a line are within the rank tolerance.
    expect(() => validateFitSelection(new Float64Array([0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 1e-9, 0])))
      .toThrow(DegenerateSelectionError);
  });

  it('rejects non-finite coordinates and invalid weights', () => {
    expect(() => validateFitSelection(Float64Array.of(0, 0, 0, 1, 0, 0, 0, 1, Number.NaN)))
      .toThrow('non-finite');
    const reference = flat(fixtures.planar_rank_two!.reference);
    expect(() => fitFrame(reference, reference, { mode: 'fit', weights: Float64Array.of(1, 1, 1) }))
      .toThrow('weights must match');
    expect(() => fitFrame(reference, reference, { mode: 'fit', weights: Float64Array.of(1, 1, 1, -1, 1) }))
      .toThrow('non-negative');
    expect(() => fitFrame(reference, reference, { mode: 'fit', weights: new Float64Array(5) }))
      .toThrow('sum to zero');
  });

  it('rejects mismatched frames and a missing mode', () => {
    expect(() => fitFrame(flat(fixtures.planar_rank_two!.reference), Float64Array.of(0, 0, 0), { mode: 'fit' }))
      .toThrow('same atom count');
    expect(() => fitFrame(flat(fixtures.planar_rank_two!.reference), flat(fixtures.planar_rank_two!.mobile), { mode: 'rotate' as never }))
      .toThrow('explicit center or fit mode');
    expect(() => fitFrame(Float64Array.of(), Float64Array.of(), { mode: 'fit' }))
      .toThrow(TrajectoryFitError);
  });
});

describe('periodic-boundary preview policy', () => {
  const box = { lengths: [10, 10, 10] as [number, number, number] };

  it('reports a declared box and an absent one distinctly', () => {
    expect(pbcPolicyOf(box)).toBe('periodic');
    expect(pbcPolicyOf(null)).toBe('none');
    expect(pbcPolicyOf({ lengths: [0, 0, 0] })).toBe('none');
    expect(pbcPolicyOf({ lengths: [Number.NaN, 10, 10] })).toBe('none');
  });

  it('warns when the positions span more than half the declared box', () => {
    expect(positionsSpanPeriodicBoundary(Float64Array.of(0.5, 0.5, 0.5, 9.5, 0.5, 0.5), box)).toBe(true);
    expect(positionsSpanPeriodicBoundary(Float64Array.of(4.0, 4.0, 4.0, 5.0, 5.0, 5.0), box)).toBe(false);
  });

  it('never warns without a periodic box', () => {
    expect(positionsSpanPeriodicBoundary(Float64Array.of(0, 0, 0, 100, 0, 0), { lengths: [0, 0, 0] })).toBe(false);
  });
});
