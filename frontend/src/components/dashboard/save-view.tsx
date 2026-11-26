/**
 * The global toolbar's two that are the tab's (F161.5; the mockup's `frame.js` and `views.js`,
 * `saveViewPopover`): Reset, the tab back to what it opened with, its saved view, the start from
 * scratch or a link's state, there to press only where the tab's state differs from it in the
 * server's normal form; and Save view, a pane that asks a name, for everyone, the field holding the
 * name of the saved view the tab is of. A name a saved view has is replaced; a system view's stays,
 * the saved view standing beside it in the other list, where the mockup's pane refuses the name.
 */

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { Popover } from '@/components/shared/popover';
import type { useViewTabMoves, ViewTab } from '@/hooks/use-view-tabs';
import { useSaveView } from '@/hooks/use-view-writes';
import { addressQuery, catalogueQuery } from '@/lib/dashboard/queries';

type Moves = ReturnType<typeof useViewTabMoves>;

/** The longest name a view takes (`backend/app/schemas/dashboard_store.py`, `VIEW_NAME`). */
const NAME_LENGTH = 80;

export function ResetButton({ tab, now, moves }: { tab: ViewTab; now: string; moves: Moves }) {
  const queryClient = useQueryClient();
  const { opened } = tab;
  const apart = opened !== null && opened !== now;
  const at = useQuery({ ...addressQuery(queryClient, now), enabled: apart });
  const back = useQuery({ ...addressQuery(queryClient, opened ?? ''), enabled: apart });
  const differs = apart && at.data !== undefined && back.data !== undefined && at.data.address !== back.data.address;
  return (
    <button type="button" className="btn btn-sm" disabled={!differs} onClick={() => moves.reset(tab.id)} title="This tab back to what it opened with" data-testid="dashboard.reset">
      Reset
    </button>
  );
}

export function SaveViewButton({ tab, now }: { tab: ViewTab; now: string }) {
  return (
    <Popover
      label="Save view"
      className="dash-save"
      testId="dashboard.save"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          className="btn btn-sm"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
          title="Save this view under a name, for everyone"
          data-testid="dashboard.save-view"
        >
          <Save className="icon" aria-hidden="true" />
          Save view
        </button>
      )}
    >
      {(close) => <SavePane tab={tab} now={now} onSaved={close} />}
    </Popover>
  );
}

function SavePane({ tab, now, onSaved }: { tab: ViewTab; now: string; onSaved: () => void }) {
  const views = useQuery(catalogueQuery('stored')).data?.saved_views;
  const save = useSaveView();
  const [name, setName] = useState(() => (tab.view === null ? '' : (views?.find((each) => each.id === tab.view!.id)?.name ?? tab.view.name)));
  const typed = name.trim();
  const named = (system: boolean) => views?.some((each) => each.system === system && each.name === typed) === true;
  const note = typed === '' ? null : named(false) ? `Replaces the saved view "${typed}".` : named(true) ? 'A system view has this name: yours is saved beside it, in Saved views.' : null;
  const go = () => {
    if (typed === '' || save.isPending) return;
    save.mutate({ tab: tab.id, name: typed, state: now }, { onSuccess: onSaved });
  };
  return (
    <div className="dash-save-pane">
      <h3>Save view</h3>
      <input
        type="text"
        className="field"
        value={name}
        maxLength={NAME_LENGTH}
        placeholder="The view’s name"
        aria-label="The view’s name"
        autoFocus
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') go();
        }}
        data-testid="dashboard.save.name"
      />
      {note !== null && (
        <p className="note" data-testid="dashboard.save.note">
          {note}
        </p>
      )}
      <div className="foot">
        <button type="button" className="btn btn-primary btn-sm" disabled={typed === '' || save.isPending} onClick={go} data-testid="dashboard.save.save">
          Save
        </button>
      </div>
    </div>
  );
}
