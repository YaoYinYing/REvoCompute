/*
 * Browser-local rigid-body fitting for a trajectory preview.
 *
 * Every value here is a *preview* quantity: a Kabsch fit of selected atoms to a
 * reference frame, used to recentre or superpose the displayed frames. It is not
 * a simulation observable, a stability measure, or a published result. The
 * source coordinates are never written; callers apply the returned transform to
 * a separate preview layer.
 *
 * Coordinates are Angstrom and accumulate in Float64. The fit is a weighted
 * least-squares problem
 *
 *   argmin_{R,t} sum_i w_i || R x_i(f) + t - x_i(ref) ||^2,
 *   R^T R = I, det(R) = +1,
 *
 * solved with Kabsch's SVD formulation and an explicit proper-rotation
 * correction. A selection whose points are collinear, duplicated, non-finite, or
 * otherwise rank-deficient is rejected instead of yielding an arbitrary
 * rotation.
 */
import type { XYZ } from './molecular-scene';

export type FitMode = 'center' | 'fit';

/** Nine numbers in row-major 3x3 order. */
type Matrix9 = [number, number, number, number, number, number, number, number, number];

/** Row-major 3x3 rotation and an Angstrom translation. */
export interface RigidTransform {
  rotation: readonly [number, number, number, number, number, number, number, number, number];
  translation: readonly [number, number, number];
}

export const IDENTITY_TRANSFORM: RigidTransform = {
  rotation: [1, 0, 0, 0, 1, 0, 0, 0, 1],
  translation: [0, 0, 0],
};

export interface FitFrameOptions {
  mode: FitMode;
  /** One non-negative weight per atom; omitted means uniform weights. */
  weights?: Float64Array;
}

export interface FrameFitResult {
  transform: RigidTransform;
  /** Root-mean-square deviation over the fit atoms after the transform, in Angstrom. */
  rmsd: number;
}

/** A selection is unusable as a fit target. The message names the reason. */
export class TrajectoryFitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TrajectoryFitError';
  }
}

export class DegenerateSelectionError extends TrajectoryFitError {
  constructor(detail: string) {
    super(`The fit selection is degenerate: ${detail}`);
    this.name = 'DegenerateSelectionError';
  }
}

/** One component of a periodic box, as read from the source frame. */
export interface PeriodicBox {
  /** Full lattice-vector lengths in Angstrom. */
  lengths: readonly [number, number, number];
  /** Lattice angles in radians, when the source provides them. */
  angles?: readonly [number, number, number];
}

export type PbcPolicy = 'none' | 'periodic';

function atomCount(coordinates: Float64Array): number {
  if (!(coordinates instanceof Float64Array)) throw new TrajectoryFitError('Fit coordinates must be a Float64Array.');
  if (coordinates.length === 0 || coordinates.length % 3 !== 0) {
    throw new TrajectoryFitError('Fit coordinates must be a flat xyz triple list.');
  }
  return coordinates.length / 3;
}

function assertFinitePositions(coordinates: Float64Array, label: string): void {
  for (let index = 0; index < coordinates.length; index += 1) {
    if (!Number.isFinite(coordinates[index])) throw new TrajectoryFitError(`${label} contains a non-finite coordinate.`);
  }
}

function validateWeights(weights: Float64Array | undefined, count: number): Float64Array {
  if (!weights) return new Float64Array(count).fill(1);
  if (weights.length !== count) throw new TrajectoryFitError('Fit weights must match the atom count.');
  let total = 0;
  for (let index = 0; index < weights.length; index += 1) {
    const weight = weights[index]!;
    if (!Number.isFinite(weight) || weight < 0) throw new TrajectoryFitError('Fit weights must be finite and non-negative.');
    total += weight;
  }
  if (!(total > 0)) throw new TrajectoryFitError('Fit weights must not sum to zero.');
  return weights;
}

