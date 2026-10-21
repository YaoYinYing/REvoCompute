import { resultFileName, type ResultFile } from '../../../api/result-types';
import { t } from '../../../app/i18n';
import type { MolecularViewer, MolecularViewerFactory, TrajectoryInfo } from './viewer-contract';

const MAX_STRUCTURE_BYTES = 64 * 1024 * 1024;

// A runner may publish a compressed structure (`*.cif.gz` is what RFdiffusion3
// writes). The viewer parses the decompressed bytes, so the compression suffix
// is peeled before the format is read and the payload is gunzipped on the way
// in; without that, a `.cif.gz` name selected the PDB parser and the gzip
// payload was handed to it verbatim.
const GZIPPED = /\.gz$/i;

// A structure is ASCII, so the size of its text and the size of its UTF-8
// encoding are the same number; the test makes that the common case cheap and
// leaves the character-by-character measure for text that has to be measured.
const NON_ASCII = /[^\x00-\x7f]/;

function structureFormat(path: string): 'pdb' | 'mmcif' | 'pqr' {
  if (/\.pqr(?:\.gz)?$/i.test(path)) return 'pqr';
  return /\.(?:cif|mmcif)(?:\.gz)?$/i.test(path) ? 'mmcif' : 'pdb';
}

function aborted(): DOMException {
  return new DOMException('The trajectory load was superseded.', 'AbortError');
}

function readSource(path: string, response: Response): Promise<string> {
  const compressed = GZIPPED.test(path);
  if (response.body) return boundedText(compressed ? inflate(response.body) : response.body, MAX_STRUCTURE_BYTES);
  // No readable stream: the platform hands the body back whole, so the bytes are
  // measured once rather than trusted from the declared size, and a compressed
  // payload is still bounded as it inflates.
  return boundedWhole(compressed, response);
}

/** Bound a whole body the platform handed back without a stream. */
async function boundedWhole(compressed: boolean, response: Response): Promise<string> {
  const payload = await response.arrayBuffer();
  if (payload.byteLength > MAX_STRUCTURE_BYTES) throw new Error(t('results.structure.tooLarge'));
  if (compressed) return boundedText(inflate(new Blob([payload]).stream()), MAX_STRUCTURE_BYTES);
  const text = new TextDecoder().decode(payload);
  // Decoding invalid bytes emits U+FFFD, so the text can be larger than the bytes
  // it came from; measure what the parser would actually receive, with the same
  // measure the streamed path applies.
  if (encodedLength(text) > MAX_STRUCTURE_BYTES) throw new Error(t('results.structure.tooLarge'));
  return text;
}

/**
 * Read a byte stream into a binary payload, refusing anything past `limit`.
 *
 * Coordinate frames (XTC/DCD) are binary and must reach Mol* byte-for-byte, so
 * unlike a structure they are never decoded. The accepted byte count is both
 * the declared and the streamed size: the limit is the same 64 MiB the
 * structure preview applies, and a body without a readable stream is measured
 * whole.
 */
async function boundedBinary(response: Response, limit: number): Promise<Uint8Array> {
  if (!response.body) {
    const payload = new Uint8Array(await response.arrayBuffer());
    if (payload.byteLength > limit) throw new Error(t('results.structure.tooLarge'));
    return payload;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      if (received > limit) throw new Error(t('results.structure.tooLarge'));
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  const payload = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) { payload.set(chunk, offset); offset += chunk.byteLength; }
  return payload;
}

/**
 * Read a coordinate body as the text a multi-model PDB coordinate source is.
 * The XTC/DCD path stays binary; only a text coordinate format is decoded, with
 * the same bounded measure a structure string gets.
 */
async function readCoordinates(path: string, response: Response): Promise<Uint8Array | string> {
  if (/\.pdb(?:\.gz)?$/i.test(path)) return readSource(path, response);
  return boundedBinary(response, MAX_STRUCTURE_BYTES);
}

/** A byte stream whose gzip payload is inflated as it is read. */
function inflate(bytes: ReadableStream<Uint8Array<ArrayBuffer>>): ReadableStream<Uint8Array> {
  if (typeof DecompressionStream === 'undefined') throw new Error(t('results.structure.compressedUnsupported'));
  return bytes.pipeThrough(new DecompressionStream('gzip'));
}

/**
 * The UTF-8 byte length of `text` -- what the parser receives, and what
 * `new TextEncoder().encode(text).byteLength` returns -- without materializing
 * the encoded bytes.
 *
 * A character outside ASCII encodes to two, three, or four bytes instead of one,
 * and `TextDecoder` replaces every undecodable byte with a three-byte U+FFFD. The
 * text a body decodes to is therefore never smaller than the body and can be
 * three times larger: 64 MiB of `0xff` decodes to one replacement character per
 * byte, 192 MiB of UTF-8. Counting the incoming bytes alone does not bound what
 * is parsed.
 *
 * `NON_ASCII` is a whole-string scan, so an ordinary ASCII structure costs one
 * pass over its text and only text that needs measuring is measured per character.
 */
