import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { VersionInfo } from '../src/api/app-api';
import { applyLocale } from '../src/app/i18n';
import { compareBuildIdentity, type BuildIdentity } from '../src/app/build-identity';
import { changelogSection, identitySection } from '../src/features/version';
import { installHarness, type HarnessNode } from './dom-harness';

/*
 * The Version page's identity and changelog states, driven through the DOM the
 * page builds. The assertions are on what a reader is told: two unknowns are not
 * a match, a verified mismatch is an explicit diagnostic, and changelog text is
 * rendered as plain text in the order the server published it.
 */

const SHA = 'b'.repeat(40);
const FRONTEND: BuildIdentity = { gitSha: SHA, builtAt: '2026-11-12T10:00:00Z', baseVersion: '0.1.0' };

function identity(overrides: Partial<VersionInfo> = {}): VersionInfo {
  return {
    base_version: '0.1.0',
    app_version: `0.1.0+${SHA.slice(0, 7)}`,
    git_sha: SHA,
    revision_status: 'verified',
    release_channel: 'development',
    built_at: '2026-11-12T10:00:00Z',
    build_id: null,
    changelog: {
      source_sha256: 'a'.repeat(64),
      truncated: false,
      sections: [
        {
          version: 'Unreleased',
          date: null,
          kind: 'unreleased',
          categories: [{ name: 'Added', items: [{ text: 'A new surface.', depth: 0 }] }],
        },
        {
          version: '0.1.0+2890609',
          date: '2026-11-12',
          kind: 'development-snapshot',
          categories: [{ name: 'Changed', items: [{ text: 'A recorded change.', depth: 1 }] }],
        },
      ],
    },
    ...overrides,
  };
}

beforeEach(() => {
  installHarness(vi.stubGlobal, { pathname: '/compute/version' });
  applyLocale('en', false);
});

afterEach(() => vi.unstubAllGlobals());

describe('build identity comparison', () => {
  it('matches only two verified identities that agree', () => {
    expect(compareBuildIdentity(FRONTEND, identity())).toBe('match');
    expect(compareBuildIdentity(FRONTEND, identity({ git_sha: 'c'.repeat(40) }))).toBe('mixed');
    expect(compareBuildIdentity(FRONTEND, identity({ base_version: '0.2.0' }))).toBe('mixed');
  });

  it('keeps an unknown frontend separate from an unknown server', () => {
    expect(compareBuildIdentity({ ...FRONTEND, gitSha: '' }, identity())).toBe('frontend-unknown');
    expect(compareBuildIdentity(FRONTEND, identity({ git_sha: null, revision_status: 'unknown' }))).toBe('api-unknown');
  });
});

describe('identity section', () => {
  it('shows the display version, full revision and build facts when verified', () => {
    const section = identitySection(identity(), FRONTEND) as unknown as HarnessNode;
    expect(section.textContent).toContain(identity().app_version);
    expect(section.textContent).toContain(SHA);
    expect(section.textContent).toContain('Development build');
    expect(section.querySelectorAll('.version-build-warning')).toHaveLength(0);
  });

  it('states a mixed deployment and offers a reload, never a silent match', () => {
    const section = identitySection(identity({ git_sha: 'c'.repeat(40) }), FRONTEND) as unknown as HarnessNode;
    const warning = section.querySelector('.version-build-warning')!;
    expect(warning.getAttribute('role')).toBe('alert');
    expect(warning.textContent).toContain('mixed or stale');
    expect(warning.querySelectorAll('button')).toHaveLength(1);
    expect(warning.querySelector('button')!.textContent).toBe('Reload');
  });

  it('states an unknown frontend revision instead of inventing one', () => {
    const section = identitySection(identity(), { ...FRONTEND, gitSha: '' }) as unknown as HarnessNode;
    expect(section.textContent).toContain('records no source revision');
    expect(section.querySelectorAll('.version-build-warning')).toHaveLength(0);
    // The server's revision is still shown; only the comparison is unknown.
    expect(section.textContent).toContain(SHA);
  });

  it('states an unverified server identity and shows absent build fields explicitly', () => {
    const section = identitySection(
      identity({ git_sha: null, revision_status: 'unknown', built_at: null, app_version: '0.1.0+unknown' }),
      FRONTEND,
    ) as unknown as HarnessNode;
    expect(section.textContent).toContain('cannot be confirmed as equal');
    expect(section.textContent).toContain('Not recorded');
    expect(section.textContent).toContain('0.1.0+unknown');
  });
});

describe('changelog section', () => {
  it('renders sections in server order with kinds, categories and nested items', () => {
    const section = changelogSection(identity().changelog) as unknown as HarnessNode;
    const headings = section.querySelectorAll('h3').map(node => node.textContent);
    expect(headings).toEqual(['Unreleased', '0.1.0+2890609 — 2026-11-12']);
    expect(section.textContent).toContain('Development snapshot');
    expect(section.textContent).toContain('Added');
    expect(section.querySelectorAll('.version-item-nested')).toHaveLength(1);
    // Changelog text is a text node, never parsed as markup.
    expect(section.querySelectorAll('strong')).toHaveLength(0);
  });

  it('states an absent changelog explicitly', () => {
    const section = changelogSection({ ...identity().changelog, sections: [] }) as unknown as HarnessNode;
    expect(section.textContent).toContain('No changelog is recorded');
  });

  it('states when the server bounded the changelog', () => {
    const section = changelogSection({ ...identity().changelog, truncated: true }) as unknown as HarnessNode;
    expect(section.textContent).toContain('truncated');
  });
});
