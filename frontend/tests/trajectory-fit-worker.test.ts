import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  FIT_MAX_FRAMES,
  FIT_MAX_TRANSFER_BYTES,
  FrameFitSession,
  assertFitJobSize,
  assertUniqueAtomIndices,
  type FitRequest,
} from '../src/features/structure/trajectory-fit-protocol';
import { TrajectoryFitClient, type FitWorkerFactory } from '../src/features/structure/trajectory-fit-client';
import { TrajectoryFitError } from '../src/features/structure/trajectory-fit';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

const REFERENCE = new Float64Array([
  0, 0, 0,
  4, 0, 0,
  0, 3, 0,
  2, 2, 5,
]);

function translated(x: number, y: number, z: number): Float64Array {
  const frame = new Float64Array(REFERENCE.length);
  for (let index = 0; index < REFERENCE.length; index += 3) {
    frame[index] = REFERENCE[index]! + x;
    frame[index + 1] = REFERENCE[index + 1]! + y;
    frame[index + 2] = REFERENCE[index + 2]! + z;
  }
  return frame;
}

function start(generation: number, frameCount = 2): FitRequest {
  return { type: 'start', generation, mode: 'fit', atomCount: 4, frameCount, reference: REFERENCE };
}

describe('bounded fit session', () => {
  it('fits each frame independently and reports a known zero RMSD', () => {
    const session = new FrameFitSession({
      type: 'start', generation: 1, mode: 'fit', atomCount: 4, frameCount: 2, reference: REFERENCE,
    });
    expect(session.pushChunk(0, translated(1, 2, 3))).toBe(1);
    expect(session.pushChunk(1, translated(-4, 0, 2))).toBe(2);
    expect(session.complete).toBe(true);
    const result = session.finish();
    expect(result.rejectedFrames).toEqual([]);
    // Frame 0's translation is recovered exactly; frame 1's is a different one.
    expect(result.rmsd[0]!).toBeCloseTo(0, 9);
    expect(result.rmsd[1]!).toBeCloseTo(0, 9);
    expect(result.transforms[12]!).toBeCloseTo(-1, 9);
    expect(result.transforms[28]!).toBeCloseTo(4, 9);
  });

  it('marks a degenerate frame unfit instead of emitting an arbitrary rotation', () => {
    const session = new FrameFitSession({
      type: 'start', generation: 1, mode: 'fit', atomCount: 4, frameCount: 2, reference: REFERENCE,
    });
    const collapsed = new Float64Array(12).fill(1);
    session.pushChunk(0, collapsed);
    session.pushChunk(1, translated(0, 0, 0));
    const result = session.finish();
    expect(result.rejectedFrames).toEqual([0]);
    expect(Number.isNaN(result.rmsd[0]!)).toBe(true);
    expect(result.transforms[0]!).toBe(1);
    expect(result.transforms[12]!).toBe(0);
    expect(result.rmsd[1]!).toBeCloseTo(0, 9);
  });

  it('rejects a malformed chunk and an invalid reference selection', () => {
    const session = new FrameFitSession({
      type: 'start', generation: 1, mode: 'fit', atomCount: 4, frameCount: 2, reference: REFERENCE,
    });
    expect(() => session.pushChunk(0, new Float64Array(6))).toThrow('whole frames');
    expect(() => session.pushChunk(2, translated(0, 0, 0))).toThrow('exceeds');
    expect(() => new FrameFitSession({
      type: 'start', generation: 2, mode: 'fit', atomCount: 3, frameCount: 1,
      reference: new Float64Array([0, 0, 0, 1, 0, 0, 2, 0, 0]),
    })).toThrow('degenerate');
  });

  it('enforces the transfer envelope before any chunk is read', () => {
    expect(() => assertFitJobSize(2, 10)).toThrow('3 to');
    expect(() => assertFitJobSize(20001, 10)).toThrow('3 to');
    expect(() => assertFitJobSize(10, FIT_MAX_FRAMES + 1)).toThrow('frames');
    expect(() => assertFitJobSize(20000, 50000)).toThrow('too large');
    expect(FIT_MAX_TRANSFER_BYTES).toBeLessThan(20000 * 50000 * 24);
    expect(() => assertFitJobSize(100, 100)).not.toThrow();
  });

  it('rejects duplicated or non-integer atom indices', () => {
    expect(() => assertUniqueAtomIndices([0, 1, 2])).not.toThrow();
    expect(() => assertUniqueAtomIndices([0, 1, 1])).toThrow('same atom');
    expect(() => assertUniqueAtomIndices([0, -1])).toThrow('non-negative integers');
    expect(() => assertUniqueAtomIndices([0, 1.5])).toThrow('non-negative integers');
  });
});

