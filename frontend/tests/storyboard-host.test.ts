import { describe, expect, it, vi } from 'vitest';

import { StoryboardHost } from '../src/features/results/storyboard-host';

describe('StoryboardHost preview ownership', () => {
  it('does not clear a preview it never mounted', () => {
    const child = {} as Node;
    const host = { replaceChildren: vi.fn(), firstChild: child } as unknown as HTMLElement;
    const storyboard = new StoryboardHost(host, { openFile: vi.fn(), downloadFile: vi.fn() });
    storyboard.destroy();
    expect(host.replaceChildren).not.toHaveBeenCalled();
  });
});
