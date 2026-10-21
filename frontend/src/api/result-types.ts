import type { components } from './schema.generated';

export type ApiArtifact = components['schemas']['Artifact'];
export type LogicalResultFile = components['schemas']['LogicalResultFile'];
export type ApiResultManifest = components['schemas']['ResultManifest'];
export type TaskStatus = components['schemas']['TaskStatus'];
export type ResultView = components['schemas']['ResultView'];
export type ResultStoryboardDeclaration = components['schemas']['Storyboard'];
export type ResultRun = components['schemas']['ResultRun'];
export type ArtifactRole = ApiArtifact['role'];
export type PreviewCapability = ApiArtifact['capability'] | NonNullable<ApiArtifact['preview']>;

export interface ResultArtifact extends ApiArtifact {
  name?: string;
  table_url?: string;
  cardinality?: 'one' | 'many';
  id?: string;
}
/** A published artifact and a logical file both name their published path. */
export type ResultFile = ResultArtifact | LogicalResultFile;
export function resultFileName(file: ResultFile): string { return file.path; }

export interface ResultManifest extends Omit<ApiResultManifest, 'artifacts'> {
  filename?: string;
  artifacts: ResultArtifact[];
  message?: string;
}
