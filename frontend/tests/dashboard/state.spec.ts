/**
 * A view's state on the page (F159), held to the forms of the file of states (F154.2,
 * `backend/dashboard-states/states.json`), which the backend's suite reads whole: the page reads
 * each normal form there and writes it back as it is, tells its look-only parts from the rest as
 * the server does, and writes its parts in the server's order and its lists in the server's,
 * whatever order it read them in; every other state the file holds it reads or throws its own
 * `StateFormError`, the server's normal form and its refusals being the server's. No browser, no
 * backend and no test suite lock: the module the page reads and writes a state through is pure.
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { lookOf, readState, StateFormError, withoutLook, writeState } from '@/lib/dashboard/state';

const FILE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../backend/dashboard-states/states.json',
);

interface Entry {
  about: string;
  state: string;
  normal?: string;
  look?: string[];
}

const ENTRIES = (JSON.parse(readFileSync(FILE, 'utf-8')) as { states: Entry[] }).states;

/** The entries that read, each with its normal form and its look-only parts. */
const READING = ENTRIES.flatMap(({ about, state, normal, look }) =>
  normal === undefined || look === undefined ? [] : [{ about, state, normal, look }],
);

/** The parts a state holds more than once, whose order is the view's. */
const REPEATED = ['m', 'dr', 'c'];

test('the file holds states that read and states the server refuses', () => {
  expect(READING.length).toBeGreaterThan(0);
  expect(READING.length).toBeLessThan(ENTRIES.length);
});

test('each normal form is read and written back as it is, the address before it read off', () => {
  for (const { about, normal } of READING) {
    expect(writeState(readState(normal)), about).toBe(normal);
    expect(writeState(readState(`#dash/${normal}`)), about).toBe(normal);
  }
});

test('each normal form tells its look-only parts, and the rest, as the server does', () => {
  for (const { about, normal, look } of READING) {
    const state = readState(normal);
    expect(lookOf(state), about).toEqual(look);
    const rest = normal.split('&').filter((part) => !look.includes(part));
    expect(withoutLook(state), about).toBe(rest.join('&'));
  }
});

test('a change of each look-only part, on its own, leaves the rest as it was', () => {
  for (const { about, normal } of READING) {
    const state = readState(normal);
    const changes = [
      { ...state, drawer: !state.drawer },
      { ...state, relative: !state.relative },
      { ...state, markers: state.markers === null ? [] : null },
      { ...state, draw: { ...state.draw, med: !state.draw.med } },
      { ...state, lit: state.lit === null ? ['…'] : null },
      { ...state, events: state.events === null ? [{ kind: 'cache_miss', drawn: false }] : null },
      { ...state, zoom: state.zoom === null ? ([1763600000, 1763686400] as const) : null },
    ];
    for (const changed of changes) {
      expect(lookOf(changed), about).not.toEqual(lookOf(state));
      expect(withoutLook(changed), about).toBe(withoutLook(state));
    }
  }
});

test("a normal form's parts read in another order are written in the server's", () => {
  for (const { about, normal } of READING) {
    const parts = normal.split('&');
    const repeated = parts.filter((part) => REPEATED.includes(part.split('=')[0]));
    const once = parts.filter((part) => !repeated.includes(part));
    const shuffled = [...repeated, ...once.reverse()].join('&');
    expect(writeState(readState(shuffled)), about).toBe(normal);
  }
});

test("a state's lists are written in the server's order, each value once", () => {
  const twice = <T>(list: readonly T[]) => [...list].reverse().concat(list);
  for (const { about, normal } of READING) {
    const state = readState(normal);
    const time = state.time.kind === 'weeks' ? { ...state.time, starts: twice(state.time.starts) } : state.time;
    const turned = {
      ...state,
      time,
      quickFilters: twice(state.quickFilters),
      markers: state.markers && twice(state.markers),
      lit: state.lit && twice(state.lit),
      events: state.events && twice(state.events),
    };
    expect(writeState(turned), about).toBe(normal);
  }
});

test('every state the file holds is read, or thrown out as in no form the page reads', () => {
  const read = (state: string) => {
    try {
      return readState(state);
    } catch (error) {
      expect(error, state).toBeInstanceOf(StateFormError);
      return null;
    }
  };
  for (const { about, state } of ENTRIES) {
    const found = read(state);
    if (found === null) continue;
    const written = writeState(found);
    expect(writeState(readState(written)), about).toBe(written);
  }
});

test("a threshold's number is written as the server writes it", () => {
  const written = (threshold: string) =>
    writeState(readState(`c=@rows,gt,${threshold},cost.sum`)).match(/@rows,gt,([^,]+),/)?.[1];
  // The server's `number`, Python's `repr` past a whole number.
  const SERVER: Record<string, string> = {
    '1.50': '1.5',
    '100.0': '100',
    '0.00001': '1e-05',
    '9.99e-5': '9.99e-05',
    '0.0001': '0.0001',
    '1.5e-7': '1.5e-07',
    '123.456': '123.456',
    '-0.5': '-0.5',
    '1e22': '10000000000000000000000',
  };
  for (const [threshold, form] of Object.entries(SERVER)) {
    expect(written(threshold), threshold).toBe(form);
  }
});

test('a value holding ~ ! \' ( ) * is written with each escaped, as the server writes it', () => {
  const written = 'c=effort:%7E%21%27%28%29%2A,a%27b';
  const chip = (state: string) => state.split('&').find((part) => part.startsWith('c='));
  expect(chip(writeState(readState(written)))).toBe(written);
});

test("a bound typed with :00 seconds is written without them, as the server writes it", () => {
  const time = (state: string) => state.split('&').find((part) => part.startsWith('t='));
  expect(time(writeState(readState('t=c,2026-11-01T08%3A30%3A00,')))).toBe('t=c,2026-11-01T08%3A30,');
  expect(time(writeState(readState('t=c,2026-11-01T08%3A30%3A15,2026-11-02T09%3A00%3A00')))).toBe(
    't=c,2026-11-01T08%3A30%3A15,2026-11-02T09%3A00',
  );
});
