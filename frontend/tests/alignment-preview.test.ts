import { expect, it } from 'vitest';
import { buildSubmissionFormData } from '../src/features/create-task/submission';
import type { TaskFormDefinition } from '../src/features/create-task/types';
import { alignmentPreview } from '../src/features/create-task/input-workspace/alignment-preview';

it('projects A3M aligned columns without changing source or confusing source positions', () => {
  const source = '>query\nACde.F-G\n>homolog\nAC...F-G\n';
  const result = alignmentPreview(source, true)!;
  expect(result.rows.map(row => row.cells.map(cell => cell.symbol).join(''))).toEqual(['ACF-G', 'ACF-G']);
  expect(result.rows[0]!.cells[2]).toEqual({ symbol: 'F', sourceCharacter: 6, residue: 5 });
  expect(result.rows[0]!.cells[3]!.residue).toBeNull();
  expect(source).toContain('ACde.F-G');
  expect(result.columns).toBe(5);
});
it('preserves lowercase FASTA residues and aligned gaps while flagging unequal rows', () => {
  const result = alignmentPreview('>one\nAc.d-\n>two\nAC--\n', false)!;
  expect(result.rows[0]!.cells.map(cell => cell.symbol).join('')).toBe('AC.D-');
  expect(result.ragged).toBe(true); expect(result.columns).toBeNull();
});
it('bounds rows and cells and discards a partial final source record', () => {
  const source = Array.from({length: 10}, (_, i) => `>row${i}\n${'A'.repeat(300)}\n`).join('');
  const result = alignmentPreview(source, true, true)!;
  expect(result.rows).toHaveLength(8); expect(result.rows[0]!.cells).toHaveLength(160);
  expect(result.columns).toBe(300); expect(result.limited).toBe(true);
  expect(alignmentPreview('>complete\nACD\n>partial\nA', true, true)!.rows).toHaveLength(1);
});
it('does not turn unsupported or malformed text into scientific alignment data', () => {
  expect(alignmentPreview('CLUSTAL W\nseq ACD', false)).toBeNull();
  expect(alignmentPreview('>bad\nA$C', true)).toBeNull();
});

it('submits the unchanged original A3M after constructing an aligned preview', async () => {
  const source = '>query\nACde.F-G\n>homolog\nAC...F-G\n';
  const file = new File([source], 'input.a3m', { type: 'text/plain' });
  alignmentPreview(await file.text(), true);
  const data = buildSubmissionFormData({ name: 'alignment_task', inputs: [] } as unknown as TaskFormDefinition, {
    inputFiles: () => [{ role: 'alignment', file }], sequence: () => '', sequenceName: () => '', sequenceRole: () => null,
    parameters: () => ({ iterations: '400' }),
  }, {});
  expect(await (data.get('files') as File).text()).toBe(source);
  expect(data.get('input_roles')).toBe('alignment');
  expect(data.get('params[iterations]')).toBe('400');
});