function weightedCentroid(coordinates: Float64Array, weights: Float64Array, count: number): [number, number, number] {
  let total = 0;
  let x = 0;
  let y = 0;
  let z = 0;
  for (let index = 0; index < count; index += 1) {
    const weight = weights[index]!;
    x += weight * coordinates[index * 3]!;
    y += weight * coordinates[index * 3 + 1]!;
    z += weight * coordinates[index * 3 + 2]!;
    total += weight;
  }
  return [x / total, y / total, z / total];
}

/**
 * Validate that a selection can define a rigid-body frame: at least three
 * finite, non-collinear atoms. Used before a job is queued so the reader gets
 * an actionable message rather than a failed worker job.
 */
export function validateFitSelection(reference: Float64Array, weights?: Float64Array): void {
  const count = atomCount(reference);
  if (count < 3) throw new TrajectoryFitError('A rigid fit needs at least three atoms.');
  assertFinitePositions(reference, 'The reference frame');
  const useWeights = validateWeights(weights, count);
  // The rank of the centred reference selection is what makes the rotation
  // unique. A collinear set has rank one and cannot define a proper rotation.
  const singular = singularValues(correlationMatrix(reference, reference, useWeights, count));
  if (!(singular[1]! > 1e-6 * singular[0]!)) {
    throw new DegenerateSelectionError('select at least three atoms that are not collinear.');
  }
}

/**
 * Fit one mobile frame to a reference frame.
 *
 * `mode: 'center'` translates the weighted centroids together and reports the
 * residual RMSD; `mode: 'fit'` additionally finds the proper rotation. Both
 * modes require the same non-degenerate selection.
 */
export function fitFrame(reference: Float64Array, mobile: Float64Array, options: FitFrameOptions): FrameFitResult {
  const count = atomCount(reference);
  if (atomCount(mobile) !== count) throw new TrajectoryFitError('The reference and mobile frames must have the same atom count.');
  if (options.mode !== 'center' && options.mode !== 'fit') throw new TrajectoryFitError('An explicit center or fit mode is required.');
  const weights = validateWeights(options.weights, count);
  assertFinitePositions(reference, 'The reference frame');
  assertFinitePositions(mobile, 'The mobile frame');
  const referenceCenter = weightedCentroid(reference, weights, count);
  const mobileCenter = weightedCentroid(mobile, weights, count);

  if (options.mode === 'center') {
    // The selection contract is the same in both modes: three non-collinear
    // atoms. A centre-only preview of a line would still be an ambiguous frame.
    validateFitSelection(reference, weights);
    const translation: [number, number, number] = [
      referenceCenter[0] - mobileCenter[0],
      referenceCenter[1] - mobileCenter[1],
      referenceCenter[2] - mobileCenter[2],
    ];
    return { transform: { rotation: IDENTITY_TRANSFORM.rotation, translation }, rmsd: rmsdOf(reference, mobile, weights, count, IDENTITY_TRANSFORM.rotation, translation) };
  }

  const rotation = kabschRotation(reference, mobile, weights, count, referenceCenter, mobileCenter);
  const translation: [number, number, number] = [
    referenceCenter[0] - dotRow(rotation, 0, mobileCenter),
    referenceCenter[1] - dotRow(rotation, 1, mobileCenter),
    referenceCenter[2] - dotRow(rotation, 2, mobileCenter),
  ];
  return { transform: { rotation, translation }, rmsd: rmsdOf(reference, mobile, weights, count, rotation, translation) };
}

/** Apply a preview transform to one Angstrom position. */
export function applyRigidTransform(transform: RigidTransform, point: XYZ): XYZ {
  const r = transform.rotation;
  const [x, y, z] = [point.x, point.y, point.z];
  return {
    x: r[0] * x + r[1] * y + r[2] * z + transform.translation[0],
    y: r[3] * x + r[4] * y + r[5] * z + transform.translation[1],
    z: r[6] * x + r[7] * y + r[8] * z + transform.translation[2],
  };
}

