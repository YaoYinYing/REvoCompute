import { ArrowLeft, ArrowRight, BookOpen, Cpu, ExternalLink, Search, ShieldCheck, Zap } from 'lucide';
import { createIcons } from 'lucide';
import { getParameterSchema, getReadiness, getTaskCatalog, getTaskType, type ParameterDefinition, type TaskTypeDetail, type TaskTypeSummary } from '../../api/app-api';
import { metadataValue, safeExternalUrl } from '../../app/domain-vocabulary';
import { t } from '../../app/i18n';
import { guidedTour } from '../../app/guided-tour';
import './runners.css';
import { ApiError } from '../../app/session';
import type { AppShell } from '../../app/shell';

function text(tag: keyof HTMLElementTagNameMap, value: string, className = ''): HTMLElement { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; }
// A request that failed for a reason the server did not author. The typed
// ApiError keeps a server-authored message worth showing (a 404 "Unknown task
// type" tells the reader their link is wrong); anything else — a thrown
// TypeError from a malformed body, a 503 — is described by frontend copy
// instead of leaking an engine-internal string into the fallback body.
function failureBody(error: unknown, key: 'runners.loadFailed' | 'runners.detail.loadFailed'): string {
  if (error instanceof ApiError && error.status === 404) return error.message;
  return t(key);
}

// A restricted policy's published terms: the server-projected notice title and
// summary, and the licence as a guarded external link. §11: this is server-owned
// policy vocabulary, so it is emitted verbatim and never routed through t().
function accessTerms(access: TaskTypeDetail['access']): HTMLElement | null {
  if (!access.restricted) return null;
  const noticeTitle = metadataValue(access.notice, 'title'), noticeSummary = metadataValue(access.notice, 'summary');
  const licenseUrl = safeExternalUrl(metadataValue(access.license, 'url')), licenseName = metadataValue(access.license, 'name');
  if (!noticeTitle && !noticeSummary && !licenseUrl) return null;
  const block = document.createElement('div'); block.className = 'access-terms';
  if (noticeTitle) block.append(text('p', noticeTitle, 'access-terms-title'));
  if (noticeSummary) block.append(text('p', noticeSummary, 'access-terms-summary'));
  if (licenseUrl) { const link = document.createElement('a'); link.href = licenseUrl; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = licenseName || licenseUrl; block.append(link); }
  return block;
}

function accessKey(task: TaskTypeSummary | TaskTypeDetail): string { if (!task.access.restricted) return 'runners.access.available'; if (task.access.granted) return 'runners.access.granted'; if (task.access.request_status === 'pending') return 'runners.access.pending'; return 'runners.access.restricted'; }
function accessLabel(task: TaskTypeSummary | TaskTypeDetail): string { return t(accessKey(task)); }
function createTaskLink(task: { name: string; access: { restricted: boolean; granted?: boolean; request_status?: string | null } }): HTMLAnchorElement { const link = document.createElement('a'); link.className = 'primary-button'; link.href = `/compute/create_task?task_type=${encodeURIComponent(task.name)}`; link.innerHTML = `<span>${t('runners.createTask')}</span><i data-lucide="arrow-right"></i>`; return link; }

