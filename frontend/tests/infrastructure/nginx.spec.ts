/**
 * The production image's nginx.conf, read from the file the Dockerfile copies: which location
 * nginx picks for a path, by nginx's own rule — an exact `=` match; else the longest prefix,
 * kept if it is `^~`; else the first regex in file order that matches; else that longest
 * prefix. A regex location in front of /api/ answers its paths from the static root.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect } from '@playwright/test';

interface Directive {
  name: string;
  args: string[];
  block: Directive[];
}

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

function tokenize(text: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (/\s/.test(c)) {
      i++;
    } else if (c === '#') {
      while (i < text.length && text[i] !== '\n') i++;
    } else if (c === '{' || c === '}' || c === ';') {
      tokens.push(c);
      i++;
    } else if (c === '"' || c === "'") {
      let j = i + 1;
      while (text[j] !== c) j += text[j] === '\\' ? 2 : 1;
      tokens.push(text.slice(i + 1, j));
      i = j + 1;
    } else {
      let j = i;
      while (j < text.length && !/[\s{};]/.test(text[j])) j++;
      tokens.push(text.slice(i, j));
      i = j;
    }
  }
  return tokens;
}

function parse(tokens: string[]): Directive[] {
  let i = 0;
  function block(): Directive[] {
    const directives: Directive[] = [];
    while (i < tokens.length && tokens[i] !== '}') {
      const words: string[] = [];
      while (tokens[i] !== ';' && tokens[i] !== '{') words.push(tokens[i++]);
      const [name, ...args] = words;
      if (tokens[i++] === '{') {
        directives.push({ name, args, block: block() });
        i++;
      } else {
        directives.push({ name, args, block: [] });
      }
    }
    return directives;
  }
  return block();
}

function only(directives: Directive[], name: string): Directive {
  const found = directives.filter(d => d.name === name);
  if (found.length !== 1) throw new Error(`nginx.conf has ${found.length} ${name} blocks, not one`);
  return found[0];
}

const config = parse(tokenize(readFileSync(resolve(frontendRoot, 'nginx.conf'), 'utf8')));
const locations = only(only(config, 'http').block, 'server').block.filter(
  d => d.name === 'location'
);

function location(path: string): Directive {
  const exact = locations.find(l => l.args[0] === '=' && l.args[1] === path);
  if (exact) return exact;

  const prefixes = locations
    .filter(l => l.args.length === 1 || l.args[0] === '^~')
    .filter(l => path.startsWith(l.args[l.args.length - 1]));
  const longest = prefixes.sort(
    (a, b) => b.args[b.args.length - 1].length - a.args[a.args.length - 1].length
  )[0];
  if (longest?.args[0] === '^~') return longest;

  const regex = locations.find(
    l =>
      (l.args[0] === '~' || l.args[0] === '~*') &&
      new RegExp(l.args[1], l.args[0] === '~*' ? 'i' : '').test(path)
  );
  return regex ?? longest;
}

function values(l: Directive, name: string): string[][] {
  return l.block.filter(d => d.name === name).map(d => d.args);
}

test.describe('The production nginx', () => {
  test('proxies every path under /api/ to the backend, whatever its extension', () => {
    const paths = [
      '/api/sync/files/reference.json',
      '/api/sync/files/acme-rollout/plan.json',
      '/api/sync/files/acme-rollout/timeline.json',
      '/api/sync/files/draft-3/plan.json',
      '/api/sync/files/acme-rollout/items/1-kick-off.md',
      '/api/sse/stream',
      ...['js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'ico', 'svg', 'JSON', 'html', 'txt'].map(
        extension => `/api/attachments/sample.${extension}`
      ),
    ];

    for (const path of paths) {
      expect(values(location(path), 'proxy_pass'), path).toEqual([['http://127.0.0.1:3501']]);
    }
  });

  test('has the browser revalidate every file of the root', () => {
    const files = readdirSync(resolve(frontendRoot, 'public'));

    expect(files).not.toHaveLength(0);
    for (const file of files) {
      expect(values(location(`/${file}`), 'add_header'), file).toEqual([
        ['Cache-Control', 'no-cache'],
      ]);
    }
  });

  test("caches the build's hashed assets for a year", () => {
    for (const path of ['/assets/index-3f9a1c.js', '/assets/index-3f9a1c.css']) {
      const assets = location(path);
      expect(values(assets, 'expires'), path).toEqual([['1y']]);
      expect(values(assets, 'add_header'), path).toEqual([
        ['Cache-Control', 'public, immutable'],
      ]);
    }
  });

  test('answers the SPA, its index and the health check from their own locations', () => {
    expect(values(location('/projects/acme-rollout'), 'try_files')).toEqual([
      ['$uri', '$uri/', '/index.html'],
    ]);
    expect(location('/index.html').args).toEqual(['=', '/index.html']);
    expect(values(location('/health'), 'return')).toEqual([['200', 'healthy\\n']]);
  });
});
