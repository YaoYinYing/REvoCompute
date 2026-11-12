import { gunzipSync, gzipSync } from 'node:zlib';

import { describe, expect, it } from 'vitest';

import { buildSubmissionFormData, encodeSubmissionFormData } from '../src/features/create-task/submission';
import type { TaskFormDefinition } from '../src/features/create-task/types';

const GZIP_CAPABILITY = {
  version: 1 as const,
  supported: ['identity', 'gzip'] as Array<'identity' | 'gzip'>,
  max_expansion_ratio: 200,
};

function form(overrides: Record<string, unknown> = {}): TaskFormDefinition {
  return {
    name: 'method',
    inputs: [
      { id: 'structure', formats: ['pdb'], extensions: ['.pdb'] },
      { id: 'trajectory', formats: ['xtc'], extensions: ['.xtc'] },
    ],
    file_encodings: GZIP_CAPABILITY,
    ...overrides,
  } as unknown as TaskFormDefinition;
}

function submission(files: File[], roles: string[]): FormData {
  const data = new FormData();
  files.forEach((file, index) => {
    data.append('files', file);
    data.append('input_paths', file.name);
    data.append('input_roles', roles[index]!);
  });
  data.append('task_type', 'method');
  data.append('execution_mode', 'full');
  return data;
}

/** Text-like PDB records that compress normally, well inside the 200:1 bound. */
function textPdb(bytes: number): File {
  const lines: string[] = [];
  let size = 0;
  for (let index = 0; size < bytes; index += 1) {
    const line = `ATOM  ${String(index % 99999).padStart(5)}  CA  ALA A${String(index % 9999).padStart(4)}    `
      + `${((index * 1.7) % 100).toFixed(3).padStart(8)}${((index * 2.3) % 100).toFixed(3).padStart(8)}`
      + `${((index * 3.1) % 100).toFixed(3).padStart(8)}  1.00 20.00           C\n`;
    lines.push(line);
    size += line.length;
  }
  return new File([lines.join('')], 'model.pdb', { type: 'chemical/x-pdb' });
}

function repetitiveFasta(): File {
  return new File([`>sample\n${'ACDEFGHIKLMNPQRSTVWY'.repeat(4000)}\n`], 'sample.fasta', { type: 'text/plain' });
}

function fastaForm(overrides: Record<string, unknown> = {}): TaskFormDefinition {
  return form({
    inputs: [{ id: 'sequence', formats: ['fasta'], extensions: ['.fasta'] }],
    ...overrides,
  });
}

