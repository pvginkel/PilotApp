/**
 * The view's scope, above its card (F162.3, F162.4; the mockup's `scope.js`, `renderDrill`,
 * `renderChips`, `filterPicker` and `valuePane`): in one line the drill path, then the chips, then
 * the filter picker.
 *
 * The drill path is one segmented bar: All first, then a segment per level of the drill stack, its
 * kind small and muted before what no level before it said (`pathWords`), the whole path its
 * title. A parent's press goes back to it with the By it had (`upTo`), All's clears the drill; the
 * last segment is where the view is, and no button.
 *
 * A chip: its kind's sign, a funnel where it filters and a diamond where it marks, which a press
 * flips; its words, which open a dimension's chip's pane, its values cut before "n more" and every
 * value in its tooltip, of a negated chip only "is not" marked out; its ×. At most 300 px wide.
 * The picker lists the parts and the attributes, no time: the time is the global toolbar's. A
 * dimension's pane lists its values in the view's scope without its own chips, each with its cost
 * and its rows, searched by the server; the values picked, Is or Is not, a filter or a mark. Each
 * change is a new entry (F160.4). Under the line the quick filters' (`quick-filters.tsx`, F162.6); a
 * pane's foot keeps the chip as the pane has it as a quick filter under a name, for everyone, no chip
 * joining the scope.
 */

import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Diamond, Filter, Plus, X } from 'lucide-react';
import { Popover } from '@/components/shared/popover';
import { useFailureShown } from '@/hooks/use-dashboard-view';
import { useViewWords } from '@/hooks/use-view-words';
import { useQuickFilterWrites } from '@/hooks/use-view-writes';
import { dimensionLabel } from '@/lib/dashboard/describe';
import { figure, whole } from '@/lib/dashboard/figures';
import { catalogueQuery, knowLabel, valuesQuery, valueText } from '@/lib/dashboard/queries';
import { chipDoes, chipText, chipWords, pathWords, upTo, type LabelOf } from '@/lib/dashboard/scope';
import { chipKey, type Chip, type ViewState } from '@/lib/dashboard/state';
import { cn } from '@/lib/utils';
import { useDebouncedValue } from '@/lib/utils/debounce';
import { QuickFilters } from './quick-filters';
import { Segmented } from './segmented';

type Pin = Extract<Chip, { kind: 'pin' }>;

/** The longest name a quick filter takes (`backend/app/schemas/dashboard_store.py`, `NAME`). */
const NAME_LENGTH = 60;

/** What the filter picker lists, in its groups. */
const GROUPS = [
  ['part', 'Parts'],
  ['attribute', 'Attributes'],
] as const;

/**
 * A pane dropped from the scope's line kept inside the main area, 12px short of its right edge,
 * where the main area would otherwise scroll sideways to show it.
 */
function keepInside(body: HTMLElement): void {
  const pop = body.parentElement!;
  const main = pop.closest('.dash-main')!;
  const over = pop.getBoundingClientRect().right - (main.getBoundingClientRect().left + main.clientWidth - 12);
  if (over > 0) pop.style.left = `${-over}px`;
}

interface ScopeProps {
  state: ViewState;
  /** The view's state without its look-only parts: what a pane's values are read in. */
  scope: string;
  label: LabelOf;
  /** The view moved to `state`, a new entry. */
  onState: (state: ViewState) => void;
}

export function Scope({ state, scope, label, onState }: ScopeProps) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const { chips } = state;
  const replaced = (index: number, chip: Chip) => chips.map((each, at) => (at === index ? chip : each));
  return (
    <section className="dash-scope" aria-label="Scope" data-testid="dashboard.scope">
      <div className="dash-line">
        <DrillPath state={state} label={label} onUp={(index) => onState(upTo(state, index, dimensions))} />
        {chips.map((chip, index) => (
          <ChipView
            key={index}
            chip={chip}
            scope={scope}
            label={label}
            onFlip={() => onState({ ...state, chips: replaced(index, { ...chip, marked: !chip.marked }) })}
            onApply={(next) => onState({ ...state, chips: replaced(index, next), selected: null })}
            onRemove={() => onState({ ...state, chips: chips.filter((_, at) => at !== index), selected: null, item: null, itemGrain: null })}
          />
        ))}
        <AddFilter scope={scope} label={label} onAdd={(chip) => onState({ ...state, chips: [...chips, chip], selected: null })} />
      </div>
      <QuickFilters state={state} scope={scope} label={label} onState={onState} />
    </section>
  );
}

