import type { components } from './schema.generated';

export type ApiArtifact = components['schemas']['Artifact'];
export type LogicalResultFile = components['schemas']['LogicalResultFile'];
export type ApiResultManifest = components['schemas']['ResultManifest'];
export type TaskStatus = components['schemas']['TaskStatus'];
export type ArtifactRole = ApiArtifact['role'];
export type PreviewCapability = ApiArtifact['capability'] | NonNullable<ApiArtifact['preview']>;

export interface ResultArtifact extends ApiArtifact {
  name?: string;
  table_url?: string;
  cardinality?: 'one' | 'many';
  id?: string;
}
export type ResultFile = ResultArtifact | LogicalResultFile;
export function resultFileName(file: ResultFile): string { return 'path' in file ? file.path : file.name; }

export interface ResultView {
  id: string;
  plugin: string;
  role?: string;
  title: string;
  description?: string;
  sources?: Record<string, string[]>;
  mapping?: Record<string, unknown>;
}

export interface ResultStoryboardDeclaration {
  identifier: string;
  entrypoint: string;
  entrypoint_url: string;
  requires: string[];
  optional: string[];
}

export interface ResultRun {
  submitted_at?: string;
  started_at?: string;
  finished_at?: string;
  walltime_seconds?: number | null;
  method?: { name?: string; output_summary?: string };
  inputs?: Array<{ path: string; sha256: string; role?: string }>;
  parameters?: Array<{ label: string; value: unknown; unit?: string }>;
  citations?: Array<{ title: string; doi?: string; url?: string }>;
}

export interface ResultManifest extends Omit<ApiResultManifest, 'artifacts' | 'run' | 'views' | 'storyboard' | 'result'> {
  filename?: string;
  artifacts: ResultArtifact[];
  views: ResultView[];
  storyboard: ResultStoryboardDeclaration | null;
  result: { files: Record<string, LogicalResultFile[]> };
  run: ResultRun;
  message?: string;
}
