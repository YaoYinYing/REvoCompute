import type { TaskTypeSummary } from '../../api/app-api';
import type { components } from '../../api/schema.generated';
import { t } from '../../app/i18n';

/**
 * Whether the authenticated catalog projection is present.
 *
 * The server emits either the compact anonymous shape (``submittable`` only) or
 * the authenticated shape (``ready`` plus the server's own reason and recovery
 * action). A missing projection means this deployment does not gate submission
 * on Runner readiness; the frontend never derives readiness from a status enum.
 */
type SubmissionState = NonNullable<TaskTypeSummary['submission']>;

/** Display copy for the server's recovery vocabulary, which stays server-owned. */
export function nextActionLabel(action: string): string {
  switch (action) {
    case 'doctor':
      return t('runners.nextAction.doctor');
    case 'build-sif':
      return t('runners.nextAction.build');
    case 'live-test':
      return t('runners.nextAction.validate');
    case 'promote':
      return t('runners.nextAction.activate');
    case 'none':
      return t('runners.nextAction.none');
    default:
      return action;
  }
}

export function isSubmissionBlocked(submission: TaskTypeSummary['submission'] | undefined): boolean {
  if (!submission || typeof submission !== 'object') return false;
  return 'submittable' in submission ? submission.submittable === false : submission.ready === false;
}

export interface SubmissionNotice {
  /** The server's explanation, when this reader is entitled to the detailed shape. */
  message: string | null;
  /** The server's recovery action, when the detailed shape is present. */
  recovery: string | null;
}

export function submissionNotice(
  submission: TaskTypeSummary['submission'] | undefined,
): SubmissionNotice | null {
  if (!isSubmissionBlocked(submission) || !submission) return null;
  if (!('message' in submission)) return { message: null, recovery: null };
  return {
    message: submission.message,
    recovery: t('runners.recovery', { action: nextActionLabel(submission.next_action) }),
  };
}

/**
 * The admission refusal a final POST can return, in the same shape the method
 * detail projects.
 *
 * A READY preflight does not bind the submission; readiness can change between
 * the two requests. The server answers that race with the same typed refusal it
 * uses at the admission boundary, so the page can keep the reader's inputs and
 * show the current reason instead of collapsing it into the generic error
 * string. Anything that is not that exact payload stays a generic failure.
 */
export function submissionRefusal(payload: unknown): SubmissionState | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const item = payload as Record<string, unknown>;
  if (item.runner === undefined) return null;
  for (const field of ['status', 'reason', 'message', 'next_action'] as const) {
    if (typeof item[field] !== 'string' || !item[field]) return null;
  }
  return {
    ready: false,
    status: item.status as components['schemas']['RunnerReadinessStatus'],
    reason_code: item.reason as string,
    message: item.message as string,
    next_action: item.next_action as string,
  };
}