/** The inverse of a rigid transform: R^T and -R^T t. */
export function invertRigidTransform(transform: RigidTransform): RigidTransform {
  const r = transform.rotation;
  const rotation: RigidTransform['rotation'] = [r[0], r[3], r[6], r[1], r[4], r[7], r[2], r[5], r[8]];
  const t = transform.translation;
  return {
    rotation,
    translation: [
      -(rotation[0] * t[0] + rotation[1] * t[1] + rotation[2] * t[2]),
      -(rotation[3] * t[0] + rotation[4] * t[1] + rotation[5] * t[2]),
      -(rotation[6] * t[0] + rotation[7] * t[1] + rotation[8] * t[2]),
    ],
  };
}

/** Determinant of the row-major rotation. */
export function rotationDeterminant(transform: RigidTransform): number {
  const r = transform.rotation;
  return r[0] * (r[4] * r[8] - r[5] * r[7]) - r[1] * (r[3] * r[8] - r[5] * r[6]) + r[2] * (r[3] * r[7] - r[4] * r[6]);
}

/** 4x4 column-major matrix, the layout Mol*'s Mat4 and WebGL use. */
export function toColumnMajorMatrix(transform: RigidTransform): Float64Array {
  const r = transform.rotation;
  const t = transform.translation;
  return Float64Array.of(
    r[0], r[3], r[6], 0,
    r[1], r[4], r[7], 0,
    r[2], r[5], r[8], 0,
    t[0], t[1], t[2], 1,
  );
}

export function fromColumnMajorMatrix(matrix: ArrayLike<number>): RigidTransform {
  if (matrix.length < 16) throw new TrajectoryFitError('A preview transform needs 16 matrix values.');
  return {
    rotation: [matrix[0]!, matrix[4]!, matrix[8]!, matrix[1]!, matrix[5]!, matrix[9]!, matrix[2]!, matrix[6]!, matrix[10]!],
    translation: [matrix[12]!, matrix[13]!, matrix[14]!],
  };
}

// ---------------------------------------------------------------------------
// Periodic-boundary preview policy.
// ---------------------------------------------------------------------------

/**
 * Source periodic-boundary policy, as the loaded frame declares it.
 *
 * A zero or absent cell means the source declares no periodic box. This is a
 * statement about the artifact, not a scientific inference about the simulation.
 */
export function pbcPolicyOf(box: PeriodicBox | null | undefined): PbcPolicy {
  if (!box) return 'none';
  return box.lengths.every((length) => Number.isFinite(length) && length > 0) ? 'periodic' : 'none';
}

/**
 * Preview-only warning: do these positions span more than half a declared
 * periodic box along an axis?
 *
 * The check is deliberately conservative and orthorhombic-flavoured; a
 * triclinic box may produce a false positive. It never unwraps, reconstructs
 * chains, or changes topology, and a wrapped preview carries no scientific
 * claim. Use a validated server Tool to unwrap coordinates for analysis.
 */
export function positionsSpanPeriodicBoundary(coordinates: Float64Array, box: PeriodicBox): boolean {
  if (pbcPolicyOf(box) === 'none') return false;
  const count = atomCount(coordinates);
  if (!count) return false;
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  for (let index = 0; index < count; index += 1) {
    for (let axis = 0; axis < 3; axis += 1) {
      const value = coordinates[index * 3 + axis]!;
      if (!Number.isFinite(value)) continue;
      minimum[axis] = Math.min(minimum[axis]!, value);
      maximum[axis] = Math.max(maximum[axis]!, value);
    }
  }
  return [0, 1, 2].some((axis) => maximum[axis]! - minimum[axis]! > 0.5 * box.lengths[axis]!);
}

// ---------------------------------------------------------------------------
// Kabsch.
// ---------------------------------------------------------------------------