function DrillPath({ state, label, onUp }: { state: ViewState; label: LabelOf; onUp: (index: number) => void }) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const { levels } = state;
  const labels = levels.map((level) => label(level.dimension, level.value));
  const words = pathWords(labels);
  const kinds = levels.map((level) => dimensionLabel(dimensions, level.dimension));
  const segment = (index: number, content: ReactNode) => {
    const here = index === levels.length - 1;
    const className = cn('crumb', index < 0 && 'all', here ? 'here' : 'up');
    return here ? (
      <span className={className} aria-current="location" data-testid="dashboard.path.segment">
        {content}
      </span>
    ) : (
      <button type="button" className={className} onClick={() => onUp(index)} data-testid="dashboard.path.segment">
        {content}
      </button>
    );
  };
  return (
    <nav className="dash-path" aria-label="Drill path" title={['All', ...labels.map((each, index) => `${kinds[index]} ${each}`)].join(' › ')} data-testid="dashboard.path">
      {segment(-1, 'All')}
      {levels.map((_, index) => (
        <Fragment key={index}>
          <svg className="crumb-sep" viewBox="0 0 9 28" preserveAspectRatio="none" aria-hidden="true">
            <path d="M0.5 0 L8.5 14 L0.5 28" vectorEffect="non-scaling-stroke" />
          </svg>
          {segment(
            index,
            <>
              <span className="k" data-testid="dashboard.path.kind">
                {kinds[index]}
              </span>
              <span className="v" data-testid="dashboard.path.value">
                {words[index]}
              </span>
            </>,
          )}
        </Fragment>
      ))}
    </nav>
  );
}

interface ChipProps {
  chip: Chip;
  scope: string;
  label: LabelOf;
  onFlip: () => void;
  onApply: (chip: Pin) => void;
  onRemove: () => void;
}

function ChipView({ chip, scope, label, onFlip, onApply, onRemove }: ChipProps) {
  const words = chipWords(chip, label, useViewWords());
  const flip = chip.marked ? 'Marks. Press to filter instead' : 'Filters. Press to mark instead: what it names is highlighted, nothing is filtered out';
  const title = `${words.all === null ? '' : `${words.all}\n`}${chipDoes(chip)}`;
  const text = (
    <>
      <span className="on">{words.on}</span>
      {words.not !== '' && (
        <span className="not" data-testid="dashboard.chip.not">
          {` ${words.not}`}
        </span>
      )}
      <span className="what">{words.what}</span>
      {words.more !== '' && <span className="more">, {words.more}</span>}
    </>
  );
  const body = (pane: { open: boolean; toggle: () => void } | null) => (
    <span className={cn('dash-chip', chip.marked ? 'mark' : 'filter')} data-kind={chip.kind} data-testid="dashboard.chip">
      <button type="button" className="kind" title={flip} aria-label={flip} onClick={onFlip} data-testid="dashboard.chip.kind">
        {chip.marked ? <Diamond className="icon" aria-hidden="true" /> : <Filter className="icon" aria-hidden="true" />}
      </button>
      {pane === null ? (
        <span className="lab" title={title} data-testid="dashboard.chip.words">
          {text}
        </span>
      ) : (
        <button type="button" className="lab" title={title} aria-haspopup="dialog" aria-expanded={pane.open} onClick={pane.toggle} data-testid="dashboard.chip.words">
          {text}
        </button>
      )}
      <button type="button" className="x" title="Remove" aria-label={`Remove the filter ${chipText(words)}`} onClick={onRemove} data-testid="dashboard.chip.remove">
        <X className="icon" aria-hidden="true" />
      </button>
    </span>
  );
  if (chip.kind !== 'pin') return body(null);
  return (
    <Popover label={chipText(words)} anchorClassName="dash-chip-anchor" className="dash-pane-pop" testId="dashboard.chip.pane" trigger={body} onOpened={keepInside}>
      {(close) => (
        <ValuePane
          dimension={chip.dimension}
          chip={chip}
          scope={scope}
          label={label}
          onDone={(next) => {
            close();
            onApply(next);
          }}
          onClose={close}
          onRemove={() => {
            close();
            onRemove();
          }}
        />
      )}
    </Popover>
  );
}

