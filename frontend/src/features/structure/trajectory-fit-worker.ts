/*
 * Dedicated worker entry for browser-local trajectory fitting.
 *
 * The session is pure (`FrameFitSession`); this file is only the message plumbing
 * and the transfer of the compact result buffers. A stale generation is dropped
 * without touching the active session.
 */
import { FrameFitSession, type FitRequest, type FitResponse } from './trajectory-fit-protocol';

let session: FrameFitSession | null = null;
let generation = -1;

/** The worker global this module runs in; typed locally because the DOM lib omits it. */
interface WorkerScope {
  postMessage(message: FitResponse, transfer?: Transferable[]): void;
  addEventListener(type: 'message', listener: (event: MessageEvent<FitRequest>) => void): void;
}

function describe(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

function post(message: FitResponse, transfer: Transferable[] = []): void {
  (self as unknown as WorkerScope).postMessage(message, transfer);
}

function handle(message: FitRequest): void {
  if (message.type === 'start') {
    generation = message.generation;
    session = null;
    try {
      session = new FrameFitSession(message);
      post({ type: 'progress', generation, completed: 0, total: message.frameCount });
    } catch (error) {
      post({ type: 'error', generation, message: describe(error) });
    }
    return;
  }
  if (message.type === 'cancel') {
    if (message.generation === generation) {
      session = null;
      generation = -1;
    }
    return;
  }
  if (message.generation !== generation || !session) return;
  try {
    const completed = session.pushChunk(message.frameStart, message.coordinates);
    if (session.complete) {
      const done = session.finish();
      session = null;
      post(done, [done.transforms.buffer, done.rmsd.buffer]);
    } else {
      post({ type: 'progress', generation, completed, total: session.frameCount });
    }
  } catch (error) {
    session = null;
    post({ type: 'error', generation, message: describe(error) });
  }
}

const scope = typeof self !== 'undefined' && typeof (self as { addEventListener?: unknown }).addEventListener === 'function'
  ? self as unknown as WorkerScope
  : null;

if (scope) {
  scope.addEventListener('message', (event: MessageEvent<FitRequest>) => handle(event.data));
}