interface FakeScope {
  sent: Array<{ message: Record<string, unknown>; transfer: Transferable[] }>;
  addEventListener(type: string, listener: (event: { data: FitRequest }) => void): void;
  postMessage(message: Record<string, unknown>, transfer?: Transferable[]): void;
  dispatch(message: FitRequest): void;
}

function fakeScope(): FakeScope {
  const listeners: Array<(event: { data: FitRequest }) => void> = [];
  const scope: FakeScope = {
    sent: [],
    addEventListener: (_type, listener) => listeners.push(listener),
    postMessage: (message, transfer = []) => { scope.sent.push({ message, transfer }); },
    dispatch: (message) => listeners.forEach((listener) => listener({ data: message })),
  };
  return scope;
}

describe('worker message contract', () => {
  it('posts progress and one transferred result, then ignores a stale generation', async () => {
    const scope = fakeScope();
    vi.stubGlobal('self', scope);
    await import('../src/features/structure/trajectory-fit-worker');

    scope.dispatch(start(7));
    expect(scope.sent[0]!.message).toMatchObject({ type: 'progress', generation: 7, completed: 0, total: 2 });
    scope.dispatch({ type: 'chunk', generation: 7, frameStart: 0, coordinates: translated(1, 0, 0) });
    scope.dispatch({ type: 'chunk', generation: 7, frameStart: 1, coordinates: translated(2, 0, 0) });
    const done = scope.sent.at(-1)!;
    expect(done.message).toMatchObject({ type: 'done', generation: 7 });
    expect(done.transfer).toHaveLength(2);

    // A chunk from an older generation must not reach the new session.
    const before = scope.sent.length;
    scope.dispatch({ type: 'chunk', generation: 6, frameStart: 0, coordinates: translated(1, 0, 0) });
    expect(scope.sent.length).toBe(before);
  });

  it('cancels a generation and reports a bad reference as an error', async () => {
    const scope = fakeScope();
    vi.stubGlobal('self', scope);
    await import('../src/features/structure/trajectory-fit-worker');

    scope.dispatch({ type: 'start', generation: 3, mode: 'fit', atomCount: 3, frameCount: 1, reference: new Float64Array([0, 0, 0, 1, 0, 0, 2, 0, 0]) });
    expect(scope.sent.at(-1)!.message).toMatchObject({ type: 'error', generation: 3 });
    expect(String(scope.sent.at(-1)!.message.message)).toContain('degenerate');

    scope.dispatch(start(4));
    scope.dispatch({ type: 'cancel', generation: 4 });
    const before = scope.sent.length;
    scope.dispatch({ type: 'chunk', generation: 4, frameStart: 0, coordinates: translated(1, 0, 0) });
    expect(scope.sent.length).toBe(before);
  });
});

interface FakeWorker {
  messages: Array<Record<string, unknown>>;
  terminated: boolean;
  postMessage(message: Record<string, unknown>, transfer?: Transferable[]): void;
  addEventListener(type: string, listener: (event: { data?: unknown; message?: string }) => void): void;
  removeEventListener(type: string, listener: (event: { data?: unknown; message?: string }) => void): void;
  terminate(): void;
  emit(data: unknown): void;
  emitError(message: string): void;
}

