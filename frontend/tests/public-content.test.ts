import { describe, expect, it } from 'vitest';

import { accessState } from '../src/features/profile/sections';
import { parseLegalMarkdown } from '../src/features/legal/index';

describe('public and Account presentation data', () => {
  it('parses the canonical legal document without accepting HTML as markup', () => {
    const blocks = parseLegalMarkdown('# Terms\n\n## Access {#restricted}\n\n- Keep credentials private.\n- Open **Account**.\n\n<script>alert(1)</script>');
    expect(blocks).toEqual([
      { kind: 'heading', level: 1, text: 'Terms' },
      { kind: 'heading', level: 2, text: 'Access', id: 'restricted' },
      { kind: 'list', ordered: false, items: ['Keep credentials private.', 'Open **Account**.'] },
      { kind: 'paragraph', text: '<script>alert(1)</script>' },
    ]);
  });

  it('projects server-owned Runner access facts into user-facing states', () => {
    expect(accessState({ restricted: true, granted: true })).toBe('Granted');
    expect(accessState({ restricted: true, expired: true })).toBe('Expired');
    expect(accessState({ restricted: true, request_status: 'pending' })).toBe('Pending');
    expect(accessState({ restricted: true, request_status: 'rejected' })).toBe('Rejected');
    expect(accessState({ restricted: true, requestable: true })).toBe('Requestable');
    expect(accessState({ restricted: true, requestable: false })).toBe('Restricted');
  });

  it('keeps a live grant and a live request ahead of the history behind them', () => {
    // A grant is the decisive fact even if an old request row still says pending.
    expect(accessState({ restricted: true, granted: true, request_status: 'pending' })).toBe('Granted');
    expect(accessState({ restricted: true, granted: true, expired: true })).toBe('Granted');
    // The server's projection can carry an expired grant plus a newer request;
    // its access list counts that policy as pending, so the live request wins.
    expect(accessState({ restricted: true, expired: true, request_status: 'pending', requestable: true })).toBe('Pending');
    expect(accessState({ restricted: true, expired: true, request_status: 'rejected' })).toBe('Expired');
    expect(accessState({ restricted: true, request_status: 'approved', requestable: true })).toBe('Requestable');
  });
});
