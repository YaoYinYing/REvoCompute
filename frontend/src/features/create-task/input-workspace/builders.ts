/*
 * Copyright (c) 2026 The REvoDesign Developers.
 * Distributed under the terms of the GNU General Public License v3.0.
 * SPDX-License-Identifier: GPL-3.0-only
 */

/*
 * Thin adapters onto upstream editors.  An adapter owns only transport and
 * provider-native capture: it never interprets scientific semantics, never
 * decides which Task input role a result belongs to, and never submits.
 */

import { t } from '../../../app/i18n';

export interface BuilderOutput {
  role: 'input';
  name: string;
  mime: string;
  bytes: Uint8Array<ArrayBuffer>;
  sha256: string;
}

export interface BuilderDependency {
  id: string;
  kind: string;
  name: string;
  size: number;
  sha256: string;
}

export interface BuilderMaterialized {
  snapshot: unknown;
  revision: number;
  output: BuilderOutput;
  dependencies: BuilderDependency[];
  errors: string[];
  warnings: string[];
}

export interface BuilderAdapterInstance {
  /** Capture the native state and one target-native output. */
  materialize(): Promise<BuilderMaterialized>;
  /** Reconstruct the editor from recorded native state. */
  restore(state: unknown): Promise<void>;
  /** Invalidate host-owned output when the editor changes. */
  subscribe(listener: () => void): () => void;
  destroy(): void;
}

export interface BuilderAdapter {
  mount(
    container: HTMLElement,
    options: { target: string; editorPath?: string; adapterPath?: string },
  ): Promise<BuilderAdapterInstance>;
}

type ChangeListener = () => void;

export class BuilderUnavailableError extends Error {}
export class BuilderDependencyUnsupported extends Error {}
export class BuilderChangedDuringCapture extends Error {}

export async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

/** An adapter-owned byte view backed by a fresh ArrayBuffer. */
function copyBytes(value: Uint8Array): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(value.byteLength);
  bytes.set(value);
  return bytes;
}

function safeName(name: string, fallback: string): string {
  const base = String(name || '').split(/[\\/]/).pop()!.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '');
  return base && base !== '.' && base !== '..' ? base : fallback;
}

/** The upstream BioNuTA adapter is served from the pinned workbench tree. */
interface BioNuTAModule {
  mount(
    container: Element,
    options: { target: string; editorURL?: string | URL },
  ): Promise<{
    materialize(): Promise<{
      snapshot: unknown;
      revision: number;
      output: { role: 'input'; name: string; mime: string; bytes: Uint8Array; sha256: string };
      dependencies: Array<{ id: string; kind: string; name: string; size: number; sha256: string }>;
      diagnostics: { errors: string[]; warnings: string[] };
    }>;
    restore(snapshot: unknown): Promise<void>;
    subscribe(listener: (event: { revision: number }) => void): () => void;
    listDependencies(): Promise<Array<{ id: string; kind: string; slot: unknown[] }>>;
    destroy(): void;
  }>;
}

class BioNuTAAdapter implements BuilderAdapterInstance {
  private readonly listeners = new Set<ChangeListener>();
  private readonly unsubscribe: () => void;

  private constructor(private readonly builder: Awaited<ReturnType<BioNuTAModule['mount']>>) {
    this.unsubscribe = builder.subscribe(() => this.listeners.forEach(listener => listener()));
  }

  static async mount(
    container: HTMLElement,
    options: { target: string; editorPath?: string; adapterPath?: string },
  ): Promise<BioNuTAAdapter> {
    const adapterUrl = options.adapterPath || '';
    const allowed = new URL(adapterUrl, window.location.origin);
    if (allowed.origin !== window.location.origin || !allowed.pathname.startsWith('/compute/bionuta/')) {
      throw new BuilderUnavailableError('The BioNuTA adapter is not served from this application.');
    }
    let module: BioNuTAModule;
    try {
      module = await import(/* @vite-ignore */ allowed.href) as BioNuTAModule;
    } catch {
      throw new BuilderUnavailableError('The BioNuTA workbench could not be loaded.');
    }
    const editorURL = options.editorPath ? new URL(options.editorPath, window.location.origin) : undefined;
    if (editorURL && (editorURL.origin !== window.location.origin || editorURL.search || editorURL.hash)) {
      throw new BuilderUnavailableError('The BioNuTA editor is not served from this application.');
    }
    const builder = await module.mount(container, { target: options.target, editorURL });
    return new BioNuTAAdapter(builder);
  }

