import { afterEach, describe, expect, it, vi } from 'vitest';

import { inputBuilder } from '../src/features/create-task/input-workspace/input-builder';
import { BuilderUnavailableError, builderAdapters, sha256Hex } from '../src/features/create-task/input-workspace/builders';
import type { WorkspaceContext, WorkspacePluginInstance } from '../src/features/create-task/input-workspace/plugin-contract';
import type { TaskFormDefinition, WorkspaceBuilder } from '../src/features/create-task/types';
import { HarnessNode, installHarness } from './dom-harness';

afterEach(() => { delete builderAdapters.synthetic; vi.unstubAllGlobals(); });

const builder: WorkspaceBuilder = {
  id: 'synthetic', owner: null, api_version: 1, builder_version: 3, state_schema_version: 1,
  targets: { af3: 'json' }, adapter: 'synthetic', available: true,
};

function form(inputs: Array<{ id: string; title: string; multiplied?: boolean }>): TaskFormDefinition {
  return {
    name: 'task', display_name: 'Task', category: 'analysis', summary: '', use_when: '', input_summary: '',
    output_summary: '', considerations: [], access: { restricted: false }, submission: null,
    parameters_url: '', params: [], execution_modes: [], max_request_bytes: 1024,
    inputs: inputs.map(item => ({
      id: item.id, title: item.title, type: 'supporting_data', formats: ['json'], extensions: ['.json'],
      accept: '.json', cardinality: { min: 0, max: 1 }, description: '',
    })),
    input_workspace: {
      version: 3, plugins: [], builders: [builder],
      steps: [{ id: 'material', title: 'Material', capabilities: [
        { plugin: 'files', id: 'files', title: 'Files', options: {} },
        { plugin: 'input-builder', id: 'builder', title: 'Build', stepId: 'material',
          options: { builder: 'synthetic', target: 'af3', outputs: { input: 'specification' } } },
      ] }],
    },
  } as unknown as TaskFormDefinition;
}

function context(formValue: TaskFormDefinition, files: Map<string, File[]>): WorkspaceContext {
  return {
    form: formValue,
    roleFiles: role => [...(files.get(role) || [])],
    setRoleFiles: (role, next) => { files.set(role, next); },
    primaryIndex: () => 0, setPrimaryIndex: () => undefined,
    primaryFile: role => (files.get(role) || [])[0] || null,
    inputFiles: () => [...files.entries()].flatMap(([role, bound]) => bound.map(file => ({ role, file }))),
    structureFile: () => null, setSequenceRole: () => undefined, sequenceRole: () => null,
    sequence: () => '', sequenceName: () => '', parameters: () => ({}), setParameter: () => undefined,
    structureSelections: () => [], setStructureSelections: () => undefined,
    summaries: () => [], changed: () => undefined, filesChanged: () => undefined,
  };
}

function findByText(root: HarnessNode, text: string): HarnessNode | null {
  if (root.tag !== '#TEXT' && root.ownText === text) return root;
  for (const child of root.nodes) {
    const found = findByText(child, text);
    if (found) return found;
  }
  return null;
}

function mountPlugin() {
  const files = new Map<string, File[]>();
  const definition = form([{ id: 'specification', title: 'Specification' }]).input_workspace.steps[0]!.capabilities[1]!;
  const target = new HarnessNode('DIV');
  const instance = inputBuilder.mount(target as unknown as HTMLElement, definition as never, context(form([{ id: 'specification', title: 'Specification' }]), files), { fetch: async () => new Response('') }) as WorkspacePluginInstance;
  return { instance, files, target };
}

