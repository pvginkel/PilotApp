/**
 * The quick filters' line, under the scope's (F162.6; the mockup's `scope.js`, `renderBadges` and
 * `removeBadge`): everyone's quick filters the catalogue offers, in the order they were made, each a
 * toggle in a chip's form, a diamond first where it marks, its name, its count and the amount of its
 * figure over what it keeps in the view's scope, both a task's answer, the last drawn until the next
 * arrive. A press turns one on, its chip joining the scope as it was made, filtering or marking, with
 * no chip shown; a second press turns it off; each a new entry (F160.4). One that is on narrows the
 * others' counts. One that counts nothing and is off is muted and takes no press. On hover its × lies
 * over its right end, which removes it for everyone, after the dialog's question. The quick filters
 * are everyone's: read again each time the line shows, as the new tab's panel reads its lists.
 */

import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Diamond, Trash2, X } from 'lucide-react';
import { ConfirmDialog } from '@/components/shared/dialog';
import { useSseContext } from '@/contexts/sse-context';
import { useFailureShown } from '@/hooks/use-dashboard-view';
import { useViewWords } from '@/hooks/use-view-words';
import { useQuickFilterWrites } from '@/hooks/use-view-writes';
import { figure, whole } from '@/lib/dashboard/figures';
import { catalogueQuery, quickFilterCountsQuery, type QuickFilter } from '@/lib/dashboard/queries';
import { chipDoes, chipText, chipWords, type LabelOf } from '@/lib/dashboard/scope';
import { chipOf, type ViewState } from '@/lib/dashboard/state';
import { cn } from '@/lib/utils';

interface QuickFiltersProps {
  state: ViewState;
  /** The view's state without its look-only parts: what the counts are read in. */
  scope: string;
  label: LabelOf;
  /** The view moved to `state`, a new entry. */
  onState: (state: ViewState) => void;
}

export function QuickFilters({ state, scope, label, onState }: QuickFiltersProps) {
  const held = useQuery({ ...catalogueQuery('stored'), staleTime: 0 }).data?.quick_filters;
  const { addEventListener } = useSseContext();
  const counts = useQuery({ ...quickFilterCountsQuery(scope, addEventListener), placeholderData: keepPreviousData });
  useFailureShown(counts);
  const words = useViewWords();
  const writes = useQuickFilterWrites();
  const [removing, setRemoving] = useState<QuickFilter | null>(null);
  const offered = held?.filter((each) => each.offered) ?? [];
  if (offered.length === 0) return null;
  const counted = new Map(counts.data?.quick_filters.map((each) => [each.key, each]));
  const formatOf = (amount: string) => words.measures?.figures?.find((each) => each.key === amount)?.format;
  const toggle = (key: string, on: boolean) =>
    onState({ ...state, quickFilters: on ? state.quickFilters.filter((each) => each !== key) : [...state.quickFilters, key], selected: null });
  return (
    <div className={cn('dash-line dash-quick-line', counts.isPlaceholderData && 'changing')} role="group" aria-label="Quick filters" aria-busy={counts.isPlaceholderData} data-testid="dashboard.quick-filters">
      {offered.map((quickFilter) => {
        const on = state.quickFilters.includes(quickFilter.key);
        const count = counted.get(quickFilter.key);
        const idle = !on && count?.count === 0;
        const format = quickFilter.amount === null ? undefined : formatOf(quickFilter.amount);
        const chip = { ...chipOf(quickFilter.condition), marked: quickFilter.marks };
        const title = `${quickFilter.note ?? chipText(chipWords(chip, label, words))}\n${chipDoes(chip)}`;
        return (
          <span key={quickFilter.id} className={cn('dash-chip dash-quick', on && 'on', idle && 'idle')} data-key={quickFilter.key} data-testid="dashboard.quick-filter">
            <button
              type="button"
              className="main"
              title={title}
              aria-pressed={on}
              aria-disabled={idle || undefined}
              onClick={() => {
                if (!idle) toggle(quickFilter.key, on);
              }}
              data-testid="dashboard.quick-filter.toggle"
            >
              {quickFilter.marks && <Diamond className="icon" aria-label="Marks" />}
              <span className="l" data-testid="dashboard.quick-filter.label">
                {quickFilter.label}
              </span>
              <span className="n" data-testid="dashboard.quick-filter.count">
                {whole(count?.count ?? null)}
              </span>
              {format !== undefined && count?.amount != null && (
                <span className="amt" data-testid="dashboard.quick-filter.amount">
                  {figure(format, count.amount)}
                </span>
              )}
            </button>
            <button
              type="button"
              className="x"
              title="Remove this quick filter, for everyone"
              aria-label={`Remove the quick filter ${quickFilter.label}`}
              onClick={() => setRemoving(quickFilter)}
              data-testid="dashboard.quick-filter.remove"
            >
              <X className="icon" aria-hidden="true" />
            </button>
          </span>
        );
      })}
      {removing !== null && (
        <ConfirmDialog
          title={`Remove the quick filter "${removing.label}"?`}
          lines={['It is removed for everyone.']}
          note="A view that has it on, here or saved, shows without it."
          act={{ label: 'Remove quick filter', icon: Trash2 }}
          pending={writes.remove.isPending}
          onConfirm={() => writes.remove.mutate(removing, { onSettled: () => setRemoving(null) })}
          onCancel={() => setRemoving(null)}
          testId="dashboard.quick-filter.remove-dialog"
        />
      )}
    </div>
  );
}
