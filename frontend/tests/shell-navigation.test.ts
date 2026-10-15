import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { documentOrder, installHarness, type HarnessNode } from './dom-harness';

/*
 * The shell's navigation regions are captions over their destinations, not document
 * sections. §23 requires source order to match reading order: a screen-reader user
 * who navigates by heading must meet the page's own h1 before anything else, so the
 * region captions must not be headings. These tests build the real shell, render a
 * page heading into the outlet as a route does, and read the resulting outline.
 *
 * `shell.ts` reads `matchMedia` at module scope, so the browser globals are
 * installed before the module is loaded.
 */

type ShellModule = typeof import('../src/app/shell');

let mountShell: ShellModule['mountShell'];

beforeEach(async () => {
  installHarness(vi.stubGlobal, { pathname: '/compute/dashboard' });
  ({ mountShell } = await import('../src/app/shell'));
});

afterEach(() => vi.unstubAllGlobals());

/** Mount the real shell and render a page heading into its outlet, as `main.ts` does. */
function shellWithPageHeading(): { root: HarnessNode; outlet: HarnessNode } {
  const root = document.createElement('div') as unknown as HarnessNode;
  const shell = mountShell(root as unknown as HTMLElement);
  const outlet = shell.outlet as unknown as HarnessNode;
  outlet.innerHTML = '<header class="page-heading"><div><p class="page-kicker">Task register</p><h1>Dashboard</h1></div></header>';
  return { root, outlet };
}

const captionOf = (group: HarnessNode): HarnessNode => group.querySelector('span.app-nav-group-label')!;

describe('shell navigation structure', () => {
  it('opens the document outline with the page h1, never with a navigation caption', () => {
    const { root } = shellWithPageHeading();
    const headings = documentOrder(root).filter(node => /^H[1-6]$/.test(node.tag));
    expect(headings.map(node => node.tag)).toEqual(['H1']);
    expect(headings[0]!.textContent).toBe('Dashboard');
    // The navigation captions are still rendered; they are simply not headings.
    expect(documentOrder(root).filter(node => node.classList.contains('app-nav-group-label')).length).toBe(3);
  });

  it('names each navigation region through its caption instead of a heading', () => {
    const { root } = shellWithPageHeading();
    const nav = root.querySelector('nav.app-nav')!;
    expect(nav.getAttribute('aria-label')).toBe('Primary');
    const groups = nav.querySelectorAll('div.app-nav-group');
    expect(groups.map(group => group.dataset.navGroup)).toEqual(['compute', 'account', 'admin']);

    expect(groups.map(group => group.getAttribute('role'))).toEqual(['group', 'group', 'group']);
    expect(groups.map(group => captionOf(group).textContent)).toEqual(['Compute', 'Account', 'Administration']);
    // Each region keeps an accessible name: the group points at its own caption.
    for (const group of groups) {
      const caption = captionOf(group);
      expect(group.getAttribute('aria-labelledby')).toBe(caption.id);
      expect(caption.id).toBeTruthy();
      expect(caption.textContent.trim()).not.toBe('');
      expect(caption.tag).toBe('SPAN');
    }
  });

  it('names both secondary navigation regions on mobile', () => {
    const { root } = shellWithPageHeading();
    const caption = (region: string): HarnessNode => captionOf(root.querySelector(`div.app-nav-group[data-nav-group="${region}"]`)!);
    // Compute sits on the top bar. Account and Administration live in the same
    // expandable menu, where their captions name the two regions.
    expect(caption('compute').hidden).toBe(true);
    expect(caption('account').hidden).toBe(false);
    expect(caption('admin').hidden).toBe(false);
    expect(caption('admin').textContent).toBe('Administration');
    expect(root.querySelector('div.app-nav-group[data-nav-group="admin"]')!.hidden).toBe(true);
  });

  it('keeps one navigation landmark and lets the route own the page heading', () => {
    const { root, outlet } = shellWithPageHeading();
    expect(root.querySelectorAll('nav.app-nav').length).toBe(1);
    expect(outlet.querySelector('h1')!.textContent).toBe('Dashboard');
  });
});
