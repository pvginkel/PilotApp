/**
 * The words of dimensions' values in a view (F162.3, F162.4): a closed list's value is its name, the
 * value with none its dimension's label of none, and any other its label as the page was told it,
 * else as it is looked up among the values in its scope (`labelQuery`, `valuesNamed`); its key
 * until the label comes, and where the scope holds no such value. A lookup that fails stands in the
 * banner, with a Retry that asks every lookup refused again. Not `enabled`, the labels the page holds are kept, none is looked up and
 * none of their failures shown.
 */

import { useLayoutEffect, useRef } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { useFailureShown } from '@/hooks/use-dashboard-view';
import { catalogueQuery, labelQuery, type Catalogue } from '@/lib/dashboard/queries';
import type { LabelOf, Named } from '@/lib/dashboard/scope';

const dimensionOf = (dimensions: Catalogue | undefined, key: string) => dimensions?.dimensions?.find((each) => each.key === key);

/** A value's name in its dimension's closed list; none where its words are the record's. */
const listed = (dimensions: Catalogue | undefined, dimension: string, value: string) => dimensionOf(dimensions, dimension)?.values?.find((each) => each.code === value)?.name;

const keyOf = (dimension: string, value: string) => `${dimension}\u0000${value}`;

export function useValueLabels(asked: readonly Named[], enabled = true): LabelOf {
  const dimensions = useQuery(catalogueQuery('dimensions')).data;
  const looked = new Map<string, { dimension: string; value: string; scope: string }>();
  if (dimensions !== undefined) {
    for (const { dimension, value, scope } of asked) {
      if (value !== null && listed(dimensions, dimension, value) === undefined && !looked.has(keyOf(dimension, value))) looked.set(keyOf(dimension, value), { dimension, value, scope });
    }
  }
  const wanted = [...looked.values()];
  const answers = useQueries({ queries: wanted.map(({ dimension, value, scope }) => ({ ...labelQuery(dimension, value, scope), enabled })) });

  // One reader in the banner for every lookup refused: its Retry asks again each of those refused
  // as it is pressed, the banner keeping the failure it was given as the first was refused.
  const refused = enabled ? answers.filter((answer) => answer.isError) : [];
  const refusedNow = useRef(refused);
  useLayoutEffect(() => {
    refusedNow.current = refused;
  });
  useFailureShown(refused.length === 0 ? undefined : { ...refused[0], refetch: () => Promise.all(refusedNow.current.map((answer) => answer.refetch())).then(([first]) => first) });

  const found = new Map(wanted.map(({ dimension, value }, index) => [keyOf(dimension, value), answers[index].data]));
  return (dimension, value) =>
    value === null ? (dimensionOf(dimensions, dimension)?.null ?? '(none)') : (listed(dimensions, dimension, value) ?? found.get(keyOf(dimension, value)) ?? value);
}
