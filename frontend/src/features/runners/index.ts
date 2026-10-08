import { ArrowLeft, ArrowRight, BookOpen, Cpu, ExternalLink, Search, ShieldCheck, Zap } from 'lucide';
import { createIcons } from 'lucide';
import { getParameterSchema, getReadiness, getTaskCatalog, getTaskType, type ParameterDefinition, type TaskTypeDetail, type TaskTypeSummary } from '../../api/app-api';
import { guidedTour } from '../../app/guided-tour';
import type { AppShell } from '../../app/shell';

function text(tag: keyof HTMLElementTagNameMap, value: string, className = ''): HTMLElement { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; }
function accessLabel(task: TaskTypeSummary | TaskTypeDetail): string { if (!task.access.restricted) return 'Available'; if (task.access.granted) return 'Access granted'; if (task.access.request_status === 'pending') return 'Access pending'; return 'Restricted'; }
function createTaskLink(task: { name: string; access: { restricted: boolean; granted?: boolean; request_status?: string | null } }): HTMLAnchorElement { const link = document.createElement('a'); link.className = 'primary-button'; link.href = `/compute/create_task?task_type=${encodeURIComponent(task.name)}`; link.innerHTML = '<span>Create task</span><i data-lucide="arrow-right"></i>'; return link; }

