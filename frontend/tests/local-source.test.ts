import { afterEach, describe, expect, it, vi } from 'vitest';

import { applyLocale, translate } from '../src/app/i18n';
import { resolveRoute, routePath } from '../src/app/router';
import { openLocalResult } from '../src/features/results/local-source';
import { ResultWorkspace } from '../src/features/results/ResultWorkspace';
import { readLocalTablePage } from '../src/features/results/table-page';
import { installHarness } from './dom-harness';

/*
 * The Local Result Workspace: an extracted archive read as a result.
 *
 * The fixtures here follow a real REvoCompute export: `manifest.json` at the folder root plus
 * one member per declared artifact, with the served fields (status, archive, entrypoint URL)
 * absent because an archive never contains them. A few fixtures deliberately go beyond what an
 * export writes — a logical file with no artifact twin, a folder-authored citation — because a
 * folder is ordinary bytes a reader may have edited, and the workspace is what refuses that.
 * See `docs/developer-guide/local-result-workspace.md` and the six authentic exports it records.
 */

const TASK = '0123456789abcdef0123456789abcdef';
const sha = async (text: string): Promise<string> => {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
};

interface Member { path: string; text: string; role?: string; preview?: string | null; capability?: string; logicalType?: string }

/** One authentic-shaped archive: the manifest its own export writes, and its members. */
async function archive(members: Member[], extra: Record<string, unknown> = {}): Promise<File[]> {
  const artifacts = [];
  for (const member of members) {
    artifacts.push({
      path: member.path,
      size: new TextEncoder().encode(member.text).length,
      sha256: await sha(member.text),
      role: member.role || 'primary',
      media_type: 'text/plain',
      preview: member.preview === undefined ? 'text' : member.preview,
      capability: member.capability || 'text',
    });
  }
  const manifest = {
    schema_version: 3,
    task_id: TASK,
    task_type: 'demo',
    created_at: '2026-10-22T00:00:00Z',
    total_size: artifacts.reduce((sum, artifact) => sum + artifact.size, 0),
    limitations: [],
    outcome: null,
    output_check: { state: 'passed', checks: [], problems: [] },
    run: { method: { name: 'Demo method' }, inputs: [], parameters: [], citations: [] },
    artifacts,
    views: [],
    result: { files: {} },
    storyboard: null,
    ...extra,
  };
  const folder = 'demo-result';
  const files = [{ name: 'manifest.json', text: JSON.stringify(manifest, null, 2) },
    ...members.map((member) => ({ name: member.path, text: member.text }))];
  return files.map((file) => new File([file.text], file.name.split('/').pop()!, { type: 'text/plain' })) .map((file, index) => {
    Object.defineProperty(file, 'webkitRelativePath', { value: `${folder}/${files[index]!.name}` });
    return file;
  });
}

afterEach(() => { applyLocale('en', false); vi.unstubAllGlobals(); });

