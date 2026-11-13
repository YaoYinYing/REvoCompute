import { afterEach, describe, expect, it, vi } from 'vitest';

import { jaagBuilder } from '../src/features/create-task/input-workspace/jaag-builder';
import type { WorkspaceContext } from '../src/features/create-task/input-workspace/plugin-contract';
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

function mount(initial: File[] = []) {
  installHarness(vi.stubGlobal as never);
  const target = document.createElement('div') as unknown as HarnessNode;
  const roleFiles = new Map<string, File[]>([['system', initial]]);
  const changed = vi.fn();
  const context = {
    form,
    roleFiles: (role: string) => [...(roleFiles.get(role) ?? [])],
    setRoleFiles: (role: string, files: File[]) => { roleFiles.set(role, files); },
    primaryIndex: () => 0,
    setPrimaryIndex: () => undefined,
    primaryFile: (role: string) => roleFiles.get(role)?.[0] ?? null,
    inputFiles: () => [], structureFile: () => null,
    setSequenceRole: () => undefined, sequenceRole: () => null,
    sequence: () => '', sequenceName: () => '',
    parameters: () => ({}), setParameter: () => undefined,
    structureSelections: () => [], setStructureSelections: () => undefined,
    summaries: () => [], changed,
    filesChanged: changed,
  } as unknown as WorkspaceContext;
  const instance = jaagBuilder.mount(target as unknown as HTMLElement, definition, context, { fetch })!;
  const byPlaceholder = (tag: string, placeholder: string): HarnessNode => {
    const match = target.querySelectorAll(tag).find(node => (node as unknown as { placeholder?: string }).placeholder === placeholder);
    if (!match) throw new Error(`missing ${tag} with placeholder ${placeholder}`);
    return match;
  };
  return { target, roleFiles, changed, instance, byPlaceholder };
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
    const ligand = byPlaceholder('input', 'CCD codes or SMILES (for example NAG)');
    (ligand as unknown as { value: string }).value = 'NAG';
    ligand.dispatch('input', {});

    const file = (roleFiles.get('system') ?? [])[0]!;
    const yaml = await file.text();
    expect(yaml).toContain('entity_type: ligand');
    expect(yaml).toContain('ccd_code: NAG');
  });
});