function installFake(payload = 'generated'):
  { listener: (() => void) | null; restored: unknown; materializeCalls: number } {
  const state = { listener: null as (() => void) | null, restored: null as unknown, materializeCalls: 0 };
  builderAdapters.synthetic = {
    async mount() {
      return {
        async materialize() {
          state.materializeCalls += 1;
          const bytes = new TextEncoder().encode(payload);
          return {
            snapshot: { native: true }, revision: 4,
            output: { role: 'input' as const, name: `af3-${state.materializeCalls}.json`, mime: 'application/json', bytes, sha256: await sha256Hex(bytes) },
            dependencies: [], errors: [], warnings: [],
          };
        },
        async restore(value: unknown) { state.restored = value; },
        subscribe(listener: () => void) { state.listener = listener; return () => { state.listener = null; }; },
        destroy() { state.listener = null; },
      };
    },
  };
  return state;
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
async function waitFor(assertion: () => void): Promise<void> {
  await vi.waitFor(assertion, { timeout: 3000, interval: 5 });
}

describe('generic Input Builder capability', () => {
  it('binds a captured output to its declared role with a versioned envelope', async () => {
    installHarness(vi.stubGlobal);
    const state = installFake();
    const { instance, files, target } = mountPlugin();

    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(files.get('specification')?.length).toBe(1));

    expect(state.materializeCalls).toBe(1);
    expect(files.get('specification')?.length).toBe(1);
    expect(files.get('specification')![0]!.name).toBe('af3-1.json');
    const envelope = instance.readValue!() as Record<string, unknown>;
    expect(envelope).toMatchObject({
      version: 1, builder: 'synthetic', builder_version: 3, state_schema_version: 1, target: 'af3', revision: 4,
    });
    expect(envelope.outputs).toEqual([
      expect.objectContaining({ logical: 'input', role: 'specification', name: 'af3-1.json', size: 9 }),
    ]);
    expect(instance.validate!()).toEqual([]);
  });

  it('invalidates only its own output when the editor changes', async () => {
    installHarness(vi.stubGlobal);
    const state = installFake();
    const { instance, files, target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(instance.readValue!()).toBeTruthy());

    state.listener?.();
    expect(files.get('specification')).toEqual([]);
    expect(instance.readValue!()).toBeUndefined();
    expect(String((instance.validate!() as string[]).join(' '))).toContain('Apply the builder output');
  });

  it('releases ownership instead of overwriting an independent upload', async () => {
    installHarness(vi.stubGlobal);
    installFake();
    const { instance, files, target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(files.get('specification')?.length).toBe(1));

    const upload = new File(['{"other":true}'], 'other.json', { type: 'application/json' });
    files.set('specification', [upload]);
    instance.refresh!();
    expect(files.get('specification')).toEqual([upload]);
    expect(instance.readValue!()).toBeUndefined();
  });

  it('switching to Upload clears the builder-owned file and never submits stale state', async () => {
    installHarness(vi.stubGlobal);
    installFake();
    const { instance, files, target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(files.get('specification')?.length).toBe(1));

    findByText(target, 'Upload file')!.dispatch('click', new Event('click'));
    expect(files.get('specification')).toEqual([]);
    expect(instance.readValue!()).toBeUndefined();
    expect(instance.validate!()).toEqual([]);
  });

  it('restores native state and labels a re-materialized digest change', async () => {
    installHarness(vi.stubGlobal);
    const state = installFake('restored-bytes');
    const { instance, target } = mountPlugin();
    const entry = {
      capability_id: 'builder', builder: 'synthetic', target: 'af3', builder_version: 3, state_schema_version: 1,
      revision: 1, outputs: [{ logical: 'input', role: 'specification', name: 'source.json', size: 1, sha256: '0'.repeat(64) }],
      dependencies: [], state_available: true, compatible: true, reason: null,
    };
    await instance.restoreAuthoring!(entry, { native: 'recorded' });
    expect(state.restored).toEqual({ native: 'recorded' });
    expect(instance.readValue!()).toBeTruthy();
    const root = target.nodes[0] as HarnessNode;
    expect(root.dataset.builderRestore).toBe('changed');
  });

  it('refuses to submit an exclusive builder beside another bound role', async () => {
    installHarness(vi.stubGlobal);
    installFake();
    const files = new Map<string, File[]>();
    const value = form([{ id: 'specification', title: 'Specification' }, { id: 'scaffold', title: 'Scaffold' }]);
    const definition = {
      ...value.input_workspace.steps[0]!.capabilities[1]!,
      options: { builder: 'synthetic', target: 'af3', outputs: { input: 'specification' }, exclusive: true },
    };
    const target = new HarnessNode('DIV');
    const instance = inputBuilder.mount(target as unknown as HTMLElement, definition as never, context(value, files), { fetch: async () => new Response('') }) as WorkspacePluginInstance;
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(files.get('specification')?.length).toBe(1));
    files.set('scaffold', [new File(['x'], 'scaffold.cif')]);
    const errors = instance.validate!() as string[];
    expect(errors.join(' ')).toContain('self-contained');
  });

  it('offers upload only when the deployment cannot serve the builder', () => {
    installHarness(vi.stubGlobal);
    const files = new Map<string, File[]>();
    const value = form([{ id: 'specification', title: 'Specification' }]);
    value.input_workspace.builders = [{ ...builder, available: false }];
    const target = new HarnessNode('DIV');
    const instance = inputBuilder.mount(
      target as unknown as HTMLElement, value.input_workspace.steps[0]!.capabilities[1]! as never, context(value, files), { fetch: async () => new Response('') },
    ) as WorkspacePluginInstance;
    expect(instance.readValue!()).toBeUndefined();
    expect(findByText(target, 'This builder is unavailable in this deployment; upload a prepared file instead.')).toBeTruthy();
  });

  it('lets a plain upload proceed after a clone restore could not mount the builder', async () => {
    installHarness(vi.stubGlobal);
    builderAdapters.synthetic = { async mount() { throw new BuilderUnavailableError('builder is offline'); } };
    const { instance, files } = mountPlugin();
    await instance.restoreAuthoring!({
      capability_id: 'builder', builder: 'synthetic', target: 'af3', builder_version: 3, state_schema_version: 1,
      revision: 1, outputs: [], dependencies: [], state_available: true, compatible: true, reason: null,
    }, { native: 'recorded' });
    expect((instance.validate!() as string[]).join(' ')).toContain('could not be restored');

    const upload = new File(['{"prepared":true}'], 'prepared.json', { type: 'application/json' });
    files.set('specification', [upload]);
    instance.refresh!();
    expect(files.get('specification')).toEqual([upload]);
    expect(instance.validate!()).toEqual([]);
  });

  it('refuses a capture that finishes after an editor change', async () => {
    installHarness(vi.stubGlobal);
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let listener: (() => void) | null = null;
    let materializeCalls = 0;
    builderAdapters.synthetic = {
      async mount() {
        return {
          async materialize() {
            materializeCalls += 1;
            await gate;
            const bytes = new TextEncoder().encode('late');
            return {
              snapshot: { native: true }, revision: 1,
              output: { role: 'input' as const, name: 'late.json', mime: 'application/json', bytes, sha256: await sha256Hex(bytes) },
              dependencies: [], errors: [], warnings: [],
            };
          },
          async restore() {},
          subscribe(value: () => void) { listener = value; return () => { listener = null; }; },
          destroy() { listener = null; },
        };
      },
    };
    const { instance, files, target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await tick();
    expect(materializeCalls).toBe(1);
    expect(listener).not.toBeNull();

    listener!();
    release();
    await waitFor(() => expect(String((instance.validate!() as string[]).join(' '))).toContain('Apply the builder output'));
    expect(files.get('specification')).toBeUndefined();
    expect(instance.readValue!()).toBeUndefined();
  });

  it('refuses dependency-bearing provider output in the generic host', async () => {
    installHarness(vi.stubGlobal);
    builderAdapters.synthetic = {
      async mount() {
        return {
          async materialize() {
            const bytes = new TextEncoder().encode('with-deps');
            return {
              snapshot: { native: true }, revision: 1,
              output: { role: 'input' as const, name: 'deps.json', mime: 'application/json', bytes, sha256: await sha256Hex(bytes) },
              dependencies: [{ id: 'msa', kind: 'msa', name: 'a.a3m', size: 1, sha256: '0'.repeat(64) }],
              errors: [], warnings: [],
            };
          },
          async restore() {},
          subscribe() { return () => undefined; },
          destroy() {},
        };
      },
    };
    const { instance, files, target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Apply builder output')!.dispatch('click', new Event('click'));
    await waitFor(() => expect(String((instance.validate!() as string[]).join(' '))).toContain('Apply the builder output'));
    expect(files.get('specification')).toBeUndefined();
  });

  it('does not install a mount that finishes after switching to Upload', async () => {
    installHarness(vi.stubGlobal);
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let destroyed = false;
    builderAdapters.synthetic = {
      async mount() {
        await gate;
        return {
          async materialize() { throw new Error('unused'); },
          async restore() {},
          subscribe() { return () => undefined; },
          destroy() { destroyed = true; },
        };
      },
    };
    const { target } = mountPlugin();
    findByText(target, 'Build input')!.dispatch('click', new Event('click'));
    await tick();
    findByText(target, 'Upload file')!.dispatch('click', new Event('click'));
    release();
    await waitFor(() => expect(destroyed).toBe(true));
  });
});
