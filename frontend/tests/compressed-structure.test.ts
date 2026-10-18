import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { StructureController } from '../src/features/results/molecular/structure-controller';
import { artifactCapability } from '../src/features/results/renderer-registry';
import type { MolecularViewer } from '../src/features/results/molecular/viewer-contract';

const file = (path: string, media_type = 'chemical/x-pdb'): ResultArtifact => ({ path, size: 8, sha256: 'a'.repeat(64), url: `/${path}`, media_type, preview: 'structure', capability: 'molecular_structure', role: 'primary' });
const viewer = (): MolecularViewer => ({ setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {}, captureImage: async () => '', dispose: () => {}, loadStructure: async () => {} });
afterEach(() => vi.unstubAllGlobals());

// RFdiffusion3 writes compressed mmCIF (`<example_id>_model_<n>.cif.gz`). The
// published bytes are gzip, so both the capability decision and the parse
// format have to survive the compression suffix, and the payload has to be
// inflated before it reaches the viewer.
async function gzip(text: string): Promise<ArrayBuffer> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'));
  return new Response(stream).arrayBuffer();
}

const PREVIEW_LIMIT = 64 * 1024 * 1024;

/**
 * A readable stream of `bytes` bytes of `0xff`, delivered in `step`-sized chunks.
 *
 * The byte count is what a counter of incoming bytes measures, and it is
 * deliberately not over the preview limit: the text these bytes decode to is
 * three times larger, and that text is what reaches the parser.
 */
function invalidStream(bytes: number, step = 16 * 1024 * 1024) {
  const state = { sent: 0 };
  let remaining = bytes;
  const chunk = new Uint8Array(step).fill(0xff);
  return {
    state,
    stream: new ReadableStream<Uint8Array<ArrayBuffer>>({
      pull(controller) {
        if (remaining <= 0) { controller.close(); return; }
        const size = Math.min(step, remaining);
        remaining -= size;
        state.sent += size;
        controller.enqueue(chunk.subarray(0, size) as Uint8Array<ArrayBuffer>);
      },
    }),
  };
}

/** The same invalid bytes, gzipped: a small envelope whose declared size is honest. */
async function gzipInvalid(bytes: number): Promise<ArrayBuffer> {
  const unit = new Uint8Array(bytes).fill(0xff);
  const compressed = new Blob([unit]).stream().pipeThrough(new CompressionStream('gzip'));
  return new Response(compressed).arrayBuffer();
}

