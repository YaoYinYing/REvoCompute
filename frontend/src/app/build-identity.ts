/*
 * The build identity baked into this frontend bundle at build time.
 *
 * Vite replaces `__REVOCOMPUTE_BUILD__` with the same immutable commit, time and
 * base version the server image records, so the version page can state whether
 * the two halves of a deployment came from one source revision. A bundle built
 * without those values records empty strings, which the page reports as an
 * unknown identity instead of inventing a revision or claiming a false match.
 */

export interface BuildIdentity {
  gitSha: string;
  builtAt: string;
  baseVersion: string;
}

export type IdentityComparison = 'match' | 'mixed' | 'frontend-unknown' | 'api-unknown';

export interface ApiIdentity {
  base_version: string;
  git_sha: string | null;
  revision_status: 'verified' | 'unknown';
}

export const frontendBuildIdentity: BuildIdentity =
  typeof __REVOCOMPUTE_BUILD__ === 'undefined'
    ? { gitSha: '', builtAt: '', baseVersion: '' }
    : __REVOCOMPUTE_BUILD__;

/**
 * Compare the baked frontend identity with the server's projection.
 *
 * An absent frontend revision and an unverified server revision are different
 * unknowns: neither is treated as a match with the other. Only two verified
 * identities that agree on the commit (and on the base version, when the
 * frontend records one) are a match.
 */
export function compareBuildIdentity(frontend: BuildIdentity, api: ApiIdentity): IdentityComparison {
  if (!frontend.gitSha) return 'frontend-unknown';
  if (api.revision_status !== 'verified' || !api.git_sha) return 'api-unknown';
  if (frontend.gitSha.toLowerCase() !== api.git_sha.toLowerCase()) return 'mixed';
  if (frontend.baseVersion && frontend.baseVersion !== api.base_version) return 'mixed';
  return 'match';
}