export async function mountRunnerCatalog(root: HTMLElement): Promise<void> {
  root.replaceChildren(); root.className = 'app-outlet runners-page';
  const head = document.createElement('header'); head.className = 'page-heading'; head.innerHTML = '<div><h1>Runner catalog</h1><p>Explore the scientific methods and reproducible runtime families available on REvoCompute.</p></div>';
  const readiness = document.createElement('div'); readiness.className = 'readiness-state'; readiness.textContent = 'Checking infrastructure'; head.append(readiness);
  const toolbar = document.createElement('section'); toolbar.className = 'work-toolbar runner-toolbar'; toolbar.innerHTML = '<label class="search-control"><span>Search methods</span><span class="input-with-action"><i data-lucide="search"></i><input type="search" placeholder="Name, category, or summary"></span></label><label><span>Category</span><select><option value="">All categories</option></select></label><fieldset class="layout-switch"><legend>Density</legend><button type="button" data-density="comfortable" aria-pressed="true">Comfortable</button><button type="button" data-density="compact" aria-pressed="false">Compact</button></fieldset><p class="catalog-count" aria-live="polite"></p>';
  const catalog = document.createElement('div'); catalog.className = 'runner-catalog'; catalog.dataset.density = 'comfortable'; const state = text('p', 'Loading methods...', 'empty-state'); catalog.append(state); root.append(head, toolbar, catalog);
  createIcons({ icons: { Search }, root });
  // An in-progress guided tour resumes on the surface it advanced to.
  guidedTour.resumeIfActive();
  try {
    const [payload, infrastructure] = await Promise.all([getTaskCatalog(), getReadiness().catch(() => null)]); state.remove();
    if (infrastructure) { readiness.textContent = infrastructure.status === 'READY' ? 'Infrastructure ready' : `Infrastructure ${infrastructure.status.toLowerCase()}`; readiness.dataset.status = infrastructure.status; }
    const select = toolbar.querySelector('select')!; payload.categories.forEach(category => { const option = document.createElement('option'); option.value = category.name; option.textContent = category.label; select.append(option); });
    // Density is a scan aid for a fleet of methods; with one or a few it is ornamental.
    if (payload.task_types.length <= 3) toolbar.querySelector<HTMLElement>('.layout-switch')?.setAttribute('hidden', '');
    const input = toolbar.querySelector('input')!, count = toolbar.querySelector<HTMLElement>('.catalog-count')!;
    const render = (): void => {
      const query = input.value.trim().toLowerCase(), category = select.value; const tasks = payload.task_types.filter(task => (!category || task.category === category) && (!query || [task.display_name, task.name, task.category, task.summary].join(' ').toLowerCase().includes(query)));
      const filtered = Boolean(query || category), noun = tasks.length === 1 ? 'method' : 'methods';
      // "enabled on this deployment" describes the deployment; a filter that hides
      // every method must not make that claim read as "0 methods enabled".
      count.textContent = filtered ? `${tasks.length} of ${payload.task_types.length} ${payload.task_types.length === 1 ? 'method' : 'methods'}` : payload.task_types.length <= 3 ? `${tasks.length} ${noun} enabled on this deployment` : `${tasks.length} ${noun}`; catalog.replaceChildren();
      payload.categories.forEach(group => { const items = tasks.filter(task => task.category === group.name); if (!items.length) return; const section = document.createElement('section'); section.className = 'runner-group'; const groupHead = document.createElement('header'); groupHead.append(text('h2', group.label), text('span', `${items.length === 1 ? 'method' : 'methods'}`)); const grid = document.createElement('div'); grid.className = 'runner-grid'; items.forEach(task => grid.append(runnerCard(task))); section.append(groupHead, grid); catalog.append(section); });
      if (!tasks.length) catalog.append(text('p', 'No methods match the current filters.', 'empty-state'));
      createIcons({ icons: { ArrowRight, Cpu, ShieldCheck, Zap }, root: catalog });
    };
    input.addEventListener('input', render); select.addEventListener('change', render); toolbar.querySelectorAll<HTMLButtonElement>('[data-density]').forEach(button => button.addEventListener('click', () => { catalog.dataset.density = button.dataset.density; toolbar.querySelectorAll('[data-density]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); })); render();
  } catch (error) { state.textContent = (error as Error).message || 'Unable to load runners.'; state.classList.add('error-state'); }
}

function runnerCard(task: TaskTypeSummary): HTMLElement {
  const card = document.createElement('article'); card.className = 'runner-card';
  const badges = document.createElement('div'); badges.className = 'runner-badges'; const access = text('span', accessLabel(task), task.access.restricted ? 'badge restricted' : 'badge available'); badges.append(access);
  const title = text('h3', task.display_name), summary = text('p', task.summary, 'runner-summary'); const link = document.createElement('a'); link.href = `/runners/${encodeURIComponent(task.name)}`; link.innerHTML = '<span>View method</span><i data-lucide="arrow-right"></i>'; const footer = document.createElement('footer'); footer.append(link); card.append(badges, title, summary, footer); return card;
}

export async function mountRunnerDetail(root: HTMLElement, name: string, shell: AppShell): Promise<void> {
  root.replaceChildren(); root.className = 'app-outlet runner-detail-page'; root.append(text('p', 'Loading method contract...', 'empty-state'));
  try {
    const [task, schema] = await Promise.all([getTaskType(name), getParameterSchema(name)]); root.replaceChildren(); document.title = `${task.display_name} | REvoCompute`;
    const back = document.createElement('a'); back.href = '/runners'; back.className = 'back-link'; back.innerHTML = '<i data-lucide="arrow-left"></i><span>Runner catalog</span>';
    const head = document.createElement('header'); head.className = 'runner-detail-heading'; const intro = document.createElement('div'); intro.append(back, text('p', task.category.replaceAll('_', ' '), 'page-kicker'), text('h1', task.display_name), text('p', task.summary, 'runner-intro'));
    const access = text('p', accessLabel(task), `access-banner ${task.access.restricted && !task.access.granted ? 'restricted' : ''}`); if (task.access.restricted && task.access.description) access.append(`. ${task.access.description}`); intro.append(access); const actions = document.createElement('div'); actions.className = 'page-actions'; actions.append(createTaskLink(task)); const dashboard = document.createElement('a'); dashboard.href = '/compute/dashboard'; dashboard.className = 'secondary-button'; dashboard.textContent = 'Dashboard'; actions.append(dashboard); intro.append(actions);
    const facts = document.createElement('dl'); facts.className = 'runner-facts'; const roles = task.inputs || []; const factValues: Array<[string, string]> = [['Runtime family', task.runtime_family || '-'], ['Compute', task.gpus ? 'GPU' : 'CPU'], ['Network', task.requires_network ? 'Required' : 'Isolated'], ['Input roles', String(roles.length)], ['Parameters', String(Object.keys(schema.properties || {}).length)]]; factValues.forEach(([label, value]) => { const row = document.createElement('div'); row.append(text('dt', label), text('dd', value)); facts.append(row); }); head.append(intro, facts); root.append(head);
    const body = document.createElement('div'); body.className = 'method-reference';
    const index = document.createElement('nav'); index.className = 'method-index'; index.setAttribute('aria-label', 'On this method');
    index.append(text('p', 'On this method', 'page-kicker'));
    const content = document.createElement('div'); content.className = 'method-sections';
    const addSection = (id: string, kicker: string, heading: string, contents: HTMLElement): void => {
      const section = detailSection(heading, contents); section.id = id; section.tabIndex = -1;
      const title = section.querySelector('h2')!; title.id = `${id}-title`;
      section.setAttribute('aria-labelledby', title.id);
      const link = document.createElement('a'); link.href = `#${id}`; link.textContent = kicker;
      index.append(link); content.append(section);
    };
    addSection('scientific-contract', 'Scientific contract', 'When to use this method', guidance(task));
    if (task.workflow?.length) addSection('execution', 'Execution', 'Workflow stages', stages(task));
    addSection('inputs', 'Inputs', 'Accepted data roles', inputRoles(task));
    addSection('controls', 'Controls', 'Task parameters', parameters(schema.properties || {}, new Set(schema.required || [])));
    if (task.citations?.length) addSection('references', 'References', 'Citations', citations(task));
    body.append(index, content); root.append(body);
    const cta = document.createElement('section'); cta.className = 'runner-detail-cta'; cta.append(text('div', `Configure ${task.display_name} with the active server contract.`), createTaskLink(task)); content.append(cta);
    createIcons({ icons: { ArrowLeft, ArrowRight, BookOpen, Cpu, ExternalLink, ShieldCheck, Zap }, root });
  } catch (error) { root.replaceChildren(text('h1', 'Runner unavailable'), text('p', (error as Error).message || 'Unable to load this runner.', 'empty-state')); shell.notify('Unable to load the runner contract.', 'error'); }
}

function detailSection(heading: string, content: HTMLElement): HTMLElement { const section = document.createElement('section'); section.className = 'detail-section'; const head = document.createElement('header'); head.append(text('h2', heading)); section.append(head, content); return section; }
function guidance(task: TaskTypeDetail): HTMLElement { const grid = document.createElement('div'); grid.className = 'guidance-grid'; const values: Array<[string, string]> = [['Use when', task.use_when], ['Provide', task.input_summary], ['Receive', task.output_summary]]; values.forEach(([title, body]) => { const item = document.createElement('article'); item.append(text('h3', title), text('p', body)); grid.append(item); }); if (task.considerations.length) { const item = document.createElement('article'); item.append(text('h3', 'Consider')); const list = document.createElement('ul'); task.considerations.forEach(value => { const row = document.createElement('li'); row.textContent = value; list.append(row); }); item.append(list); grid.append(item); } return grid; }
function stages(task: TaskTypeDetail): HTMLElement { const list = document.createElement('ol'); list.className = 'stage-list'; task.workflow?.forEach((stage, index) => { const item = document.createElement('li'); item.append(text('span', String(index + 1).padStart(2, '0')), text('strong', stage.display_name), text('small', [stage.requires_gpu ? 'GPU' : 'CPU', stage.requires_network ? 'network' : 'isolated'].join(' / '))); list.append(item); }); return list; }
function inputRoles(task: TaskTypeDetail): HTMLElement { const list = document.createElement('div'); list.className = 'input-role-list'; (task.inputs || []).forEach(role => { const item = document.createElement('article'); item.append(text('h3', role.title), text('code', role.id), text('p', role.description || role.type)); const formats = text('p', role.formats.join(', '), 'role-formats'); item.append(formats); list.append(item); }); if (!list.childElementCount) list.append(text('p', 'This method does not require uploaded files.', 'empty-state')); return list; }
function parameters(definitions: Record<string, ParameterDefinition>, required: Set<string>): HTMLElement { const list = document.createElement('div'); list.className = 'parameter-list'; Object.entries(definitions).forEach(([name, parameter]) => { const item = document.createElement('article'); const identity = document.createElement('div'); identity.append(text('h3', parameter.title || name), text('code', name)); const description = text('p', parameter.description || 'No additional description.'); const facts = document.createElement('dl'); const values: Array<[string, string]> = [['Type', Array.isArray(parameter.type) ? parameter.type.join(' / ') : parameter.type || '-']]; if (parameter.default !== undefined) values.push(['Default', String(parameter.default)]); if (parameter.enum) values.push(['Choices', parameter.enum.join(', ')]); if (parameter.minimum !== undefined || parameter.maximum !== undefined) values.push(['Range', `${parameter.minimum ?? 'any'} to ${parameter.maximum ?? 'any'}${parameter.unit ? ` ${parameter.unit}` : ''}`]); values.forEach(([label, value]) => { const row = document.createElement('div'); row.append(text('dt', label), text('dd', value)); facts.append(row); }); const flags = document.createElement('div'); flags.className = 'parameter-flags'; if (required.has(name)) flags.append(text('span', 'Required')); if (parameter.advanced) flags.append(text('span', 'Advanced')); item.append(identity, description, facts, flags); list.append(item); }); if (!list.childElementCount) list.append(text('p', 'This method uses validated defaults and has no user-facing parameters.', 'empty-state')); return list; }
function citations(task: TaskTypeDetail): HTMLElement { const list = document.createElement('ol'); list.className = 'citation-list'; task.citations?.forEach(citation => { const item = document.createElement('li'); const link = document.createElement('a'); link.href = citation.url || `https://doi.org/${citation.doi}`; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = citation.title || citation.doi || 'Publication'; item.append(link); list.append(item); }); return list; }
