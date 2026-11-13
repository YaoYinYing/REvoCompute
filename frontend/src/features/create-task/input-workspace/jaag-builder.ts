/*
 * Copyright (c) 2026 The REvoDesign Developers.
 * Distributed under the terms of the GNU General Public License v3.0.
 * SPDX-License-Identifier: GPL-3.0-only
 */

/*
 * JAAG System YAML builder for the create-task workspace.
 *
 * The serializer is the pinned JAAG core (Apache-2.0), materialized at build
 * time by scripts/fetch-jaag-core.mjs. This module is the REvoCompute-owned
 * adapter: it collects a molecular model, validates it with JAAGCore.build, and
 * binds the generated YAML to a declared input role. A plain YAML upload stays
 * a first-class path through the files capability; the builder never changes
 * the server's role validation or the Task snapshot authority.
 */

import '../../../../vendor/jaag-core.global.js';
import type { WorkspaceContext, WorkspacePlugin, WorkspacePluginInstance } from './plugin-contract';
import { element } from './utils';

interface JaagResult {
  data: unknown;
  errors: string[];
  warnings: string[];
}

interface JaagCore {
  TARGETS: Record<string, { outputFormat?: string }>;
  build(model: Record<string, unknown>, target: string): JaagResult;
}

interface EntityRow {
  root: HTMLElement;
  type: HTMLSelectElement;
  chainIds: HTMLInputElement;
  sequence: HTMLTextAreaElement;
  ligand: HTMLInputElement;
  ligandSource: HTMLSelectElement;
  modifications: HTMLInputElement;
  sequenceField: HTMLElement;
  ligandSourceField: HTMLElement;
  ligandField: HTMLElement;
  modificationsField: HTMLElement;
}

const ENTITY_TYPES = ['protein', 'dna', 'rna', 'ligand'] as const;

//: CCD identifiers and SMILES overlap syntactically (`CCO`, `c1ccccc1`), so the
//: representation is an explicit choice rather than an inference from the text.
const LIGAND_SOURCES = ['ccd', 'smiles'] as const;

function core(): JaagCore {
  const loaded = (globalThis as unknown as Record<string, unknown>).JAAGCore as JaagCore | undefined;
  if (!loaded || typeof loaded.build !== 'function') {
    throw new Error('JAAG core is unavailable; run npm run jaag:fetch');
  }
  return loaded;
}

function labelled(control: HTMLElement, text: string): HTMLElement {
  const wrap = element('div', 'builder-field');
  wrap.append(element('label', 'param-label', text), control);
  return wrap;
}

function select(options: readonly string[], selected: string): HTMLSelectElement {
  const control = element('select', 'text-input');
  options.forEach(value => {
    const option = element('option', '', value);
    option.value = value;
    option.selected = value === selected;
    control.append(option);
  });
  control.value = selected;
  return control;
}

function parseModifications(raw: string): { modifications: Array<{ ccdCode: string; position: number }>; errors: string[] } {
  const modifications: Array<{ ccdCode: string; position: number }> = [];
  const errors: string[] = [];
  raw.split(',').map(item => item.trim()).filter(Boolean).forEach(item => {
    const [position, ccdCode] = item.split(':');
    const parsed = Number(position);
    if (!Number.isInteger(parsed) || parsed < 1 || !ccdCode?.trim()) {
      errors.push(`Invalid modification "${item}" — expected position:CCD (for example 1:MSE)`);
      return;
    }
    modifications.push({ ccdCode: ccdCode.trim(), position: parsed });
  });
  return { modifications, errors };
}

function parseBonds(raw: string): { bonds: Array<{ left: BondEndpoint; right: BondEndpoint }>; errors: string[] } {
  const bonds: Array<{ left: BondEndpoint; right: BondEndpoint }> = [];
  const errors: string[] = [];
  const endpoint = (text: string): BondEndpoint | null => {
    const [chainId, position, atom] = text.split(':');
    const parsed = Number(position);
    if (!chainId?.trim() || !Number.isInteger(parsed) || parsed < 1 || !atom?.trim()) return null;
    return { chainId: chainId.trim(), position: parsed, atom: atom.trim() };
  };
  raw.split(/\n/).map(line => line.trim()).filter(Boolean).forEach(line => {
    const halves = line.split(/\s+/);
    const left = halves.length === 2 ? endpoint(halves[0]!) : null;
    const right = halves.length === 2 ? endpoint(halves[1]!) : null;
    if (!left || !right) {
      errors.push(`Invalid covalent bond "${line}" — expected CHAIN:POS:ATOM CHAIN:POS:ATOM`);
      return;
    }
    bonds.push({ left, right });
  });
  return { bonds, errors };
}

interface BondEndpoint {
  chainId: string;
  position: number;
  atom: string;
}

