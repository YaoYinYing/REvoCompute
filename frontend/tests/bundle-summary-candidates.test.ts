import { afterEach, describe, expect, it, vi } from 'vitest';

import { resultFileName } from '../src/api/result-types';
import { bundleItems, createEvidenceBundleViewRenderer } from '../src/features/results/evidence-bundle-view';
import { createCandidateCollectionViewRenderer, isSequenceCollection, parseFasta } from '../src/features/results/candidate-collection-view';
import { createScalarSummaryViewRenderer, declaredFields, resolveScalarPath, scalarMetrics } from '../src/features/results/scalar-summary-view';
import { installHarness, type HarnessNode } from './dom-harness';

const artifact = (path: string, extra: Record<string, unknown> = {}) => ({
  path, size: 2048, sha256: 'a'.repeat(64), url: '/artifacts/' + path,
  media_type: 'application/octet-stream', preview: null, capability: 'unknown' as const, role: 'evidence' as const, ...extra,
});

afterEach(() => vi.unstubAllGlobals());

function serve(text: string, status = 200) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(text, { status })));
}

describe('scalar summary', () => {
  it('reads only declared field paths and keeps a declared unit and direction with the value', () => {
    const metrics = scalarMetrics({ alignment: { width: 12 }, cluster_count: 3, absent: null }, declaredFields({
      id: 'profile_summary', plugin: 'scalar-summary', role: 'evidence', title: 'Profile summary',
      sources: { data: ['summary.json'] },
      mapping: { fields: [
        { path: 'alignment.width', label: 'Alignment width', unit: 'residues', direction: 'neutral' },
        { path: 'cluster_count', label: 'Clusters', unit: 'clusters', direction: 'lower' },
        { path: 'absent', label: 'Nothing here', unit: 'none', direction: 'neutral', nullable: true },
      ] },
    } as never));
    expect(metrics[0]).toMatchObject({ label: 'Alignment width', value: 12, unit: 'residues', meaning: '' });
    expect(metrics[1]).toMatchObject({ value: 3, meaning: 'Lower is better' });
    expect(metrics[2]).toMatchObject({ label: 'Nothing here', value: null, nullable: true });
    expect(resolveScalarPath({ alignment: { width: 12 } }, 'alignment.width')).toBe(12);
  });

  it('renders the declared fields through the shared scalar grid', async () => {
    installHarness(vi.stubGlobal);
    serve(JSON.stringify({ msa_rows: 1, mean_entropy: 2.4999139308929443, mean_log_prob: -2.2544448375701904 }));
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'profile_summary', plugin: 'scalar-summary', role: 'evidence', title: 'Profile summary',
      sources: { data: ['msa1b_summary.json'] }, mapping: { fields: [
        { path: 'msa_rows', label: 'MSA rows', unit: 'sequences', direction: 'neutral' },
        { path: 'mean_entropy', label: 'Mean entropy', unit: 'nats', direction: 'lower' },
        { path: 'mean_log_prob', label: 'Mean log probability', unit: 'nats', direction: 'higher' },
      ] } };
    await createScalarSummaryViewRenderer().render(view as never,
      { data: [artifact('msa1b_summary.json', { url: '/artifacts/summary' })] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.querySelectorAll('dt').map((node) => node.textContent))
      .toEqual(['MSA rows', 'Mean entropy', 'Mean log probability']);
    expect(host.textContent).toContain('1 sequences');
    expect(host.textContent).toContain('nats');
    expect(host.textContent).toContain('Higher is better');
  });
});

describe('evidence bundle', () => {
  it('lists every declared item with its source and capability', () => {
    const items = bundleItems({
      items: [artifact('a.png', { preview: 'image' }), artifact('b.pt', { preview: null })],
      evidence: [artifact('c.csv', { preview: 'table' })],
    });
    expect(items.map((item) => [item.source, resultFileName(item.file), item.capability])).toEqual([
      ['items', 'a.png', 'image'], ['items', 'b.pt', 'download_only'], ['evidence', 'c.csv', 'table'],
    ]);
  });

  it('renders an image inline and an opaque artifact as a download only', async () => {
    installHarness(vi.stubGlobal);
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'embedding_artifacts', plugin: 'evidence-bundle', role: 'evidence', title: 'Embedding artifacts',
      sources: { items: ['residue_embeddings.npy'] }, mapping: {} };
    await createEvidenceBundleViewRenderer().render(view as never, {
      items: [
        artifact('contact_probabilities.png', { preview: 'image', media_type: 'image/png' }),
        artifact('residue_embeddings.npy', { preview: 'download_only' }),
      ],
    } as never, host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.querySelectorAll('li.evidence-bundle-item')).toHaveLength(2);
    expect(host.querySelectorAll('img')).toHaveLength(1);
    expect(host.querySelectorAll('a[download]')).toHaveLength(2);
    expect(host.textContent).toContain('download_only');
  });

  it('states an empty bundle rather than showing a blank stage', async () => {
    installHarness(vi.stubGlobal);
    const host = document.createElement('section') as unknown as HarnessNode;
    await createEvidenceBundleViewRenderer().render(
      { id: 'items', plugin: 'evidence-bundle', role: 'primary', title: 'Items', sources: {}, mapping: {} } as never,
      {} as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.textContent).toContain('No evidence artifact was published');
  });
});