describe('per-file-part submission encoding', () => {
  it('gzips only the eligible text-like part and preserves every other field', async () => {
    const pdb = textPdb(64 * 1024);
    const trajectory = new File([new Uint8Array(8192).map((_, index) => index % 251)], 'run.xtc');
    const data = submission([pdb, trajectory], ['structure', 'trajectory']);

    const encoded = await encodeSubmissionFormData(data, form());

    expect(encoded.compressedFiles).toBe(1);
    expect(encoded.originalBytes).toBe(pdb.size + trajectory.size);
    expect(encoded.encodedBytes).toBeLessThan(encoded.originalBytes);
    expect(encoded.data.getAll('file_encodings')).toEqual(['gzip', 'identity']);
    const files = encoded.data.getAll('files') as File[];
    expect(files[0]!.name).toBe('model.pdb');
    expect(files[1]).toBe(trajectory);
    const decompressed = gunzipSync(Buffer.from(await files[0]!.arrayBuffer()));
    expect(decompressed.equals(Buffer.from(await pdb.arrayBuffer()))).toBe(true);
    expect(encoded.data.get('task_type')).toBe('method');
    expect(encoded.data.getAll('input_paths')).toEqual(['model.pdb', 'run.xtc']);
    expect(encoded.data.getAll('input_roles')).toEqual(['structure', 'trajectory']);
  });

  it('keeps identity for a compressible part above the Server expansion ratio', async () => {
    const fasta = repetitiveFasta();
    const compressedSize = gzipSync(Buffer.from(await fasta.arrayBuffer())).length;
    // The fixture is legitimate but the Server necessarily refuses this ratio.
    expect(fasta.size / compressedSize).toBeGreaterThan(GZIP_CAPABILITY.max_expansion_ratio);
    const data = submission([fasta], ['sequence']);

    const encoded = await encodeSubmissionFormData(data, fastaForm());

    expect(encoded.compressedFiles).toBe(0);
    expect(encoded.data.get('file_encodings')).toBeNull();
    expect(encoded.data.getAll('files')[0]).toBe(fasta);
  });

  it('applies gzip at the advertised ratio and keeps identity just above it', async () => {
    const pdb = textPdb(64 * 1024);
    const compressedSize = gzipSync(Buffer.from(await pdb.arrayBuffer())).length;
    const ratio = pdb.size / compressedSize;
    const acceptedRatio = Math.ceil(ratio);
    const refusedRatio = ratio === Math.floor(ratio) ? ratio - 1 : Math.floor(ratio);

    const accepted = await encodeSubmissionFormData(
      submission([pdb], ['structure']),
      form({ file_encodings: { ...GZIP_CAPABILITY, max_expansion_ratio: acceptedRatio } }),
    );
    expect(accepted.compressedFiles).toBe(1);
    expect(accepted.data.getAll('file_encodings')).toEqual(['gzip']);

    const refused = await encodeSubmissionFormData(
      submission([pdb], ['structure']),
      form({ file_encodings: { ...GZIP_CAPABILITY, max_expansion_ratio: refusedRatio } }),
    );
    expect(refused.compressedFiles).toBe(0);
    expect(refused.data.get('file_encodings')).toBeNull();
  });

  it('does not guess a ratio when the Server omits it', async () => {
    const pdb = textPdb(64 * 1024);
    const capability = { version: 1 as const, supported: ['identity', 'gzip'] as Array<'identity' | 'gzip'> };

    const encoded = await encodeSubmissionFormData(
      submission([pdb], ['structure']),
      form({ file_encodings: capability }),
    );

    expect(encoded.compressedFiles).toBe(0);
    expect(encoded.data.get('file_encodings')).toBeNull();
  });

  it('keeps identity for every part when the Server does not advertise gzip', async () => {
    const pdb = textPdb(64 * 1024);
    const data = submission([pdb], ['structure']);

    const encoded = await encodeSubmissionFormData(data, form({ file_encodings: undefined }));

    expect(encoded.compressedFiles).toBe(0);
    expect(encoded.data.get('file_encodings')).toBeNull();
    expect(encoded.data.getAll('files')[0]).toBe(pdb);
  });

  it('falls back to identity when compression does not pay for itself', async () => {
    const bytes = new Uint8Array(16 * 1024);
    let state = 123456789;
    for (let index = 0; index < bytes.length; index += 1) {
      state = (state * 1664525 + 1013904223) >>> 0;
      bytes[index] = state >>> 24;
    }
    const noise = new File([bytes], 'noisy.pdb');
    const data = submission([noise], ['structure']);

    const encoded = await encodeSubmissionFormData(data, form());

    expect(encoded.compressedFiles).toBe(0);
    expect(encoded.data.get('file_encodings')).toBeNull();
    expect(encoded.data.getAll('files')[0]).toBe(noise);
  });

  it('leaves a small eligible file alone because framing costs more than it saves', async () => {
    const tiny = textPdb(128);
    const data = submission([tiny], ['structure']);

    const encoded = await encodeSubmissionFormData(data, form());

    expect(encoded.compressedFiles).toBe(0);
    expect(encoded.data.getAll('files')[0]).toBe(tiny);
  });

  it('cancels an in-flight encode through the supplied AbortSignal', async () => {
    const controller = new AbortController();
    controller.abort();
    const data = submission([textPdb(64 * 1024)], ['structure']);

    await expect(
      encodeSubmissionFormData(data, form(), { signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('builds identity forms unchanged for clients without the capability', () => {
    const pdb = textPdb(1024);
    const data = buildSubmissionFormData(
      form({ file_encodings: undefined }),
      {
        inputFiles: () => [{ role: 'structure', file: pdb }],
        sequence: () => '',
        sequenceName: () => '',
        sequenceRole: () => null,
        parameters: () => ({}),
        executionMode: () => 'full',
      },
      {},
    );

    expect(data.getAll('files')).toEqual([pdb]);
    expect(data.get('file_encodings')).toBeNull();
  });
});
