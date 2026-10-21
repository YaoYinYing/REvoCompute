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
/** Whether a result file is the Server's logical-file projection rather than a raw artifact.
 *
 * The parser assigns `path`, `name`, and `id` on both shapes, so a key test does
 * not discriminate; `viewer` is projected only on a logical file.
 */
export function isLogicalFile(file: ResultFile): file is LogicalResultFile { return 'viewer' in file; }
/** The name a result file is shown and labelled by: a logical file's declared name, an artifact's path. */
export function resultFileName(file: ResultFile): string { return isLogicalFile(file) ? file.name : file.path; }

export interface ResultManifest extends Omit<ApiResultManifest, 'artifacts'> {
  filename?: string;
  artifacts: ResultArtifact[];
  message?: string;
}
