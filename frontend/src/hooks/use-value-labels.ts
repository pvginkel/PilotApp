/**
 * The words of dimensions' values in a view (F162.3, F162.4): a closed list's value is its name, the
 * value with none its dimension's label of none, and any other its label as the page was told it,
 * else as it is looked up among the values in its scope (`labelQuery`, `valuesNamed`); its key
 * until the label comes, and where the scope holds no such value. A lookup that fails shows in the
 * banner, with its Retry. Not `enabled`, the labels the page holds are kept and none is looked up.
 */

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

  useFailureShown(answers.find((answer) => answer.isError));

  const found = new Map(wanted.map(({ dimension, value }, index) => [keyOf(dimension, value), answers[index].data]));
  return (dimension, value) =>
    value === null ? (dimensionOf(dimensions, dimension)?.null ?? '(none)') : (listed(dimensions, dimension, value) ?? found.get(keyOf(dimension, value)) ?? value);
}