  async materialize(): Promise<BuilderMaterialized> {
    // No current Task declares a role or Runner staging contract for builder
    // dependency bytes, so a dependency-bearing build is refused explicitly
    // instead of silently submitting a different system.
    if ((await this.builder.listDependencies()).length) {
      throw new BuilderDependencyUnsupported(t('ct.builder.dependencies'));
    }
    const result = await this.builder.materialize();
    if (result.diagnostics.errors.length) {
      throw new Error(result.diagnostics.errors.join('; '));
    }
    return {
      snapshot: result.snapshot,
      revision: result.revision,
      output: {
        role: 'input',
        name: safeName(result.output.name, 'input.json'),
        mime: result.output.mime || 'application/octet-stream',
        bytes: copyBytes(result.output.bytes),
        sha256: result.output.sha256,
      },
      dependencies: [],
      errors: result.diagnostics.errors,
      warnings: result.diagnostics.warnings,
    };
  }

  restore(state: unknown): Promise<void> {
    return this.builder.restore(state);
  }

  subscribe(listener: ChangeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  destroy(): void {
    this.unsubscribe();
    this.listeners.clear();
    this.builder.destroy();
  }
}

/** The optional AtomWorks Studio service, reached only through the gateway. */
class AtomWorksAdapter implements BuilderAdapterInstance {
  private sessionId: string | null = null;
  private revision = 0;
  private frame: HTMLIFrameElement | null = null;
  private readonly onMessage = (event: MessageEvent): void => {
    if (!this.frame || event.source !== this.frame.contentWindow) return;
    const payload = event.data as { source?: unknown; type?: unknown; session_id?: unknown } | null;
    // The pinned editor emits `changed` from `HOST_MESSAGE_SOURCE`; `selection`
    // is not a document edit.  Only this adapter's own session may invalidate.
    if (
      payload && payload.source === 'atomworks-annotation-studio'
      && payload.type === 'changed' && payload.session_id === this.sessionId
    ) {
      for (const listener of this.listeners) listener();
    }
  };
  private readonly listeners = new Set<ChangeListener>();

  private constructor(private readonly container: HTMLElement) {}

  static async mount(container: HTMLElement): Promise<AtomWorksAdapter> {
    const adapter = new AtomWorksAdapter(container);
    window.addEventListener('message', adapter.onMessage);
    await adapter.renderPicker();
    return adapter;
  }

  private async renderPicker(): Promise<void> {
    const section = document.createElement('div');
    section.className = 'ct-atomworks';
    const label = document.createElement('label');
    label.className = 'ct-label';
    label.textContent = 'Starting CIF';
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.cif,.mmcif';
    label.append(input);
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'btn btn-soft';
    open.textContent = 'Open AtomWorks Studio';
    const status = document.createElement('p');
    status.className = 'muted';
    const frameHost = document.createElement('div');
    frameHost.className = 'ct-atomworks-frame';
    section.append(label, open, status, frameHost);
    this.container.append(section);
    open.addEventListener('click', () => {
      const file = input.files?.[0];
      if (!file) {
        status.textContent = 'Choose a starting CIF first.';
        return;
      }
      open.disabled = true;
      status.textContent = 'Opening the editor…';
      void this.open(file, frameHost, status).catch(error => {
        open.disabled = false;
        status.textContent = error instanceof Error ? error.message : String(error);
      });
    });
  }

