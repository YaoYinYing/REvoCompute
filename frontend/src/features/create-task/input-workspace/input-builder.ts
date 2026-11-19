/*
 * Copyright (c) 2026 The REvoDesign Developers.
 * Distributed under the terms of the GNU General Public License v3.0.
 * SPDX-License-Identifier: GPL-3.0-only
 */

/*
 * Generic Input Builder capability.
 *
 * Core owns the role binding, the bounded envelope, digest verification and the
 * ordinary submission path.  A registered builder adapter owns only its
 * scientific authoring UI and native snapshot.  Uploading a prepared file
 * remains a first-class path and is never replaced by this plugin.
 */

import type {
  WorkspaceAuthoringEntry,
  WorkspaceContext,
  WorkspacePlugin,
  WorkspacePluginInstance,
} from './plugin-contract';
import type { WorkspaceBuilder } from '../types';
import { t } from '../../../app/i18n';
import { element } from './utils';
import {
  BuilderChangedDuringCapture,
  BuilderDependencyUnsupported,
  BuilderUnavailableError,
  builderAdapters,
  sha256Hex,
  type BuilderAdapterInstance,
  type BuilderMaterialized,
} from './builders';

type Mode = 'upload' | 'build';

//: Kept below the 1 MiB workspace document cap so the explicit
//: "state too large" diagnostic is reachable before the generic limit.
const MAX_AUTHORING_STATE_BYTES = 512 * 1024;

interface EnvelopeOutput {
  logical: 'input';
  role: string;
  name: string;
  size: number;
  sha256: string;
}

function envelopeFor(
  builder: WorkspaceBuilder,
  target: string,
  output: BuilderMaterialized,
  binding: EnvelopeOutput,
): Record<string, unknown> {
  return {
    version: 1,
    builder: builder.id,
    builder_version: builder.builder_version,
    state_schema_version: builder.state_schema_version,
    target,
    revision: output.revision,
    state: output.snapshot,
    dependencies: [],
    outputs: [binding],
  };
}

