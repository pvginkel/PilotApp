/**
 * A custom ratio's form (F163.6, F155.1; the mockup's `view.js`, `ratioForm`): a name, a numerator
 * and a denominator, and the format its numbers are written in. Each side is a figure of the
 * catalogue under one of its aggregates, over the items of one of its grains, with filters of its
 * own (`measure := <figure>.<aggregate>[.<grain>][(<filter>;…)]`), each picked in a dimension's pane
 * in the form's place, Is or Is not, among the dimensions that reach the side's fact. The format is
 * the person's pick, by default the one a ratio of the two sides is given where no one picks
 * (`ratioFormat`), until they pick one. Save keeps it for everyone, under its key: a new one, or one
 * of theirs changed, which every view that shows it shows changed; a name another person's ratio has
 * is said under the field, which stays open. A change keeps the ratio's note, which the form does
 * not show.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, X } from 'lucide-react';
import { useValueLabels } from '@/hooks/use-value-labels';
import { useViewWords } from '@/hooks/use-view-words';
import { isNameTaken, useRatioWrites } from '@/hooks/use-view-writes';
import { dimensionLabel } from '@/lib/dashboard/describe';
import { aggregatesOf, FORMATS, grainOf, grainsOf, overGrain, ratioFormat, sideOf, type Simple } from '@/lib/dashboard/measures';
import { catalogueQuery, type CustomRatio } from '@/lib/dashboard/queries';
import { measureKey } from '@/lib/dashboard/state';
import { FilterPicker } from './scope';

type Format = (typeof FORMATS)[number];

/** The longest name a ratio takes (`backend/app/schemas/dashboard_store.py`, `NAME`). */
const NAME_LENGTH = 60;

/** Each format in words, what the ratio's numbers read as. */
const FORMAT_WORDS: Record<Format, string> = {
  usd: 'Dollars',
  tokens: 'Tokens',
  count: 'A number',
  seconds: 'A duration',
  share: 'A percentage',
};

type Side = 'numerator' | 'denominator';

const SIDE_WORDS: Record<Side, string> = { numerator: 'Numerator', denominator: 'Denominator' };

interface RatioFormProps {
  /** The person's ratio it changes; none for a new one. */
  ratio: CustomRatio | null;
  /** The view's state without its look-only parts: what a side's filter's values are read in. */
  scope: string;
  /** Saved, the ratio by its key. */
  onSaved: (key: string) => void;
  /** Back to what it was opened from. */
  onBack: () => void;
}

export function RatioForm({ ratio, scope, onSaved, onBack }: RatioFormProps) {
  const words = useViewWords();
  const { save } = useRatioWrites();
  const figures = words.measures?.figures ?? [];
  const [name, setName] = useState(ratio?.name ?? '');
  const [sides, setSides] = useState<Record<Side, Simple>>(() =>
    ratio === null
      ? { numerator: fresh(words, 'cost'), denominator: fresh(words, 'calls') }
      : { numerator: sideOf(ratio.numerator), denominator: sideOf(ratio.denominator) },
  );
  const [picked, setPicked] = useState<Format | null>(ratio?.format ?? null);
  const [filtering, setFiltering] = useState<Side | null>(null);
  const [taken, setTaken] = useState(false);
  const label = useValueLabels(Object.values(sides).flatMap((side) => side.filters.flatMap((filter) => filter.values.map((value) => ({ dimension: filter.dimension, value, scope })))));
  const format = picked ?? ratioFormat(words.measures, sides.numerator, sides.denominator);
  const typed = name.trim();
  const set = (side: Side, measure: Simple) => setSides((was) => ({ ...was, [side]: measure }));

  if (filtering !== null) {
    const side = sides[filtering];
    const fact = figures.find((figure) => figure.key === side.figure)?.fact ?? '';
    const back = () => setFiltering(null);
    return (
      <div className="dash-ratioform" data-testid="dashboard.ratio-form.filter">
        <div className="panehead">
          <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Back to the ratio" aria-label="Back to the ratio" onClick={back} data-testid="dashboard.ratio-form.filter.back">
            <ArrowLeft className="icon" aria-hidden="true" />
          </button>
          <span className="t">{`A filter of the ${SIDE_WORDS[filtering].toLowerCase()}’s own`}</span>
        </div>
        <FilterPicker
          scope={scope}
          label={label}
          forMeasure={fact}
          onAdd={(chip) => {
            set(filtering, { ...side, filters: [...side.filters.filter((filter) => filter.dimension !== chip.dimension), { dimension: chip.dimension, values: chip.values, negated: chip.negated }] });
            back();
          }}
          onClose={back}
        />
      </div>
    );
  }

  const submit = () => {
    if (typed === '' || save.isPending) return;
    save.mutate(
      // A change keeps the note the ratio carries, which the form does not show: a write without one sets none.
      { ratio, body: { name: typed, numerator: measureKey(sides.numerator), denominator: measureKey(sides.denominator), format, ...(ratio === null ? {} : { note: ratio.note }) } },
      {
        onSuccess: (saved) => onSaved(saved.key),
        onError: (error) => setTaken(isNameTaken(error)),
      },
    );
  };
  const heading = ratio === null ? 'New ratio' : 'Change the ratio';
  return (
    <div className="dash-valuepane dash-ratioform" role="group" aria-label={heading} data-testid="dashboard.ratio-form">
      <div className="panehead">
        <button type="button" className="btn btn-ghost btn-sm btn-icon" title="Back" aria-label="Back" onClick={onBack} data-testid="dashboard.ratio-form.back">
          <ArrowLeft className="icon" aria-hidden="true" />
        </button>
        <span className="t">{heading}</span>
      </div>
      <input
        type="text"
        className="field"
        value={name}
        maxLength={NAME_LENGTH}
        placeholder="Its name"
        aria-label="The ratio’s name"
        aria-invalid={taken}
        autoFocus
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => {
          setName(event.target.value);
          setTaken(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') submit();
        }}
        data-testid="dashboard.ratio-form.name"
      />
      {taken && (
        <p className="note bad" data-testid="dashboard.ratio-form.taken">
          Another ratio has that name
        </p>
      )}
      {(['numerator', 'denominator'] as const).map((side) => (
        <SideField key={side} side={side} measure={sides[side]} label={label} onChange={(measure) => set(side, measure)} onFilter={() => setFiltering(side)} />
      ))}
      <label className="dash-ratioside">
        <span className="k">Reads as</span>
        <select className="field" value={format} onChange={(event) => setPicked(event.target.value as Format)} aria-label="Its numbers read as" data-testid="dashboard.ratio-form.format">
          {FORMATS.map((each) => (
            <option key={each} value={each}>
              {FORMAT_WORDS[each]}
            </option>
          ))}
        </select>
      </label>
      <div className="row foot">
        <button type="button" className="btn btn-primary btn-sm" disabled={typed === '' || save.isPending} onClick={submit} data-testid="dashboard.ratio-form.save">
          Save
        </button>
      </div>
      <p className="note">Kept for everyone: every view that shows it shows it as it is saved.</p>
    </div>
  );
}