function AddFilter({ scope, label, onAdd }: { scope: string; label: LabelOf; onAdd: (chip: Pin) => void }) {
  return (
    <Popover
      label="Filter"
      anchorClassName="dash-chip-anchor"
      className="dash-pane-pop"
      testId="dashboard.filter"
      onOpened={keepInside}
      trigger={({ open, toggle }) => (
        <button type="button" className="btn btn-ghost btn-sm dash-add" aria-haspopup="dialog" aria-expanded={open} onClick={toggle} title="Filter or mark by a part or an attribute" data-testid="dashboard.add-filter">
          <Plus className="icon" aria-hidden="true" />
          Filter
        </button>
      )}
    >
      {(close) => (
        <FilterPicker
          scope={scope}
          label={label}
          onAdd={(chip) => {
            close();
            onAdd(chip);
          }}
          onClose={close}
        />
      )}
    </Popover>
  );
}

/** The parts and the attributes, a press on one opening its pane in the picker's place. */
function FilterPicker({ scope, label, onAdd, onClose }: { scope: string; label: LabelOf; onAdd: (chip: Pin) => void; onClose: () => void }) {
  const dimensions = useQuery(catalogueQuery('dimensions')).data?.dimensions;
  const [picked, setPicked] = useState<string | null>(null);
  if (picked !== null) return <ValuePane dimension={picked} chip={null} scope={scope} label={label} onDone={onAdd} onClose={onClose} />;
  if (dimensions == null) return <p className="empty dash-pane-wait">Loading the dimensions…</p>;
  return (
    <div className="dash-picker" data-testid="dashboard.filter.picker">
      {GROUPS.map(([group, heading]) => (
        <div key={group} role="group" aria-label={heading}>
          <div className="menu-head">{heading}</div>
          {dimensions
            .filter((dimension) => dimension.group === group)
            .map((dimension) => (
              <button key={dimension.key} type="button" className="menu-item" title={dimension.line} onClick={() => setPicked(dimension.key)} data-testid="dashboard.filter.dimension">
                {dimension.label}
              </button>
            ))}
        </div>
      ))}
    </div>
  );
}

interface PaneProps {
  dimension: string;
  /** The chip the pane edits; none for a new one. */
  chip: Pin | null;
  scope: string;
  label: LabelOf;
  onDone: (chip: Pin) => void;
  /** The pane closed, its chip kept as a quick filter. */
  onClose: () => void;
  /** A chip that is edited is removed. */
  onRemove?: () => void;
}