export async function mountRunnerCatalog(root: HTMLElement): Promise<void> {
  root.replaceChildren(); root.className = 'app-outlet runners-page';
  const head = document.createElement('header'); head.className = 'page-heading'; head.innerHTML = `<div><h1>${t('runners.title')}</h1><p>${t('runners.subtitle')}</p></div>`;
  const readiness = document.createElement('div'); readiness.className = 'readiness-state'; readiness.textContent = t('runners.checking'); head.append(readiness);
  const toolbar = document.createElement('section'); toolbar.className = 'work-toolbar runner-toolbar'; toolbar.innerHTML = `<label class="search-control"><span>${t('catalog.searchMethods')}</span><span class="input-with-action"><i data-lucide="search"></i><input type="search" placeholder="${t('runners.searchPlaceholder')}"></span></label><label><span>${t('runners.category')}</span><select><option value="">${t('catalog.allCategories')}</option></select></label><fieldset class="layout-switch density-switch"><legend>${t('runners.density')}</legend><button type="button" data-density="comfortable" aria-pressed="true">${t('runners.comfortable')}</button><button type="button" data-density="compact" aria-pressed="false">${t('runners.compact')}</button></fieldset><p class="catalog-count" aria-live="polite"></p>`;
  const catalog = document.createElement('div'); catalog.className = 'runner-catalog'; catalog.dataset.density = 'comfortable'; const state = text('p', t('runners.loading'), 'empty-state'); catalog.append(state); root.append(head, toolbar, catalog);
  createIcons({ icons: { Search }, root });
  // An in-progress guided tour resumes on the surface it advanced to.
  guidedTour.resumeIfActive();
  try {
    const [payload, infrastructure] = await Promise.all([getTaskCatalog(), getReadiness().catch(() => null)]); state.remove();
    if (infrastructure) { readiness.textContent = infrastructure.status === 'READY' ? t('runners.ready') : t('runners.status', { status: infrastructure.status.toLowerCase() }); readiness.dataset.status = infrastructure.status; }
    // The server-owned category label is what the group heading and the option show, so search
    // has to match it. Indexed for matching only: never routed through t() and never displayed.
    const select = toolbar.querySelector('select')!, labelBySlug = new Map(payload.categories.map(category => [category.name, category.label])); payload.categories.forEach(category => { const option = document.createElement('option'); option.value = category.name; option.textContent = category.label; select.append(option); });
    // Density is a scan aid for a fleet of methods; with one or a few it is ornamental.
    if (payload.task_types.length <= 3) toolbar.querySelector<HTMLElement>('.density-switch')?.setAttribute('hidden', '');
    const input = toolbar.querySelector('input')!, count = toolbar.querySelector<HTMLElement>('.catalog-count')!;
    const render = (): void => {
      const query = input.value.trim().toLowerCase(), category = select.value; const tasks = payload.task_types.filter(task => (!category || task.category === category) && (!query || [task.display_name, task.name, task.category, task.category.replaceAll('_', ' '), labelBySlug.get(task.category) ?? '', task.summary].join(' ').toLowerCase().includes(query)));
      const filtered = Boolean(query || category);
      // "enabled on this deployment" describes the deployment; a filter that hides
      // every method must not make that claim read as "0 methods enabled".
      const countKey = filtered ? 'runners.countFiltered' : payload.task_types.length <= 3 ? (tasks.length === 1 ? 'runners.countEnabledOne' : 'runners.countEnabledMany') : (tasks.length === 1 ? 'runners.countOne' : 'runners.countMany');
      count.textContent = filtered ? t(countKey, { shown: tasks.length, total: payload.task_types.length }) : t(countKey, { count: tasks.length }); catalog.replaceChildren();
      payload.categories.forEach(group => { const items = tasks.filter(task => task.category === group.name); if (!items.length) return; const section = document.createElement('section'); section.className = 'runner-group'; const groupHead = document.createElement('header'); groupHead.append(text('h2', group.label), text('span', t(items.length === 1 ? 'runners.countOne' : 'runners.countMany', { count: items.length }))); const grid = document.createElement('div'); grid.className = 'runner-grid'; items.forEach(task => grid.append(runnerCard(task))); section.append(groupHead, grid); catalog.append(section); });
      if (!tasks.length) catalog.append(text('p', t('runners.empty'), 'empty-state'));
      createIcons({ icons: { ArrowRight, Cpu, ShieldCheck, Zap }, root: catalog });
    };
    input.addEventListener('input', render); select.addEventListener('change', render); toolbar.querySelectorAll<HTMLButtonElement>('[data-density]').forEach(button => button.addEventListener('click', () => { catalog.dataset.density = button.dataset.density; toolbar.querySelectorAll('[data-density]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); })); render();
  } catch (error) {
    // A fault after the catalog was already rebuilt has to re-establish the
    // status line, or the reader is shown an empty surface with no explanation.
    state.textContent = failureBody(error, 'runners.loadFailed'); state.classList.add('error-state');
    if (!state.isConnected) catalog.append(state);
  }
}

function runnerCard(task: TaskTypeSummary): HTMLElement {
  const card = document.createElement('article'); card.className = 'runner-card';
  const badges = document.createElement('div'); badges.className = 'runner-badges'; const access = text('span', accessLabel(task), task.access.restricted ? 'badge restricted' : 'badge available'); badges.append(access);
  const title = text('h3', task.display_name), summary = text('p', task.summary, 'runner-summary'); const link = document.createElement('a'); link.href = `/runners/${encodeURIComponent(task.name)}`; link.innerHTML = `<span>${t('runners.viewMethod')}</span><i data-lucide="arrow-right"></i>`; const footer = document.createElement('footer'); const prepare = createTaskLink(task); prepare.className = 'runner-prepare';
  footer.append(link, prepare); card.append(badges, title, summary, footer); return card;
}

export async function mountRunnerDetail(root: HTMLElement, name: string, shell: AppShell): Promise<void> {
  root.replaceChildren(); root.className = 'app-outlet runner-detail-page'; root.append(text('p', t('runners.detail.loading'), 'empty-state'));
  try {
    const [task, schema, infrastructure] = await Promise.all([getTaskType(name), getParameterSchema(name), getReadiness().catch(() => null)]); root.replaceChildren(); document.title = `${task.display_name} | REvoCompute`;
    const back = document.createElement('a'); back.href = '/runners'; back.className = 'back-link'; back.innerHTML = `<i data-lucide="arrow-left"></i><span>${t('runners.title')}</span>`;
    const head = document.createElement('header'); head.className = 'runner-detail-heading'; const intro = document.createElement('div'); intro.append(back, text('p', task.category.replaceAll('_', ' '), 'page-kicker'), text('h1', task.display_name), text('p', task.summary, 'runner-intro'));
    const access = text('p', accessLabel(task), `access-banner ${task.access.restricted && !task.access.granted ? 'restricted' : ''}`); if (task.access.restricted && task.access.description) access.append(`. ${task.access.description}`); intro.append(access); const terms = accessTerms(task.access); if (terms) intro.append(terms); const actions = document.createElement('div'); actions.className = 'page-actions'; actions.append(createTaskLink(task)); const dashboard = document.createElement('a'); dashboard.href = '/compute/dashboard'; dashboard.className = 'secondary-button'; dashboard.textContent = t('shell.nav.dashboard'); actions.append(dashboard); intro.append(actions);
    const facts = document.createElement('dl'); facts.className = 'runner-facts'; const roles = task.inputs || []; const factValues: Array<[string, string]> = [[t('runners.detail.fact.runtimeFamily'), task.runtime_family || '-'], [t('runners.detail.fact.compute'), task.gpus ? 'GPU' : 'CPU'], [t('runners.detail.fact.network'), task.requires_network ? t('runners.detail.network.required') : t('runners.detail.network.isolated')], [t('runners.detail.fact.inputRoles'), String(roles.length)], [t('runners.detail.fact.parameters'), String(Object.keys(schema.properties || {}).length)]]; factValues.forEach(([label, value]) => { const row = document.createElement('div'); row.append(text('dt', label), text('dd', value)); facts.append(row); }); const runtime = document.createElement('details'); runtime.className = 'method-runtime';
    runtime.append(text('summary', t('runners.detail.runtimeFacts', { compute: task.gpus ? 'GPU' : 'CPU' })), facts);
    if (infrastructure) {
      const readiness = text('p', infrastructure.status === 'READY' ? t('runners.ready') : t('runners.status', { status: infrastructure.status.toLowerCase() }), 'readiness-state');
      readiness.dataset.status = infrastructure.status; runtime.append(readiness);
    }
    const narrow = window.matchMedia('(max-width: 56rem)');
    const syncRuntime = (): void => { runtime.open = !narrow.matches; };
    syncRuntime(); narrow.addEventListener('change', syncRuntime);
    head.append(intro, runtime); root.append(head);
    const body = document.createElement('div'); body.className = 'method-reference';
    const index = document.createElement('nav'); index.className = 'method-index'; index.setAttribute('aria-label', t('runners.detail.onThisMethod'));
    index.append(text('p', t('runners.detail.onThisMethod'), 'page-kicker'));
    const content = document.createElement('div'); content.className = 'method-sections';
    const addSection = (id: string, kicker: string, heading: string, contents: HTMLElement): void => {
      const section = detailSection(heading, contents); section.id = id; section.tabIndex = -1;
      const title = section.querySelector('h2')!; title.id = `${id}-title`;
      section.setAttribute('aria-labelledby', title.id);
      const link = document.createElement('a'); link.href = `#${id}`; link.textContent = kicker;
      index.append(link); content.append(section);
    };
    addSection('scientific-contract', t('runners.detail.section.contract'), t('runners.detail.heading.contract'), guidance(task));
    if (task.workflow?.length) addSection('execution', t('runners.detail.section.execution'), t('runners.detail.heading.execution'), stages(task));
    addSection('inputs', t('runners.detail.section.inputs'), t('runners.detail.heading.inputs'), inputRoles(task));
    addSection('controls', t('runners.detail.section.controls'), t('runners.detail.heading.controls'), parameters(schema.properties || {}, new Set(schema.required || [])));
    if (task.citations?.length) addSection('references', t('runners.detail.section.references'), t('runners.detail.heading.references'), citations(task));
    body.append(index, content); root.append(body);
    const cta = document.createElement('section'); cta.className = 'runner-detail-cta'; cta.append(text('div', t('runners.detail.cta', { name: task.display_name })), createTaskLink(task)); content.append(cta);
    createIcons({ icons: { ArrowLeft, ArrowRight, BookOpen, Cpu, ExternalLink, ShieldCheck, Zap }, root });
  } catch (error) { root.replaceChildren(text('h1', t('runners.detail.unavailable')), text('p', failureBody(error, 'runners.detail.loadFailed'), 'empty-state')); shell.notify(t('runners.detail.contractFailed'), 'error'); }
}

function detailSection(heading: string, content: HTMLElement): HTMLElement { const section = document.createElement('section'); section.className = 'detail-section'; const head = document.createElement('header'); head.append(text('h2', heading)); section.append(head, content); return section; }
function guidance(task: TaskTypeDetail): HTMLElement { const grid = document.createElement('div'); grid.className = 'guidance-grid'; const values: Array<[string, string]> = [[t('runners.detail.guidance.useWhen'), task.use_when], [t('runners.detail.guidance.provide'), task.input_summary], [t('runners.detail.guidance.receive'), task.output_summary]]; values.forEach(([title, body]) => { const item = document.createElement('article'); item.append(text('h3', title), text('p', body)); grid.append(item); }); if (task.considerations.length) { const item = document.createElement('article'); item.append(text('h3', t('runners.detail.guidance.consider'))); const list = document.createElement('ul'); task.considerations.forEach(value => { const row = document.createElement('li'); row.textContent = value; list.append(row); }); item.append(list); grid.append(item); } return grid; }
function stages(task: TaskTypeDetail): HTMLElement { const list = document.createElement('ol'); list.className = 'stage-list'; task.workflow?.forEach((stage, index) => { const item = document.createElement('li'); item.append(text('span', String(index + 1).padStart(2, '0')), text('strong', stage.display_name), text('small', [stage.requires_gpu ? 'GPU' : 'CPU', stage.requires_network ? t('runners.detail.stage.network') : t('runners.detail.stage.isolated')].join(' / '))); list.append(item); }); return list; }
function inputRoles(task: TaskTypeDetail): HTMLElement { const list = document.createElement('div'); list.className = 'input-role-list'; (task.inputs || []).forEach(role => { const item = document.createElement('article'); item.append(text('h3', role.title), text('code', role.id), text('p', role.description || role.type)); const formats = text('p', `${role.formats.join(', ')} · ${role.cardinality.min}–${role.cardinality.max}`, 'role-formats'); item.append(formats); list.append(item); }); if (!list.childElementCount) list.append(text('p', t('runners.detail.noInputs'), 'empty-state')); return list; }
function parameters(definitions: Record<string, ParameterDefinition>, required: Set<string>): HTMLElement { const list = document.createElement('div'); list.className = 'parameter-list'; Object.entries(definitions).forEach(([name, parameter]) => { const item = document.createElement('article'); const identity = document.createElement('div'); identity.append(text('h3', parameter.title || name), text('code', name)); const description = text('p', parameter.description || t('runners.detail.param.noDescription')); const facts = document.createElement('dl'); const values: Array<[string, string]> = [[t('runners.detail.param.type'), Array.isArray(parameter.type) ? parameter.type.join(' / ') : parameter.type || '-']]; if (parameter.default !== undefined) values.push([t('runners.detail.param.default'), String(parameter.default)]); if (parameter.enum) values.push([t('runners.detail.param.choices'), parameter.enum.join(', ')]); if (parameter.minimum !== undefined || parameter.maximum !== undefined || parameter.exclusiveMinimum !== undefined || parameter.exclusiveMaximum !== undefined) {
    const unit = parameter['x-unit'] || parameter.unit;
    const range = parameter.exclusiveMinimum !== undefined || parameter.exclusiveMaximum !== undefined
      ? [parameter.exclusiveMinimum !== undefined ? `> ${parameter.exclusiveMinimum}` : parameter.minimum !== undefined ? `≥ ${parameter.minimum}` : '', parameter.exclusiveMaximum !== undefined ? `< ${parameter.exclusiveMaximum}` : parameter.maximum !== undefined ? `≤ ${parameter.maximum}` : ''].filter(Boolean).join(' · ') + (unit ? ` ${unit}` : '')
      : t('runners.detail.param.range', { minimum: parameter.minimum ?? t('runners.detail.param.any'), maximum: parameter.maximum ?? t('runners.detail.param.any'), unit: unit ? ` ${unit}` : '' });
    values.push([t('runners.detail.param.rangeLabel'), range]);
  } values.forEach(([label, value]) => { const row = document.createElement('div'); row.append(text('dt', label), text('dd', value)); facts.append(row); }); const flags = document.createElement('div'); flags.className = 'parameter-flags'; if (required.has(name)) flags.append(text('span', t('runners.detail.param.required'))); if (parameter['x-advanced'] || parameter.advanced) flags.append(text('span', t('runners.detail.param.advanced'))); item.append(identity, description, facts, flags); list.append(item); }); if (!list.childElementCount) list.append(text('p', t('runners.detail.param.none'), 'empty-state')); return list; }
function citations(task: TaskTypeDetail): HTMLElement { const list = document.createElement('ol'); list.className = 'citation-list'; task.citations?.forEach(citation => { const item = document.createElement('li'); const link = document.createElement('a'); link.href = citation.url || `https://doi.org/${citation.doi}`; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = citation.title || citation.doi || t('runners.detail.publication'); item.append(link); list.append(item); }); return list; }
