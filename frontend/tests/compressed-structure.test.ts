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

  it('refuses a structure whose bytes are handed back whole without a stream', async () => {
    // `Response.body` is nullable, so the controller cannot assume a stream to
    // bound while it reads; the bytes it hands back are measured once instead of
    // trusting the declared size.
    const load = vi.fn();
    const fake = { ...viewer(), loadStructure: async (source: unknown) => { load(source); } };
    const body = 'data_test\n' + 'A'.repeat(64 * 1024 * 1024 + 1) + '\n';
    const artifact = { ...file('model.cif', 'chemical/x-cif'), size: 8 };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: null, text: async () => body })));
    const controller = new StructureController(async () => fake as unknown as MolecularViewer);

    await expect(controller.mount({} as HTMLElement, artifact, 'light')).rejects.toThrow(
      'This structure exceeds the safe inline preview limit.',
    );
    expect(load).not.toHaveBeenCalled();
  });
});
