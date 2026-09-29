import { afterEach, describe, expect, it, vi } from 'vitest';

import { parseWorkspaceDescriptor } from '../src/features/create-task/api';
import { parametersFromSchema } from '../src/features/create-task/parameter-controls';
import { buildSubmissionFormData } from '../src/features/create-task/submission';
import type { TaskFormDefinition } from '../src/features/create-task/types';

afterEach(() => vi.unstubAllGlobals());

describe('Create Task server contracts', () => {
  it('accepts only canonical descriptor-approved same-origin assets', () => {
    vi.stubGlobal('window', { location: { origin: 'https://compute.example' } });
    expect(parseWorkspaceDescriptor({
      id: 'regions', owner: 'runner', global_id: 'runner:regions',
      descriptor_url: '/compute/api/workspace/plugins/runner/regions',
      module: { url: '/compute/api/workspace/assets/runner/regions/index.js', type: 'module' },
      stylesheets: [{ url: '/compute/api/workspace/assets/runner/regions/style.css', media_type: 'text/css' }],
    }).module.url).toBe('/compute/api/workspace/assets/runner/regions/index.js');
    expect(() => parseWorkspaceDescriptor({
      id: 'regions', owner: 'runner', global_id: 'runner:regions',
      descriptor_url: '/compute/api/workspace/plugins/runner/regions',
      module: { url: 'https://evil.example/index.js', type: 'module' }, stylesheets: [],
    })).toThrow(/same-origin/);
  });

  it('projects parameter type, bounds, enum, help, unit, default, and seed metadata', () => {
    const params = parametersFromSchema({
      $schema: 'https://json-schema.org/draft/2020-12/schema', type: 'object', additionalProperties: false,
      required: ['samples'], properties: {
        samples: { type: 'integer', title: 'Samples', minimum: 1, maximum: 9, multipleOf: 2, default: 3, description: 'Count', 'x-unit': 'models', 'x-help': 'Controls output count.', 'x-advanced': true, 'x-ui-control': { kind: 'seed', random: { minimum: 2, maximum: 8 } } },
        mode: { type: 'string', enum: ['fast', 'exact'], default: 'fast' },
        enabled: { type: 'boolean', default: true },
      },
    });
    expect(params[0]).toMatchObject({ name: 'samples', type: 'int', required: true, minimum: 1, maximum: 9, step: 2, unit: 'models', help: 'Controls output count.', advanced: true, seed: { minimum: 2, maximum: 8 } });
    expect(params[1]?.choices).toEqual(['fast', 'exact']);
    expect(params[2]).toMatchObject({ type: 'bool', defaultValue: true });
  });

  it('binds files to named roles and emits the versioned workspace document', () => {
    const file = new File(['ATOM'], 'model.pdb');
    const definition = { name: 'method', inputs: [] } as unknown as TaskFormDefinition;
    const data = buildSubmissionFormData(definition, {
      inputFiles: () => [{ role: 'structure', file }], sequence: () => '', sequenceName: () => '', sequenceRole: () => null,
      parameters: () => ({ models: '4', enabled: 'true' }),
    }, { selection: { chains: ['A'] } });
    expect(data.getAll('files')).toEqual([file]);
    expect(data.getAll('input_roles')).toEqual(['structure']);
    expect(data.get('params[models]')).toBe('4');
    expect(JSON.parse(String(data.get('workspace')))).toEqual({ version: 2, capabilities: { selection: { chains: ['A'] } } });
  });
});

