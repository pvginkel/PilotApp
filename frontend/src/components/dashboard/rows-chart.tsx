/**
 * The Rows presentation (F163.3; the mockup's `rows.js`), drawn from its geometry
 * (`rows-layout.ts`) at the card's width, down to 320 px: the legend of the color's values, each
 * with the first stacked measure's amount and its share of All; the headings' row, the page's own
 * elements over the chart's columns, in sight while the rows scroll; the All row; a row per value
 * of the By, its label cut to its column and whole in its tooltip where it is cut, its time under
 * it where the By's values have one; each measure's bar, split by the color, and figure; the
 * peers' median per column. Past 40 rows, Show all draws up to 1,000 until what is shown changes.
 * A row is a button where the view drills into its value (`onDrill`, by its place in the answer).
 */

import { useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
import type { Measure } from '@/lib/dashboard/clip';
import { figure, percent, whole } from '@/lib/dashboard/figures';
import { layOut, SHOW_ALL, type Layout, type Rows } from '@/lib/dashboard/rows-layout';
import { cn } from '@/lib/utils';

const measures = new Map<string, Measure>();

/** Text measured on a canvas in `family`, the font the chart's text is drawn in. */
function measureIn(family: string): Measure {
  let found = measures.get(family);
  if (found === undefined) {
    const context = document.createElement('canvas').getContext('2d') as CanvasRenderingContext2D;
    found = (text, size, weight) => {
      context.font = `${weight} ${size}px ${family}`;
      return context.measureText(text).width;
    };
    measures.set(family, found);
  }
  return found;
}

/** The width of what `ref` holds, and the font it draws text in, as they stand. */
function useBox(ref: RefObject<HTMLDivElement | null>): { width: number; measure: Measure | null } {
  const [box, setBox] = useState<{ width: number; measure: Measure | null }>({ width: 0, measure: null });
  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const measure = measureIn(getComputedStyle(element).fontFamily);
    const read = () => setBox((was) => (was.width === element.clientWidth && was.measure === measure ? was : { width: element.clientWidth, measure }));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return box;
}

interface RowsChartProps {
  rows: Rows;
  relative: boolean;
  onDrill: ((index: number) => void) | undefined;
}

export function RowsChart({ rows, relative, onDrill }: RowsChartProps) {
  const holder = useRef<HTMLDivElement>(null);
  const { width, measure } = useBox(holder);
  // Show all holds for the answer it was asked on.
  const [allFor, setAllFor] = useState<string | null>(null);
  const all = allFor === rows.address;
  const layout = width > 0 && measure !== null ? layOut(rows, { width, relative, all, measure }) : null;
  return (
    <>
      <Legend rows={rows} />
      <div ref={holder} className="bars">
        {layout !== null && (
          <>
            <Headings layout={layout} />
            {layout.rows.length === 0 ? (
              <div className="empty" data-testid="dashboard.empty">
                Nothing in this scope
              </div>
            ) : (
              <Plot layout={layout} onDrill={onDrill} />
            )}
            {layout.total > layout.shown && (
              <div className="showall" data-testid="dashboard.cut">
                The first {whole(layout.shown)} of {whole(layout.total)} rows, in this order
                {all ? (
                  ` (show all: at most ${whole(SHOW_ALL)})`
                ) : (
                  <>
                    {' · '}
                    <button type="button" className="btn btn-sm" onClick={() => setAllFor(rows.address)} title={`Raise the cap to ${whole(SHOW_ALL)} until what is shown changes`}>
                      {layout.total > SHOW_ALL ? `Show the first ${whole(SHOW_ALL)}` : `Show all ${whole(layout.total)}`}
                    </button>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

/** The color's values, with the first stacked measure's amounts and their shares of All. */
function Legend({ rows }: { rows: Rows }) {
  const color = rows.color;
  if (color === null) return null;
  const stacked = rows.measures.findIndex((measure) => measure.stacks);
  if (stacked < 0) {
    return (
      <div className="legend" data-testid="dashboard.legend">
        <span className="lbl">Color {color.label}: no measure shown stacks.</span>
      </div>
    );
  }
  const measure = rows.measures[stacked];
  const total = rows.all.values[stacked] ?? 0;
  return (
    <div className="legend" data-testid="dashboard.legend">
      <span className="lbl">
        {color.label}, by {measure.label}
      </span>
      {color.values.map((value, index) => (
        <span key={value.others > 0 ? '…' : String(value.key)} className="lg" data-testid="dashboard.legend.value">
          <span className="sw" style={{ background: value.others > 0 ? 'var(--series-other)' : `var(--series-${index % 20})` }} />
          {value.label ?? String(value.key)}
          <span className="amt">
            {figure(measure.format, value.total)}
            {total && value.total !== null ? ` · ${percent(value.total / total)}` : ''}
          </span>
        </span>
      ))}
    </div>
  );
}

/** The headings' row: the By and n, each measure's heading at its column's start, the columns' rules through it. */
function Headings({ layout }: { layout: Layout }) {
  const { head } = layout;
  return (
    <div className="dash-heads rowheads" style={{ width: layout.width, height: head.height }} data-testid="dashboard.heads">
      <svg width={layout.width} height={head.height} className="chart rowschart" aria-hidden="true">
        {layout.rules.map((x) => (
          <line key={x} x1={x} x2={x} y1={2} y2={head.height} className="grid" />
        ))}
      </svg>
      <span className="colhead" style={{ left: 6, maxWidth: head.by.room }} data-testid="dashboard.heads.by">
        <span className="t">{head.by.words}</span>
      </span>
      <span className="colhead" style={{ right: head.nRight }} title="The items behind the first measure">
        <span className="t">n</span>
      </span>
      {head.columns.map((column, index) => (
        <span key={index} className="colhead mcol" style={{ left: column.x, maxWidth: column.width }} data-testid="dashboard.heads.measure">
          <span className="t">{column.words}</span>
        </span>
      ))}
    </div>
  );
}

function Plot({ layout, onDrill }: { layout: Layout; onDrill: RowsChartProps['onDrill'] }) {
  const { all } = layout;
  const press = (index: number) => ({
    role: 'button',
    tabIndex: 0,
    onClick: () => onDrill!(index),
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      onDrill!(index);
    },
  });
  return (
    <svg width={layout.width} height={layout.height} className="chart rowschart" data-testid="dashboard.rows">
      {layout.rules.map((x) => (
        <line key={x} x1={x} x2={x} y1={0} y2={layout.height - 2} className="grid" />
      ))}
      <g className="allrow" data-testid="dashboard.all">
        <rect x={0} y={all.y} width={layout.width} height={all.height} rx={4} className="allbg" />
        <text x={6} y={all.baseline} className="alltext">
          {all.words}
        </text>
        <text x={layout.nX} y={all.baseline} className="muted" textAnchor="end">
          {all.n}
        </text>
        {all.values.map((value, index) => (
          <text key={index} x={value.x} y={all.baseline} className="alltext" data-testid="dashboard.all.value">
            {value.words}
          </text>
        ))}
      </g>
      <line x1={0} x2={layout.width} y1={layout.top - 2} y2={layout.top - 2} className="grid" />
      {layout.rows.map((row, index) => (
        <g
          key={index}
          className={cn('row', row.marked && 'marked', onDrill !== undefined && 'drill')}
          aria-label={onDrill === undefined ? undefined : row.whole}
          {...(onDrill === undefined ? {} : press(index))}
          data-key={row.key}
          data-testid="dashboard.row"
        >
          <rect x={0} y={row.y} width={layout.width} height={layout.rowHeight - 2} rx={4} className="bg" />
          <g>
            {row.label !== row.whole && <title data-testid="dashboard.row.whole">{row.whole}</title>}
            <text x={6} y={row.first} className="lab" data-testid="dashboard.row.label">
              {row.label}
            </text>
          </g>
          {row.at !== null && (
            <text x={6} y={row.second} className="muted at" data-testid="dashboard.row.at">
              {row.at}
            </text>
          )}
          <text x={layout.nX} y={row.first} className="muted" textAnchor="end">
            {row.n}
          </text>
          {row.cells.map((cell, column) => (
            <g key={column}>
              {cell.segments.map((segment, part) => (
                <rect key={part} x={segment.x} y={row.barY} width={segment.width} height={layout.barHeight} className="bseg" style={{ fill: segment.fill }} />
              ))}
              {cell.mark !== null && <rect x={cell.mark.x} y={row.barY + layout.barHeight + 1} width={cell.mark.width} height={2.5} className="markline" />}
              <text x={cell.text.x} y={row.barY + layout.barHeight / 2 + 4} className="muted" data-testid="dashboard.row.value">
                {cell.text.words}
              </text>
            </g>
          ))}
        </g>
      ))}
      {layout.medians.map((median, index) => (
        <g key={index}>
          <line x1={median.x} x2={median.x} y1={layout.top - 2} y2={layout.bottom} className="medtick" />
          <g>
            <title>{median.title}</title>
            <text x={median.labelX} y={layout.bottom + 28} className="medlab" textAnchor="middle" data-testid="dashboard.median">
              {median.words}
            </text>
          </g>
        </g>
      ))}
    </svg>
  );
}