function fakeWorkerFactory(): { factory: FitWorkerFactory; worker: FakeWorker } {
  const listeners: Record<string, Array<(event: { data?: unknown; message?: string }) => void>> = {};
  let received = 0;
  let declared: { generation: number; frameCount: number; atomCount: number } | null = null;
  const worker: FakeWorker = {
    messages: [],
    terminated: false,
    postMessage(message) {
      this.messages.push(message);
      if (message.type === 'start') {
        declared = { generation: Number(message.generation), frameCount: Number(message.frameCount), atomCount: Number(message.atomCount) };
        received = 0;
      }
      if (message.type === 'chunk' && declared) {
        received += Number((message.coordinates as Float64Array).length) / (declared.atomCount * 3);
        if (received === declared.frameCount) {
          setTimeout(() => {
            this.emit({ type: 'progress', generation: declared!.generation, completed: received, total: declared!.frameCount });
            this.emit({
              type: 'done',
              generation: declared!.generation,
              transforms: new Float64Array(declared!.frameCount * 16),
              rmsd: new Float64Array(declared!.frameCount),
              rejectedFrames: [],
            });
          }, 0);
        }
      }
    },
    addEventListener(type, listener) {
      (listeners[type] ||= []).push(listener);
    },
    removeEventListener(type, listener) {
      const registered = listeners[type] || [];
      const index = registered.indexOf(listener);
      if (index >= 0) registered.splice(index, 1);
    },
    terminate() { this.terminated = true; },
    emit(data) { (listeners.message || []).slice().forEach((listener) => listener({ data })); },
    emitError(message) { (listeners.error || []).slice().forEach((listener) => listener({ message })); },
  };
  return { factory: () => worker as unknown as Worker, worker };
}

describe('fit worker client', () => {
  it('reads frames in bounded chunks, reports progress, and returns the result', async () => {
    const { factory, worker } = fakeWorkerFactory();
    const client = new TrajectoryFitClient(factory);
    const frames: number[] = [];
    const progress: Array<[number, number]> = [];
    const result = await client.run({
      mode: 'fit', reference: REFERENCE, atomCount: 4, frameCount: 3,
      readFrame: (frame) => { frames.push(frame); return translated(frame, 0, 0); },
      onProgress: (completed, total) => progress.push([completed, total]),
    });
    expect(frames).toEqual([0, 1, 2]);
    expect(result.transforms).toHaveLength(48);
    expect(progress).toEqual([[3, 3]]);
    expect(worker.messages[0]).toMatchObject({ type: 'start', generation: 1, frameCount: 3 });
    const chunks = worker.messages.filter((message) => message.type === 'chunk') as Array<{ coordinates: Float64Array }>;
    expect(chunks).toHaveLength(1);
    expect(chunks[0]!.coordinates.length).toBe(3 * 4 * 3);
    client.dispose();
    expect(worker.terminated).toBe(true);
  });

  it('cancels the active run and a newer run supersedes the old one', async () => {
    const { factory, worker } = fakeWorkerFactory();
    const client = new TrajectoryFitClient(factory);
    const controller = new AbortController();
    const first = client.run({
      mode: 'fit', reference: REFERENCE, atomCount: 4, frameCount: 5,
      readFrame: (frame) => translated(frame, 0, 0), signal: controller.signal,
    });
    controller.abort();
    await expect(first).rejects.toMatchObject({ name: 'AbortError' });
    expect(worker.messages.some((message) => message.type === 'cancel')).toBe(true);

    const second = client.run({
      mode: 'center', reference: REFERENCE, atomCount: 4, frameCount: 1,
      readFrame: () => translated(0, 0, 0),
    });
    await expect(second).resolves.toBeDefined();
  });

  it('refuses a job outside the bounded envelope before creating a worker', async () => {
    const factory = vi.fn(() => fakeWorkerFactory().worker as unknown as Worker);
    const client = new TrajectoryFitClient(factory as unknown as FitWorkerFactory);
    await expect(client.run({
      mode: 'fit', reference: REFERENCE, atomCount: 20001, frameCount: 10,
      readFrame: () => REFERENCE,
    })).rejects.toBeInstanceOf(TrajectoryFitError);
    expect(factory).not.toHaveBeenCalled();
  });

  it('rejects when a frame does not match the declared selection', async () => {
    const { factory } = fakeWorkerFactory();
    const client = new TrajectoryFitClient(factory);
    await expect(client.run({
      mode: 'fit', reference: REFERENCE, atomCount: 4, frameCount: 1,
      readFrame: () => new Float64Array(3),
    })).rejects.toThrow('did not match the fit selection');
    client.dispose();
  });
});
