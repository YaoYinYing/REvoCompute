import { ArrowRight } from 'lucide';
import { createIcons } from 'lucide';
import { getTaskCatalog } from '../../api/app-api';
import { loadEnvironment } from '../../app/environment';
import { t } from '../../app/i18n';
import './demo.css';

interface ReplaySummary {
  id: string;
  title: string;
  summary: string;
  task_type: string;
  provenance: { kind: string; label: string; capture_source: string };
  bundle_digest: string;
  task: { id: string; type: string; display_name?: string };
}

function text(tag: keyof HTMLElementTagNameMap, value: string, className = ''): HTMLElement {
  const node = document.createElement(tag); node.className = className; node.textContent = value; return node;
}

function link(href: string, label: string, className: string): HTMLAnchorElement {
  const anchor = document.createElement('a'); anchor.className = className; anchor.href = href;
  anchor.innerHTML = `<span>${label}</span><i data-lucide="arrow-right" aria-hidden="true"></i>`; return anchor;
}

async function replayScenarios(): Promise<ReplaySummary[]> {
  const response = await fetch('/compute/api/demo/replays', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json() as { scenarios?: ReplaySummary[] };
  return Array.isArray(payload.scenarios) ? payload.scenarios : [];
}

export async function mountDemoLanding(root: HTMLElement): Promise<void> {
  root.replaceChildren(); root.className = 'app-outlet demo-page';
  const heading = document.createElement('header'); heading.className = 'page-heading';
  const intro = document.createElement('div');
  intro.append(text('p', t('demo.kicker'), 'page-kicker'), text('h1', t('demo.title')), text('p', t('demo.subtitle'), 'demo-intro'));
  heading.append(intro);
  const badge = text('span', t('demo.badge'), 'app-demo-badge demo-badge'); heading.append(badge);
  root.append(heading);

  const environment = await loadEnvironment();
  if (!environment) {
    root.append(text('p', t('environment.unresolved'), 'empty-state'));
    return;
  }
  if (!environment.demo_mode) {
    root.append(text('p', t('demo.notDemo'), 'empty-state'));
    return;
  }
  root.append(text('p', environment.notice || t('demo.notice'), 'demo-notice'));

  const catalog = await getTaskCatalog();
  const preview = document.createElement('section'); preview.className = 'demo-section';
  preview.append(text('h2', t('demo.preview.heading')), text('p', t('demo.preview.intro'), 'demo-section-intro'));
  const groups = document.createElement('div'); groups.className = 'demo-groups';
  catalog.categories.forEach((category) => {
    const tasks = catalog.task_types.filter((task) => task.category === category.name);
    if (!tasks.length) return;
    const group = document.createElement('section'); group.className = 'demo-group';
    group.append(text('h3', category.label));
    const grid = document.createElement('div'); grid.className = 'demo-grid';
    tasks.forEach((task) => {
      const card = document.createElement('article'); card.className = 'demo-card';
      card.append(text('p', task.category.replaceAll('_', ' '), 'demo-card-kicker'), text('h4', task.display_name), text('p', task.summary, 'demo-card-summary'));
      const actions = document.createElement('footer'); actions.className = 'demo-card-actions';
      actions.append(link(`/runners/${encodeURIComponent(task.name)}`, t('demo.preview.view'), 'secondary-button'));
      actions.append(link(`/compute/create_task?task_type=${encodeURIComponent(task.name)}`, t('demo.preview.configure'), 'secondary-button'));
      card.append(actions); grid.append(card);
    });
    group.append(grid); groups.append(group);
  });
  preview.append(groups); root.append(preview);

  const replay = document.createElement('section'); replay.className = 'demo-section';
  // A failed catalog read is not an empty catalog. The failure is stated and
  // retried in place; "none installed" is reserved for a served empty list.
  const renderReplay = async (): Promise<void> => {
    replay.replaceChildren(text('h2', t('demo.replay.heading')), text('p', t('demo.replay.intro'), 'demo-section-intro'));
    let scenarios: ReplaySummary[];
    try { scenarios = await replayScenarios(); }
    catch (error) {
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'secondary-button'; retry.textContent = t('demo.replay.retry');
      retry.addEventListener('click', () => { retry.disabled = true; void renderReplay(); });
      const actions = document.createElement('div'); actions.className = 'demo-card-actions'; actions.append(retry);
      replay.append(text('p', t('demo.replay.loadFailed', { message: error instanceof Error ? error.message : String(error) }), 'empty-state'), actions);
      return;
    }
    if (!scenarios.length) { replay.append(text('p', t('demo.replay.empty'), 'empty-state')); return; }
    const replayGrid = document.createElement('div'); replayGrid.className = 'demo-grid';
    scenarios.forEach((scenario) => {
      const card = document.createElement('article'); card.className = 'demo-card demo-card-replay';
      card.append(text('p', scenario.provenance.label, 'demo-provenance'), text('h4', scenario.title), text('p', scenario.summary, 'demo-card-summary'));
      const meta = text('p', t('demo.replay.meta', { type: scenario.task_type }), 'demo-card-meta');
      card.append(meta);
      const actions = document.createElement('footer'); actions.className = 'demo-card-actions';
      actions.append(link(`/compute/demo/replays/${encodeURIComponent(scenario.id)}`, t('demo.replay.open'), 'primary-button'));
      card.append(actions); replayGrid.append(card);
    });
    replay.append(replayGrid);
  };
  root.append(replay);
  await renderReplay();

  const limits = document.createElement('section'); limits.className = 'demo-section demo-limitations';
  limits.append(text('h2', t('demo.limitations.heading')));
  const list = document.createElement('ul');
  [t('demo.limitations.live'), t('demo.limitations.data'), t('demo.limitations.replay')].forEach((item) => list.append(text('li', item)));
  limits.append(list); root.append(limits);
  createIcons({ icons: { ArrowRight }, root });
}

export async function mountDemoReplay(root: HTMLElement, scenarioId: string): Promise<{ destroy(): void } | null> {
  let workspace: { destroy(): void } | null = null;
  let destroyed = false;
  const render = async (): Promise<'ok' | 'missing' | 'failed'> => {
    root.replaceChildren(); root.className = 'app-outlet demo-replay-page';
    let scenarios: ReplaySummary[];
    try { scenarios = await replayScenarios(); }
    catch (error) {
      // A failed read is stated and retried; it is not "this scenario does not exist".
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'secondary-button'; retry.textContent = t('demo.replay.retry');
      retry.addEventListener('click', () => { retry.disabled = true; void render(); });
      root.append(text('h1', t('demo.replay.missingTitle')), text('p', t('demo.replay.loadFailed', { message: error instanceof Error ? error.message : String(error) }), 'empty-state'), retry);
      return 'failed';
    }
    const scenario = scenarios.find((item) => item.id === scenarioId);
    if (!scenario) {
      root.append(text('h1', t('demo.replay.missingTitle')), text('p', t('demo.replay.missingBody'), 'empty-state'));
      return 'missing';
    }
    const banner = document.createElement('section'); banner.className = 'demo-replay-banner';
    const copy = document.createElement('div');
    copy.append(text('p', scenario.provenance.label, 'demo-provenance'), text('h1', scenario.title), text('p', scenario.summary, 'demo-card-summary'));
    const back = link('/compute/demo', t('demo.replay.back'), 'secondary-button');
    banner.append(copy, back);
    const attribution = text('p', t('demo.replay.attribution', { source: scenario.provenance.capture_source, digest: scenario.bundle_digest }), 'demo-card-meta');
    banner.append(attribution);
    const stage = document.createElement('div'); stage.className = 'demo-replay-stage';
    root.append(banner, stage);
    createIcons({ icons: { ArrowRight }, root: banner });
    // The one Result Workspace is loaded only when a recorded result is opened, so
    // the playground's catalog page never carries the viewer bundle.
    const { mountDemoResultWorkspace } = await import('../results/index.js');
    const mounted = await mountDemoResultWorkspace(stage, scenario.id, scenario.task.id);
    // A retry that finishes after the route was left must not keep its workspace
    // alive; the router already released the handle it was given.
    if (destroyed) { mounted.destroy(); return 'ok'; }
    workspace = mounted;
    return 'ok';
  };
  const state = await render();
  if (state === 'missing') return null;
  return { destroy: () => { destroyed = true; workspace?.destroy(); workspace = null; } };
}
