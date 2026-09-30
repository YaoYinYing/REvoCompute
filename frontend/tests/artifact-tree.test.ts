import { describe, expect, it } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { buildArtifactTree, filterArtifacts } from '../src/features/results/artifact-tree';

const artifact = (path: string, size: number, role: ResultArtifact['role'] = 'artifact'): ResultArtifact => ({
  path,
  size,
  sha256: 'a'.repeat(64),
  url: `/compute/api/results/0123456789abcdef0123456789abcdef/artifacts/${path}`,
  media_type: 'text/plain',
  preview: 'text',
  capability: 'text',
  role,
});

describe('filterArtifacts', () => {
  it('returns every declared artifact when no query is given, including zero-byte ones', () => {
    const declared = [artifact('result.csv', 512, 'primary'), artifact('execution/task_finished', 0, 'diagnostic')];
    expect(filterArtifacts(declared, '')).toEqual(declared);
  });

  it('narrows by path without discarding a zero-byte artifact', () => {
    const declared = [artifact('result.csv', 512, 'primary'), artifact('execution/task_finished', 0, 'diagnostic')];
    expect(filterArtifacts(declared, 'result')).toEqual([declared[0]]);
    expect(filterArtifacts(declared, 'task_finished')).toEqual([declared[1]]);
    expect(filterArtifacts(declared, 'missing')).toEqual([]);
  });
});

describe('buildArtifactTree', () => {
  it('keeps a declared zero-byte artifact in its directory node', () => {
    const declared = [artifact('result.csv', 512, 'primary'), artifact('execution/task_finished', 0, 'diagnostic')];
    const root = buildArtifactTree(declared);
    const execution = root.directories.find(directory => directory.name === 'execution');
    expect(execution).toBeDefined();
    expect(execution!.artifacts.map(item => item.path)).toEqual(['execution/task_finished']);
  });
});