/**
 * Proper rotation that best maps the centred mobile points onto the reference.
 *
 * The correlation matrix H = sum w (x_mobile - c_m)(x_ref - c_r)^T is
 * decomposed as U S V^T through the symmetric eigenproblem of H^T H. The
 * reflection correction D = diag(1, 1, det(V U^T)) turns the unconstrained
 * orthogonal solution into a proper rotation, so a mirrored selection still
 * yields det(R) = +1 instead of a reflection. When the selection is planar the
 * third singular direction is undefined; the right-handed completion of the two
 * fitted directions is the unique proper map.
 */
function kabschRotation(
  reference: Float64Array,
  mobile: Float64Array,
  weights: Float64Array,
  count: number,
  referenceCenter: readonly [number, number, number],
  mobileCenter: readonly [number, number, number],
): RigidTransform['rotation'] {
  const h = correlationMatrix(reference, mobile, weights, count, referenceCenter, mobileCenter);
  // H^T H is a real symmetric matrix; its eigenvectors are V's columns.
  const a = [
    h[0] * h[0] + h[3] * h[3] + h[6] * h[6],
    h[0] * h[1] + h[3] * h[4] + h[6] * h[7],
    h[0] * h[2] + h[3] * h[5] + h[6] * h[8],
    h[0] * h[1] + h[3] * h[4] + h[6] * h[7],
    h[1] * h[1] + h[4] * h[4] + h[7] * h[7],
    h[1] * h[2] + h[4] * h[5] + h[7] * h[8],
    h[0] * h[2] + h[3] * h[5] + h[6] * h[8],
    h[1] * h[2] + h[4] * h[5] + h[7] * h[8],
    h[2] * h[2] + h[5] * h[5] + h[8] * h[8],
  ];
  const eigen = jacobiEigenSymmetric3(a);
  const singular = eigen.values.map((value) => Math.sqrt(Math.max(0, value))) as [number, number, number];
  if (!(singular[0] > 0) || !(singular[1] > 1e-6 * singular[0])) {
    throw new DegenerateSelectionError('the selected atoms do not span a plane.');
  }
  // V columns.
  const v1 = [eigen.vectors[0]!, eigen.vectors[3]!, eigen.vectors[6]!];
  const v2 = [eigen.vectors[1]!, eigen.vectors[4]!, eigen.vectors[7]!];
  let v3 = [eigen.vectors[2]!, eigen.vectors[5]!, eigen.vectors[8]!];
  // The third singular direction is undefined for planar data; make V a
  // right-handed basis so the proper completion is unambiguous.
  const planar = !(singular[2] > 1e-6 * singular[0]);
  if (planar) v3 = cross(v1, v2);
  const u1 = unitVector(matrixVector(h, v1, singular[0]));
  const u2 = unitVector(matrixVector(h, v2, singular[1]));
  let u3 = planar ? cross(u1, u2) : unitVector(matrixVector(h, v3, singular[2]));
  const determinantProduct = determinant3(v1, v2, v3) * determinant3(u1, u2, u3);
  const reflection = determinantProduct < 0 ? -1 : 1;
  // R = V D U^T with D = diag(1, 1, reflection). Rows i, columns j.
  const rotation: [number, number, number, number, number, number, number, number, number] = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) {
      rotation[i * 3 + j] = v1[i]! * u1[j]! + v2[i]! * u2[j]! + reflection * v3[i]! * u3[j]!;
    }
  }
  return rotation;
}

