/*
 * The signed-in Version page: this deployment's own build identity and the
 * canonical changelog.
 *
 * One authenticated API response supplies every fact. The page never reads git,
 * the environment or a second version registry: the display version is the
 * server's, the changelog is already bounded structured plain text, and the
 * frontend's baked identity is compared with the server's so a mixed or stale
 * deployment is stated rather than silently asserted to match. Server text is
 * rendered through text nodes only.
 */

import type { VersionChangelog, VersionChangelogSection, VersionInfo } from '../../api/app-api';
import { getVersionInfo } from '../../api/app-api';
import {
  compareBuildIdentity,
  frontendBuildIdentity,
  type BuildIdentity,
} from '../../app/build-identity';
import { t } from '../../app/i18n';
import { button, element, empty, text } from '../../components/dom';
import './version.css';

const notRecorded = (): string => t('version.identity.notRecorded');

function fact(label: string, value: string): HTMLElement {
  const group = element('div', 'version-fact');
  group.append(text('dt', label), text('dd', value));
  return group;
}

/** The explicit frontend/server identity state, or nothing when they agree. */
export function buildDiagnostic(identity: VersionInfo, frontend: BuildIdentity): HTMLElement | null {
  const comparison = compareBuildIdentity(frontend, identity);
  if (comparison === 'mixed') {
    const warning = element('div', 'version-build-warning');
    warning.setAttribute('role', 'alert');
    const reload = button(t('version.build.reload'), 'secondary-button');
    reload.addEventListener('click', () => location.reload());
    warning.append(text('p', t('version.build.mixed')), reload);
    return warning;
  }
  if (comparison === 'frontend-unknown') {
    return text('p', t('version.build.frontendUnknown'), 'version-build-note');
  }
  if (comparison === 'api-unknown') {
    return text('p', t('version.build.apiUnknown'), 'version-build-note');
  }
  return null;
}

/** The prominent display version, revision and build facts. */
export function identitySection(identity: VersionInfo, frontend: BuildIdentity): HTMLElement {
  const section = element('section', 'version-identity');
  section.dataset.section = 'identity';
  section.append(
    element('header', 'version-identity-head', [
      text('h2', t('version.identity.title')),
      text('p', identity.app_version, 'version-display'),
      text(
        'p',
        identity.release_channel === 'release' ? t('version.state.release') : t('version.state.development'),
        'version-channel',
      ),
    ]),
  );
  const facts = element('dl', 'version-facts');
  facts.append(
    fact(t('version.identity.application'), identity.app_version),
    fact(t('version.identity.base'), identity.base_version),
    fact(t('version.identity.revisionShort'), identity.git_sha ? identity.git_sha.slice(0, 7) : notRecorded()),
    fact(t('version.identity.revisionFull'), identity.git_sha || notRecorded()),
    fact(
      t('version.identity.revisionStatus'),
      identity.revision_status === 'verified' ? t('version.identity.verified') : notRecorded(),
    ),
    fact(t('version.identity.channel'), identity.release_channel),
    fact(t('version.identity.built'), identity.built_at || notRecorded()),
    fact(t('version.identity.buildId'), identity.build_id || notRecorded()),
  );
  section.append(facts);
  const diagnostic = buildDiagnostic(identity, frontend);
  if (diagnostic) section.append(diagnostic);
  return section;
}

function kindLabel(kind: VersionChangelogSection['kind']): string {
  if (kind === 'unreleased') return t('version.kind.unreleased');
  if (kind === 'development-snapshot') return t('version.kind.development');
  return t('version.kind.release');
}

function sectionArticle(section: VersionChangelogSection): HTMLElement {
  const article = element('article', 'version-section');
  const header = element('header', 'version-section-head');
  header.append(
    text('h3', section.date ? `${section.version} — ${section.date}` : section.version),
    text('span', kindLabel(section.kind), `version-kind version-kind-${section.kind}`),
  );
  article.append(header);
  for (const category of section.categories) {
    article.append(text('h4', category.name));
    const list = element('ul', 'version-items');
    for (const item of category.items) {
      const entry = text('li', item.text, item.depth ? 'version-item version-item-nested' : 'version-item');
      list.append(entry);
    }
    article.append(list);
  }
  return article;
}

/** The reverse-chronological changelog, in the order the server publishes it. */
export function changelogSection(changelog: VersionChangelog): HTMLElement {
  const section = element('section', 'version-changelog');
  section.dataset.section = 'changelog';
  section.append(text('h2', t('version.changelog.title')), text('p', t('version.changelog.note'), 'version-note'));
  if (!changelog.sections.length) {
    section.append(empty(t('version.changelog.empty')));
    return section;
  }
  if (changelog.truncated) section.append(text('p', t('version.changelog.truncated'), 'version-note'));
  for (const entry of changelog.sections) section.append(sectionArticle(entry));
  return section;
}

function errorState(message: string, retry: () => void): HTMLElement {
  const state = element('div', 'version-error');
  state.setAttribute('role', 'alert');
  const control = button(t('version.retry'));
  control.addEventListener('click', retry);
  state.append(text('p', message), control);
  return state;
}

class VersionView {
  private readonly root: HTMLElement;
  private readonly body: HTMLElement;

  constructor() {
    const section = element('section', 'account-section version-hero');
    section.dataset.section = 'version';
    section.append(
      element('header', '', [text('h1', t('version.title')), text('p', t('version.description'))]),
    );
    this.body = element('div', 'version-body', [empty(t('version.loading'))]);
    section.append(this.body);
    this.root = element('main', 'account-page version-page', [section]);
  }

  async mount(outlet: HTMLElement): Promise<void> {
    outlet.replaceChildren(this.root);
    await this.load();
  }

  private async load(): Promise<void> {
    this.body.replaceChildren(empty(t('version.loading')));
    try {
      const identity = await getVersionInfo();
      const content: HTMLElement[] = [identitySection(identity, frontendBuildIdentity), changelogSection(identity.changelog)];
      this.body.replaceChildren(...content);
    } catch (error) {
      this.body.replaceChildren(
        errorState((error as Error).message || t('version.error'), () => void this.load()),
      );
    }
  }

  /** The page owns no subscription; the region leaves with the route. */
  destroy(): void {
    this.root.remove();
  }
}

/** Mount the Version page and return the disposable view. */
export async function mountVersionView(outlet: HTMLElement): Promise<VersionView> {
  const view = new VersionView();
  await view.mount(outlet);
  return view;
}