/** A dimension's values in the view's scope, those picked checked; Is or Is not; a filter or a mark. */
function ValuePane({ dimension, chip, scope, label, onDone, onClose, onRemove }: PaneProps) {
  const queryClient = useQueryClient();
  const words = useViewWords();
  const about = useQuery(catalogueQuery('dimensions')).data?.dimensions?.find((each) => each.key === dimension);
  const name = about?.label ?? dimension;
  const [typed, setTyped] = useState('');
  const search = useDebouncedValue(typed.trim(), 250);
  // Focused once the pane stands where it is shown, so that nothing scrolls to it before.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current!.focus({ preventScroll: true }), []);
  const values = useQuery({ ...valuesQuery(scope, dimension, search), placeholderData: keepPreviousData });
  useFailureShown(values);
  const [picked, setPicked] = useState<readonly (string | null)[]>(chip?.values ?? []);
  const [negated, setNegated] = useState(chip?.negated ?? false);
  const [marked, setMarked] = useState(chip?.marked ?? false);
  const listed = values.data?.values ?? [];
  const pick = (value: string | null) => setPicked((was) => (was.includes(value) ? was.filter((each) => each !== value) : [...was, value]));
  // The quick filter's name while it is asked, the foot's place; none, the foot.
  const [naming, setNaming] = useState<string | null>(null);
  /** The chip as the pane has it, those of its values listed first in the list's order. */
  const built = (): Pin => {
    const shown = listed.map((each) => valueText(each.key)).filter((value) => picked.includes(value));
    for (const each of listed) {
      const value = valueText(each.key);
      if (value !== null && picked.includes(value)) knowLabel(queryClient, dimension, value, each.label);
    }
    return { kind: 'pin', dimension, values: [...shown, ...picked.filter((value) => !shown.includes(value))], negated, marked };
  };
  const done = () => {
    if (picked.length > 0) onDone(built());
  };
  /** A value's words: as the pane lists it, else as the view names it. */
  const named: LabelOf = (of, value) => {
    const each = listed.find((one) => valueText(one.key) === value);
    return each === undefined ? label(of, value) : (each.label ?? label(of, value));
  };
  const total = values.data?.total ?? 0;
  return (
    <div className="dash-valuepane" data-testid="dashboard.pane">
      <div className="menu-head" title={about?.line}>
        {name}
      </div>
      <input
        ref={field}
        type="search"
        className="field"
        value={typed}
        placeholder={`Search ${name}`}
        aria-label={`Search ${name}`}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => setTyped(event.target.value)}
        data-testid="dashboard.pane.search"
      />
      <div className={cn('dash-values', values.isPlaceholderData && 'changing')} data-testid="dashboard.pane.values">
        {values.data === undefined ? (
          <p className="empty">{values.isError ? 'The values did not come.' : 'Loading the values…'}</p>
        ) : listed.length === 0 ? (
          <p className="empty">No value in this scope</p>
        ) : (
          listed.map((each) => {
            const value = valueText(each.key);
            return (
              <label key={value ?? '~'} className="dash-val" data-testid="dashboard.pane.value">
                <input type="checkbox" checked={picked.includes(value)} onChange={() => pick(value)} />
                <span className="l" data-testid="dashboard.pane.value.label">
                  {each.label ?? value}
                </span>
                <span className="a" data-testid="dashboard.pane.value.amount">
                  {each.cost === null ? whole(each.count) : `${figure('usd', each.cost)} · ${whole(each.count)}`}
                </span>
              </label>
            );
          })
        )}
      </div>
      {total > listed.length && (
        <p className="note" data-testid="dashboard.pane.cut">
          The first {whole(listed.length)} of {whole(total)}: a search finds the others
        </p>
      )}
      <div className="row">
        <Segmented
          label="Is or is not"
          value={negated}
          onChange={setNegated}
          options={[
            { value: false, label: 'Is', testId: 'dashboard.pane.is' },
            { value: true, label: 'Is not', testId: 'dashboard.pane.is-not' },
          ]}
        />
        <Segmented
          label="Filter or mark"
          value={marked}
          onChange={setMarked}
          options={[
            {
              value: false,
              label: (
                <>
                  <Filter className="icon" aria-hidden="true" />
                  Filter
                </>
              ),
              testId: 'dashboard.pane.filter',
            },
            {
              value: true,
              label: (
                <>
                  <Diamond className="icon" aria-hidden="true" />
                  Mark
                </>
              ),
              testId: 'dashboard.pane.mark',
            },
          ]}
        />
      </div>
      {naming === null ? (
        <div className="row foot">
          <button type="button" className="btn btn-primary btn-sm" disabled={picked.length === 0} onClick={done} data-testid="dashboard.pane.apply">
            {chip === null ? 'Add' : 'Apply'}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={picked.length === 0}
            onClick={() => setNaming(chipText(chipWords(built(), named, words)))}
            title="Keep it as a quick filter, for everyone: a press on it turns it on, with no chip added"
            data-testid="dashboard.pane.quick-filter"
          >
            Add as quick filter
          </button>
          {onRemove !== undefined && (
            <>
              <span className="grow" />
              <button type="button" className="btn btn-sm" onClick={onRemove} data-testid="dashboard.pane.remove">
                Remove
              </button>
            </>
          )}
        </div>
      ) : (
        <QuickFilterName name={naming} ready={picked.length > 0} chip={built} onName={setNaming} onBack={() => setNaming(null)} onSaved={onClose} />
      )}
    </div>
  );
}

interface QuickFilterNameProps {
  name: string;
  /** Whether the pane has a chip to keep. */
  ready: boolean;
  chip: () => Pin;
  onName: (name: string) => void;
  /** Esc: the foot again, the pane staying open. */
  onBack: () => void;
  onSaved: () => void;
}

/** A pane's foot asking the quick filter's name, filled with its chip's words: Enter or Save makes it, of the chip as the pane has it then. */
function QuickFilterName({ name, ready, chip, onName, onBack, onSaved }: QuickFilterNameProps) {
  const { add } = useQuickFilterWrites();
  const typed = name.trim();
  const save = () => {
    if (typed === '' || !ready || add.isPending) return;
    add.mutate({ label: typed, chip: chipKey(chip()) }, { onSuccess: onSaved });
  };
  return (
    <div className="row foot">
      <input
        type="text"
        className="field grow"
        value={name}
        maxLength={NAME_LENGTH}
        placeholder="The quick filter’s name"
        aria-label="The quick filter’s name"
        autoFocus
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => onName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') save();
          else if (event.key === 'Escape') onBack();
        }}
        data-testid="dashboard.pane.quick-filter.name"
      />
      <button type="button" className="btn btn-primary btn-sm" disabled={typed === '' || !ready || add.isPending} onClick={save} data-testid="dashboard.pane.quick-filter.save">
        Save
      </button>
    </div>
  );
}
