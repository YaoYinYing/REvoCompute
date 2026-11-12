/*
 * Main-thread driver for the trajectory fit worker.
 *
 * The client owns the bounded transfer envelope, chunking, progress, cancellation
 * and the generation token that drops stale results. It never reads every
 * source frame into a long-lived buffer: one chunk is built, transferred, and
 * released before the next is read.
 */
import { TrajectoryFitError, type FitMode } from './trajectory-fit';
import {
  assertFitJobSize,
  type FitChunkMessage,
  type FitDoneMessage,
  type FitErrorMessage,
  type FitProgressMessage,
  type FitRequest,
  type FitResponse,
} from './trajectory-fit-protocol';

/** Coordinate bytes per chunk; small enough to keep cancellation responsive. */
const MAX_CHUNK_BYTES = 4 * 1024 * 1024;
const MAX_CHUNK_FRAMES = 64;

export interface FitJobInput {
  mode: FitMode;
  /** Fit-subset reference coordinates, flat xyz. */
  reference: Float64Array;
  atomCount: number;
  frameCount: number;
  weights?: Float64Array;
  /** Read one frame's fit-subset coordinates from the loaded trajectory. */
  readFrame(frame: number): Float64Array;
  signal?: AbortSignal;
  onProgress?(completed: number, total: number): void;
}

export interface FitJobResult {
  /** Column-major 4x4 preview transform per frame. */
  transforms: Float64Array;
  /** RMSD on the fit selection per frame, in Angstrom; NaN for a rejected frame. */
  rmsd: Float64Array;
  rejectedFrames: number[];
}

export type FitWorkerFactory = () => Worker;

function aborted(): DOMException {
  return new DOMException('The trajectory fit was superseded.', 'AbortError');
}

function defaultWorkerFactory(): Worker {
  if (typeof Worker === 'undefined') throw new TrajectoryFitError('This browser cannot run a background fit worker.');
  return new Worker(new URL('./trajectory-fit-worker.ts', import.meta.url), { type: 'module' });
}

function yieldToMain(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

interface ActiveRun {
  generation: number;
  onProgress?: (completed: number, total: number) => void;
  /** Settle the run's promise; idempotent. */
  fail(reason: unknown): void;
}

export class TrajectoryFitClient {
  private worker: Worker | null = null;
  private generation = 0;
  private active: ActiveRun | null = null;

  constructor(private readonly createWorker: FitWorkerFactory = defaultWorkerFactory) {}

  /** Fit every frame, transferring bounded chunks. A newer run cancels this one. */
  async run(input: FitJobInput): Promise<FitJobResult> {
    assertFitJobSize(input.atomCount, input.frameCount);
    const generation = ++this.generation;
    this.supersede();
    if (input.signal?.aborted) throw aborted();
    const worker = this.workerFor();

    let settle: ((reason: unknown) => void) | null = null;
    const completed = new Promise<FitJobResult>((resolve, reject) => {
      let settled = false;
      const fail = (reason: unknown): void => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(reason);
      };
      const onMessage = (event: MessageEvent<FitResponse>): void => {
        const message = event.data;
        if (!message || message.generation !== generation || settled) return;
        if (message.type === 'progress') {
          this.progress(message);
          return;
        }
        if (message.type === 'error') {
          fail(new TrajectoryFitError((message as FitErrorMessage).message));
          return;
        }
        settled = true;
        cleanup();
        const done = message as FitDoneMessage;
        resolve({ transforms: done.transforms, rmsd: done.rmsd, rejectedFrames: done.rejectedFrames });
      };
      const onFailure = (event: ErrorEvent): void => {
        fail(new TrajectoryFitError(event.message || 'The background fit worker failed.'));
      };
      const cleanup = (): void => {
        worker.removeEventListener('message', onMessage);
        worker.removeEventListener('error', onFailure);
        if (this.active?.generation === generation) this.active = null;
      };
      worker.addEventListener('message', onMessage);
      worker.addEventListener('error', onFailure);
      settle = fail;
    });
    const active: ActiveRun = { generation, onProgress: input.onProgress, fail: (reason) => settle?.(reason) };
    this.active = active;
    // The run can be cancelled while a chunk is being read, before `await
    // completed` is reached; mark the rejection observed so cancellation is not
    // reported as an unhandled rejection.
    completed.catch(() => undefined);
    const onAbort = (): void => this.cancel();
    input.signal?.addEventListener('abort', onAbort, { once: true });

    try {
      this.post({
        type: 'start',
        generation,
        mode: input.mode,
        atomCount: input.atomCount,
        frameCount: input.frameCount,
        reference: input.reference,
        ...(input.weights ? { weights: input.weights } : {}),
      });
      const framesPerChunk = Math.max(1, Math.min(MAX_CHUNK_FRAMES, Math.floor(MAX_CHUNK_BYTES / (input.atomCount * 3 * 8))));
      const frameBytes = input.atomCount * 3;
      for (let frameStart = 0; frameStart < input.frameCount; frameStart += framesPerChunk) {
        if (generation !== this.generation || input.signal?.aborted) throw aborted();
        const chunkFrames = Math.min(framesPerChunk, input.frameCount - frameStart);
        const coordinates = new Float64Array(chunkFrames * frameBytes);
        for (let offset = 0; offset < chunkFrames; offset += 1) {
          const frame = input.readFrame(frameStart + offset);
          if (frame.length !== frameBytes) throw new TrajectoryFitError('A trajectory frame did not match the fit selection.');
          coordinates.set(frame, offset * frameBytes);
        }
        const chunk: FitChunkMessage = { type: 'chunk', generation, frameStart, coordinates };
        this.post(chunk, [coordinates.buffer]);
        await yieldToMain();
      }
      return await completed;
    } catch (error) {
      active.fail(error);
      throw error;
    } finally {
      input.signal?.removeEventListener('abort', onAbort);
      if (this.active?.generation === generation) this.active = null;
    }
  }

  /** Cancel the active run without terminating the reusable worker. */
  cancel(): void {
    const active = this.active;
    this.active = null;
    if (!active) return;
    this.generation += 1;
    this.post({ type: 'cancel', generation: active.generation });
    active.fail(aborted());
  }

  dispose(): void {
    const active = this.active;
    this.active = null;
    this.generation += 1;
    if (active) {
      this.post({ type: 'cancel', generation: active.generation });
      active.fail(aborted());
    }
    this.worker?.terminate();
    this.worker = null;
  }

  private workerFor(): Worker {
    this.worker ??= this.createWorker();
    return this.worker;
  }

  private supersede(): void {
    const previous = this.active;
    if (!previous) return;
    this.active = null;
    this.post({ type: 'cancel', generation: previous.generation });
    previous.fail(aborted());
  }

  private progress(message: FitProgressMessage): void {
    const active = this.active;
    if (!active || active.generation !== message.generation) return;
    active.onProgress?.(message.completed, message.total);
  }

  private post(message: FitRequest, transfer: Transferable[] = []): void {
    try {
      this.worker?.postMessage(message, transfer);
    } catch {
      // A terminated worker cannot accept a cancel; the rejecting promise stands.
    }
  }
}