describe('a local result source', () => {
  it('projects an archived manifest into the workspace shape without a served envelope', async () => {
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\n' }]);
    const local = await openLocalResult({ files, label: 'demo-result' });
    try {
      expect(local.taskId).toBe('local');
      expect(local.manifest.task_id).toBe('local');
      expect(local.manifest.status).toBe('finished');
      expect(local.manifest.artifacts).toHaveLength(1);
      expect(local.manifest.artifacts[0]!.url).toMatch(/^blob:/);
      // The archive's own Task identity is not this page's identity.
      expect(local.manifest.task_id).toBe('local');
      expect(local.storyboard).toBeNull();
      expect(local.verification).toEqual({ present: 1, hashed: 1, unchecked: [] });
    } finally { local.close(); }
  });

  it('reports a declared Storyboard by identifier and never loads it', async () => {
    const files = await archive([{ path: 'model.cif', text: 'data_demo\n' }],
      { storyboard: { identifier: 'demo-result', entrypoint: 'index.js', requires: [], optional: [] } });
    const local = await openLocalResult({ files, label: 'demo-result' });
    try {
      expect(local.storyboard).toBe('demo-result');
      // An archived Storyboard declaration carries no entrypoint URL, and the workspace is
      // told none: nothing in the folder is ever imported.
      expect(local.manifest.storyboard).toBeNull();
    } finally { local.close(); }
  });

  it('refuses a folder whose declared file is missing', async () => {
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\n' }, { path: 'extra.txt', text: 'x' }]);
    const withoutExtra = files.filter((file) => !(file as File & { webkitRelativePath: string }).webkitRelativePath.endsWith('extra.txt'));
    await expect(openLocalResult({ files: withoutExtra, label: 'demo-result' }))
      .rejects.toThrow(/missing from this folder: extra\.txt/);
  });

  it('refuses a folder whose bytes no longer match the manifest', async () => {
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\n' }]);
    const tampered = files.map((file) => file.name === 'scores.csv'
      ? Object.assign(new File(['name,score\na,9\n'], file.name), { webkitRelativePath: 'demo-result/scores.csv' })
      : file);
    await expect(openLocalResult({ files: tampered, label: 'demo-result' }))
      .rejects.toThrow(/differ from the manifest/);
  });

  it('refuses a declared path that escapes the folder', async () => {
    const files = await archive([{ path: 'scores.csv', text: 'name,score\n' }]);
    const manifest = JSON.parse(await files[0]!.text());
    manifest.artifacts[0].path = '../scores.csv';
    const escaped = [new File([JSON.stringify(manifest)], 'manifest.json'), ...files.slice(1)];
    await expect(openLocalResult({ files: escaped, label: 'demo-result' }))
      .rejects.toThrow(/unsafe path/);
  });

  it('verifies a logical file whose path the artifact list does not name', async () => {
    // A view reaches a logical file by its own path, so a path only `result.files`
    // declares is still a path a renderer can be handed: it must be checked too.
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\n' }]);
    const manifest = JSON.parse(await files[0]!.text());
    manifest.result.files = { structures: [{ path: 'extra.txt', size: 10, sha256: await sha('unverified'), preview: 'structure', capability: 'molecular_structure', cardinality: 'many', media_type: 'chemical/x-cif', role: 'primary' }] };
    const withManifest = new File([JSON.stringify(manifest)], 'manifest.json');
    Object.defineProperty(withManifest, 'webkitRelativePath', { value: 'demo-result/manifest.json' });
    const member = (text: string): File => {
      const file = new File([text], 'extra.txt');
      Object.defineProperty(file, 'webkitRelativePath', { value: 'demo-result/extra.txt' });
      return file;
    };
    const folder = (extra: File): File[] => [withManifest, files[1]!, extra];
    const local = await openLocalResult({ files: folder(member('unverified')), label: 'demo-result' });
    try {
      // Two declared paths were present and hashed, not only the one artifact.
      expect(local.verification).toEqual({ present: 2, hashed: 2, unchecked: [] });
    } finally { local.close(); }
    // The same folder with that logical file altered is refused by its digest.
    await expect(openLocalResult({ files: folder(member('evil-bytes')), label: 'demo-result' }))
      .rejects.toThrow(/differ from the manifest.*extra\.txt/);
  });

  it('reads a logical file\'s capability from its declared type, as the Server does', async () => {
    // An archive's logical record inherits the artifact's extension-guessed preview, so a table
    // with no extension is `download_only` there. The Server re-derives the capability from the
    // declared `type` when it serves the same manifest; a folder has to derive it the same way
    // or the same result shows less locally than remotely.
    const files = await archive([{ path: 'pssm_msa/query_ascii_mtx_file', text: 'A 1 2\n' }]);
    const manifest = JSON.parse(await files[0]!.text());
    const [artifact] = manifest.artifacts;
    artifact.preview = null;
    artifact.capability = 'download_only';
    manifest.result.files = { pssm: [{ path: artifact.path, size: artifact.size, sha256: artifact.sha256,
      logical_type: 'table', preview: null, capability: 'download_only', cardinality: 'one',
      media_type: 'application/octet-stream', role: 'primary' }] };
    const withManifest = new File([JSON.stringify(manifest)], 'manifest.json');
    Object.defineProperty(withManifest, 'webkitRelativePath', { value: 'demo-result/manifest.json' });
    const local = await openLocalResult({ files: [withManifest, files[1]!], label: 'demo-result' });
    try {
      expect(local.manifest.result.files.pssm?.[0]?.capability).toBe('table');
    } finally { local.close(); }
  });

  it('states a run whose output was never assessed as failed, not finished', async () => {
    // The Server writes `not_assessed` exactly when the run itself failed, so a folder that
    // carries it must not present the run as a finished result.
    const files = await archive([{ path: 'scores.csv', text: 'name,score\n' }],
      { output_check: { state: 'not_assessed', checks: [], problems: [] } });
    const local = await openLocalResult({ files, label: 'demo-result' });
    try {
      expect(local.manifest.status).toBe('failed');
    } finally { local.close(); }
  });

  it('reads a local table page through the same bounded loader the route uses', async () => {
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\nb,2\n' }]);
    const local = await openLocalResult({ files, label: 'demo-result' });
    try {
      const page = await readLocalTablePage(local, local.manifest.artifacts[0]!, { offset: 1, limit: 1 });
      expect(page.rows).toEqual([['b', '2']]);
      expect(page.has_more).toBe(false);
    } finally { local.close(); }
  });

  it('releases every object URL it created', async () => {
    const revoked: string[] = [];
    vi.stubGlobal('URL', { ...URL, createObjectURL: (file: File) => `blob:${file.name}`, revokeObjectURL: (url: string) => revoked.push(url) });
    const files = await archive([{ path: 'scores.csv', text: 'name,score\n' }]);
    const local = await openLocalResult({ files, label: 'demo-result' });
    expect(revoked).toHaveLength(0);
    local.close();
    expect(revoked).toEqual(['blob:scores.csv']);
    expect(local.file('scores.csv')).not.toBeNull();
  });
});

