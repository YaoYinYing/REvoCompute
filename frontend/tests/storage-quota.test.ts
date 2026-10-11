import { describe, expect, it } from 'vitest';
import { QUOTA_STATES, quotaRequest, quotaStateLabel, quotaTransition } from '../src/features/admin/users/ResourceEnvelope';
import type { StorageQuotaEntitlement } from '../src/features/admin/api';

/*
 * The durable-storage quota control's decisions.
 *
 * The control must send one of the three decisions the server distinguishes and
 * must never compose an effective ceiling of its own: "no ceiling" and "a
 * ceiling of zero bytes" are different decisions with different effects, and a
 * form that blurred them would be a quieter second policy. These cases pin the
 * boundary the form owns (what it sends) rather than any rendering detail.
 */

const entitlement = (overrides: Partial<StorageQuotaEntitlement>): StorageQuotaEntitlement => ({
  subject_type: 'user',
  subject_id: 7,
  state: 'limited',
  soft_limit_bytes: 0,
  logical_owned_bytes: 0,
  remaining_bytes: 0,
  over_soft_limit: false,
  ...overrides,
});

describe('storage quota decisions', () => {
  it('offers exactly the three decisions the server distinguishes', () => {
    expect(QUOTA_STATES.map(state => state.value)).toEqual(['limited', 'unlimited', 'inherit']);
  });

  it('sends a byte ceiling only for a limited quota', () => {
    expect(quotaRequest('limited', '0')).toEqual({ limitBytes: 0 });
    expect(quotaRequest('limited', '10737418240')).toEqual({ limitBytes: 10737418240 });
    expect(quotaRequest('unlimited', '999')).toEqual({ limitBytes: null });
    expect(quotaRequest('inherit', '999')).toEqual({ limitBytes: null });
  });

  it('refuses a limited quota whose ceiling is not a whole non-negative number', () => {
    for (const raw of ['', '   ', '-1', '1.5', '10 GiB', '1e9']) {
      const request = quotaRequest('limited', raw);
      expect('error' in request).toBe(true);
    }
  });

  it('names the decision in force rather than only the number', () => {
    expect(quotaStateLabel(entitlement({ state: 'unlimited', soft_limit_bytes: null }))).toContain('explicit grant');
    expect(quotaStateLabel(entitlement({ state: 'inherit' }))).toContain('deployment default');
    expect(quotaStateLabel(entitlement({ state: 'limited', soft_limit_bytes: 0 }))).toContain('Fixed');
  });

  it('reports a zero ceiling and no ceiling as different transitions', () => {
    const zero = entitlement({ state: 'limited', soft_limit_bytes: 0 });
    const none = entitlement({ state: 'unlimited', soft_limit_bytes: null });
    const limitedToZero = quotaTransition(zero, none);
    const grantToZero = quotaTransition(none, zero);
    expect(limitedToZero).not.toBe(grantToZero);
    expect(limitedToZero).toContain('no ceiling');
    expect(limitedToZero).toContain('0 B');
    expect(grantToZero).toContain('no ceiling');
  });
});
