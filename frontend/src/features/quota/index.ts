/*
 * The Quota feature: the reader's own resource position.
 *
 * The router mounts this feature for its own protected route, `/compute/quota`,
 * and the Account navigation links to it as a destination of the Account region.
 * The page reads the read endpoints scoped to the reader; the administrator's
 * drill-in on the same canonical projection lives in ``envelope.ts``.
 */

export {
  QuotaView,
  loadAdminQuota,
  mountQuotaView,
  quotaBar,
  quotaBars,
  quotaLedgerSection,
  quotaPosition,
} from './QuotaView';
export {
  attributionLabel,
  attributionSummary,
  creditLine,
  isUnattributed,
  kindLabel,
  type QuotaBar,
} from './QuotaView';
