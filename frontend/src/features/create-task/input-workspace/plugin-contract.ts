import type { TaskFormDefinition, WorkspaceCapability, WorkspaceSummary } from '../types';

export interface WorkspaceContext {
  form: TaskFormDefinition;
  roleFiles(role: string): File[];
  setRoleFiles(role: string, files: File[]): void;
  primaryIndex(role: string): number;
  setPrimaryIndex(role: string, index: number): void;
  primaryFile(role: string): File | null;
  inputFiles(): Array<{ role: string; file: File }>;
  structureFile(role?: string): File | null;
  setSequenceRole(role: string): void;
  sequenceRole(): string | null;
  sequence(): string;
  sequenceName(): string;
  parameters(): Record<string, string>;
  structureSelections(): Array<{ chain: string; residue: number }>;
  setStructureSelections(value: Array<{ chain: string; residue: number }>): void;
  summaries(): WorkspaceSummary[];
  changed(): void;
  filesChanged(): void;
}

export interface WorkspacePluginServices {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

export interface WorkspacePluginInstance {
  readValue?(): unknown;
  summarize?(): WorkspaceSummary | WorkspaceSummary[] | null;
  validate?(): string | string[] | null;
  refresh?(): void | Promise<void>;
  destroy?(): void;
}

export interface WorkspacePlugin {
  id: string;
  mount(
    target: HTMLElement,
    definition: WorkspaceCapability,
    context: WorkspaceContext,
    services: WorkspacePluginServices,
  ): WorkspacePluginInstance | void;
}

export interface WorkspacePluginModule { default: WorkspacePlugin }

export function isWorkspacePlugin(value: unknown): value is WorkspacePlugin {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<WorkspacePlugin>;
  return typeof candidate.id === 'string' && typeof candidate.mount === 'function';
}
