import { afterEach, describe, expect, it, vi } from 'vitest';

import { jaagBuilder } from '../src/features/create-task/input-workspace/jaag-builder';
import type { WorkspaceContext, WorkspacePluginInstance } from '../src/features/create-task/input-workspace/plugin-contract';
import type { TaskFormDefinition, WorkspaceCapability } from '../src/features/create-task/types';
import { HarnessNode, installHarness } from './dom-harness';

afterEach(() => vi.unstubAllGlobals());

const form = {
  name: 'bioemu2',
  inputs: [{ id: 'system', title: 'BioEmu2 system', type: 'supporting_data', cardinality: { min: 1, max: 1 } }],
  params: [],
  input_workspace: { version: 3, plugins: [], steps: [] },
} as unknown as TaskFormDefinition;

const definition: WorkspaceCapability = {
  plugin: 'jaag-builder',
  id: 'jaag_system_builder',
  title: 'Build a System YAML',
  options: { target: 'bioemu2', role: 'system' },
  stepId: 'material',
};

function mount(initial: File[] = [], reentrant = false) {
  installHarness(vi.stubGlobal as never);
  const target = document.createElement('div') as unknown as HarnessNode;
  const roleFiles = new Map<string, File[]>([['system', initial]]);
  let instance: WorkspacePluginInstance | undefined;
  const changed = vi.fn(() => { if (reentrant) instance?.refresh?.(); });
  const context = {
    form,
    roleFiles: (role: string) => [...(roleFiles.get(role) ?? [])],
    setRoleFiles: (role: string, files: File[]) => { roleFiles.set(role, files); },
    primaryIndex: () => 0,
    setPrimaryIndex: () => undefined,
    primaryFile: (role: string) => roleFiles.get(role)?.[0] ?? null,
    inputFiles: () => [...roleFiles].flatMap(([role, files]) => files.map(file => ({ role, file }))),
    structureFile: () => null,
    setSequenceRole: () => undefined, sequenceRole: () => null,
    sequence: () => '', sequenceName: () => '',
    parameters: () => ({}), setParameter: () => undefined,
    structureSelections: () => [], setStructureSelections: () => undefined,
    summaries: () => [], changed,
    filesChanged: changed,
  } as unknown as WorkspaceContext;
  instance = jaagBuilder.mount(target as unknown as HTMLElement, definition, context, { fetch })!;
  const byPlaceholder = (tag: string, placeholder: string): HarnessNode => {
    const match = target.querySelectorAll(tag).find(node => (node as unknown as { placeholder?: string }).placeholder === placeholder);
    if (!match) throw new Error(`missing ${tag} with placeholder ${placeholder}`);
    return match;
  };
  return { target, roleFiles, changed, context, instance, byPlaceholder };
}

