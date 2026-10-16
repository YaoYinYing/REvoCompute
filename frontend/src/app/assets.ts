export function appAsset(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`;
}

/** The approved Daylight Bench identity mark. */
export const DAYLIGHT_MARK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v20M2 12h20M5 5l14 14M5 19L19 5" stroke="currentColor" stroke-width="1.6"/></svg>';