describe('the Local Result Workspace page', () => {
  const noFetch = (): void => {
    installHarness(vi.stubGlobal, { pathname: '/compute/local_results' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('the local workspace requested the server'); }));
  };

  it('serves its own route and is a protected page', () => {
    expect(resolveRoute('/compute/local_results')).toEqual({ id: 'local-results' });
    expect(routePath({ id: 'local-results' })).toBe('/compute/local_results');
  });

  it('renders a local result without one server request', async () => {
    noFetch();
    const files = await archive([{ path: 'scores.csv', text: 'name,score\na,1\n' }]);
    const local = await openLocalResult({ files, label: 'demo-result' });
    const root = document.createElement('div');
    let fetches = 0;
    vi.stubGlobal('fetch', vi.fn(async () => { fetches += 1; throw new Error('unexpected request'); }));
    const workspace = new ResultWorkspace(root, async () => { throw new Error('no viewer'); }, local);
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';
    try {
      await workspace.load();
      expect(fetches).toBe(0);
      expect(root.querySelector('.result-source-badge')?.textContent).toBe('Local');
      expect(root.textContent).toContain('1 file matches the size and SHA-256 hash');
      // The archive's Task identity is the archive's provenance, never this page's own:
      // the identity line names the folder, and the run record names the exported Task.
      expect(root.querySelector('.result-meta')?.textContent).toBe('Demo method · demo-result');
      expect(root.textContent).toContain('Exported from task');
      expect(root.querySelector('.result-record')?.textContent).toContain(TASK);
      // A local result has no Server archive to prepare: the shell's archive action
      // stays present but hidden, exactly as it does in the browser.
      expect((root.querySelector('.result-archive-action') as unknown as { hidden: boolean }).hidden).toBe(true);
      // A blob handle carries no filename, so the row states the folder's own name for the file.
      expect(root.querySelector('.result-file-download')?.getAttribute('download')).toBe('scores.csv');
    } finally { local.close(); workspace.destroy(); }
  });

  it('never turns a folder-authored citation into an executable link', async () => {
    noFetch();
    const files = await archive([{ path: 'scores.csv', text: 'name,score\n' }], {
      run: { method: { name: 'Demo method' }, inputs: [], parameters: [], citations: [
        { num: 1, doi: '10.1000/x', title: 'Paper', url: 'javascript:alert(document.cookie)' },
        { num: 2, doi: '10.1000/y', title: 'Real paper', url: 'https://doi.org/10.1000/y' },
      ] },
    });
    const local = await openLocalResult({ files, label: 'demo-result' });
    const root = document.createElement('div');
    const workspace = new ResultWorkspace(root, async () => { throw new Error('no viewer'); }, local);
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';
    try {
      await workspace.load();
      // Only an absolute `https:` locator (or a DOI) becomes an anchor; the folder's other
      // address is stated as plain text, so it cannot be clicked into execution here.
      // The folder's `javascript:` address is never emitted; the citation falls back to its
      // DOI, which is the same https locator the Server would have derived.
      const anchors = [...root.querySelectorAll('.result-citations a')] as unknown as Array<{ getAttribute(name: string): string | null }>;
      expect(anchors.map((anchor) => anchor.getAttribute('href'))).toEqual([
        'https://doi.org/10.1000%2Fx', 'https://doi.org/10.1000/y',
      ]);
      expect(root.querySelector('.result-citations')?.textContent).toContain('Paper');
    } finally { local.close(); workspace.destroy(); }
  });

  it('states a declared Storyboard as unavailable, by identifier', async () => {
    noFetch();
    const files = await archive([{ path: 'scores.csv', text: 'name,score\n' }],
      { storyboard: { identifier: 'demo-archive-storyboard', entrypoint: 'index.js', requires: [], optional: [] } });
    const local = await openLocalResult({ files, label: 'demo-result' });
    const root = document.createElement('div');
    const workspace = new ResultWorkspace(root, async () => { throw new Error('no viewer'); }, local);
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';
    try {
      await workspace.load();
      expect(root.textContent).toContain('demo-archive-storyboard');
      expect(root.textContent).toContain('code is not run from a folder');
    } finally { local.close(); workspace.destroy(); }
  });

  it('starts no result request when the page opens', async () => {
    noFetch();
    const fetches = vi.fn(async () => new Response('{}'));
    vi.stubGlobal('fetch', fetches);
    const { mountLocalResultWorkspace } = await import('../src/features/results/local-workspace');
    const root = document.createElement('div');
    const view = mountLocalResultWorkspace(root);
    try {
      expect(root.querySelector('input[webkitdirectory]')).not.toBeNull();
      expect(root.textContent).toContain('never uploaded');
      expect(fetches).not.toHaveBeenCalled();
    } finally { view.destroy(); }
  });
});

