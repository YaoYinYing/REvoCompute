/*
 * A result folder the reader extracted from a downloaded REvoCompute archive.
 *
 * A local result is a projection of the same ResultManifest v3 the Server publishes, read from
 * the reader's own disk instead of the authenticated API. Nothing here is trusted because it
 * came from REvoCompute: the folder is ordinary bytes a reader could have edited, so every
 * declared path is checked before it is used, every declared size is compared with the file on
 * disk, and every file small enough to read whole has its SHA-256 compared. A folder that does
 * not match its own manifest is refused with the list of files that differ, because a
 * half-rendered result states a result the archive does not contain.
 *
 * A local result never becomes server-authorized: its Task identity is the literal `local`,
 * which no Server route matches, and its files are handed to views only as `blob:` URLs this
 * document created from the reader's own files.
 *
 * The projection mirrors `revocompute/result_projection.py`: an archived artifact record
 * already carries `capability`, `preview`, `role`, `media_type`, `sha256` and `size`, so only
 * the fields the Server adds at serve time are supplied here.
 */
import { parseResultManifest } from '../../api/result-api';
import type { ResultManifest } from '../../api/result-types';
import { t } from '../../app/i18n';
import type { LocalSourceFiles } from './renderer-registry';

/** The ceiling the Server refuses to publish a manifest above (`MANIFEST_MAX_BYTES`). */
export const MANIFEST_MAX_BYTES = 8 * 1024 * 1024;
/** A declared file at or below this size is read whole for a SHA-256 check. */
export const HASH_MAX_BYTES = 8 * 1024 * 1024;
/** The one Task identity a local result has: no Server route matches it. */
export const LOCAL_TASK_ID = 'local';
/** How many differing paths one refusal names before it summarises the rest. */
const NAMED = 5;

const MANIFEST = 'manifest.json';
const UTF8 = new TextDecoder('utf-8', { fatal: true });

export interface LocalVerification {
  /** Declared paths (artifacts and logical files) whose file is present with its declared length. */
  readonly present: number;
  /** Files whose SHA-256 was compared with the manifest. */
  readonly hashed: number;
  /** Files past the hash budget, verified by length only. */
  readonly unchecked: readonly string[];
}

export interface LocalResultSource extends LocalSourceFiles {
  readonly taskId: typeof LOCAL_TASK_ID;
  /** The archived manifest, projected into the shape the Result Workspace renders. */
  readonly manifest: ResultManifest;
  readonly verification: LocalVerification;
  /** The Storyboard the archive declares, by identifier only: its code is never loaded. */
  readonly storyboard: string | null;
  /** The Task the archive was exported from, as the manifest records it. */
  readonly sourceTaskId: string | null;
  /** The local handle for one declared path: the `blob:` URL views reach the file through. */
  url(path: string): string;
  /** Release every object URL this source created. */
  close(): void;
}

/** One file's path under the chosen result root. */
function relativePath(file: File, root: string | null): string {
  const entry = file as File & { webkitRelativePath?: string };
  const parts = (entry.webkitRelativePath || file.name).split('/').filter(Boolean);
  if (root !== null && parts[0] === root) parts.shift();
  return parts.join('/');
}

/**
 * The one shallowest `manifest.json`, and the folder it sits in.
 *
 * A selection holds one result: the manifest is taken from the folder that holds it, a manifest
 * nested deeper is not opened, and two manifests at the same depth are two results rather than
 * one. Picking a directory *above* the result is refused — the declared paths are relative to
 * the manifest's folder, so every one of them would miss.
 */
function findRoot(files: File[]): { root: string | null; manifest: File } {
  const matches = files.filter((file) => relativePath(file, null).split('/').pop() === MANIFEST);
  if (!matches.length) throw new Error(t('results.local.manifestMissing'));
  const depth = (file: File): number => relativePath(file, null).split('/').length;
  const shallowest = Math.min(...matches.map(depth));
  const candidates = matches.filter((file) => depth(file) === shallowest);
  if (candidates.length > 1) throw new Error(t('results.local.ambiguous'));
  const parts = relativePath(candidates[0]!, null).split('/');
  return { root: parts.length > 1 ? parts.slice(0, -1).join('/') : null, manifest: candidates[0]! };
}

