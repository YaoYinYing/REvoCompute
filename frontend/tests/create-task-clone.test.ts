import { afterEach, describe, expect, it, vi } from 'vitest';

import { clonePreset, renderClonePanel } from '../src/features/create-task/clone';
import type { ClonePlan } from '../src/features/create-task/clone';
import { parametersFromSchema } from '../src/features/create-task/parameter-controls';
import { buildSubmissionFormData } from '../src/features/create-task/submission';
import type { TaskFormDefinition } from '../src/features/create-task/types';
import { HarnessNode, installHarness } from './dom-harness';

afterEach(() => vi.unstubAllGlobals());

const plan: ClonePlan = {
  plan_id: 'reference_reference_reference',
  expires_at: null,
  source_task_id: 'a'.repeat(32),
  source_task_type: 'method',
  source_submitted_at: null,
  target_task_type: 'method',
  target_display_name: 'Method',
  target_schema_revision: 'b'.repeat(64),
  compatible_parameters: [
    { name: 'seed', value: '0', source: 'recorded' },
    { name: 'enabled', value: 'false', source: 'recorded' },
    { name: 'sample', value: '7', source: 'current_default' },
  ],
  reusable_inputs: [
    {
      role: 'sequence', title: 'Sequence', formats: ['fasta'], required: true, reuse: 'reupload_required',
      files: [{ original_name: 'source.fasta', sha256: 'c'.repeat(64), size: 12, format: 'fasta', reuse: 'reupload_required', available: true, reason: null }],
    },
  ],
  warnings: [{ code: 'source_schema_not_recorded', message: 'Checked against the current schema.' }],
  blocked_fields: [{ field: 'mode', code: 'parameter_choice_unavailable', message: 'Not offered anymore.', recorded_value: 'legacy' }],
  can_submit: false,
};

describe('Clone & Reuse draft', () => {
  it('applies one preset with recorded zero and false preserved and no files', () => {
    const preset = clonePreset(plan);
    expect(preset.files.size).toBe(0);
    expect(preset.parameters).toEqual({ seed: '0', enabled: 'false', sample: '7' });
  });

  it('renders every warning, blocked field and re-upload requirement accessibly', () => {
    installHarness(vi.stubGlobal);
    const panel = renderClonePanel(plan) as unknown as HarnessNode;
    expect(panel.tag).toBe('SECTION');
    const headingId = panel.querySelector('h2')!.id;
    expect(panel.getAttribute('aria-labelledby')).toBe(headingId);
    expect(panel.querySelector('.ct-clone-warnings')?.textContent).toContain('Checked against the current schema.');
    expect(panel.querySelector('.ct-clone-blocked')?.textContent).toContain('mode');
    expect(panel.querySelectorAll('.ct-clone-files li')).toHaveLength(1);
    expect(panel.textContent).toContain('source.fasta');
    expect(panel.textContent).toContain('Upload this file again to use it.');
    // Read-only: no reset/revert controls are invented for a plan with no form.
    expect(panel.querySelectorAll('button')).toHaveLength(0);
  });

  it('offers reset and revert as explicit reader actions', () => {
    installHarness(vi.stubGlobal);
    let reset = 0; let revert = 0;
    const panel = renderClonePanel(plan, { onReset: () => { reset += 1; }, onRevert: () => { revert += 1; } }) as unknown as HarnessNode;
    const [resetButton, revertButton] = panel.querySelectorAll('button');
    resetButton!.dispatch('click', {});
    revertButton!.dispatch('click', {});
    expect(reset).toBe(1);
    expect(revert).toBe(1);
  });
});

describe('schema-owned placeholders', () => {
  it('projects the annotation onto the control description but not a value', () => {
    const [note] = parametersFromSchema({
      properties: { note: { type: 'string', 'x-ui-placeholder': 'e.g. a short note' } },
    });
    expect(note?.placeholder).toBe('e.g. a short note');
    expect(note?.defaultValue).toBeUndefined();
    expect(note?.required).toBe(false);
  });

  it('never submits a placeholder as a parameter or a default', () => {
    const definition = {
      name: 'method', inputs: [],
      params: [{ name: 'note', type: 'string', label: 'Note', description: '', help: '', unit: '', required: false, choices: [], advanced: false, dateFormat: false, placeholder: 'e.g. a short note' }],
    } as unknown as TaskFormDefinition;
    const data = buildSubmissionFormData(definition, {
      inputFiles: () => [], sequence: () => '', sequenceName: () => '', sequenceRole: () => null,
      parameters: () => ({}), executionMode: () => 'full',
    }, {});
    expect(data.get('params[note]')).toBeNull();
    expect([...data.keys()].some(key => key.startsWith('params['))).toBe(false);
  });

  it('adds cloned_from as provenance only for a cloned draft', () => {
    const definition = { name: 'method', inputs: [] } as unknown as TaskFormDefinition;
    const source = {
      inputFiles: () => [], sequence: () => '', sequenceName: () => '', sequenceRole: () => null,
      parameters: () => ({ seed: '0' }), executionMode: () => 'full',
    };
    const plain = buildSubmissionFormData(definition, source, {});
    expect(plain.get('cloned_from')).toBeNull();
    const cloned = buildSubmissionFormData(definition, source, {}, 'a'.repeat(32));
    expect(cloned.get('cloned_from')).toBe('a'.repeat(32));
    // Provenance is not a parameter.
    expect(cloned.get('params[cloned_from]')).toBeNull();
  });
});