/** H = sum w (mobile - c_m)(reference - c_r)^T, row-major 3x3. */
function correlationMatrix(
  reference: Float64Array,
  mobile: Float64Array,
  weights: Float64Array,
  count: number,
  referenceCenter?: readonly [number, number, number],
  mobileCenter?: readonly [number, number, number],
): Matrix9 {
  const rc = referenceCenter ?? weightedCentroid(reference, weights, count);
  const mc = mobileCenter ?? weightedCentroid(mobile, weights, count);
  const h: Matrix9 = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  for (let index = 0; index < count; index += 1) {
    const weight = weights[index]!;
    const mx = mobile[index * 3]! - mc[0];
    const my = mobile[index * 3 + 1]! - mc[1];
    const mz = mobile[index * 3 + 2]! - mc[2];
    const rx = reference[index * 3]! - rc[0];
    const ry = reference[index * 3 + 1]! - rc[1];
    const rz = reference[index * 3 + 2]! - rc[2];
    h[0] += weight * mx * rx; h[1] += weight * mx * ry; h[2] += weight * mx * rz;
    h[3] += weight * my * rx; h[4] += weight * my * ry; h[5] += weight * my * rz;
    h[6] += weight * mz * rx; h[7] += weight * mz * ry; h[8] += weight * mz * rz;
  }
  return h;
}

/** The three singular values of a row-major 3x3 matrix, descending. */
function singularValues(matrix: Matrix9): [number, number, number] {
  const a = [
    matrix[0]! * matrix[0]! + matrix[3]! * matrix[3]! + matrix[6]! * matrix[6]!,
    matrix[0]! * matrix[1]! + matrix[3]! * matrix[4]! + matrix[6]! * matrix[7]!,
    matrix[0]! * matrix[2]! + matrix[3]! * matrix[5]! + matrix[6]! * matrix[8]!,
    matrix[0]! * matrix[1]! + matrix[3]! * matrix[4]! + matrix[6]! * matrix[7]!,
    matrix[1]! * matrix[1]! + matrix[4]! * matrix[4]! + matrix[7]! * matrix[7]!,
    matrix[1]! * matrix[2]! + matrix[4]! * matrix[5]! + matrix[7]! * matrix[8]!,
    matrix[0]! * matrix[2]! + matrix[3]! * matrix[5]! + matrix[6]! * matrix[8]!,
    matrix[1]! * matrix[2]! + matrix[4]! * matrix[5]! + matrix[7]! * matrix[8]!,
    matrix[2]! * matrix[2]! + matrix[5]! * matrix[5]! + matrix[8]! * matrix[8]!,
  ];
  return jacobiEigenSymmetric3(a).values.map((value) => Math.sqrt(Math.max(0, value))) as [number, number, number];
}

/**
 * Cyclic Jacobi eigen-decomposition of a real symmetric 3x3 matrix.
 *
 * `values` are descending; `vectors` is row-major with eigenvector k in column
 * k. Float64 throughout; no dependence on a DOM or Mol* runtime.
 */
function jacobiEigenSymmetric3(source: readonly number[]): { values: [number, number, number]; vectors: number[] } {
  const a = source.slice();
  const v = [1, 0, 0, 0, 1, 0, 0, 0, 1];
  for (let sweep = 0; sweep < 32; sweep += 1) {
    const pairs: Array<[number, number]> = [[0, 1], [0, 2], [1, 2]];
    let largest = 0;
    let pivot: [number, number] = [0, 1];
    for (const pair of pairs) {
      const magnitude = Math.abs(a[pair[0] * 3 + pair[1]]!);
      if (magnitude > largest) { largest = magnitude; pivot = pair; }
    }
    const scale = Math.abs(a[pivot[0] * 3 + pivot[0]]!) + Math.abs(a[pivot[1] * 3 + pivot[1]]!) + 1e-30;
    if (largest <= 1e-15 * scale) break;
    const [p, q] = pivot;
    const apq = a[p * 3 + q]!;
    const theta = (a[q * 3 + q]! - a[p * 3 + p]!) / (2 * apq);
    const t = theta >= 0 ? 1 / (theta + Math.sqrt(theta * theta + 1)) : 1 / (theta - Math.sqrt(theta * theta + 1));
    const c = 1 / Math.sqrt(t * t + 1);
    const s = t * c;
    for (let k = 0; k < 3; k += 1) {
      const akp = a[k * 3 + p]!;
      const akq = a[k * 3 + q]!;
      a[k * 3 + p] = c * akp - s * akq;
      a[k * 3 + q] = s * akp + c * akq;
    }
    for (let k = 0; k < 3; k += 1) {
      const apk = a[p * 3 + k]!;
      const aqk = a[q * 3 + k]!;
      a[p * 3 + k] = c * apk - s * aqk;
      a[q * 3 + k] = s * apk + c * aqk;
    }
    for (let k = 0; k < 3; k += 1) {
      const vkp = v[k * 3 + p]!;
      const vkq = v[k * 3 + q]!;
      v[k * 3 + p] = c * vkp - s * vkq;
      v[k * 3 + q] = s * vkp + c * vkq;
    }
  }
  const order = [0, 1, 2].sort((left, right) => a[right * 3 + right]! - a[left * 3 + left]!);
  const values = order.map((index) => a[index * 3 + index]!) as [number, number, number];
  const vectors: number[] = new Array(9);
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 3; column += 1) vectors[row * 3 + column] = v[row * 3 + order[column]!]!;
  }
  return { values, vectors };
}