function fileFor(target: string, data: unknown): File {
  const outputFormat = core().TARGETS[target]?.outputFormat;
  const extension = outputFormat === 'yaml' ? 'yaml' : outputFormat === 'fasta' ? 'fasta' : 'json';
  const type = extension === 'json' ? 'application/json' : 'text/plain';
  const rendered = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  return new File([rendered.endsWith('\n') ? rendered : `${rendered}\n`], `jaag-${target}.${extension}`, { type });
}

const jaagBuilder: WorkspacePlugin = {
  id: 'jaag-builder',
  mount(target, definition, context, _services): WorkspacePluginInstance {
    const options = definition.options as { role?: unknown; target?: unknown };
    const role = typeof options.role === 'string' ? options.role : 'system';
    const dialect = typeof options.target === 'string' ? options.target : 'bioemu2';
    const roleExists = context.form.inputs.some(input => input.id === role);

    const details = element('details', 'ct-jaag-builder');
    details.append(element('summary', '', 'Build System YAML with JAAG'));
    details.append(element(
      'p',
      'ct-help',
      'The builder writes the generated System YAML to the declared input role. '
      + 'A YAML uploaded above is equally valid; generating here replaces that upload.',
    ));

    const entityList = element('div', 'builder-entities');
    const rows: EntityRow[] = [];
    const bonds = element('textarea', 'sequence-input');
    bonds.placeholder = 'one bond per line: A:2:ND2 G:1:C1';
    bonds.value = '';
    const error = element('p', 'param-error');
    error.hidden = true;
    const status = element('p', 'muted');
    const generate = element('button', 'btn btn-soft', 'Generate System YAML');
    generate.type = 'button';
    const clear = element('button', 'btn btn-soft', 'Clear builder output');
    clear.type = 'button';
    const add = element('button', 'btn btn-soft', 'Add entity');
    add.type = 'button';

    let engaged = false;
    let generated: File | null = null;
    let errors: string[] = [];
    let refreshing = false;
    let destroyed = false;

    const ownsRole = (): boolean => {
      const files = context.roleFiles(role);
      return generated !== null && files.length === 1 && files[0] === generated;
    };

    //: ``builder`` is the generated YAML; ``external`` is any file another
    //: capability bound; ``idle`` is an empty role. The attribute lets the form
    //: and its tests read the ownership state without parsing status copy.
    const setOwnership = (state: 'idle' | 'builder' | 'external'): void => {
      details.dataset.jaagOwnership = state;
    };
    setOwnership(context.roleFiles(role).length ? 'external' : 'idle');

    const clearOwnOutput = (notify = true): void => {
      if (!ownsRole()) return;
      context.setRoleFiles(role, []);
      generated = null;
      setOwnership('idle');
      if (notify) context.filesChanged();
    };

    const collect = (): { model: Record<string, unknown>; parseErrors: string[] } => {
      const parseErrors: string[] = [];
      const entities = rows.map((row, index) => {
        const type = row.type.value;
        const chainIds = row.chainIds.value.split(',').map(value => value.trim()).filter(Boolean);
        const resolvedChains = chainIds.length ? chainIds : [type === 'ligand' ? 'L' : 'A'];
        if (type === 'ligand') {
          const ligandText = row.ligand.value.trim();
          const ligand = row.ligandSource.value === 'smiles'
            ? { source: 'smiles', smiles: ligandText }
            : { source: 'ccd', ccdCodes: ligandText.split(',').map(code => code.trim()).filter(Boolean) };
          return { type, chainIds: resolvedChains, ligand };
        }
        const entity: Record<string, unknown> = {
          type,
          chainIds: resolvedChains,
          sequence: row.sequence.value.trim(),
        };
        const parsed = parseModifications(row.modifications.value);
        parseErrors.push(...parsed.errors.map(message => `Entity ${index + 1}: ${message}`));
        if (parsed.modifications.length) entity.modifications = parsed.modifications;
        return entity;
      });
      const parsedBonds = parseBonds(bonds.value);
      parseErrors.push(...parsedBonds.errors);
      const model: Record<string, unknown> = { name: 'BioEmu2 system', seeds: [1], entities };
      if (parsedBonds.bonds.length) model.bonds = parsedBonds.bonds;
      return { model, parseErrors };
    };

    const regenerate = (): void => {
      const { model, parseErrors } = collect();
      const result = core().build(model, dialect);
      errors = [...parseErrors, ...result.errors];
      if (!errors.length && result.data != null) {
        generated = fileFor(dialect, result.data);
        context.setRoleFiles(role, [generated]);
        setOwnership('builder');
        status.textContent = `System YAML ready: ${rows.length} entities.`;
        context.filesChanged();
      } else {
        clearOwnOutput();
        status.textContent = 'System YAML is not ready.';
      }
    };

    const refresh = (edited = false): void => {
      // A host refresh (``filesChanged``) runs for every capability and must not
      // write the role: only a builder edit or explicit generation may. If
      // another capability replaced the generated file, the builder relinquishes
      // ownership and never regenerates over that upload.
      if (refreshing || destroyed) return;
      refreshing = true;
      try {
        errors = [];
        error.hidden = true;
        if (!roleExists) {
          errors = [`The builder cannot bind to unknown input role "${role}".`];
        } else if (edited) {
          engaged = true;
          regenerate();
        } else if (!ownsRole()) {
          // A host refresh that is not a builder edit never writes the role. If
          // the generated file is gone, another capability replaced or removed
          // it: relinquish ownership instead of regenerating over that input.
          engaged = false;
          generated = null;
          const bound = context.roleFiles(role).length > 0;
          setOwnership(bound ? 'external' : 'idle');
          status.textContent = bound
            ? 'The system role now holds a YAML from another source; edit the builder to generate a replacement.'
            : 'Fill the entities, then generate the System YAML.';
        }
        if (errors.length) {
          error.textContent = errors.join('; ');
          error.hidden = false;
        }
      } finally {
        refreshing = false;
      }
    };

    const addEntity = (initial: { type: string; chainIds: string }): void => {
      const root = element('div', 'builder-entity');
      const type = select(ENTITY_TYPES, initial.type);
      const chainIds = element('input', 'text-input');
      chainIds.type = 'text';
      chainIds.placeholder = 'chain IDs, comma separated';
      chainIds.value = initial.chainIds;
      const sequence = element('textarea', 'sequence-input');
      sequence.placeholder = 'sequence';
      sequence.value = '';
      const ligand = element('input', 'text-input');
      ligand.type = 'text';
      ligand.placeholder = 'NAG or A1L3H for CCD; CCO for SMILES';
      ligand.value = '';
      const ligandSource = select(LIGAND_SOURCES, 'ccd');
      const modifications = element('input', 'text-input');
      modifications.type = 'text';
      modifications.placeholder = 'modifications: position:CCD';
      modifications.value = '';
      const remove = element('button', 'btn btn-soft', 'Remove');
      remove.type = 'button';
      const sequenceField = labelled(sequence, 'Sequence');
      const ligandSourceField = labelled(ligandSource, 'Ligand representation');
      const ligandField = labelled(ligand, 'Ligand value');
      const modificationsField = labelled(modifications, 'Modifications');
      root.append(
        labelled(type, 'Entity type'), labelled(chainIds, 'Chain IDs'),
        sequenceField, ligandSourceField, ligandField, modificationsField, remove,
      );
      entityList.append(root);
      const row: EntityRow = {
        root, type, chainIds, sequence, ligand, ligandSource, modifications,
        sequenceField, ligandSourceField, ligandField, modificationsField,
      };
      rows.push(row);

      const sync = (): void => {
        const isLigand = type.value === 'ligand';
        sequenceField.hidden = isLigand;
        ligandSourceField.hidden = !isLigand;
        ligandField.hidden = !isLigand;
        modificationsField.hidden = isLigand;
      };
      const edited = (): void => { engaged = true; refresh(true); };
      [type, chainIds, sequence, ligand, ligandSource, modifications].forEach(control => {
        control.addEventListener('input', edited);
        control.addEventListener('change', edited);
      });
      type.addEventListener('change', sync);
      remove.addEventListener('click', () => {
        rows.splice(rows.indexOf(row), 1);
        root.remove();
        engaged = true;
        refresh(true);
      });
      sync();
    };

    target.append(details);
    details.append(entityList, add, element('h4', '', 'Covalent bonds'), labelled(bonds, 'Bonded atom pairs'), generate, clear, status, error);
    bonds.addEventListener('input', () => { engaged = true; refresh(true); });
    bonds.addEventListener('change', () => { engaged = true; refresh(true); });
    generate.addEventListener('click', () => { engaged = true; refresh(true); });
    add.addEventListener('click', () => addEntity({ type: 'protein', chainIds: 'A' }));
    clear.addEventListener('click', () => {
      engaged = false;
      errors = [];
      clearOwnOutput();
      error.hidden = true;
      status.textContent = 'Fill the entities, then generate the System YAML.';
    });

    addEntity({ type: 'protein', chainIds: 'A' });
    status.textContent = 'Fill the entities, then generate the System YAML.';

    return {
      // Every host refresh is a non-edit; only the builder's own handlers call
      // the local ``refresh(true)``. The host may pass preset options that only
      // the structure viewer consumes.
      refresh: () => refresh(false),
      readValue: () => ({ active: engaged, target: dialect, entities: rows.length }),
      summarize: () => (engaged && generated ? { label: 'System YAML', value: `JAAG builder · ${rows.length} entities` } : null),
      validate: () => (engaged || !roleExists ? errors : []),
      destroy: () => { destroyed = true; clearOwnOutput(false); },
    };
  },
};

export { jaagBuilder };
