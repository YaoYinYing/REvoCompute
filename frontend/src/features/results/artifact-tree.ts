import type { ResultArtifact } from '../../api/result-types';

export interface ArtifactTreeNode {
  name: string;
  path: string;
  directories: ArtifactTreeNode[];
  artifacts: ResultArtifact[];
}

export function localName(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.at(-1) || path;
}

export function buildArtifactTree(artifacts: ResultArtifact[]): ArtifactTreeNode {
  const root: ArtifactTreeNode = { name: '', path: '', directories: [], artifacts: [] };
  const directories = new Map<string, ArtifactTreeNode>([['', root]]);
  for (const artifact of [...artifacts].sort((left, right) => left.path.localeCompare(right.path))) {
    const segments = artifact.path.split('/').filter(Boolean);
    let parent = root;
    let currentPath = '';
    for (const segment of segments.slice(0, -1)) {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      let directory = directories.get(currentPath);
      if (!directory) {
        directory = { name: segment, path: currentPath, directories: [], artifacts: [] };
        directories.set(currentPath, directory);
        parent.directories.push(directory);
      }
      parent = directory;
    }
    parent.artifacts.push(artifact);
  }
  const sort = (node: ArtifactTreeNode): void => {
    node.directories.sort((left, right) => left.name.localeCompare(right.name));
    node.artifacts.sort((left, right) => localName(left.path).localeCompare(localName(right.path)));
    node.directories.forEach(sort);
  };
  sort(root);
  return root;
}

export function filterArtifacts(artifacts: ResultArtifact[], query: string): ResultArtifact[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return artifacts;
  // A zero-byte artifact carries no information a reader can use; listing it only adds noise.
  return artifacts.filter((artifact) => artifact.size > 0 && artifact.path.toLocaleLowerCase().includes(normalized));
}