function dotRow(rotation: RigidTransform['rotation'], row: number, vector: readonly [number, number, number]): number {
  return rotation[row * 3]! * vector[0] + rotation[row * 3 + 1]! * vector[1] + rotation[row * 3 + 2]! * vector[2];
}

function rmsdOf(
  reference: Float64Array,
  mobile: Float64Array,
  weights: Float64Array,
  count: number,
  rotation: RigidTransform['rotation'],
  translation: readonly [number, number, number],
): number {
  let sum = 0;
  let total = 0;
  for (let index = 0; index < count; index += 1) {
    const weight = weights[index]!;
    const x = mobile[index * 3]!;
    const y = mobile[index * 3 + 1]!;
    const z = mobile[index * 3 + 2]!;
    const dx = rotation[0]! * x + rotation[1]! * y + rotation[2]! * z + translation[0] - reference[index * 3]!;
    const dy = rotation[3]! * x + rotation[4]! * y + rotation[5]! * z + translation[1] - reference[index * 3 + 1]!;
    const dz = rotation[6]! * x + rotation[7]! * y + rotation[8]! * z + translation[2] - reference[index * 3 + 2]!;
    sum += weight * (dx * dx + dy * dy + dz * dz);
    total += weight;
  }
  return Math.sqrt(sum / total);
}

function matrixVector(matrix: Matrix9, vector: number[], scale = 1): [number, number, number] {
  return [
    (matrix[0]! * vector[0]! + matrix[1]! * vector[1]! + matrix[2]! * vector[2]!) / scale,
    (matrix[3]! * vector[0]! + matrix[4]! * vector[1]! + matrix[5]! * vector[2]!) / scale,
    (matrix[6]! * vector[0]! + matrix[7]! * vector[1]! + matrix[8]! * vector[2]!) / scale,
  ];
}

function unitVector(vector: readonly [number, number, number]): [number, number, number] {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  if (!(length > 0) || !Number.isFinite(length)) throw new TrajectoryFitError('The fit produced a degenerate rotation axis.');
  return [vector[0] / length, vector[1] / length, vector[2] / length];
}

function cross(left: number[], right: number[]): [number, number, number] {
  return [
    left[1]! * right[2]! - left[2]! * right[1]!,
    left[2]! * right[0]! - left[0]! * right[2]!,
    left[0]! * right[1]! - left[1]! * right[0]!,
  ];
}

function determinant3(a: number[], b: number[], c: number[]): number {
  return a[0]! * (b[1]! * c[2]! - b[2]! * c[1]!) - a[1]! * (b[0]! * c[2]! - b[2]! * c[0]!) + a[2]! * (b[0]! * c[1]! - b[1]! * c[0]!);
}