const inputBuilder: WorkspacePlugin = {
  id: 'input-builder',
  mount(target, definition, context): WorkspacePluginInstance {
    const options = definition.options as {
      builder?: unknown; target?: unknown; outputs?: unknown; exclusive?: unknown;
    };
    const builderId = typeof options.builder === 'string' ? options.builder : '';
    const builder = context.form.input_workspace.builders?.find(item => item.id === builderId);
    const dialect = typeof options.target === 'string' ? options.target : '';
    const outputs = options.outputs && typeof options.outputs === 'object' ? options.outputs as Record<string, unknown> : {};
    const role = typeof outputs.input === 'string' ? outputs.input : '';
    const exclusive = options.exclusive === true;
    const roleExists = context.form.inputs.some(input => input.id === role);
    const otherRoles = context.form.inputs.filter(input => input.id !== role);

    const root = element('div', 'ct-input-builder');
    const heading = element('p', 'ct-help', '');
    const modes = element('div', 'ct-builder-modes');
    const uploadMode = element('button', 'btn btn-soft', t('ct.builder.upload'));
    const buildMode = element('button', 'btn btn-soft', t('ct.builder.build'));
    uploadMode.type = 'button'; buildMode.type = 'button';
    modes.append(uploadMode, buildMode);
    const editorHost = element('div', 'ct-builder-editor');
    editorHost.hidden = true;
    const status = element('p', 'muted');
    status.setAttribute('role', 'status');
    const error = element('p', 'param-error');
    error.setAttribute('role', 'alert');
    error.hidden = true;
    const actions = element('div', 'ct-actions');
    const apply = element('button', 'btn btn-soft', t('ct.builder.apply'));
    const clear = element('button', 'btn btn-soft', t('ct.builder.clear'));
    apply.type = 'button'; clear.type = 'button';
    actions.append(apply, clear);
    root.append(heading, modes, editorHost, actions, status, error);
    target.append(root);

    let mode: Mode = context.roleFiles(role).length ? 'upload' : 'build';
    let adapter: BuilderAdapterInstance | null = null;
    let unsubscribe: (() => void) | null = null;
    let opening: Promise<BuilderAdapterInstance | null> | null = null;
    let generated: File | null = null;
    let envelope: Record<string, unknown> | null = null;
    let epoch = 0;
    let pending = false;
    let destroyed = false;
    let restoreError: string | null = null;
    let lastWarnings: string[] = [];
    let changeToken = 0;

    const available = Boolean(builder?.available);
    const canBuild = Boolean(builder && roleExists && available && builder.adapter in builderAdapters);

    const ownsRole = (): boolean => {
      const files = context.roleFiles(role);
      return generated !== null && files.length === 1 && files[0] === generated;
    };

    const renderMode = (): void => {
      // A builder this deployment cannot serve is never presented as usable:
      // the role stays on the ordinary upload path.
      if (!canBuild) mode = 'upload';
      uploadMode.classList.toggle('active', mode === 'upload');
      buildMode.classList.toggle('active', mode === 'build');
      uploadMode.setAttribute('aria-pressed', String(mode === 'upload'));
      buildMode.setAttribute('aria-pressed', String(mode === 'build'));
      buildMode.disabled = !canBuild;
      editorHost.hidden = mode !== 'build';
      actions.hidden = mode !== 'build';
      root.dataset.builderMode = mode;
      root.dataset.builderOwnership = ownsRole() ? 'builder' : context.roleFiles(role).length ? 'external' : 'idle';
      if (!canBuild) {
        heading.textContent = roleExists
          ? t('ct.builder.unavailable')
          : t('ct.builder.roleInvalid', { role });
      } else if (mode === 'build') {
        heading.textContent = t('ct.builder.help');
      } else {
        heading.textContent = t('ct.builder.uploadHelp');
      }
      apply.disabled = pending || !canBuild;
      clear.disabled = pending;
    };

    const setError = (message: string | null): void => {
      error.textContent = message || '';
      error.hidden = !message;
    };

    const detachAdapter = (): void => {
      epoch += 1;
      unsubscribe?.(); unsubscribe = null;
      adapter?.destroy(); adapter = null;
      editorHost.replaceChildren();
      opening = null;
    };

    const clearOwnOutput = (notify = true): void => {
      if (!ownsRole()) return;
      epoch += 1;
      context.setRoleFiles(role, []);
      generated = null;
      envelope = null;
      if (notify) context.filesChanged();
    };

    const invalidate = (): void => {
      // An edit makes the applied bytes stale immediately, and any capture
      // already in flight no longer describes the document the reader sees.
      // Only the builder's own bound file is removed; an independent upload is
      // never touched.
      changeToken += 1;
      if (ownsRole()) {
        clearOwnOutput(false);
        generated = null;
        envelope = null;
      }
      status.textContent = t('ct.builder.changed');
      renderMode();
      context.changed();
    };

    const ensureAdapter = async (): Promise<BuilderAdapterInstance | null> => {
      if (!canBuild || !builder) return null;
      if (adapter) return adapter;
      if (opening) return opening;
      const current = epoch;
      let pendingMount!: Promise<BuilderAdapterInstance | null>;
      pendingMount = (async () => {
        const factory = builderAdapters[builder.adapter];
        if (!factory) throw new BuilderUnavailableError(t('ct.builder.unavailable'));
        status.textContent = t('ct.builder.opening');
        const mounted = await factory.mount(editorHost, {
          target: dialect,
          editorPath: builder.editor_path,
          adapterPath: builder.adapter_path,
        });
        // Switching back to Upload detaches the host while the mount may still
        // be running; that mount must not install itself afterwards.
        if (destroyed || current !== epoch) { mounted.destroy(); return null; }
        if (adapter) { mounted.destroy(); return adapter; }
        adapter = mounted;
        unsubscribe = mounted.subscribe(invalidate);
        status.textContent = t('ct.builder.ready');
        return mounted;
      })().catch(errorValue => {
        setError(errorValue instanceof Error ? errorValue.message : String(errorValue));
        status.textContent = '';
        return null;
      }).finally(() => {
        // Only the current mount may clear the slot: a superseded mount must
        // not let a newer in-flight mount be started twice.
        if (opening === pendingMount) opening = null;
      });
      opening = pendingMount;
      return pendingMount;
    };

    const bind = async (state: BuilderAdapterInstance, recorded: WorkspaceAuthoringEntry | null): Promise<void> => {
      const current = epoch;
      const token = changeToken;
      const captured = await state.materialize();
      if (captured.dependencies.length) {
        // No Task declares a role or staging layout for dependency bytes, so
        // the host refuses them rather than letting an adapter drop them.
        throw new BuilderDependencyUnsupported(t('ct.builder.dependencies'));
      }
      // Core persists the native state with the Task and bounds it; refuse an
      // oversized snapshot here, where the reader can still switch to Upload,
      // instead of failing only at submission.
      let stateBytes = 0;
      try {
        stateBytes = new TextEncoder().encode(JSON.stringify(captured.snapshot)).byteLength;
      } catch {
        throw new Error(t('ct.builder.stateUnavailable'));
      }
      if (stateBytes > MAX_AUTHORING_STATE_BYTES) throw new Error(t('ct.builder.stateTooLarge'));
      const digest = await sha256Hex(captured.output.bytes);
      if (!captured.output.sha256 || captured.output.sha256 !== digest) {
        throw new Error(t('ct.builder.digest'));
      }
      // Recheck ownership and the edit counter after every await: another
      // capability may have bound or removed the role while the provider was
      // working, and an edit means these bytes no longer match the editor.
      if (destroyed || current !== epoch) throw new Error(t('ct.builder.stale'));
      if (token !== changeToken) throw new BuilderChangedDuringCapture(t('ct.builder.stale'));
      const occupied = context.roleFiles(role).length > 0 && !ownsRole();
      if (occupied) throw new Error(t('ct.builder.occupied', { role }));
      if (!builder) throw new BuilderUnavailableError(t('ct.builder.unavailable'));
      const file = new File([captured.output.bytes], captured.output.name, { type: captured.output.mime });
      if (file.size !== captured.output.bytes.byteLength) throw new Error(t('ct.builder.digest'));
      generated = file;
      envelope = envelopeFor(builder, dialect, captured, {
        logical: 'input', role, name: file.name, size: file.size, sha256: digest,
      });
      context.setRoleFiles(role, [file]);
      lastWarnings = captured.warnings;
      restoreError = null;
      const recordedDigest = recorded?.outputs?.[0]?.sha256;
      if (recordedDigest && recordedDigest !== digest) {
        // A restore that re-materializes different bytes is a deliberate new
        // input, not the source's scientific document silently reused.
        status.textContent = t('ct.builder.restoreChanged', {
          before: recordedDigest.slice(0, 12), after: digest.slice(0, 12),
        });
        root.dataset.builderRestore = 'changed';
      } else {
        status.textContent = t('ct.builder.applied', { name: file.name, revision: captured.revision });
        root.dataset.builderRestore = recordedDigest ? 'verified' : 'applied';
      }
      root.dataset.builderOwnership = 'builder';
      setError(lastWarnings.length ? lastWarnings.join('; ') : null);
      renderMode();
      context.filesChanged();
    };

    const doApply = async (): Promise<void> => {
      if (pending) return;
      pending = true; renderMode(); setError(null);
      try {
        const state = await ensureAdapter();
        if (!state) return;
        await bind(state, null);
      } catch (errorValue) {
        if (errorValue instanceof BuilderDependencyUnsupported || errorValue instanceof BuilderUnavailableError) {
          setError(errorValue.message);
        } else {
          setError(errorValue instanceof Error ? errorValue.message : String(errorValue));
        }
        status.textContent = t('ct.builder.failed');
      } finally {
        pending = false; renderMode(); context.changed();
      }
    };

    uploadMode.addEventListener('click', () => {
      if (mode === 'upload') return;
      mode = 'upload';
      restoreError = null;
      clearOwnOutput();
      detachAdapter();
      status.textContent = t('ct.builder.uploadHelp');
      renderMode(); context.changed();
    });
    buildMode.addEventListener('click', () => {
      if (mode !== 'build') {
        mode = 'build';
        renderMode();
      }
      void ensureAdapter();
      context.changed();
    });
    apply.addEventListener('click', () => void doApply());
    clear.addEventListener('click', () => {
      clearOwnOutput();
      setError(null);
      restoreError = null;
      status.textContent = t('ct.builder.cleared');
      renderMode(); context.changed();
    });

    const render = (): void => {
      if (!ownsRole() && generated) {
        // Another capability replaced or removed the bound file. Relinquish
        // ownership rather than regenerate over that input.
        generated = null;
        envelope = null;
        root.dataset.builderOwnership = context.roleFiles(role).length ? 'external' : 'idle';
        status.textContent = context.roleFiles(role).length ? t('ct.builder.external') : '';
      }
      renderMode();
    };

    renderMode();
    if (mode === 'build') void ensureAdapter();

    return {
      readValue: () => envelope ?? undefined,
      summarize: () => (envelope
        ? { label: t('ct.builder.summary'), value: generated ? `${builderId} · ${generated.name}` : builderId }
        : null),
      validate: () => {
        const errors: string[] = [];
        if (!roleExists) return [t('ct.builder.roleInvalid', { role })];
        // A role already supplied by another capability or a plain upload is
        // the documented fallback: this editor must not keep the form blocked.
        // That includes a clone restore that could not mount its builder.
        if (mode === 'build' && !context.roleFiles(role).length) {
          if (restoreError) errors.push(restoreError);
          if (canBuild && !envelope) errors.push(t('ct.builder.applyRequired'));
        }
        if (exclusive && context.roleFiles(role).length) {
          const extra = otherRoles.filter(item => context.roleFiles(item.id).length);
          if (extra.length) errors.push(t('ct.builder.exclusive', { roles: extra.map(item => item.title).join(', ') }));
        }
        return errors;
      },
      refresh: () => render(),
      restoreAuthoring: async (entry, state) => {
        if (entry.builder !== builderId || entry.target !== dialect) {
          throw new Error(t('ct.builder.restoreRejected'));
        }
        mode = 'build';
        renderMode();
        restoreError = null;
        try {
          const instance = await ensureAdapter();
          if (!instance) throw new BuilderUnavailableError(t('ct.builder.unavailable'));
          await instance.restore(state);
          await bind(instance, entry);
          context.changed();
        } catch (errorValue) {
          const failure = errorValue instanceof Error ? errorValue.message : String(errorValue);
          restoreError = t('ct.builder.restoreFailed', { message: failure });
          status.textContent = restoreError;
          root.dataset.builderRestore = 'failed';
          context.changed();
          // The host and the draft must learn that this restore failed; a
          // resolved promise here would be reported as a successful clone.
          throw new Error(failure);
        }
      },
      destroy: () => {
        destroyed = true;
        generated = null;
        envelope = null;
        detachAdapter();
      },
    };
  },
};

export { inputBuilder };
