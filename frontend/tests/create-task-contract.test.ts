import { afterEach, describe, expect, it, vi } from 'vitest';

import { parseWorkspaceDescriptor } from '../src/features/create-task/api';
import { parametersFromSchema, seedConstant } from '../src/features/create-task/parameter-controls';
import { buildSubmissionFormData } from '../src/features/create-task/submission';
import type { ParameterDefinition, TaskFormDefinition } from '../src/features/create-task/types';

afterEach(() => vi.unstubAllGlobals());

/** One projected parameter, built through the real schema projection. */
function projected(property: Record<string, unknown>): ParameterDefinition {
  const [definition] = parametersFromSchema({ properties: { value: { type: 'integer', ...property } } });
  return definition!;
}

/** A deterministic draw that walks the supplied values and repeats the last. */
function draws(...values: number[]): (target: Uint32Array) => Uint32Array {
  let index = 0;
  return target => {
    target[0] = values[Math.min(index++, values.length - 1)]!;
    return target;
  };
}

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

  it('projects a declared calendar-date format only when the declared default can inhabit one', () => {
    // ``max_template_date`` (alphafold3) declares ``format: date`` with an ISO
    // default; a native date control holds that default unchanged.
    expect(projected({ format: 'date', default: '2021-09-30' })).toMatchObject({ dateFormat: true });
    // Without a default the field starts empty, so the picker still describes the
    // contract. A non-ISO default would be blanked by the picker and the task's own
    // default silently dropped, so that shape keeps the plain text field.
    expect(projected({ format: 'date' })).toMatchObject({ dateFormat: true });
    expect(projected({ format: 'date', default: 'tomorrow' })).toMatchObject({ dateFormat: false });
    expect(projected({ default: '2021-09-30' })).toMatchObject({ dateFormat: false });
  });

  it('draws a seed inside the task’s declared generation domain', () => {
    // ``x-ui-control.random`` narrows the API range: dynamicmpnn declares
    // ``random.minimum: 1`` over an API range starting at 0, so a drawn seed is
    // never the sentinel zero the schema reserves for upstream randomization.
    const narrowed = projected({ minimum: 0, maximum: 2147483647, 'x-ui-control': { kind: 'seed', random: { minimum: 1 } } });
    expect(seedConstant(narrowed, draws(0))).toBe(1);
    // The largest draw the whole-domain band admits is the declared maximum.
    expect(seedConstant(narrowed, draws(4_294_967_293))).toBe(2_147_483_647);

    // A fully declared range projects its own bounds, inclusive.
    const bounded = projected({ minimum: 0, maximum: 100, 'x-ui-control': { kind: 'seed', random: { minimum: 0, maximum: 100 } } });
    expect(seedConstant(bounded, draws(0))).toBe(0);
    expect(seedConstant(bounded, draws(100))).toBe(100);

    // An exclusive API bound is stepped inside the range rather than widened.
    const exclusive = projected({ exclusiveMinimum: 0, exclusiveMaximum: 10, 'x-ui-control': { kind: 'seed' } });
    expect(seedConstant(exclusive, draws(0))).toBe(1);
    expect(seedConstant(exclusive, draws(8))).toBe(9);
  });

  it('draws a seed by rejection, so no value in the domain is over-represented', () => {
    // A 3-value domain leaves a remainder no 32-bit draw divides evenly, so a
    // modulo-only implementation folds the over-band draws back onto the low end
    // and over-represents it. The rejection draws are discarded instead, so the
    // value the next in-band draw names is the one that lands.
    const domain = projected({ minimum: 0, maximum: 2, 'x-ui-control': { kind: 'seed' } });
    // 2**32 % 3 == 1, so the one over-band draw (2**32 - 1) is rejected; a
    // modulo-only draw of that same value would have answered 0.
    expect(seedConstant(domain, draws(4_294_967_295, 2))).toBe(2);
    expect(seedConstant(domain, draws(4_294_967_295, 0))).toBe(0);

    // A degenerate domain (an empty declared range) still answers inside it
    // rather than escaping the bounds the task declared.
    const empty = projected({ minimum: 5, maximum: 4, 'x-ui-control': { kind: 'seed' } });
    expect(seedConstant(empty, draws(0))).toBe(5);
  });

  it('covers the whole declared domain a 32-bit draw spans, and refuses a wider one', () => {
    // The widest domain a shipped task declares is ``0..4294967295`` (boltz, chai1,
    // evosplit, pallatom): a span of exactly the 2**32 values one 32-bit draw
    // addresses, so both ends are reachable and every draw is in band.
    const widest = projected({ minimum: 0, maximum: 4_294_967_295, 'x-ui-control': { kind: 'seed' } });
    expect(seedConstant(widest, draws(0))).toBe(0);
    expect(seedConstant(widest, draws(4_294_967_295))).toBe(4_294_967_295);

    // One value wider and no 32-bit draw covers the domain uniformly. Sampling
    // only its low 2**32 values would present a biased result as the declared
    // range the schema published, so it fails loud instead.
    const wider = projected({ minimum: 0, maximum: 4_294_967_296, 'x-ui-control': { kind: 'seed' } });
    expect(() => seedConstant(wider, draws(0))).toThrow(/wider than a 32-bit draw/);
  });
});

