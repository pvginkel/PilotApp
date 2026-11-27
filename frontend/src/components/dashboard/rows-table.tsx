/**
 * The Table presentation (F163.3; the mockup's `table.js`, `renderTable`): the By's rows as a table
 * in the card, under the All row, its columns `table.ts`'s; a row's name and, where the By's values
 * have one, its time under it in the engine's zone; a marked row on the marks' tint, a diamond
 * before its name; each row's share of All with a bar against the largest's. It scrolls both ways
 * inside the card, its headings in sight above the rows. The first 1,000 rows are drawn; Copy and
 * CSV take them all.
 */

import type { Ref } from 'react';
import { dayTime } from '@/lib/dashboard/dates';
import { whole } from '@/lib/dashboard/figures';
import { SHOW_ALL, type Rows } from '@/lib/dashboard/rows-layout';
import { columnsOf, type Column } from '@/lib/dashboard/table';
import { cn } from '@/lib/utils';

/** The widest share's bar, in pixels. */
const BAR = 40;

interface RowsTableProps {
  rows: Rows;
  /** The box that scrolls, whose scroll the tab keeps. */
  scrollRef: Ref<HTMLDivElement>;
}

export function RowsTable({ rows, scrollRef }: RowsTableProps) {
  const columns = columnsOf(rows);
  const shown = rows.rows.slice(0, SHOW_ALL);
  const share = columns.find((column) => column.kind === 'share');
  const widest = share === undefined ? 0 : Math.max(...shown.map((row) => share.value(row) ?? 0), 1e-9);
  const cells = (line: Rows['all'], all: boolean) =>
    columns.map((column: Column, index) => {
      const value = column.value(line);
      return (
        <td key={index} className={cn('num', column.kind === 'n' && 'nn', column.kind === 'split' && 'sp')} data-testid="dashboard.table.cell">
          {column.words(value)}
          {column.kind === 'share' && !all && <span className="share" style={{ width: Math.round(((value ?? 0) / widest) * BAR) }} />}
        </td>
      );
    });
  return (
    <>
      <div ref={scrollRef} className="dash-tablewrap" data-testid="dashboard.table">
        <table className="dash-table">
          <thead>
            <tr>
              <th className="lab" data-testid="dashboard.heads.by">
                {rows.by.label}
              </th>
              {columns.map((column, index) => (
                <th
                  key={index}
                  className={cn('num', column.kind === 'n' && 'nn', column.kind === 'split' && 'sp')}
                  title={column.title ?? undefined}
                  data-testid={column.kind === 'measure' ? 'dashboard.heads.measure' : 'dashboard.table.head'}
                >
                  {column.swatch !== null && <span className="sw" style={{ background: column.swatch }} />}
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          {shown.length > 0 && (
            <tbody>
              <tr className="allrow" data-testid="dashboard.table.all">
                <td className="lab">All · {whole(rows.total_rows)}</td>
                {cells(rows.all, true)}
              </tr>
              {shown.map((row, index) => (
                <tr key={index} className={cn(row.marked && 'marked')} data-key={row.key === null ? '~' : String(row.key)} data-testid="dashboard.table.row">
                  <td className="lab">
                    <div className="t" data-testid="dashboard.table.row.label">
                      {`${row.marked ? '◇ ' : ''}${row.label ?? String(row.key)}`}
                    </div>
                    {row.at !== null && (
                      <div className="at" data-testid="dashboard.table.row.at">
                        {dayTime(row.at, rows.zone)}
                      </div>
                    )}
                  </td>
                  {cells(row, false)}
                </tr>
              ))}
            </tbody>
          )}
        </table>
        {shown.length === 0 && (
          <div className="empty" data-testid="dashboard.empty">
            Nothing in this scope
          </div>
        )}
      </div>
      {rows.rows.length > shown.length && (
        <div className="showall" data-testid="dashboard.cut">
          The first {whole(shown.length)} of {whole(rows.rows.length)} rows, in this order; Copy and CSV take them all
        </div>
      )}
    </>
  );
}
