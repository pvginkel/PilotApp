/**
 * The measures are the view's columns, with no chip (F163.4, F163.5; the mockup's `heads.js` and
 * `view.js`): each shown and changed in its heading, a column's in the rows and in a table, through
 * what `use-measure-heads.ts` gives.
 *
 * A heading is the measure's name (`measures.ts`), which sorts by its column, with the arrow of the
 * sort the rows are drawn in; at its right the menu's sign and a ×, the last measure having none:
 * both show under the pointer and while the keyboard's focus is inside the heading, a name cut to
 * its column then cut short of them. The menu's sign opens the heading's panel under it, held in
 * the window so that a table's scroll does not cut it: the aggregate and the grain of a figure's
 * measure, a ratio's two sides; it closes by its ×, by Esc and by a press outside it. A heading
 * lifted fades in place, its name following the pointer and a line marking its drop.
 *
 * + Measure lists the catalogue's measures in their groups and adds one as the last column, the
 * entry in place (F160.4). Where the By refuses a measure, the card says which, and the one that
 * stands in for it where one does (F163.5).
 */

import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Ellipsis, Plus, X } from 'lucide-react';
import { Popover } from '@/components/shared/popover';
import { useDismiss } from '@/hooks/use-dismiss';
import type { Heads } from '@/hooks/use-measure-heads';
import { useViewWords } from '@/hooks/use-view-words';
import { measureWords, type Words } from '@/lib/dashboard/describe';
import { added, aggregatesOf, grainOf, grainsOf, measureMenu, overGrain } from '@/lib/dashboard/measures';
import { measureKey, readState, type ViewState } from '@/lib/dashboard/state';
import { cn } from '@/lib/utils';
import { Segmented } from './segmented';

/** The view moved to `state`, a new entry, or the entry in place where `replace`. */
type Place = (state: ViewState, replace?: boolean) => void;

interface MeasureHeadProps {
  heads: Heads;
  /** The measure's place among the answer's. */
  j: number;
  /** Its name cut to its column at rest, and short of its controls under the pointer; none where its column grows to the name whole. */
  cut?: { rest: string; hover: string };
}

