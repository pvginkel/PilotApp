/**
 * A place in a project by its path within the project: `documents/<id>`, `handbook`, none for the
 * project's own address. A project is at more than one address, its id and a created project's
 * `draft-<number>` giving way to its own (`use-project-address.ts`), so what the browser keeps of
 * a place — a tab of the desktop's line, a view on a phone — is its path, and its address is built
 * from the one the project is at.
 */

const PROJECT = /^\/projects\/[^/]+\/?/;

/** The path within its project of a pathname under a project's address; a path as it stands. */
export function pathWithin(pathname: string): string {
  return pathname.replace(PROJECT, '');
}

/** The pathname of the path within the project at `address`. */
export function addressUnder(address: string, path: string): string {
  return path === '' ? `/projects/${address}` : `/projects/${address}/${path}`;
}