  private async open(file: File | string, host: HTMLElement, status: HTMLElement): Promise<void> {
    await this.closeSession();
    host.replaceChildren();
    const data = new FormData();
    data.append('file', typeof file === 'string'
      ? new File([file], 'restored.cif', { type: 'chemical/x-mmcif' })
      : file);
    data.append('parse_preset', 'minimal');
    const response = await fetch('/api/sessions', { method: 'POST', body: data, credentials: 'same-origin' });
    if (!response.ok) throw new Error(`AtomWorks Studio refused the CIF (HTTP ${response.status}).`);
    const created = await response.json() as { session_id?: unknown; editor_path?: unknown };
    if (typeof created.session_id !== 'string' || typeof created.editor_path !== 'string') {
      throw new Error('AtomWorks Studio returned an invalid session.');
    }
    this.sessionId = created.session_id;
    this.revision = 0;
    const frame = document.createElement('iframe');
    frame.title = 'AtomWorks Studio annotated CIF editor';
    // The editor only posts `changed`/`ready` to its parent when told the
    // trusted parent origin.  Without it, edits would not invalidate a capture.
    const editorUrl = new URL(created.editor_path, window.location.origin);
    editorUrl.searchParams.set('parent_origin', window.location.origin);
    frame.src = `${editorUrl.pathname}${editorUrl.search}`;
    frame.hidden = false;
    frame.style.width = '100%';
    frame.style.minHeight = '640px';
    frame.style.border = '0';
    frame.addEventListener('load', () => { status.textContent = 'Editor ready. Apply captures the current annotated snapshot.'; });
    host.append(frame);
    this.frame = frame;
  }

  private async closeSession(): Promise<void> {
    if (this.sessionId) {
      const session = this.sessionId;
      this.sessionId = null;
      await fetch(`/api/sessions/${encodeURIComponent(session)}`, {
        method: 'DELETE', credentials: 'same-origin',
      }).catch(() => undefined);
    }
    this.frame?.remove();
    this.frame = null;
  }

  async materialize(): Promise<BuilderMaterialized> {
    if (!this.sessionId) throw new Error('Open an AtomWorks Studio session before applying.');
    const response = await fetch(`/api/sessions/${encodeURIComponent(this.sessionId)}/export`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (response.status === 404) {
      await this.closeSession();
      throw new Error('The editor session expired. Re-open the structure and apply again.');
    }
    if (!response.ok) throw new Error(`AtomWorks Studio export failed (HTTP ${response.status}).`);
    const exported = await response.json() as {
      cif?: unknown; name?: unknown; revision?: unknown;
      issues?: Array<{ severity?: string; message?: string }>;
    };
    if (typeof exported.cif !== 'string' || !exported.cif.trim()) {
      throw new Error('AtomWorks Studio exported no annotated CIF.');
    }
    const bytes = new TextEncoder().encode(exported.cif);
    const errors = (exported.issues || []).filter(issue => issue.severity === 'error').map(issue => issue.message || 'Invalid annotated CIF');
    const warnings = (exported.issues || []).filter(issue => issue.severity !== 'error').map(issue => issue.message || 'Validation notice');
    if (errors.length) throw new Error(errors.join('; '));
    const name = safeName(`${String(exported.name || 'condition')}_annotated.cif`, 'condition_annotated.cif');
    this.revision = typeof exported.revision === 'number' ? exported.revision : this.revision;
    return {
      // Studio's durable native state is the annotated CIF itself.  Keeping it
      // as the opaque state makes a clone restore a new session from exactly
      // the bytes the source accepted, rather than from a live session ID.
      snapshot: { format: 'annotated-cif', cif: exported.cif },
      revision: this.revision,
      output: { role: 'input', name, mime: 'chemical/x-mmcif', bytes, sha256: await sha256Hex(bytes) },
      dependencies: [],
      errors,
      warnings,
    };
  }

  async restore(state: unknown): Promise<void> {
    const cif = (state as { cif?: unknown } | null)?.cif;
    if (typeof cif !== 'string' || !cif.trim()) throw new Error('The recorded AtomWorks state carries no annotated CIF.');
    const host = this.container.querySelector<HTMLElement>('.ct-atomworks-frame');
    const status = this.container.querySelector<HTMLElement>('.muted');
    if (!host || !status) throw new Error('The AtomWorks editor is unavailable.');
    await this.open(cif, host, status);
  }

  subscribe(listener: ChangeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  destroy(): void {
    window.removeEventListener('message', this.onMessage);
    this.listeners.clear();
    void this.closeSession();
  }
}

export const builderAdapters: Record<string, BuilderAdapter> = {
  bionuta: { mount: (container, options) => BioNuTAAdapter.mount(container, options) },
  atomworks: { mount: container => AtomWorksAdapter.mount(container) },
};