/** A side of a new ratio: the figure `key` under its own aggregate, over its fact's own rows; the catalogue's first figure where it has no such one. */
function fresh(words: ReturnType<typeof useViewWords>, key: string): Simple {
  const figures = words.measures?.figures ?? [];
  const figure = figures.find((each) => each.key === key) ?? figures[0];
  return { kind: 'simple', figure: figure.key, aggregate: figure.aggregate, grain: null, filters: [] };
}

interface SideFieldProps {
  side: Side;
  measure: Simple;
  label: (dimension: string, value: string | null) => string;
  onChange: (measure: Simple) => void;
  onFilter: () => void;
}

/** A side of the ratio: its figure, by its fact, its aggregate, its grain, and its own filters, each with its ×. */
function SideField({ side, measure, label, onChange, onFilter }: SideFieldProps) {
  const words = useViewWords();
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const facts = words.measures?.facts ?? [];
  const figures = words.measures?.figures ?? [];
  const testId = `dashboard.ratio-form.${side}`;
  const pick = (key: string) => {
    const figure = figures.find((each) => each.key === key)!;
    const reaches = (dimension: string) => dimensions?.dimensions?.find((each) => each.key === dimension)?.facts.includes(figure.fact) ?? false;
    onChange({ kind: 'simple', figure: key, aggregate: figure.aggregate, grain: null, filters: measure.filters.filter((filter) => reaches(filter.dimension)) });
  };
  const grain = grainOf(words.measures, measure);
  return (
    <div className="dash-ratioside" role="group" aria-label={SIDE_WORDS[side]} data-testid={testId}>
      <span className="k">{SIDE_WORDS[side]}</span>
      <select className="field" value={measure.figure} onChange={(event) => pick(event.target.value)} aria-label={`The ${side}’s figure`} data-testid={`${testId}.figure`}>
        {facts.map((fact) => (
          <optgroup key={fact.key} label={fact.label}>
            {figures
              .filter((figure) => figure.fact === fact.key)
              .map((figure) => (
                <option key={figure.key} value={figure.key}>
                  {figure.label}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <select className="field" value={measure.aggregate} onChange={(event) => onChange({ ...measure, aggregate: event.target.value })} aria-label={`The ${side}’s aggregate`} data-testid={`${testId}.aggregate`}>
        {aggregatesOf(words.measures, measure.figure).map((aggregate) => (
          <option key={aggregate.key} value={aggregate.key} title={aggregate.line}>
            {aggregate.label}
          </option>
        ))}
      </select>
      <select
        className="field"
        value={grain ?? ''}
        onChange={(event) => onChange(overGrain(words.measures, measure, event.target.value))}
        aria-label={`The ${side}’s items`}
        title="The aggregate takes the figure of each item: a part’s items each sum their fact’s rows first"
        data-testid={`${testId}.grain`}
      >
        {grainsOf(words.measures, dimensions, measure.figure).map((each) => (
          <option key={each.key} value={each.key}>
            {`Per ${each.one}`}
          </option>
        ))}
      </select>
      <div className="filters">
        {measure.filters.map((filter) => {
          const said = `${dimensionLabel(dimensions, filter.dimension)} ${filter.negated ? 'is not' : 'is'} ${filter.values.map((value) => label(filter.dimension, value)).join(' or ')}`;
          return (
            <span key={filter.dimension} className="dash-sidefilter" title={said} data-testid={`${testId}.filter`}>
              <span className="t">{said}</span>
              <button
                type="button"
                className="x"
                title="Remove this filter"
                aria-label={`Remove the filter ${said}`}
                onClick={() => onChange({ ...measure, filters: measure.filters.filter((each) => each !== filter) })}
                data-testid={`${testId}.filter.remove`}
              >
                <X className="icon" aria-hidden="true" />
              </button>
            </span>
          );
        })}
        <button type="button" className="btn btn-ghost btn-sm dash-add" onClick={onFilter} title={`A filter of the ${side}’s own: it counts only what the filter keeps`} data-testid={`${testId}.add-filter`}>
          <Plus className="icon" aria-hidden="true" />
          Filter
        </button>
      </div>
    </div>
  );
}