function encodedLength(text: string): number {
  if (!NON_ASCII.test(text)) return text.length;
  let bytes = 0;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    // A well-formed pair is two surrogate code units and one four-byte
    // character; a lone surrogate, or a pair's high half with no low half, is one
    // three-byte U+FFFD.
    else if (code >= 0xd800 && code <= 0xdbff && index + 1 < text.length
      && text.charCodeAt(index + 1) >= 0xdc00 && text.charCodeAt(index + 1) <= 0xdfff) {
      bytes += 4;
      index += 1;
    } else bytes += 3;
  }
  return bytes;
}

/**
 * Read a byte stream into text, refusing anything past `limit`.
 *
 * The manifest's declared `size` bounds the bytes a Runner *published*, which for
 * a compressed structure is the gzip envelope, not the payload the parser reads:
 * a small high-ratio `.cif.gz` inflates to something arbitrarily larger. The
 * decompressed bytes are therefore counted as they arrive, before the text is
 * materialized -- checking the compressed size alone would let the preview limit
 * be exceeded by whatever the compression ratio allows.
 *
 * The decompressed byte count is not by itself a bound on the parse, because the
 * text a stream of invalid bytes decodes to is up to three times larger. The text
 * is therefore measured against the same `limit` as it is built -- every chunk, and
 * the flush that ends the stream, which can emit a pending multi-byte sequence no
 * chunk produced -- so the streamed path and `boundedWhole` bound what the parser
 * receives by one identical rule rather than two drifting ones.
 *
 * The accepted-input envelope is unchanged for a structure that is really a
 * structure: valid text encodes to no more bytes than it occupies, so anything
 * whose decoded size is under `limit` -- every payload that was accepted before
 * -- is accepted now. What the text check additionally refuses is input whose
 * decode expands past the limit, which is not a structure at all.
 */
export async function boundedText(stream: ReadableStream<Uint8Array>, limit: number): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let text = '';
  let received = 0;
  let encoded = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      const chunk = decoder.decode(value, { stream: true });
      encoded += encodedLength(chunk);
      if (received > limit || encoded > limit) throw new Error(t('results.structure.tooLarge'));
      text += chunk;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  const tail = decoder.decode();
  if (encoded + encodedLength(tail) > limit) throw new Error(t('results.structure.tooLarge'));
  return text + tail;
}

export class StructureController {
  private viewer: MolecularViewer | null = null;
  private host: HTMLElement | null = null;
  private generation = 0;
  private geometryGeneration = 0;
  private geometryAbort: AbortController | null = null;
  private controller: AbortController | null = null;
  private representation = 'cartoon_ligand';
  private color = 'rainbow';
  private operation: Promise<void> = Promise.resolve();
  private viewerMount: Promise<MolecularViewer> | null = null;
  private selectionUnsubscribe: (() => void) | null = null;
  private loading = false;
  private pendingFocus: unknown = null;
  private pendingSelection: unknown = null;

  constructor(private readonly createViewer: MolecularViewerFactory, private readonly options: {
    selectionEnabled?: boolean;
    //: The Result workspace names itself the scientific stage owner, so the
    //: viewer's native panels start closed behind their own disclosure button.
    controlsCollapsed?: boolean;
    onSelectionChanged?: (residues: Array<{ chain: string; residue: number; auth_seq_id: number; label_seq_id: number }>) => void;
  } = {}) {}

