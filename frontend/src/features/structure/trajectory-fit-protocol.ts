/*
 * The bounded message contract between the trajectory fit panel and its Web
 * Worker, plus the pure frame-chunk session the worker runs.
 *
 * Only the fit atom subset crosses the thread boundary: the whole topology and
 * the source coordinate bytes stay in the main thread. Each chunk is one flat
 * Float64 buffer that is transferred, and the result is 16 column-major matrix
 * values plus one RMSD per frame, so memory is bounded by the selection size and
 * the frame count rather than by every atom of every frame.
 */
import {
  IDENTITY_TRANSFORM,
  TrajectoryFitError,
  fitFrame,
  toColumnMajorMatrix,
  validateFitSelection,
  type FitMode,
} from './trajectory-fit';

/** A selection larger than this is not a browser preview; use a server Tool. */
export const FIT_MAX_ATOMS = 20000;
/** More frames than this cannot be fitted within a bounded preview session. */
export const FIT_MAX_FRAMES = 50000;
/** Upper bound on the Float64 coordinate bytes a session may transfer. */
export const FIT_MAX_TRANSFER_BYTES = 128 * 1024 * 1024;

/** Reject a job whose bounded memory envelope would be exceeded. */
export function assertFitJobSize(atomCount: number, frameCount: number): void {
  if (!Number.isInteger(atomCount) || atomCount < 3 || atomCount > FIT_MAX_ATOMS) {
    throw new TrajectoryFitError(
      `A browser fit supports 3 to ${FIT_MAX_ATOMS} selected atoms. Use a validated server Tool for a larger selection, conversion, or unwrapping.`,
    );
  }
  if (!Number.isInteger(frameCount) || frameCount < 1 || frameCount > FIT_MAX_FRAMES) {
    throw new TrajectoryFitError(
      `A browser fit supports 1 to ${FIT_MAX_FRAMES} frames. Convert a longer trajectory with a validated server Tool.`,
    );
  }
  if (atomCount * frameCount * 3 * 8 > FIT_MAX_TRANSFER_BYTES) {
    throw new TrajectoryFitError(
      'This trajectory is too large for a browser-local fit. Convert or unwrap it with a validated server Tool.',
    );
  }
}

/**
 * Reject a selection that addresses the same atom more than once or a
 * non-integer/negative viewer index. A fit needs a one-to-one atom mapping.
 */
export function assertUniqueAtomIndices(indices: readonly number[]): void {
  const seen = new Set<number>();
  for (const index of indices) {
    if (!Number.isInteger(index) || index < 0) throw new TrajectoryFitError('Fit atom indices must be non-negative integers.');
    if (seen.has(index)) throw new TrajectoryFitError('The fit selection addresses the same atom more than once.');
    seen.add(index);
  }
}

export interface FitStartMessage {
  type: 'start';
  generation: number;
  mode: FitMode;
  atomCount: number;
  frameCount: number;
  reference: Float64Array;
  weights?: Float64Array;
}

export interface FitChunkMessage {
  type: 'chunk';
  generation: number;
  frameStart: number;
  coordinates: Float64Array;
}

export interface FitCancelMessage {
  type: 'cancel';
  generation: number;
}

export type FitRequest = FitStartMessage | FitChunkMessage | FitCancelMessage;

export interface FitProgressMessage {
  type: 'progress';
  generation: number;
  completed: number;
  total: number;
}

export interface FitDoneMessage {
  type: 'done';
  generation: number;
  /** Column-major 4x4 preview transform per frame, frameCount * 16 values. */
  transforms: Float64Array;
  /** Fit-selection RMSD per frame; NaN for a rejected frame. */
  rmsd: Float64Array;
  rejectedFrames: number[];
}

export interface FitErrorMessage {
  type: 'error';
  generation: number;
  message: string;
  frame?: number;
}

export type FitResponse = FitProgressMessage | FitDoneMessage | FitErrorMessage;

/**
 * One worker-side fitting session. Frames arrive in bounded chunks; each frame
 * is fitted independently and only the compact result is retained.
 */
export class FrameFitSession {
  readonly generation: number;
  readonly atomCount: number;
  readonly frameCount: number;
  private readonly mode: FitMode;
  private readonly reference: Float64Array;
  private readonly weights: Float64Array | undefined;
  private readonly transforms: Float64Array;
  private readonly rmsd: Float64Array;
  private readonly rejected: number[] = [];
  private receivedFrames = 0;

  constructor(message: FitStartMessage) {
    assertFitJobSize(message.atomCount, message.frameCount);
    this.generation = message.generation;
    this.mode = message.mode;
    this.atomCount = message.atomCount;
    this.frameCount = message.frameCount;
    this.reference = message.reference;
    this.weights = message.weights;
    validateFitSelection(message.reference, message.weights);
    this.transforms = new Float64Array(message.frameCount * 16);
    this.rmsd = new Float64Array(message.frameCount);
    this.rmsd.fill(Number.NaN);
    const identity = toColumnMajorMatrix(IDENTITY_TRANSFORM);
    for (let frame = 0; frame < message.frameCount; frame += 1) this.transforms.set(identity, frame * 16);
  }

  get complete(): boolean {
    return this.receivedFrames >= this.frameCount;
  }

  get completedFrames(): number {
    return this.receivedFrames;
  }

  /** Fit the frames in one chunk; returns the new completed-frame count. */
  pushChunk(frameStart: number, coordinates: Float64Array): number {
    if (this.complete) throw new TrajectoryFitError('The fit session already has every frame.');
    if (!Number.isInteger(frameStart) || frameStart < 0) throw new TrajectoryFitError('A chunk needs a non-negative frame start.');
    const frames = coordinates.length / (this.atomCount * 3);
    if (!Number.isInteger(frames) || frames <= 0) throw new TrajectoryFitError('A chunk needs whole frames.');
    if (frameStart + frames > this.frameCount) throw new TrajectoryFitError('A chunk exceeds the declared frame count.');
    for (let offset = 0; offset < frames; offset += 1) {
      const frame = frameStart + offset;
      const mobile = coordinates.subarray(offset * this.atomCount * 3, (offset + 1) * this.atomCount * 3);
      try {
        const result = fitFrame(this.reference, mobile, { mode: this.mode, weights: this.weights });
        this.transforms.set(toColumnMajorMatrix(result.transform), frame * 16);
        this.rmsd[frame] = result.rmsd;
      } catch (error) {
        // One degenerate frame (for example a wrapped collapse) is reported as
        // unfit rather than given an arbitrary rotation; the other frames stand.
        if (!(error instanceof TrajectoryFitError)) throw error;
        this.rejected.push(frame);
      }
    }
    this.receivedFrames += frames;
    return this.receivedFrames;
  }

  finish(): FitDoneMessage {
    if (!this.complete) throw new TrajectoryFitError('The fit session is missing frames.');
    return {
      type: 'done',
      generation: this.generation,
      transforms: this.transforms,
      rmsd: this.rmsd,
      rejectedFrames: this.rejected.slice(),
    };
  }
}