describe('the local table refusal a reader sees', () => {
  // A declared entity-table view whose own folder member is an unterminated quote:
  // the folder opens (the bytes match its manifest), and the table reader refuses
  // the page. The workspace states that reason in the note above the fallback.
  const malformedView = {
    id: 'pairs', plugin: 'entity-table', role: 'primary', title: 'Pairs',
    sources: { table: ['pairs.csv'] }, mapping: { key_columns: ['i'] },
  };

  for (const locale of ['en', 'zh-CN'] as const) {
    it(`states the refusal in ${locale}, through the note the workspace renders`, async () => {
      installHarness(vi.stubGlobal, { pathname: '/compute/local_results' });
      vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('the local workspace requested the server'); }));
      applyLocale(locale);
      const files = await archive([{ path: 'pairs.csv', text: 'i,j\n"open,2\n' }], { views: [malformedView] });
      const local = await openLocalResult({ files, label: 'demo-result' });
      const root = document.createElement('div');
      const workspace = new ResultWorkspace(root, async () => { throw new Error('no viewer'); }, local);
      (root.querySelector('.result-search') as unknown as { value: string }).value = '';
      try {
        await workspace.load();
        await (workspace as unknown as { openView(view: unknown): Promise<void> }).openView(malformedView);
        const reason = translate(locale, 'results.local.table.malformed');
        const note = root.querySelector('.result-preview .result-note');
        expect(note?.textContent).toContain(reason);
        if (locale === 'zh-CN') {
          // The catalog is the only source: a zh-CN reader must not see the English refusal.
          expect(note?.textContent).not.toContain('The local table is malformed.');
        }
      } finally { local.close(); workspace.destroy(); }
    });
  }
});