  async mount(host: HTMLElement, artifact: ResultFile, theme: 'light' | 'dark'): Promise<void> {
    if (artifact.size > MAX_STRUCTURE_BYTES) throw new Error(t('results.structure.tooLarge'));
    const generation = ++this.generation;
    const controller = new AbortController();
    this.loading = true; this.pendingFocus = null; this.pendingSelection = null;
    const masksExistingViewer = this.host === host && Boolean(this.viewer || this.viewerMount);
    if (masksExistingViewer && host.dataset) host.dataset.loading = 'true';
    try {
      this.controller?.abort();
      this.controller = controller;
      if (this.host !== host) {
        this.disposeViewer();
        this.host = host;
      }
      if (!this.viewer) {
        const created = await this.viewerFor(host, generation, theme);
        if (!created) return;
      }
      const response = await fetch(artifact.url, { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error(t('results.structure.downloadFailed', { status: response.status }));
      const name = resultFileName(artifact);
      const data = await readSource(name, response);
      if (generation !== this.generation) return;
      const viewer = this.viewer!;
      const apply = async (): Promise<void> => {
        if (generation !== this.generation || viewer !== this.viewer) return;
        await viewer.setRepresentation(this.representation);
        await viewer.setColor(this.color === 'confidence' ? 'plddt' : this.color);
        await viewer.loadStructure({ data, format: structureFormat(name), label: name });
        if (generation !== this.generation || viewer !== this.viewer) {
          if (viewer === this.viewer) await viewer.clear?.();
          return;
        }
        if (this.pendingSelection != null) viewer.select?.(this.pendingSelection);
        if (this.pendingFocus != null) viewer.focus?.(this.pendingFocus);
        this.pendingSelection = null; this.pendingFocus = null;
        viewer.resize();
      };
      const completed = this.operation.then(apply, apply);
      this.operation = completed.then(() => undefined, () => undefined);
      await completed;
    } finally {
      if (this.controller === controller) this.controller = null;
      if (generation === this.generation && this.host === host) {
        await this.operation;
        this.loading = false;
        if (masksExistingViewer && host.dataset) delete host.dataset.loading;
      }
    }
  }

  /**
   * Mount one topology plus binary coordinate frames in a single Mol* stage.
   *
   * The topology is read as bounded text and the coordinates as bounded bytes;
   * both are fetched under one abort signal, so leaving the view cancels the
   * download rather than letting it finish into a detached viewer. One stage is
   * mounted and every later frame change is a state update, never a remount.
   */
  async mountTrajectory(
    host: HTMLElement,
    topology: ResultFile,
    coordinates: ResultFile,
    format: string,
    theme: 'light' | 'dark',
  ): Promise<TrajectoryInfo> {
    if (topology.size > MAX_STRUCTURE_BYTES || coordinates.size > MAX_STRUCTURE_BYTES) {
      throw new Error(t('results.structure.tooLarge'));
    }
    const generation = ++this.generation;
    const controller = new AbortController();
    this.controller?.abort(); this.controller = controller;
    this.loading = true; this.pendingFocus = null; this.pendingSelection = null;
    try {
      if (this.host !== host) { this.disposeViewer(); this.host = host; }
      const viewer = await this.viewerFor(host, generation, theme);
      if (!viewer) throw aborted();
      if (!viewer.loadTrajectory) throw new Error(t('results.trajectory.unavailable'));
      const [topologyResponse, coordinatesResponse] = await Promise.all([
        fetch(topology.url, { credentials: 'same-origin', signal: controller.signal }),
        fetch(coordinates.url, { credentials: 'same-origin', signal: controller.signal }),
      ]);
      if (!topologyResponse.ok) throw new Error(t('results.trajectory.topologyFailed', { status: topologyResponse.status }));
      if (!coordinatesResponse.ok) {
        throw new Error(t('results.trajectory.coordinatesFailed', { status: coordinatesResponse.status }));
      }
      const topologyName = resultFileName(topology);
      const coordinateName = resultFileName(coordinates);
      const [topologyText, frames] = await Promise.all([
        readSource(topologyName, topologyResponse),
        readCoordinates(coordinateName, coordinatesResponse),
      ]);
      if (generation !== this.generation) throw aborted();
      const apply = async (): Promise<TrajectoryInfo> => {
        if (generation !== this.generation || viewer !== this.viewer) throw aborted();
        await viewer.setRepresentation(this.representation);
        await viewer.setColor(this.color === 'confidence' ? 'plddt' : this.color);
        const info = await viewer.loadTrajectory!({
          topology: topologyText, coordinates: frames, coordinateFormat: format.toLowerCase(), label: coordinateName,
        });
        if (generation !== this.generation || viewer !== this.viewer) throw aborted();
        if (!info || !(info.frameCount > 0)) throw new Error(t('results.trajectory.empty'));
        viewer.resize();
        return info;
      };
      const completed = this.operation.then(apply, apply);
      this.operation = completed.then(() => undefined, () => undefined);
      return await completed;
    } finally {
      if (this.controller === controller) this.controller = null;
      if (generation === this.generation && this.host === host) { await this.operation; this.loading = false; }
    }
  }

  /** Advance or set the current frame of the mounted trajectory. */
  async setTrajectoryFrame(action: 'set' | 'advance', value: number): Promise<TrajectoryInfo> {
    const viewer = this.viewer;
    if (!viewer?.setTrajectoryFrame) throw new Error(t('results.trajectory.unavailable'));
    return viewer.setTrajectoryFrame(action, value);
  }

  /** Empty the stage, superseding any in-flight trajectory load. */
  async clear(): Promise<void> {
    this.generation += 1;
    this.controller?.abort(); this.controller = null;
    this.loading = false;
    const viewer = this.viewer;
    if (!viewer) return;
    const completed = this.operation.then(() => viewer.clear?.(), () => viewer.clear?.());
    this.operation = completed.then(() => undefined, () => undefined);
    await completed;
  }

  private async viewerFor(host: HTMLElement, generation: number, theme: 'light' | 'dark'): Promise<MolecularViewer | null> {
    if (!this.viewer && !this.viewerMount) {
      this.viewerMount = this.createViewer(host, {
        theme, selectionEnabled: this.options.selectionEnabled, controlsCollapsed: this.options.controlsCollapsed,
      });
    }
    if (this.viewer) return this.viewer;
    const pending = this.viewerMount;
    if (!pending) return null;
    let created: MolecularViewer;
    try { created = await pending; } finally { if (this.viewerMount === pending) this.viewerMount = null; }
    // A stale generation on the same host is superseded by a newer mount awaiting
    // this same viewer, so only a viewer created for a host we no longer use is disposed.
    if (this.host !== host) { created.dispose(); return null; }
    if (generation !== this.generation) return null;
    this.viewer = created;
    if (this.options.onSelectionChanged) this.selectionUnsubscribe = created.onSelectionChanged?.(this.options.onSelectionChanged) || null;
    return created;
  }

  setRepresentation(mode: string): Promise<void> {
    this.representation = mode;
    return this.viewer?.setRepresentation(mode) || Promise.resolve();
  }

  setColor(mode: string): Promise<void> {
    this.color = mode;
    return this.viewer?.setColor(mode === 'confidence' ? 'plddt' : mode) || Promise.resolve();
  }

  setTheme(theme: 'light' | 'dark'): void { this.viewer?.setTheme(theme); }
  resize(): void { this.viewer?.resize(); }
  async setGeometry(artifact: ResultFile | null): Promise<void> {
    const generation = ++this.geometryGeneration; this.geometryAbort?.abort(); this.geometryAbort = null;
    if (!artifact) { await this.viewer?.setSphereGeometry?.(null); return; }
    if (artifact.size > 4 * 1024 * 1024) throw new Error('Alpha-sphere evidence exceeds the preview limit.');
    const controller = new AbortController(); this.geometryAbort = controller;
    const response = await fetch(artifact.url, { credentials: 'same-origin', signal: controller.signal });
    if (!response.ok) throw new Error('Alpha-sphere evidence could not be opened.');
    const source = await response.text();
    if (source.length > 4 * 1024 * 1024) throw new Error('Alpha-sphere evidence exceeds the preview limit.');
    if (generation !== this.geometryGeneration) return;
    if (!this.viewer?.setSphereGeometry) throw new Error('Recorded sphere display is unavailable.');
    await this.viewer.setSphereGeometry(source);
  }

  annotate(annotation: { point: { x: number; y: number; z: number }; label: string } | null): void { this.viewer?.annotate?.(annotation); }
  resetCamera(): void { this.viewer?.resetCamera?.(); }
  select(selection: unknown): boolean { if (this.loading) { this.pendingSelection = selection; return true; } return this.viewer?.select?.(selection) || false; }
  focus(selection: unknown): boolean { if (this.loading) { this.pendingFocus = selection; return true; } return this.viewer?.focus?.(selection) || false; }
  captureImage(): Promise<string> {
    if (!this.viewer) return Promise.reject(new Error(t('results.structure.notReady')));
    return this.viewer.captureImage();
  }

  /**
   * Dispose the shared viewer only when it is the stage inside `host`.
   *
   * A view renderer owns the stage it mounted, not the workspace's one molecular
   * stage: when another owner has since mounted there, closing is not this
   * view's to do, and doing it anyway would blank a stage it never opened.
   */
  disposeIfIn(host: HTMLElement): void {
    const current = this.host;
    if (current && (current === host || host.contains(current) || current.contains(host))) this.dispose();
  }

  dispose(): void {
    this.generation += 1; this.geometryGeneration += 1; this.geometryAbort?.abort(); this.geometryAbort = null;
    this.controller?.abort();
    this.controller = null;
    this.loading = false; this.pendingFocus = null; this.pendingSelection = null;
    this.disposeViewer();
  }

  private disposeViewer(): void {
    this.selectionUnsubscribe?.();
    this.selectionUnsubscribe = null;
    this.viewer?.dispose();
    this.viewer = null;
    const pending = this.viewerMount; this.viewerMount = null;
    if (pending) void pending.then((viewer) => viewer.dispose(), () => undefined);
    this.host = null;
  }
}