describe('candidate collection', () => {
  it('parses FASTA records with their own headers and residues', () => {
    expect(parseFasta('>2KL8, T=0.1\nMKT\nAY\n>2KL8, id=1\nMDL\n')).toEqual([
      { name: '2KL8, T=0.1', sequence: 'MKTAY' },
      { name: '2KL8, id=1', sequence: 'MDL' },
    ]);
    expect(parseFasta('>empty\n\n')).toEqual([]);
  });

  it('recognizes sequence collections and leaves other candidate artifacts alone', () => {
    expect(isSequenceCollection(artifact('seqs/2KL8.fa'))).toBe(true);
    expect(isSequenceCollection(artifact('2KL8_designs.fasta'))).toBe(true);
    expect(isSequenceCollection(artifact('ranked.cif'))).toBe(false);
  });

  it('offers each FASTA record as a candidate with its sequence and source download', async () => {
    installHarness(vi.stubGlobal);
    serve('>2KL8, T=0.1, seed=51959\nMEMDIRFRGDDL\n>2KL8, id=1, overall_confidence=0.3804\nMDLVITFKGEK\n');
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'designed_sequences', plugin: 'candidate-collection', role: 'primary', title: 'Designed sequences',
      sources: { candidates: ['seqs/2KL8.fa'] }, mapping: {} };
    await createCandidateCollectionViewRenderer().render(view as never,
      { candidates: [artifact('seqs/2KL8.fa', { url: '/artifacts/seqs/2KL8.fa' })] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    const buttons = host.querySelectorAll('button.candidate-open');
    expect(buttons.map((button) => button.textContent)).toEqual(['2KL8, T=0.1, seed=51959', '2KL8, id=1, overall_confidence=0.3804']);
    expect(buttons[0]!.getAttribute('aria-current')).toBe('true');
    expect(host.querySelector('pre.candidate-sequence')!.textContent).toBe('MEMDIRFRGDDL');
    expect(host.textContent).toContain('12');
    expect(host.querySelector('a[download]')!.getAttribute('href')).toBe('/artifacts/seqs/2KL8.fa');
  });

  it('keeps a non-sequence candidate as a named download and never invents a sequence', async () => {
    installHarness(vi.stubGlobal);
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'docked_poses', plugin: 'candidate-collection', role: 'primary', title: 'Docked poses',
      sources: { candidates: ['vina_1.pdbqt'] }, mapping: {} };
    await createCandidateCollectionViewRenderer().render(view as never,
      { candidates: [artifact('vina_1.pdbqt')] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.querySelector('pre.candidate-sequence')).toBeNull();
    expect(host.querySelector('a[download]')!.getAttribute('href')).toBe('/artifacts/vina_1.pdbqt');
    expect(host.textContent).toContain('vina_1.pdbqt');
  });

  it('states a structure candidate that cannot be shown and leaves no empty stage', async () => {
    installHarness(vi.stubGlobal);
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'models', plugin: 'candidate-collection', role: 'primary', title: 'Models',
      sources: { candidates: ['predictions/model_0.cif'] }, mapping: {} };
    await createCandidateCollectionViewRenderer().render(view as never,
      { candidates: [artifact('predictions/model_0.cif')] } as never,
      host as unknown as HTMLElement, {
        signal: new AbortController().signal, taskId: 'a'.repeat(32),
        openStructure: async () => { throw new Error('This structure exceeds the safe inline preview limit.'); },
      });
    await vi.waitFor(() => expect(host.textContent).toContain('exceeds the safe inline preview limit'));
    expect(host.querySelector('.candidate-stage')).toBeNull();
    expect(host.querySelector('a[download]')!.getAttribute('href')).toBe('/artifacts/predictions/model_0.cif');
  });

  it('states a failed sequence read instead of a blank list', async () => {
    installHarness(vi.stubGlobal);
    serve('nope', 500);
    const view = { id: 'designed_sequences', plugin: 'candidate-collection', role: 'primary', title: 'Designed',
      sources: { candidates: ['seqs/x.fa'] }, mapping: {} };
    await expect(createCandidateCollectionViewRenderer().render(view as never,
      { candidates: [artifact('seqs/x.fa')] } as never,
      document.createElement('section') as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) })).rejects.toThrow('could not be read');
  });
});
