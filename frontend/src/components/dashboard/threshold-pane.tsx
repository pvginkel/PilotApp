/**
 * A filter on a measure, its threshold's pane (F162.5; the mockup's `scope.js`, `thresholdPane`):
 * made from the measure's column, by Filter… in its heading's panel, where the pane's head has the
 * way back to that panel; opened from its chip's words to change it. On the By's rows it keeps the
 * rows that pass or marks them, and is never negated: no quick filter is made of one, since it hangs
 * on the By at hand. On each item of the measure's grain, its figure over all the item's rows, it
 * keeps the items that pass, or with Is not those that fail, or marks the rows that hold one; a
 * quick filter is made of one under a name, for everyone (F162.6). A ratio's threshold is on the
 * By's rows alone: an item has no ratio of its own, and the server refuses one on each item.
 */

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Diamond, Filter } from 'lucide-react';
import { useViewWords } from '@/hooks/use-view-words';
import { measureWords } from '@/lib/dashboard/describe';
import { chipText, chipWords, eachOf } from '@/lib/dashboard/scope';
import type { Chip, ViewState } from '@/lib/dashboard/state';
import { QuickFilterName } from './quick-filters';
import { Segmented } from './segmented';

type Measure = ViewState['measures'][number];
type Threshold = Extract<Chip, { kind: 'rows' | 'items' }>;
type Operator = Threshold['operator'];

const OPERATORS: readonly [Operator, string, string][] = [
  ['gt', '>', 'Greater than'],
  ['ge', '≥', 'At least'],
  ['lt', '<', 'Less than'],
  ['le', '≤', 'At most'],
];

/** Its words as a number, none where they are none. */
function numberOf(typed: string): number | null {
  const read = typed.trim() === '' ? NaN : Number(typed);
  return Number.isFinite(read) ? read : null;
}

interface ThresholdPaneProps {
  /** The measure it is on: the heading's, or the chip's own. */
  measure: Measure;
  /** The chip it changes; none for a new one. */
  chip: Threshold | null;
  onDone: (chip: Threshold) => void;
  /** Its quick filter made, the pane closed. */
  onClose: () => void;
  /** Back to the heading's panel it was opened from. */
  onBack?: () => void;
  /** A chip that is changed is removed. */
  onRemove?: () => void;
}

export function ThresholdPane({ measure, chip, onDone, onClose, onBack, onRemove }: ThresholdPaneProps) {
  const words = useViewWords();
  const simple = measure.kind === 'simple' ? measure : null;
  const [items, setItems] = useState(chip?.kind === 'items');
  const [operator, setOperator] = useState<Operator>(chip?.operator ?? 'gt');
  const [typed, setTyped] = useState(chip === null ? '' : String(chip.number));
  const [negated, setNegated] = useState(chip?.kind === 'items' && chip.negated);
  const [marked, setMarked] = useState(chip?.marked ?? false);
  // The quick filter's name while it is asked, the foot's place; none, the foot.
  const [naming, setNaming] = useState<string | null>(null);
  // Focused once the pane stands where it is shown, so that nothing scrolls to it before.
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => field.current!.focus({ preventScroll: true }), []);
  const number = numberOf(typed);
  const each = simple === null ? null : eachOf(simple, words);
  const onItems = items && simple !== null;
  /** The chip as the pane has it; none while its number is none. */
  const built = (): Threshold | null => {
    if (number === null) return null;
    if (onItems) return { kind: 'items', operator, number, measure: simple, negated, marked };
    return { kind: 'rows', operator, number, measure, marked };
  };
  const done = () => {
    const made = built();
    if (made !== null) onDone(made);
  };
  const name = measureWords(measure, words);
  const title = `Filter by ${name}`;
  return (
    <div className="dash-valuepane dash-threshold" data-testid="dashboard.threshold">
      <div className="panehead">
        {onBack !== undefined && (
          <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Back to the column’s menu" aria-label="Back to the column’s menu" onClick={onBack} data-testid="dashboard.threshold.back">
            <ArrowLeft className="icon" aria-hidden="true" />
          </button>
        )}
        <span className="t" title={title} data-testid="dashboard.threshold.name">
          {title}
        </span>
      </div>
      {each === null ? (
        <p className="note" data-testid="dashboard.threshold.rows-alone">
          On the By’s rows: an item has no ratio of its own
        </p>
      ) : (
        <Segmented
          label="What it is on"
          value={onItems}
          onChange={setItems}
          options={[
            { value: false, label: 'The By’s rows', title: 'Each row of the By at hand, its figure as the view shows it', testId: 'dashboard.threshold.rows' },
            { value: true, label: `Each ${each}`, title: `Each ${each}, its figure over all its rows`, testId: 'dashboard.threshold.items' },
          ]}
        />
      )}
      <div className="row">
        <Segmented
          label="Operator"
          value={operator}
          onChange={setOperator}
          options={OPERATORS.map(([value, sign, line]) => ({ value, label: sign, title: line, testId: `dashboard.threshold.op.${value}` }))}
        />
        <input
          ref={field}
          type="text"
          inputMode="decimal"
          className="field grow"
          value={typed}
          placeholder="A number"
          aria-label="The threshold"
          aria-invalid={typed.trim() !== '' && number === null}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') done();
          }}
          data-testid="dashboard.threshold.number"
        />
      </div>
      <div className="row">
        {onItems && (
          <Segmented
            label="Is or is not"
            value={negated}
            onChange={setNegated}
            options={[
              { value: false, label: 'Is', title: 'The items that pass', testId: 'dashboard.threshold.is' },
              { value: true, label: 'Is not', title: 'The items that fail', testId: 'dashboard.threshold.is-not' },
            ]}
          />
        )}
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
              testId: 'dashboard.threshold.filter',
            },
            {
              value: true,
              label: (
                <>
                  <Diamond className="icon" aria-hidden="true" />
                  Mark
                </>
              ),
              testId: 'dashboard.threshold.mark',
            },
          ]}
        />
      </div>
      {naming === null ? (
        <div className="row foot">
          <button type="button" className="btn btn-primary btn-sm" disabled={number === null} onClick={done} data-testid="dashboard.threshold.apply">
            {chip === null ? 'Add' : 'Apply'}
          </button>
          {onItems && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={number === null}
              onClick={() => setNaming(chipText(chipWords(built()!, () => '', words)))}
              title="Keep it as a quick filter, for everyone: a press on it turns it on, with no chip added"
              data-testid="dashboard.threshold.quick-filter"
            >
              Add as quick filter
            </button>
          )}
          {onRemove !== undefined && (
            <>
              <span className="grow" />
              <button type="button" className="btn btn-sm" onClick={onRemove} data-testid="dashboard.threshold.remove">
                Remove
              </button>
            </>
          )}
        </div>
      ) : (
        <QuickFilterName name={naming} ready={onItems && number !== null} chip={() => built()!} onName={setNaming} onBack={() => setNaming(null)} onSaved={onClose} />
      )}
    </div>
  );
}
