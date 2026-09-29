import type { components } from '../../api/schema.generated';

export type TaskCatalog = components['schemas']['TaskCatalog'];
export type TaskSummary = components['schemas']['TaskTypeSummary'];
export type TaskType = components['schemas']['TaskTypeDetail'];
export type TaskInputRole = components['schemas']['TaskInputRole'];
export type TaskPreflight = components['schemas']['TaskPreflight'];
export type TaskStatus = components['schemas']['TaskStatus'];

export interface ParameterDefinition {
  name: string;
  type: 'bool' | 'int' | 'float' | 'string';
  label: string;
  description: string;
  help: string;
  unit: string;
  required: boolean;
  defaultValue?: string | number | boolean;
  choices: Array<string | number | boolean>;
  minimum?: number;
  maximum?: number;
  step?: number;
  advanced: boolean;
  seed?: { minimum?: number; maximum?: number };
}

export interface WorkspaceDescriptor {
  id: string;
  owner: string;
  global_id: string;
  descriptor_url: string;
  module: { url: string; type: 'module' };
  stylesheets: Array<{ url: string; media_type: 'text/css' }>;
  configuration_schema_url?: string;
}

export interface WorkspaceCapability {
  plugin: string;
  id: string;
  title: string;
  description?: string;
  options: Record<string, unknown>;
  stepId: string;
}

export interface WorkspaceStep {
  id: string;
  title: string;
  description?: string;
  capabilities: Omit<WorkspaceCapability, 'stepId'>[];
}

export interface WorkspaceContract {
  version: 3;
  plugins: WorkspaceDescriptor[];
  steps: WorkspaceStep[];
}

export interface TaskFormDefinition {
  name: string;
  display_name: string;
  category: string;
  summary: string;
  use_when: string;
  input_summary: string;
  output_summary: string;
  considerations: string[];
  runtime_family?: string;
  gpus?: boolean;
  requires_network?: boolean;
  access: components['schemas']['RunnerAccess'];
  parameters_url: string;
  inputs: TaskInputRole[];
  input_workspace: WorkspaceContract;
  params: ParameterDefinition[];
  max_request_bytes: number;
}

export interface InputFile {
  role: string;
  file: File;
}

export interface WorkspaceSummary { label: string; value: string }
export type WorkspaceValues = Record<string, unknown>;
