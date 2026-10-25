import { beforeEach, describe, expect, it } from 'vitest';

import { applyLocale } from '../src/app/i18n';
import { isSubmissionBlocked, nextActionLabel, submissionNotice } from '../src/features/runners/readiness-copy';

/*
 * The catalog projection is the server's decision, not a client-side readiness
 * oracle. The anonymous shape carries a boolean only; the authenticated shape
 * carries the server's own reason and recovery action. These helpers must read
 * exactly those fields and never re-derive readiness from a status value.
 */

beforeEach(() => { applyLocale('en', false); });

describe('submission readiness copy', () => {
  it('reads the server boolean in both projection shapes', () => {
    expect(isSubmissionBlocked(null)).toBe(false);
    expect(isSubmissionBlocked(undefined)).toBe(false);
    expect(isSubmissionBlocked({ submittable: true })).toBe(false);
    expect(isSubmissionBlocked({ submittable: false })).toBe(true);
    expect(isSubmissionBlocked({
      ready: true, status: 'READY', reason_code: 'READY', message: 'Ready.', next_action: 'none',
    })).toBe(false);
    expect(isSubmissionBlocked({
      ready: false, status: 'VALIDATION_STALE', reason_code: 'RECEIPT_STALE',
      message: 'The receipt is stale.', next_action: 'live-test',
    })).toBe(true);
  });

  it('renders the authenticated reason and the server recovery action', () => {
    expect(submissionNotice({
      ready: false, status: 'BUILD_STALE', reason_code: 'CANDIDATE_AWAITING_PROMOTION',
      message: 'A Runner image candidate is staged for promotion.', next_action: 'promote',
    })).toEqual({
      message: 'A Runner image candidate is staged for promotion.',
      recovery: 'Recommended: Activate the staged image',
    });
  });

  it('does not invent a reason for the anonymous shape', () => {
    expect(submissionNotice({ submittable: false })).toEqual({ message: null, recovery: null });
    expect(submissionNotice({ submittable: true })).toBeNull();
  });

  it('renders the recovery vocabulary without deciding anything itself', () => {
    expect(nextActionLabel('doctor')).toBe('Run Runner Doctor');
    expect(nextActionLabel('build-sif')).toBe('Build the Runner image');
    expect(nextActionLabel('live-test')).toBe('Run the live test');
    expect(nextActionLabel('promote')).toBe('Activate the staged image');
    expect(nextActionLabel('none')).toBe('No action required');
    expect(nextActionLabel('custom-host-step')).toBe('custom-host-step');
  });
});
