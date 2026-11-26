/**
 * The view's time, in the global toolbar (F162.1, F162.2; the mockup's `time.js`, `renderTime` and
 * `timePopover`). Collapsed, a button of the time in a few words, as a view's time is worded on
 * the panel (`timeWords`): "Quota week 46", "Last 7 days", "7 Nov – 13 Nov"; its title the time the
 * view reads, exactly, from the rows' answer. Its popover: at the left From and To over a month's
 * calendar, and Apply; at the right the catalogue's ranges, then its quota weeks, newest first;
 * at the foot the zone the times are in and when the running quota week started there.
 *
 * A field is typed day first or ISO, a time of day after it or none, and an empty one is an open
 * bound, but never both. A pick on the calendar is two days, the earlier the start, a day after
 * today out of reach; each field keeps the time of day of its bound where one was typed, in the
 * field or in the range at hand, and drops it otherwise. A quota week is written by the instant it
 * starts, its key, as two weeks may share a label. The weeks follow the usage readings, so the
 * catalogue's time is read again as the popover opens. A time set closes the popover; it is a new
 * entry (F160.4).
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CalendarClock, ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Popover } from '@/components/shared/popover';
import { useViewWords } from '@/hooks/use-view-words';
import { timeWords, weekWords, type Words } from '@/lib/dashboard/describe';
import { catalogueQuery, type Catalogue } from '@/lib/dashboard/queries';
import type { Rows } from '@/lib/dashboard/rows-layout';
import type { ViewState } from '@/lib/dashboard/state';
import {
  boundAt,
  boundKey,
  boundText,
  dayName,
  dayNumber,
  dayOf,
  daysIn,
  dayWords,
  exactWords,
  inOrder,
  lastDayOf,
  monthWords,
  parseBound,
  readBound,
  spanWords,
  startedWords,
  WEEKDAYS,
  weekdayOf,
  type Bound,
} from '@/lib/dashboard/time';
import { cn } from '@/lib/utils';

type Time = ViewState['time'];

interface TimePickerProps {
  state: ViewState;
  /** The time the view reads, as its rows' answer gives it; none where the answer drawn is of another time. */
  window: Rows['window'] | undefined;
  onTime: (time: Time) => void;
}

export function TimePicker({ state, window, onTime }: TimePickerProps) {
  const words = useViewWords();
  const zone = words.time?.zone;
  const title = window === undefined || zone == null ? null : exactWords(window, zone, state.time.kind === 'between', new Date());
  return (
    <Popover
      label="Time"
      anchorClassName="dash-time"
      className="dash-time-pop"
      testId="dashboard.time-picker"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="btn btn-sm"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          title={title ?? undefined}
          data-testid="dashboard.time"
        >
          <CalendarClock className="icon" aria-hidden="true" />
          <span className="t" data-testid="dashboard.time.words">
            {timeWords(state.time, words)}
          </span>
          <ChevronDown className="icon chev" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => (
        <TimePane
          state={state}
          window={window}
          words={words}
          onTime={(time) => {
            close();
            onTime(time);
          }}
        />
      )}
    </Popover>
  );
}

interface PaneProps extends TimePickerProps {
  words: Words;
}

function TimePane(props: PaneProps) {
  const time = useQuery({ ...catalogueQuery('time'), staleTime: 0 }).data;
  if (time === undefined) return <p className="empty dash-time-wait">Loading the time…</p>;
  return <TimeForm {...props} time={time} />;
}

/** The bounds the fields open on: a range's own; a range's or a week's from the answer, to the minute, its end no later than now; none for all time. */
function openingBounds(time: Time, window: Rows['window'] | undefined, zone: string): [Bound | null, Bound | null] {
  if (time.kind === 'between') return [time.start === null ? null : readBound(time.start), time.end === null ? null : readBound(time.end)];
  if (window == null || window.length === 0) return [null, null];
  const now = new Date();
  const start = window[0].start;
  const end = window[window.length - 1].end;
  return [start === null ? null : boundAt(new Date(start), zone), end === null ? null : boundAt(new Date(Math.min(Date.parse(end), now.getTime())), zone)];
}