/** A measure's heading: its name, which sorts, the arrow of the sort, the menu's sign and its ×; its panel under it while open. */
export function MeasureHead({ heads, j, cut }: MeasureHeadProps) {
  const answered = heads.rows.measures[j];
  const name = heads.names[j];
  const open = heads.open === j;
  const anchor = useDismiss('plan', open, heads.close);
  const [pointed, setPointed] = useState(false);
  const [focused, setFocused] = useState(false);
  const sorted = heads.rows.sort.column === answered.key ? heads.rows.sort.direction : null;
  const words = cut === undefined ? name : pointed || focused || open ? cut.hover : cut.rest;
  const press = sorted === 'desc' ? 'A press sorts the smallest first' : 'A press sorts by it, the largest first';
  return (
    <div
      ref={anchor}
      className={cn('dash-mhead', sorted !== null && 'on', open && 'open', answered.refused !== null && 'refused', heads.drag?.from === j && 'dragging')}
      onPointerDown={(event) => heads.press(j, event)}
      onPointerEnter={() => setPointed(true)}
      onPointerLeave={() => setPointed(false)}
      onFocus={() => setFocused(true)}
      onBlur={(event) => setFocused(event.currentTarget.contains(event.relatedTarget as Node | null))}
      data-testid="dashboard.measure"
    >
      <button type="button" className="name" title={`${heads.titles[j]}\n${press}`} onClick={() => heads.sort(j)} data-testid="dashboard.measure.sort">
        <span className="t" data-testid="dashboard.heads.measure">
          {words}
        </span>
        {sorted !== null && (
          <span className="arr" aria-hidden="true" data-testid="dashboard.measure.arrow">
            {sorted === 'asc' ? '▲' : '▼'}
          </span>
        )}
      </button>
      <button
        type="button"
        className="ctl menu"
        title="Change this measure"
        aria-label={`Change the measure ${name}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => heads.toggle(j)}
        data-testid="dashboard.measure.menu"
      >
        <Ellipsis className="icon" aria-hidden="true" />
      </button>
      {heads.rows.measures.length > 1 && (
        <button type="button" className="ctl x" title="Remove this measure" aria-label={`Remove the measure ${name}`} onClick={() => heads.remove(j)} data-testid="dashboard.measure.remove">
          <X className="icon" aria-hidden="true" />
        </button>
      )}
      {open && heads.state.measures[j] !== undefined && <HeadPanel heads={heads} j={j} anchor={anchor} />}
    </div>
  );
}

const capital = (text: string) => `${text.charAt(0).toUpperCase()}${text.slice(1)}`;

/** A measure as a state writes it, in its words. */
const writtenWords = (written: string, words: Words) => measureWords(readState(`m=${written}`).measures[0], words);

/** A heading's panel, under it, held in the window so that a table's scroll does not cut it: the measure's aggregate and grain, or a ratio's sides. */
function HeadPanel({ heads, j, anchor }: { heads: Heads; j: number; anchor: RefObject<HTMLDivElement | null> }) {
  const words = useViewWords();
  const measure = heads.state.measures[j];
  const box = useRef<HTMLDivElement>(null);
  // Placed under its heading at each draw, the heading moving with the answer, and as anything scrolls.
  useLayoutEffect(() => {
    const place = () => {
      const at = anchor.current?.getBoundingClientRect();
      const own = box.current;
      if (at === undefined || own === null) return;
      own.style.top = `${at.bottom + 6}px`;
      own.style.left = `${Math.max(12, Math.min(at.left, window.innerWidth - own.offsetWidth - 12))}px`;
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  });
  const name = measureWords(measure, words);
  const figure = measure.kind === 'simple' ? words.measures?.figures?.find((each) => each.key === measure.figure) : undefined;
  const ratio = measure.kind === 'ratio' ? words.measures?.ratios?.find((each) => each.key === measure.key) : undefined;
  return (
    <div ref={box} className="popover dash-headpane" role="dialog" aria-label={`The measure ${name}`} data-testid="dashboard.measure-pane">
      <div className="dash-valuepane">
        <div className="panehead">
          <span className="t" title={name} data-testid="dashboard.measure-pane.name">
            {name}
          </span>
          <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Close" aria-label="Close" onClick={heads.close} data-testid="dashboard.measure-pane.close">
            <X className="icon" aria-hidden="true" />
          </button>
        </div>
        {measure.kind === 'simple' ? (
          <>
            <div className="menu-head">Aggregate</div>
            <Segmented
              label="Aggregate"
              value={measure.aggregate}
              onChange={(aggregate) => {
                if (aggregate !== measure.aggregate) heads.change(j, { ...measure, aggregate });
              }}
              options={aggregatesOf(words.measures, measure.figure).map((aggregate) => ({
                value: aggregate.key,
                label: aggregate.label,
                title: aggregate.line,
                testId: `dashboard.measure-pane.aggregate.${aggregate.key}`,
              }))}
            />
            <div className="menu-head" title="The aggregate takes the figure of each item: a part's items each sum their fact's rows first">
              Over items at the grain of
            </div>
            <Segmented
              label="Grain"
              value={grainOf(words.measures, measure)}
              onChange={(grain) => {
                if (grain !== null && grain !== grainOf(words.measures, measure)) heads.change(j, overGrain(words.measures, measure, grain));
              }}
              options={grainsOf(words.measures, words.dimensions, measure.figure).map((grain) => ({
                value: grain.key,
                label: capital(grain.one),
                testId: `dashboard.measure-pane.grain.${grain.key}`,
              }))}
            />
            {figure !== undefined && <p className="note">{figure.line}</p>}
          </>
        ) : (
          <p className="note" data-testid="dashboard.measure-pane.ratio">
            {measure.kind === 'ratio'
              ? (ratio?.line ?? (ratio === undefined ? measure.key : `${writtenWords(ratio.numerator, words)} ÷ ${writtenWords(ratio.denominator, words)}`))
              : `${measureWords(measure.numerator, words)} ÷ ${measureWords(measure.denominator, words)}`}
          </p>
        )}
      </div>
    </div>
  );
}

/** A heading dragged: its name following the pointer, and the line marking where it would drop. */
export function DragLayer({ heads }: { heads: Heads | null }) {
  const drag = heads?.drag;
  if (drag == null) return null;
  return (
    <>
      <div className="dash-dragghost" style={{ left: drag.left, top: drag.top }} data-testid="dashboard.drag-ghost">
        {drag.name}
      </div>
      {drag.mark !== null && <div className="dash-dropmark" style={drag.mark} data-testid="dashboard.drop-mark" />}
    </>
  );
}

/** + Measure, which leads the card head's right group: the catalogue's measures in their groups, one picked joining the columns at their end. */
export function AddMeasure({ state, onState }: { state: ViewState; onState: Place }) {
  const words = useViewWords();
  const shown = new Set(state.measures.map(measureKey));
  return (
    <Popover
      label="Add a measure"
      className="dash-list-pop end"
      testId="dashboard.add-measure.pop"
      trigger={({ open, toggle }) => (
        <button type="button" className="btn btn-sm" aria-haspopup="dialog" aria-expanded={open} title="Add a measure: a column" onClick={toggle} data-testid="dashboard.add-measure">
          <Plus className="icon" aria-hidden="true" />
          Measure
        </button>
      )}
    >
      {(close) =>
        words.measures === undefined ? (
          <p className="empty dash-pane-wait">Loading the measures…</p>
        ) : (
          <div className="dash-dimlist" data-testid="dashboard.add-measure.list">
            {measureMenu(words.measures).map((group) => (
              <div key={group.heading} role="group" aria-label={group.heading} className="dash-dimgroup" data-testid="dashboard.add-measure.group">
                <div className="menu-head">{group.heading}</div>
                {group.entries.map((entry) => {
                  const key = measureKey(entry.measure);
                  const on = shown.has(key);
                  return (
                    <div key={key} className={cn('dash-dimrow', on && 'on')} data-key={key} data-testid="dashboard.add-measure.entry">
                      <button
                        type="button"
                        className="menu-item"
                        title={entry.line ?? undefined}
                        aria-current={on || undefined}
                        onClick={() => {
                          close();
                          onState(added(state, entry.measure), true);
                        }}
                        data-testid="dashboard.add-measure.entry.pick"
                      >
                        <span className="t">{entry.label}</span>
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )
      }
    </Popover>
  );
}

/** What the By refuses of the measures drawn, each with the one that stands in for it where one does. */
export function Refused({ heads }: { heads: Heads }) {
  const words = useViewWords();
  const { rows, names } = heads;
  const refused = rows.measures.flatMap((measure, j) => (measure.refused === null ? [] : [{ measure, name: names[j] }]));
  if (refused.length === 0) return null;
  return (
    <div className="dash-refused" data-testid="dashboard.refused">
      {refused.map(({ measure, name }) => (
        <p key={measure.key} data-testid="dashboard.refused.measure">
          {`${rows.by.label} refuses ${name}: ${measure.refused}`}
          {measure.stand_in !== null && `; ${words.measures === undefined ? measure.stand_in.label : writtenWords(measure.stand_in.key, words)} stands in for it`}.
        </p>
      ))}
    </div>
  );
}
