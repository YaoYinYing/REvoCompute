import type { InputFile, TaskFormDefinition, WorkspaceValues } from './types';

function sequenceName(value: string): string {
  return value.trim().replace(/\s+/g, '_').replace(/[^A-Za-z0-9_.-]/g, '') || 'sequence';
}

function wrap(value: string, width = 80): string {
  const lines: string[] = []; for (let index = 0; index < value.length; index += width) lines.push(value.slice(index, index + width)); return lines.join('\n');
}

export interface SubmissionSource {
  inputFiles(): InputFile[];
  sequence(): string;
  sequenceName(): string;
  sequenceRole(): string | null;
  parameters(): Record<string, string>;
}

export function buildSubmissionFormData(form: TaskFormDefinition, source: SubmissionSource, values: WorkspaceValues): FormData {
  const inputFiles = source.inputFiles(); const sequence = source.sequence();
  if (sequence) {
    const roleId = source.sequenceRole(); const role = form.inputs.find(item => item.id === roleId);
    if (!roleId || !role) throw new Error('Sequence input role is not available.');
    const extension = role.extensions[0] || '.fasta'; const name = sequenceName(source.sequenceName());
    inputFiles.push({ role: roleId, file: new File([`>${name}\n${wrap(sequence)}\n`], `${name}${extension}`, { type: 'text/plain' }) });
  }
  const data = new FormData();
  inputFiles.forEach(item => { data.append('files', item.file); data.append('input_paths', (item.file as File & { webkitRelativePath?: string }).webkitRelativePath || item.file.name); data.append('input_roles', item.role); });
  data.append('task_type', form.name); data.append('workspace', JSON.stringify({ version: 2, capabilities: values }));
  Object.entries(source.parameters()).forEach(([name, value]) => data.append(`params[${name}]`, value));
  return data;
}