/** Where a day pick is under way: the day it started on, and the day under the pointer. */
interface DayPick {
  first: number;
  over: number;
}

function TimeForm({ state, window, words, onTime, time }: PaneProps & { time: Catalogue }) {
  const zone = time.zone!;
  const [today] = useState(() => boundAt(new Date(), zone));
  const todayNo = dayNumber(today);
  const [opening] = useState(() => openingBounds(state.time, window, zone));
  const [from, setFrom] = useState(opening[0] === null ? '' : boundText(opening[0]));
  const [to, setTo] = useState(opening[1] === null ? '' : boundText(opening[1]));
  // A field's time of day is the person's where they typed it, here or in the range at hand: a pick keeps it.
  const custom = state.time.kind === 'between';
  const [typed, setTyped] = useState({ from: custom, to: custom });
  const [pick, setPick] = useState<DayPick | null>(null);
  const [month, setMonth] = useState(() => {
    const at = opening[1] ?? opening[0] ?? today;
    const shown = dayNumber(at) > todayNo ? today : at;
    return { year: shown.year, month: shown.month };
  });
  const list = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const own = list.current!;
    const on = own.querySelector<HTMLElement>('.on');
    if (on !== null) own.scrollTop = Math.max(0, on.offsetTop - own.clientHeight / 2);
  }, []);

  const start = parseBound(from, today.year);
  const end = parseBound(to, today.year);
  const order = start == null || end == null || inOrder(start, end);
  const range = start !== undefined && end !== undefined && (start !== null || end !== null) && order ? { start, end } : null;
  const apply = () => {
    if (range !== null) onTime({ kind: 'between', start: range.start === null ? null : boundKey(range.start), end: range.end === null ? null : boundKey(range.end) });
  };

  const type = (field: 'from' | 'to', text: string) => {
    (field === 'from' ? setFrom : setTo)(text);
    setTyped((was) => ({ ...was, [field]: true }));
    setPick(null);
    const bound = parseBound(text, today.year);
    if (bound != null && dayNumber(bound) <= todayNo) setMonth({ year: bound.year, month: bound.month });
  };
  const press = (n: number) => {
    if (pick === null) {
      setPick({ first: n, over: n });
      return;
    }
    const keep = (bound: Bound | null | undefined, kept: boolean, day: number): Bound => ({ ...dayOf(day), time: kept && bound != null ? bound.time : null });
    setFrom(boundText(keep(start, typed.from, Math.min(pick.first, n))));
    setTo(boundText(keep(end, typed.to, Math.max(pick.first, n))));
    setPick(null);
  };
  const step = (by: number) => {
    const at = new Date(Date.UTC(month.year, month.month - 1 + by, 1));
    setMonth({ year: at.getUTCFullYear(), month: at.getUTCMonth() + 1 });
  };

  // The days painted: those of the pick under way, else of the range the fields hold.
  let low = Number.NaN;
  let high = Number.NaN;
  if (pick !== null) {
    low = Math.min(pick.first, pick.over);
    high = Math.max(pick.first, pick.over);
  } else if (range !== null) {
    low = range.start === null ? -Infinity : dayNumber(range.start);
    high = range.end === null ? Infinity : lastDayOf(range.end);
  }
  const first = dayNumber({ ...month, day: 1 });
  const lead = weekdayOf({ ...month, day: 1 });
  const days = Array.from({ length: daysIn(month.year, month.month) }, (_, index) => first + index);
  const atToday = month.year === today.year && month.month === today.month;

  const ranges = time.ranges ?? [];
  const weeks = time.quota_weeks ?? [];
  const running = weeks.find((week) => week.running);
  const one = state.time.kind === 'weeks' && state.time.starts.length === 1 ? Date.parse(state.time.starts[0]) : null;

  const field = (name: 'from' | 'to', label: string, text: string, bad: boolean) => (
    <label className="dash-time-field">
      <span className="lbl">{label}</span>
      <input
        type="text"
        className={cn('field', bad && 'bad')}
        value={text}
        placeholder="Day, or day and time"
        autoComplete="off"
        spellCheck={false}
        aria-invalid={bad}
        onChange={(event) => type(name, event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            apply();
          }
        }}
        data-testid={`dashboard.time-picker.${name}`}
      />
    </label>
  );

  return (
    <div className="dash-timepick">
      <div className="dash-time-range">
        <div className="dash-time-fields">
          {field('from', 'From', from, start === undefined)}
          {field('to', 'To', to, end === undefined || !order)}
        </div>
        <div className={cn('dash-cal', pick !== null && 'picking')} data-testid="dashboard.time-picker.calendar">
          <div className="dash-cal-head">
            <button type="button" className="btn btn-ghost btn-sm btn-icon" title="The month before" aria-label="The month before" onClick={() => step(-1)} data-testid="dashboard.time-picker.before">
              <ChevronLeft className="icon" aria-hidden="true" />
            </button>
            <span className="month" data-testid="dashboard.time-picker.month">
              {monthWords(month.year, month.month)}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-icon"
              title="The month after"
              aria-label="The month after"
              disabled={atToday}
              onClick={() => step(1)}
              data-testid="dashboard.time-picker.after"
            >
              <ChevronRight className="icon" aria-hidden="true" />
            </button>
          </div>
          <div className="dash-cal-grid">
            {WEEKDAYS.map((weekday) => (
              <span key={weekday} className="wd" title={weekday}>
                {weekday.slice(0, 2)}
              </span>
            ))}
            {Array.from({ length: lead }, (_, index) => (
              <span key={`pad${index}`} />
            ))}
            {days.map((n) => {
              const day = dayOf(n);
              const within = n >= low && n <= high;
              const edge = within && (n === low || n === high);
              return (
                <button
                  key={n}
                  type="button"
                  className={cn('day', n === todayNo && 'today', within && 'in', edge && 'end', within && n === low && 'first', within && n === high && 'last')}
                  disabled={n > todayNo}
                  aria-label={dayName(day)}
                  aria-pressed={edge}
                  onClick={() => press(n)}
                  onMouseEnter={() => {
                    if (pick !== null && pick.over !== n) setPick({ ...pick, over: n });
                  }}
                  data-testid="dashboard.time-picker.day"
                >
                  {day.day}
                </button>
              );
            })}
          </div>
        </div>
        <div className="dash-time-apply">
          <button type="button" className="btn btn-primary btn-sm" disabled={range === null} onClick={apply} data-testid="dashboard.time-picker.apply">
            Apply
          </button>
        </div>
      </div>
      <div className="dash-time-quick">
        <div ref={list} className="list" data-testid="dashboard.time-picker.quick">
          {ranges.map((each) => {
            const on = state.time.kind === 'preset' && state.time.key === each.key;
            return (
              <button
                key={each.key}
                type="button"
                className={cn('menu-item', on && 'on')}
                aria-pressed={on}
                title={each.line}
                onClick={() => onTime({ kind: 'preset', key: each.key })}
                data-testid="dashboard.time-picker.range"
              >
                {each.label}
              </button>
            );
          })}
          {weeks.length > 0 && <div className="menu-head">Quota weeks</div>}
          {weeks.map((week) => {
            const on = one === Date.parse(week.starts_at);
            return (
              <button
                key={week.starts_at}
                type="button"
                className={cn('menu-item', on && 'on')}
                aria-pressed={on}
                title={spanWords(week.starts_at, week.ends_at, zone)}
                onClick={() => onTime({ kind: 'weeks', starts: [week.starts_at] })}
                data-testid="dashboard.time-picker.week"
              >
                <span>Week {weekWords(week.starts_at, { ...words, time })}</span>
                <span className="sub">{dayWords(week.starts_at, zone)}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="dash-time-foot" data-testid="dashboard.time-picker.foot">
        <span>Times in {zone}</span>
        {running !== undefined && <span>This quota week started {startedWords(running.starts_at, zone)}</span>}
      </div>
    </div>
  );
}