describe('JAAG builder input workspace capability', () => {
  it('does not replace a plain YAML upload until the builder is used', () => {
    const uploaded = new File(['entities: []\n'], 'uploaded.yaml');
    const { roleFiles, changed, instance } = mount([uploaded]);
    expect(roleFiles.get('system')).toEqual([uploaded]);
    expect(changed).not.toHaveBeenCalled();
    expect(instance.validate?.() ?? []).toEqual([]);
  });

  it('serializes a protein system into the declared role', async () => {
    const { roleFiles, changed, byPlaceholder } = mount();
    const sequence = byPlaceholder('textarea', 'sequence');
    (sequence as unknown as { value: string }).value = 'ACDEFGHIK';
    sequence.dispatch('input', {});

    expect(changed).toHaveBeenCalled();
    const files = roleFiles.get('system') ?? [];
    expect(files).toHaveLength(1);
    const file = files[0]!;
    expect(file.name).toBe('jaag-bioemu2.yaml');
    const yaml = await file.text();
    expect(yaml).toContain('entity_type: protein');
    expect(yaml).toContain('asym_ids: [A]');
    expect(yaml).toContain('sequence: ACDEFGHIK');
  });

  it('refuses an invalid builder document instead of binding it', () => {
    const { roleFiles, byPlaceholder, instance } = mount();
    const sequence = byPlaceholder('textarea', 'sequence');
    (sequence as unknown as { value: string }).value = 'ACDEFGHIK';
    sequence.dispatch('input', {});
    expect(roleFiles.get('system')).toHaveLength(1);

    (sequence as unknown as { value: string }).value = '';
    sequence.dispatch('input', {});
    expect(roleFiles.get('system')).toEqual([]);
    const validation = instance.validate?.() ?? [];
    const messages = Array.isArray(validation) ? validation : [validation];
    expect(messages.join('; ')).toMatch(/sequence/i);
  });

  it('serializes a ligand entity with its CCD code', async () => {
    const { roleFiles, target, byPlaceholder } = mount();
    const type = target.querySelectorAll('select')[0]!;
    (type as unknown as { value: string }).value = 'ligand';
    type.dispatch('change', {});
    const ligand = byPlaceholder('input', 'NAG or A1L3H for CCD; CCO for SMILES');
    (ligand as unknown as { value: string }).value = 'NAG';
    ligand.dispatch('input', {});

    const file = (roleFiles.get('system') ?? [])[0]!;
    const yaml = await file.text();
    expect(yaml).toContain('entity_type: ligand');
    expect(yaml).toContain('ccd_code: NAG');
  });

  it('relinquishes the role when another capability replaces the generated YAML', async () => {
    const { roleFiles, context, target, byPlaceholder, instance } = mount([], true);
    const sequence = byPlaceholder('textarea', 'sequence');
    (sequence as unknown as { value: string }).value = 'ACDEFGHIK';
    sequence.dispatch('input', {});

    const generated = (roleFiles.get('system') ?? [])[0]!;
    expect(await generated.text()).toContain('sequence: ACDEFGHIK');

    // The files capability binds an upload and then refreshes every plugin.
    const external = new File(['entities: []\n'], 'external-system.yaml');
    context.setRoleFiles('system', [external]);
    context.filesChanged();

    expect(roleFiles.get('system')).toEqual([external]);
    // Later host refreshes keep the upload and what submission would carry.
    context.filesChanged();
    instance.refresh?.();
    expect(roleFiles.get('system')).toEqual([external]);
    expect(context.inputFiles()).toEqual([{ role: 'system', file: external }]);
    const builder = target.querySelector('.ct-jaag-builder') as unknown as { dataset: Record<string, string> };
    expect(builder.dataset.jaagOwnership).toBe('external');
  });

  it('serializes an ambiguous ligand string by the explicit representation', async () => {
    for (const value of ['CCO', 'c1ccccc1']) {
      for (const [source, key, other] of [
        ['ccd', 'ccd_code', 'smiles'],
        ['smiles', 'smiles', 'ccd_code'],
      ] as const) {
        const { roleFiles, target, byPlaceholder } = mount();
        const type = target.querySelectorAll('select')[0]!;
        (type as unknown as { value: string }).value = 'ligand';
        type.dispatch('change', {});
        const representation = target.querySelectorAll('select')[1]!;
        (representation as unknown as { value: string }).value = source;
        representation.dispatch('change', {});
        const ligand = byPlaceholder('input', 'NAG or A1L3H for CCD; CCO for SMILES');
        (ligand as unknown as { value: string }).value = value;
        ligand.dispatch('input', {});

        // A CCD code is case-insensitive and JAAG normalizes it; SMILES is not.
        const serialized = source === 'ccd' ? value.toUpperCase() : value;
        const yaml = await (roleFiles.get('system') ?? [])[0]!.text();
        expect(yaml).toContain(`${key}: ${serialized}`);
        expect(yaml).not.toContain(`${other}: ${serialized}`);
      }
    }
  });

  it('terminates when the host refresh follows its own change notification', () => {
    // ``filesChanged`` refreshes every mounted capability, including this one.
    // Regenerating during that refresh would rewrite the role forever.
    const { roleFiles, byPlaceholder } = mount([], true);
    const sequence = byPlaceholder('textarea', 'sequence');
    (sequence as unknown as { value: string }).value = 'ACDEFGHIK';
    expect(() => sequence.dispatch('input', {})).not.toThrow();
    expect(roleFiles.get('system')).toHaveLength(1);
  });
});