describe('compressed structure results', () => {
  it('routes a compressed structure to the structure renderer without a media type', () => {
    // No declared capability and no media type: the name alone has to decide, or
    // a design artifact would fall through to download-only.
    const bare = { path: 'design_0_model_0.cif.gz', size: 8, sha256: 'a'.repeat(64), url: '/design', media_type: '' } as ResultArtifact;
    expect(artifactCapability(bare)).toBe('structure');
    // The declared media type actually served for `*.cif.gz` agrees.
    expect(artifactCapability({ ...file('design_0_model_0.cif.gz', 'chemical/x-cif'), capability: 'unknown' })).toBe('structure');
    // A plain structure is unchanged.
    expect(artifactCapability({ ...file('model.cif', 'chemical/x-cif'), capability: 'unknown' })).toBe('structure');
  });

  it('inflates a gzipped mmCIF and parses it as mmCIF', async () => {
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: { format: string; data: string }) => { load(source); } };
    const payload = 'data_test\n_cell.length_a 1\n';
    vi.stubGlobal('fetch', vi.fn(async () => new Response(await gzip(payload))));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);
    await controller.mount({} as HTMLElement, file('design_0_model_0.cif.gz', 'chemical/x-cif'), 'light');

    expect(load).toHaveBeenCalledTimes(1);
    const source = load.mock.calls[0]![0] as { format: string; data: string; label: string };
    expect(source.format).toBe('mmcif');
    expect(source.data).toBe(payload);
    expect(source.label).toBe('design_0_model_0.cif.gz');
  });

  it('leaves an uncompressed structure byte-identical', async () => {
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    vi.stubGlobal('fetch', vi.fn(async () => new Response('ATOM      1  N   ALA A   1')));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);
    await controller.mount({} as HTMLElement, file('model.pdb'), 'light');

    expect((load.mock.calls[0]![0] as { format: string }).format).toBe('pdb');
    expect((load.mock.calls[0]![0] as { data: string }).data).toContain('ATOM');
  });

  it('refuses a compressed structure whose inflated bytes pass the preview limit', async () => {
    // The manifest's `size` is the gzip envelope, so a small high-ratio payload
    // passes the pre-fetch guard and inflates past the limit. The bound has to
    // apply to the decompressed bytes: `loadStructure` must never be reached.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const bomb = `data_test\n${'A'.repeat(64 * 1024 * 1024 + 1)}\n`;
    // Well under the declared compressed size, so only the inflated bound bites.
    const envelope = await gzip(bomb);
    expect(envelope.byteLength).toBeLessThan(64 * 1024 * 1024);
    const artifact = { ...file('design_0_model_0.cif.gz', 'chemical/x-cif'), size: envelope.byteLength };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(envelope)));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, artifact, 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
  });

  it('inflates a gzipped mmCIF the platform hands back whole without a stream', async () => {
    // `Response.body` is nullable, so the streamless branch is reachable; the gzip
    // envelope used to be inflated there and must still be, whether or not the
    // platform exposes a stream to read it through.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: { format: string; data: string }) => { load(source); } };
    const payload = 'data_test\n_cell.length_a 1\n';
    const envelope = await gzip(payload);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: null, text: async () => { throw new Error("response.text is not a function"); }, arrayBuffer: async () => envelope })));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);
    await controller.mount({} as HTMLElement, file('design_0_model_0.cif.gz', 'chemical/x-cif'), 'light');

    const source = load.mock.calls[0]![0] as { format: string; data: string };
    expect(source.format).toBe('mmcif');
    expect(source.data).toBe(payload);
  });

  it('refuses a compressed streamless body whose inflated bytes pass the preview limit', async () => {
    // The streamless path materializes the envelope before it can inflate, so the
    // bound has to reach the inflated bytes -- the compressed size alone is what
    // the high-ratio payload was designed to slip past.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const bomb = `data_test\n${'A'.repeat(64 * 1024 * 1024 + 1)}\n`;
    const envelope = await gzip(bomb);
    expect(envelope.byteLength).toBeLessThan(64 * 1024 * 1024);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: null, text: async () => { throw new Error("response.text is not a function"); }, arrayBuffer: async () => envelope })));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, file('design_0_model_0.cif.gz', 'chemical/x-cif'), 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
  });

  it('refuses a streamless body whose declared size is honest but whose encoded text is not', async () => {
    // A whole-body branch cannot stream, so it materializes the bytes before the
    // bound can be applied -- the reason the compressed test below exists. It is
    // still bounded: a 64 MiB body of invalid bytes decodes to 64 MiB of
    // replacement characters, whose UTF-8 encoding is 192 MiB, so the text the
    // parser would receive is measured rather than assumed.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const payload = new Uint8Array(64 * 1024 * 1024).fill(0xff);
    const artifact = { ...file('model.cif', 'chemical/x-cif'), size: payload.byteLength };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: null, arrayBuffer: async () => payload.buffer })));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, artifact, 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
    // The same body is accepted once the text it decodes to fits, so the rejection
    // is the encoded text and not the byte-level bound alone.
    const fit = new Uint8Array(1024).fill(0xff);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: null, arrayBuffer: async () => fit.buffer })));
    await new StructureController(async () => fake as unknown as MolecularViewer)
      .mount({} as HTMLElement, { ...artifact, size: fit.byteLength }, 'light');
    expect((load.mock.calls[0]![0] as { data: string }).data).toBe('�'.repeat(fit.byteLength));
  });

  it('refuses a streamed body whose byte count fits but whose decoded text does not', async () => {
    // The streamed path can bound the bytes as they arrive, which is not the same
    // as bounding the parse: a readable stream that never exceeds the limit in
    // bytes still decodes to three times as much text, and that text was what
    // reached the parser. Both paths have to measure the same thing.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const { stream, state } = invalidStream(PREVIEW_LIMIT);
    const artifact = { ...file('model.cif', 'chemical/x-cif'), size: PREVIEW_LIMIT };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: stream } as unknown as Response)));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, artifact, 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
    // The bound bites while the stream is being read, so fewer bytes arrived than
    // the body held; that is the bound working, not the body being truncated.
    expect(state.sent).toBeLessThanOrEqual(PREVIEW_LIMIT);
  });

  it('refuses a streamed gzip body whose inflated text passes the preview limit', async () => {
    // A readable stream is not a promise that the payload is small: the declared
    // size is the gzip envelope, so a small `.cif.gz` inflates to a body past the
    // limit -- and invalid bytes there decode to three times as much text again.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const envelope = await gzipInvalid(PREVIEW_LIMIT);
    // The declared size passes the pre-fetch guard; only the inflated text bites.
    expect(envelope.byteLength).toBeLessThan(PREVIEW_LIMIT);
    const artifact = { ...file('design_0_model_0.cif.gz', 'chemical/x-cif'), size: envelope.byteLength };
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, body: new Blob([envelope]).stream(),
    } as unknown as Response)));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, artifact, 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
  });

  it('still inflates a streamed gzip body that is valid text', async () => {
    // The compressed case the fix must not narrow: a real gzipped structure is
    // read through the stream, inflated, and parsed. Its text is smaller than the
    // bytes that decoded to it, so the decoded measure accepts it.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: { format: string; data: string }) => { load(source); } };
    const payload = `data_test\n${'A'.repeat(1024 * 1024)}\n`;
    const envelope = await gzip(payload);
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, body: new Blob([envelope]).stream(),
    } as unknown as Response)));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);
    await controller.mount({} as HTMLElement, { ...file('design_0_model_0.cif.gz', 'chemical/x-cif'), size: envelope.byteLength }, 'light');

    const source = load.mock.calls[0]![0] as { format: string; data: string };
    expect(source.format).toBe('mmcif');
    expect(source.data).toBe(payload);
  });

  it('keeps the accepted text envelope at the limit for both paths', async () => {
    // One rule, measured the same way: content whose text is exactly the limit is
    // accepted, and one byte more is refused -- streamed and whole-body alike.
    // Invalid bytes under the limit that decode past it are what the tests above
    // pin down.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: { data: string }) => { load(source); } };
    const under = `${'.'.repeat(PREVIEW_LIMIT - 1)}\n`;
    expect(new TextEncoder().encode(under).byteLength).toBe(PREVIEW_LIMIT);

    // Streamed: exactly at the limit, accepted.
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, body: new Blob([under]).stream(),
    } as unknown as Response)));
    await new StructureController(async () => fake as unknown as MolecularViewer)
      .mount({} as HTMLElement, file('model.pdb', 'chemical/x-pdb'), 'light');
    expect((load.mock.calls[0]![0] as { data: string }).data).toBe(under);

    // Whole body: one byte past the limit, refused.
    const oversized = new TextEncoder().encode(`${under}.`);
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, body: null, arrayBuffer: async () => oversized.buffer,
    } as unknown as Response)));
    await expect(new StructureController(async () => fake as unknown as MolecularViewer)
      .mount({} as HTMLElement, { ...file('model.pdb', 'chemical/x-pdb'), size: oversized.byteLength }, 'light'))
      .rejects.toThrow('This structure exceeds the safe inline preview limit.');
  });
});
