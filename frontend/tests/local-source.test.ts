import { afterEach, describe, expect, it, vi } from 'vitest';

import { resolveRoute, routePath } from '../src/app/router';
import { openLocalResult } from '../src/features/results/local-source';
import { ResultWorkspace } from '../src/features/results/ResultWorkspace';
import { readLocalTablePage } from '../src/features/results/table-page';
import { installHarness } from './dom-harness';

/*
 * The Local Result Workspace: an extracted archive read as a result.
 *
 * The fixtures here are shaped exactly like a real REvoCompute export: `manifest.json` at the
 * folder root plus one member per declared artifact, with the served fields (status, archive,
 * entrypoint URL) absent because an archive never contained them. See
 * `docs/developer-guide/local-result-workspace.md` and the Gate 0 evidence in `TODO.md`.
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

afterEach(() => vi.unstubAllGlobals());

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
      expect(root.textContent).toContain('1 files match the sizes and SHA-256 hashes');
      // The archive's Task identity is the archive's provenance, never this page's own:
      // the identity line names the folder, and the run record names the exported Task.
      expect(root.querySelector('.result-meta')?.textContent).toBe('Demo method · demo-result');
      expect(root.textContent).toContain('Exported from task');
      expect(root.querySelector('.result-record')?.textContent).toContain(TASK);
      expect(root.querySelector('.result-archive-action')).toBeNull();
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