/** A declared path is a relative path inside the folder: no traversal, no ambiguity. */
function safePath(path: unknown): path is string {
  if (typeof path !== 'string' || !path || path.length > 4096) return false;
  if (path.startsWith('/') || path.includes('\\') || path.includes('\0')) return false;
  return path.split('/').every((segment) => segment !== '' && segment !== '.' && segment !== '..');
}

async function readManifest(file: File): Promise<Record<string, unknown>> {
  if (file.size > MANIFEST_MAX_BYTES) throw new Error(t('results.local.manifestTooLarge'));
  let value: unknown;
  try { value = JSON.parse(UTF8.decode(await file.arrayBuffer())); }
  catch { throw new Error(t('results.local.manifestInvalid')); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(t('results.local.manifestInvalid'));
  return value as Record<string, unknown>;
}

/**
 * The renderer capability of a logical file, as `revocompute/result_projection.py::artifact_capability`
 * derives it. An archive's logical record inherits the *artifact's* preview, which is guessed from
 * the file extension; a table without one (`pssm_msa/*_ascii_mtx_file`) is `download_only` there
 * and `table` once its declared `type` is read. The Server re-derives it when it serves the same
 * manifest, so the folder's projection has to derive it the same way or a local result shows less
 * than the remote one.
 */
function projectedCapability(preview: unknown, logicalType: unknown): string {
  const declared = typeof logicalType === 'string' && logicalType ? logicalType
    : typeof preview === 'string' && preview ? preview : null;
  if (declared === 'structure') return 'molecular_structure';
  if (declared && ['table', 'plot', 'image', 'text', 'archive'].includes(declared)) return declared;
  if (declared && ['alignment', 'fasta', 'json'].includes(declared)) return 'text';
  if (declared === 'model' || declared === null) return 'download_only';
  return 'unknown';
}

async function digest(file: File): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Name the first few differing paths and count the rest. */
function describe(paths: readonly string[]): string {
  return paths.length > NAMED ? `${paths.slice(0, NAMED).join(', ')} (+${paths.length - NAMED})` : paths.join(', ');
}

export interface LocalFolderSelection {
  readonly files: readonly File[];
  readonly label: string;
}

/**
 * Open one extracted result folder.
 *
 * The folder is refused when any declared file is absent, differs in length, or (within the hash
 * budget) differs in content, because such a folder would be presented as a result it is not.
 */
export async function openLocalResult({ files, label }: LocalFolderSelection): Promise<LocalResultSource> {
  const found = findRoot([...files]);
  const raw = await readManifest(found.manifest);
  if (raw.schema_version !== 3 || !Array.isArray(raw.artifacts)) throw new Error(t('results.local.manifestInvalid'));
  const byPath = new Map<string, File>();
  for (const file of files) {
    const path = relativePath(file, found.root);
    if (!path) continue;
    // Two entries under one path make the archive's own identity ambiguous.
    if (byPath.has(path)) throw new Error(t('results.local.ambiguousPath', { path }));
    byPath.set(path, file);
  }
  const declared = raw.artifacts as Array<Record<string, unknown>>;
  const logicalRaw = (raw.result as { files?: unknown } | undefined)?.files;
  const logicalFiles = (logicalRaw && typeof logicalRaw === 'object' ? logicalRaw : {}) as Record<string, Array<Record<string, unknown>>>;
  const unsafe = [...declared, ...Object.values(logicalFiles).flat()].map((record) => record.path).filter((path) => !safePath(path));
  if (unsafe.length) throw new Error(t('results.local.unsafePath', { path: describe(unsafe.map(String)) }));

  // A logical file declares its own size and digest, and a view may reach it by that path even
  // when the artifact list does not name it. Verify the union, so every path a renderer can be
  // handed a handle to is a path this folder was checked against.
  const declaredByPath = new Map<string, Array<Record<string, unknown>>>();
  for (const record of [...declared, ...Object.values(logicalFiles).flat()]) {
    const path = String(record.path);
    declaredByPath.set(path, [...(declaredByPath.get(path) ?? []), record]);
  }

  const missing: string[] = []; const resized: string[] = []; const changed: string[] = []; const unchecked: string[] = [];
  const hashAvailable = typeof crypto?.subtle?.digest === 'function';
  let hashed = 0;
  for (const [path, records] of declaredByPath) {
    const file = byPath.get(path);
    if (!file) { missing.push(path); continue; }
    // An artifact and a logical file may both name one path. Both are the folder's declaration
    // of that file, so a file that fits only one of them is not the file either describes.
    if (records.some((record) => file.size !== Number(record.size))) { resized.push(path); continue; }
    if (!hashAvailable || file.size > HASH_MAX_BYTES) { unchecked.push(path); continue; }
    try {
      const actual = await digest(file);
      if (records.every((record) => String(record.sha256).toLowerCase() === actual)) hashed += 1;
      else changed.push(path);
    } catch { unchecked.push(path); }
  }
  if (missing.length) throw new Error(t('results.local.filesMissing', { paths: describe(missing) }));
  if (resized.length) throw new Error(t('results.local.filesChanged', { paths: describe(resized) }));
  if (changed.length) throw new Error(t('results.local.filesChanged', { paths: describe(changed) }));

  // One object URL per declared path: a handle to the reader's own file, never a copy, and the
  // only way a view or a structure viewer reaches a local artifact.
  const urls = new Map<string, string>();
  const url = (path: string): string => {
    const created = urls.get(path) ?? URL.createObjectURL(byPath.get(path)!);
    urls.set(path, created);
    return created;
  };
  const logicalProjection: Record<string, Array<Record<string, unknown>>> = {};
  for (const [id, entries] of Object.entries(logicalFiles)) {
    logicalProjection[id] = entries.map((entry) => ({
      ...entry,
      id,
      name: String(entry.path).split('/').pop() || String(entry.path),
      viewer: entry.logical_type || entry.preview || 'download',
      preview: entry.logical_type || entry.preview || null,
      capability: projectedCapability(entry.preview, entry.logical_type),
      url: url(String(entry.path)),
    }));
  }
  const storyboard = raw.storyboard && typeof raw.storyboard === 'object'
    ? String((raw.storyboard as { identifier?: unknown }).identifier || '') || null : null;
  // The archived Storyboard is reported by identifier and never loaded: its entrypoint is code
  // from the folder, and a folder is bytes, not an installer.
  // An archive records why the output check was not assessed only by leaving it unassessed, which
  // the Server writes exactly when the run itself failed. The folder can therefore state that
  // outcome, rather than presenting a failed run as a finished one.
  const outputState = (raw.output_check as { state?: unknown } | undefined)?.state;
  const parsed = parseResultManifest({
    ...raw,
    task_id: LOCAL_TASK_ID,
    status: outputState === 'not_assessed' ? 'failed' : 'finished',
    terminal: true,
    error: null,
    outcome: raw.outcome ?? null,
    archive: { ready: false, request_url: '', download_url: null },
    artifacts: declared.map((artifact) => ({ ...artifact, url: url(String(artifact.path)) })),
    result: { files: logicalProjection },
    storyboard: null,
  }) as ResultManifest;

  let closed = false;
  return {
    taskId: LOCAL_TASK_ID,
    label,
    manifest: parsed,
    verification: { present: declaredByPath.size, hashed, unchecked },
    storyboard,
    sourceTaskId: typeof raw.task_id === 'string' && raw.task_id && raw.task_id !== LOCAL_TASK_ID ? raw.task_id : null,
    file: (path) => byPath.get(path) || null,
    url,
    async readUtf8(path, maxBytes) {
      const file = byPath.get(path);
      if (!file) throw new Error(t('results.local.fileMissing', { path }));
      if (file.size > maxBytes) throw new Error(t('results.local.fileTooLarge', { path }));
      try { return UTF8.decode(await file.arrayBuffer()); }
      catch { throw new Error(t('results.local.fileNotUtf8', { path })); }
    },
    close(): void {
      if (closed) return; closed = true;
      for (const created of urls.values()) URL.revokeObjectURL(created);
      urls.clear();
    },
  };
}
