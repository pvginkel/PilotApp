/**
 * Shared authentication redirect utilities.
 * Used by both auth-context and API middleware for consistent 401 handling.
 */

/**
 * Build the login redirect URL with the current address preserved.
 * Encodes the current pathname, search params and hash so the user can be
 * redirected back after authentication.
 */
export function buildLoginUrl(): string {
  const currentPath = window.location.pathname + window.location.search + window.location.hash;
  const encodedRedirect = encodeURIComponent(currentPath);
  return `/api/auth/login?redirect=${encodedRedirect}`;
}
