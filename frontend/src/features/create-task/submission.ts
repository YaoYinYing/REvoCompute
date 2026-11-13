import { t } from '../../app/i18n';
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
  executionMode(): string;
}

export function buildSubmissionFormData(
  form: TaskFormDefinition,
  source: SubmissionSource,
  values: WorkspaceValues,
  clonedFrom: string | null = null,
): FormData {
  const inputFiles = source.inputFiles(); const sequence = source.sequence();
  if (sequence) {
    const roleId = source.sequenceRole(); const role = form.inputs.find(item => item.id === roleId);
    if (!roleId || !role) throw new Error(t('ct.sequence.roleUnavailable'));
    const extension = role.extensions[0] || '.fasta'; const name = sequenceName(source.sequenceName());
    inputFiles.push({ role: roleId, file: new File([`>${name}\n${wrap(sequence)}\n`], `${name}${extension}`, { type: 'text/plain' }) });
  }
  const data = new FormData();
  inputFiles.forEach(item => { data.append('files', item.file); data.append('input_paths', (item.file as File & { webkitRelativePath?: string }).webkitRelativePath || item.file.name); data.append('input_roles', item.role); });
  data.append('task_type', form.name); data.append('execution_mode', source.executionMode());
  // Provenance, not an input: only a cloned draft names its source.
  if (clonedFrom) data.append('cloned_from', clonedFrom);
  data.append('workspace', JSON.stringify({ version: 2, capabilities: values }));
  Object.entries(source.parameters()).forEach(([name, value]) => data.append(`params[${name}]`, value));
  return data;
}

/**
 * Formats the browser may gzip on the wire.
 *
 * These are the text-like scientific and specification files the Server's
 * per-file-part contract is intended to serve. Trajectory and archive
 * containers (XTC, DCD, ZIP, NPZ, Parquet) and already-compressed bytes are
 * deliberately absent: the Server would refuse a compressed part it cannot
 * validate as its declared scientific format, and recompressing those costs
 * CPU without saving meaningful bytes.
 */
const COMPRESSIBLE_FORMATS = new Set([
  'pdb', 'mmcif', 'cif', 'gro', 'fasta', 'fa', 'a3m', 'aln', 'sto',
  'txt', 'csv', 'tsv', 'json', 'yaml', 'yml',
]);

/** Below this size, gzip framing cost outweighs any transfer saving. */
const MIN_COMPRESS_BYTES = 4096;

/** A part is only encoded when the result is at least 10% smaller. */
const WORTHWHILE_RATIO = 0.9;

export const ABORTED = 'AbortError';

export interface EncodedSubmission {
  data: FormData;
  originalBytes: number;
  encodedBytes: number;
  compressedFiles: number;
}

export interface EncodeOptions {
  signal?: AbortSignal;
}

function abortError(): DOMException {
  return new DOMException('The submission was cancelled.', ABORTED);
}

function checkAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function eligibleFormats(file: File): string[] {
  const extension = file.name.toLowerCase().split('.').pop() || '';
  return extension === 'cif' ? ['cif', 'mmcif'] : [extension];
}

/**
 * The decoded/encoded ratio the Server accepts for a declared gzip part.
 *
 * The value is projected by the Server's encoding capability; a Server that
 * does not advertise it is treated as identity-only rather than guessed at,
 * so the browser never submits a representation the Server refuses.
 */
function serverGzipRatio(form: TaskFormDefinition): number | null {
  const capability = form.file_encodings;
  if (capability?.version !== 1 || !capability.supported.includes('gzip')) return null;
  const ratio = capability.max_expansion_ratio;
  return Number.isFinite(ratio) && ratio > 0 ? ratio : null;
}

function compressionAvailable(): boolean {
  return typeof CompressionStream === 'function';
}

async function gzipFile(file: File, signal?: AbortSignal): Promise<Blob> {
  checkAborted(signal);
  const reader = file.stream().pipeThrough(new CompressionStream('gzip')).getReader();
  const chunks: BlobPart[] = [];
  try {
    while (true) {
      checkAborted(signal);
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  }
  return new Blob(chunks, { type: 'application/gzip' });
}

/**
 * Apply the Server-advertised per-file-part encoding to a built submission.
 *
 * The original ``File`` name, type and bytes stay the scientific contract; only
 * the wire representation changes. A part falls back to identity whenever the
 * Server, the browser or the content itself does not support the encoding, so
 * the returned form is always submittable by an identity-only client.
 */
export async function encodeSubmissionFormData(
  data: FormData,
  form: TaskFormDefinition,
  options: EncodeOptions = {},
): Promise<EncodedSubmission> {
  const { signal } = options;
  const files = data.getAll('files').map(value => value as File);
  const paths = data.getAll('input_paths');
  const roles = data.getAll('input_roles').map(value => String(value));
  const formats = new Map(form.inputs.map(role => [role.id, new Set(role.formats)]));
  const maxExpansionRatio = serverGzipRatio(form) ?? 0;
  const canEncode = maxExpansionRatio > 0 && compressionAvailable();
  const encodedFiles: File[] = [];
  const declarations: string[] = [];
  let originalBytes = 0;
  let encodedBytes = 0;
  let compressedFiles = 0;

  for (const [index, file] of files.entries()) {
    checkAborted(signal);
    const role = roles[index] || '';
    const declared = formats.get(role);
    const candidates = eligibleFormats(file);
    const eligible = canEncode
      && file.size >= MIN_COMPRESS_BYTES
      && candidates.some(format => COMPRESSIBLE_FORMATS.has(format) && (declared?.has(format) ?? false));
    let encoded: File | null = null;
    if (eligible) {
      try {
        const compressed = await gzipFile(file, signal);
        // A gzip part is only useful when it saves bytes *and* its decoded/
        // encoded ratio stays within the Server's advertised bound. The
        // Server refuses (input_encoding_limit) the rest, so keep identity.
        const ratio = compressed.size > 0 ? file.size / compressed.size : Infinity;
        if (compressed.size < file.size * WORTHWHILE_RATIO && ratio <= maxExpansionRatio) {
          encoded = new File([compressed], file.name, { type: file.type, lastModified: file.lastModified });
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === ABORTED) throw error;
        // A browser that refuses to encode this content keeps the identity
        // representation; a failed optimization never blocks the submission.
        encoded = null;
      }
    }
    encodedFiles.push(encoded ?? file);
    declarations.push(encoded ? 'gzip' : 'identity');
    originalBytes += file.size;
    encodedBytes += (encoded ?? file).size;
    if (encoded) compressedFiles += 1;
  }

  const transformed = new FormData();
  for (const [key, value] of data.entries()) {
    if (key === 'files' || key === 'file_encodings' || key === 'input_paths' || key === 'input_roles') continue;
    transformed.append(key, value as string | Blob);
  }
  encodedFiles.forEach(file => transformed.append('files', file));
  paths.forEach(path => transformed.append('input_paths', path));
  roles.forEach(role => transformed.append('input_roles', role));
  // The declaration is only needed when at least one part differs from the
  // identity default; an identity submission stays byte-for-byte compatible
  // with clients that predate this contract.
  if (compressedFiles > 0) declarations.forEach(encoding => transformed.append('file_encodings', encoding));

  return { data: transformed, originalBytes, encodedBytes, compressedFiles };
}
